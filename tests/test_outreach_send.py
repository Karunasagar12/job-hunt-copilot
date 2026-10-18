import base64
import json
import tempfile
from datetime import timedelta
from unittest.mock import patch

import db
import profile as prof
import agentmail_client
import api.app as appmod


def _setup_ready_entry(client, sequence_num=1, scheduled_offset_days=0, cv_path=None):
    # ponytail: sequence_num=1 entries go through _prepare_agentmail_content's
    # CV resolution (Critical Rule 13), which needs a real PDF on disk -- an
    # absolute tmp dir here satisfies pathlib's `PROJECT_ROOT / cv_path`
    # (absolute right-hand side wins), same trick test_outreach_prepare.py
    # uses via tmp_path. mkdtemp over a pytest fixture: no signature threading
    # needed across every test that calls this helper.
    if cv_path is None:
        cv_dir = tempfile.mkdtemp()
        with open(f"{cv_dir}/cv.pdf", "wb") as f:
            f.write(b"%PDF-1.4 fake")
        cv_path = cv_dir
    conn = db._get_conn()
    conn.execute(
        "INSERT INTO jobs (company, role, geography, cv_path) VALUES ('Acme', 'Eng', 'eu', ?)",
        (cv_path,),
    )
    job_id = conn.execute("SELECT id FROM jobs WHERE company='Acme' ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.execute(
        "INSERT INTO contacts (job_id, name, email, contact_type) VALUES (?, 'A', 'a@acme.com', 'recruiter')",
        (job_id,),
    )
    contact_id = conn.execute("SELECT id FROM contacts WHERE email='a@acme.com' ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.commit()
    # Use the same profile calendar as eligibility and the atomic claim.
    scheduled = (prof.today_local() + timedelta(days=scheduled_offset_days)).isoformat()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", sequence_num, scheduled, "Hi", "Body")
    return job_id, contact_id, entry_id


def _prepare(client, entry_id):
    with patch("gmail_client._get_signature", return_value=""):
        return client.post(f"/api/outreach/{entry_id}/prepare").get_json()


def _send(client, entry_id, fingerprint):
    # ponytail: /send recomputes the fingerprint via the same
    # _prepare_agentmail_content used by /prepare -- it must see the same
    # signature state _prepare saw, or the fingerprint "changes" purely
    # because of this test's own mocking boundary, not because of
    # anything the route under test actually did. Same return_value as
    # _prepare's patch for exactly that reason.
    with patch("gmail_client._get_signature", return_value=""):
        return client.post(f"/api/outreach/{entry_id}/send", json={"fingerprint": fingerprint})


@patch("agentmail_client.send_email")
def test_send_success_marks_sent(mock_send, client):
    db.init_db()
    _, _, entry_id = _setup_ready_entry(client)
    prepared = _prepare(client, entry_id)
    mock_send.return_value = {"message_id": "m1", "thread_id": "t1"}

    resp = _send(client, entry_id, prepared["fingerprint"])

    assert resp.status_code == 200
    row = db._get_conn().execute("SELECT status, agentmail_message_id FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "sent"
    assert row["agentmail_message_id"] == "m1"


@patch("agentmail_client.send_email")
def test_send_snapshots_exactly_what_was_sent(mock_send, client):
    """Regression: the attempt snapshot (used by a later replay in Task 8)
    must store exactly what was sent to agentmail_client.send_email -- both
    the plain text_body AND the html_body, not one collapsed into the
    other, and the same inbox_id. This is the property that makes a later
    replay byte-identical to the original request instead of 409ing."""
    db.init_db()
    _, _, entry_id = _setup_ready_entry(client)
    prepared = _prepare(client, entry_id)
    mock_send.return_value = {"message_id": "m1", "thread_id": "t1"}

    _send(client, entry_id, prepared["fingerprint"])

    sent_kwargs = mock_send.call_args.kwargs
    sent_inbox_id = mock_send.call_args.args[1]
    sent_text_body = mock_send.call_args.args[4]
    attempt_key = db._get_conn().execute(
        "SELECT idempotency_key FROM outreach_send_attempts WHERE outreach_log_id = ?", (entry_id,)
    ).fetchone()["idempotency_key"]
    attempt = db.get_send_attempt(attempt_key)

    assert attempt["text_body"] == sent_text_body
    assert attempt["html_body"] == sent_kwargs["html_body"]
    assert attempt["inbox_id"] == sent_inbox_id


@patch("agentmail_client.send_email")
def test_send_includes_signature_images_as_extra_attachments(mock_send, client):
    """Regression for the AgentMail review's R2 finding: a signature with
    embedded data:image URIs must reach send_email as CID-referenced
    extra_attachments (never silently dropped), and the exact snapshot must
    be stored on the attempt row for later byte-identical replay."""
    db.init_db()
    _, _, entry_id = _setup_ready_entry(client)
    mock_send.return_value = {"message_id": "m1", "thread_id": "t1"}
    image_b64 = base64.b64encode(b"signature-image").decode("ascii")
    signature_html = f'<p>sig</p><img src="data:image/png;base64,{image_b64}">'

    with patch("gmail_client._get_signature", return_value=signature_html):
        prepared = client.post(f"/api/outreach/{entry_id}/prepare").get_json()
        resp = client.post(f"/api/outreach/{entry_id}/send", json={"fingerprint": prepared["fingerprint"]})

    assert resp.status_code == 200
    expected_inline = [{
        "filename": "signature-0.png", "content_type": "image/png", "content": image_b64,
        "content_disposition": "inline", "content_id": "signature-image-0@jobhunt.local",
    }]
    assert mock_send.call_args.kwargs["extra_attachments"] == expected_inline

    attempt_key = db._get_conn().execute(
        "SELECT idempotency_key FROM outreach_send_attempts WHERE outreach_log_id = ?", (entry_id,)
    ).fetchone()["idempotency_key"]
    attempt = db.get_send_attempt(attempt_key)
    assert json.loads(attempt["inline_attachments_json"]) == expected_inline


@patch("agentmail_client.send_email")
def test_send_definitive_failure_reverts_to_draft(mock_send, client):
    db.init_db()
    _, _, entry_id = _setup_ready_entry(client)
    prepared = _prepare(client, entry_id)
    mock_send.side_effect = agentmail_client.AgentMailError("bad recipient")

    resp = _send(client, entry_id, prepared["fingerprint"])

    assert resp.status_code >= 400
    row = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "draft"


@patch("agentmail_client.send_email")
def test_send_ambiguous_marks_uncertain(mock_send, client):
    db.init_db()
    _, _, entry_id = _setup_ready_entry(client)
    prepared = _prepare(client, entry_id)
    mock_send.side_effect = agentmail_client.AgentMailAmbiguous("timeout")

    resp = _send(client, entry_id, prepared["fingerprint"])

    assert resp.status_code == 202
    row = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "uncertain"


@patch("agentmail_client.send_email")
def test_send_replay_mismatch_marks_uncertain(mock_send, client):
    """AgentMailReplayMismatch (409 from AgentMail) must be treated exactly
    like AgentMailAmbiguous -- 'uncertain', never 'failed'/reverted to
    draft -- since a 409 is never proof the original send failed. Mirrors
    test_send_ambiguous_marks_uncertain exactly, just the other exception,
    so a future refactor that accidentally folds this except clause into
    the AgentMailError/502 branch gets caught here."""
    db.init_db()
    _, _, entry_id = _setup_ready_entry(client)
    prepared = _prepare(client, entry_id)
    mock_send.side_effect = agentmail_client.AgentMailReplayMismatch("content mismatch")

    resp = _send(client, entry_id, prepared["fingerprint"])

    assert resp.status_code == 202
    row = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "uncertain"


def test_send_rejects_stale_fingerprint(client):
    db.init_db()
    _, _, entry_id = _setup_ready_entry(client)
    _prepare(client, entry_id)
    db.update_outreach_entry(entry_id, content="Changed after review")

    resp = client.post(f"/api/outreach/{entry_id}/send", json={"fingerprint": "stale-value"})

    assert resp.status_code == 409
    row = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "draft"


@patch("agentmail_client.send_email")
def test_send_end_to_end_rejects_content_changed_before_send(mock_send, client):
    """End-to-end safety check: a content change landing BEFORE /send is
    even called must never result in a send -- caught by the fingerprint
    check. (This alone does NOT prove the claim re-validates at claim time
    -- see the two race-simulation tests below for that.)"""
    db.init_db()
    _, _, entry_id = _setup_ready_entry(client)
    prepared = _prepare(client, entry_id)
    db._get_conn().execute(
        "UPDATE outreach_log SET content = ? WHERE id = ?", ("Changed by a concurrent redraft", entry_id)
    )
    db._get_conn().commit()

    resp = _send(client, entry_id, prepared["fingerprint"])

    assert resp.status_code == 409
    mock_send.assert_not_called()
    row = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "draft"


@patch("agentmail_client.send_email")
def test_send_uses_original_snapshot_not_a_fresh_reread_for_the_claim(mock_send, client):
    """Regression (critical, the bug review caught): /send must pass the
    subject/content it validated the fingerprint against -- the `entry`
    snapshot taken at the TOP of the request -- as the claim's expected
    values, never a fresh SELECT issued after validation passed. A fresh
    re-read would silently launder a concurrent edit landing in that exact
    window into 'what's expected', making the claim succeed on content
    that was never actually validated against the client's fingerprint.

    A single synchronous request can't reproduce a real race, so this
    simulates one deterministically. The injection point matters: it must
    land strictly BETWEEN "entry is captured at the top of send_outreach"
    and "expected_subject/expected_content are evaluated for the claim
    call" -- the exact gap the historical bug (a second SELECT issued
    right before the claim call) sat in. Patching db.claim_and_record_attempt
    itself is too late to prove this: Python evaluates a call's keyword
    arguments before invoking it, so ANY second read performed by /send's
    own code -- correct or buggy -- necessarily happens before a
    patched claim_and_record_attempt's side_effect ever runs, making that
    injection point structurally unable to distinguish the two
    implementations (verified empirically while building this fix: it
    passed even with the bug deliberately reintroduced).

    _compute_send_eligibility is the right injection point instead: it
    runs after entry is captured but before the claim's expected_subject/
    expected_content are evaluated, so a mutation inside its patched
    side_effect lands exactly in that gap. If /send still passes the
    ORIGINAL (pre-mutation) entry snapshot as expected_content -- the
    correct behavior -- the claim's own WHERE clause won't match the
    now-different row and the claim fails. If /send had instead re-read
    the row after this point (the bug), expected_content would equal the
    NEW value, matching the row, and the claim would wrongly succeed."""
    db.init_db()
    _, _, entry_id = _setup_ready_entry(client)
    prepared = _prepare(client, entry_id)
    real_eligibility = appmod._compute_send_eligibility

    def racy_eligibility(*args, **kwargs):
        db._get_conn().execute(
            "UPDATE outreach_log SET content = 'Changed by a concurrent redraft' WHERE id = ?", (entry_id,)
        )
        db._get_conn().commit()
        return real_eligibility(*args, **kwargs)

    with patch("api.app._compute_send_eligibility", side_effect=racy_eligibility):
        resp = _send(client, entry_id, prepared["fingerprint"])

    assert resp.status_code == 409
    mock_send.assert_not_called()
    row = db._get_conn().execute("SELECT status, content FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "draft"
    assert row["content"] == "Changed by a concurrent redraft"  # the race's own edit survives -- just never sent


@patch("agentmail_client.send_email")
def test_send_rejects_if_contact_replies_during_the_request(mock_send, client):
    """Same race-simulation technique, applied to contact state: proves the
    atomic claim's own eligibility re-check (Task 3) -- not just the
    earlier, separate Python pre-check -- is what actually blocks a reply
    landing mid-request."""
    db.init_db()
    _, contact_id, entry_id = _setup_ready_entry(client)
    prepared = _prepare(client, entry_id)
    real_claim = db.claim_and_record_attempt

    def racy_claim(*args, **kwargs):
        db.update_contact(contact_id, replied=1)
        return real_claim(*args, **kwargs)

    with patch("db.claim_and_record_attempt", side_effect=racy_claim):
        resp = _send(client, entry_id, prepared["fingerprint"])

    assert resp.status_code == 409
    mock_send.assert_not_called()


def test_send_rejects_followup_before_scheduled_date(client):
    db.init_db()
    _, _, entry_id = _setup_ready_entry(client, sequence_num=4, scheduled_offset_days=5)
    prepared = _prepare(client, entry_id)

    resp = _send(client, entry_id, prepared["fingerprint"])

    assert resp.status_code == 403


@patch("agentmail_client.send_email")
def test_send_email_1_allowed_before_scheduled_date(mock_send, client):
    # Job #141: outreach started on a Saturday, apply_weekend_skip pushed
    # Day 0 to Monday, and Email 1 was locked until then. Day 0 is
    # whenever the human starts -- only follow-ups wait for their date.
    mock_send.return_value = {"message_id": "m1", "thread_id": "t1"}
    db.init_db()
    _, _, entry_id = _setup_ready_entry(client, sequence_num=1, scheduled_offset_days=2)
    prepared = _prepare(client, entry_id)
    assert prepared["can_send"] is True

    resp = _send(client, entry_id, prepared["fingerprint"])

    assert resp.status_code == 200
    mock_send.assert_called_once()


@patch("agentmail_client.send_email")
def test_send_blocks_email_2_until_email_1_confirmed_sent(mock_send, client):
    db.init_db()
    job_id, contact_id, email1_id = _setup_ready_entry(client, sequence_num=1)
    # Email 1 still 'draft' -- never sent
    scheduled = prof.today_local().isoformat()
    email2_id = db.create_outreach_entry(contact_id, job_id, "email", 4, scheduled, "Hi 2", "Body 2")
    prepared = _prepare(client, email2_id)

    resp = _send(client, email2_id, prepared["fingerprint"])

    assert resp.status_code == 409
    mock_send.assert_not_called()


@patch("agentmail_client.send_email")
def test_send_double_click_second_request_409(mock_send, client):
    db.init_db()
    _, _, entry_id = _setup_ready_entry(client)
    prepared = _prepare(client, entry_id)
    db.update_outreach_entry(entry_id, status="sending")  # simulate an in-flight first request

    resp = _send(client, entry_id, prepared["fingerprint"])

    assert resp.status_code == 409
    mock_send.assert_not_called()
