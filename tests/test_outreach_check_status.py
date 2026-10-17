import base64
import uuid
from datetime import date, timedelta
from unittest.mock import patch

import db
import agentmail_client


def _make_uncertain_entry(attempt_age_hours=1, cv_base64=None, cv_filename=None, inline_attachments_json=None):
    conn = db._get_conn()
    conn.execute("INSERT INTO jobs (company, role, geography) VALUES ('Acme', 'Eng', 'eu')")
    # ponytail: ORDER BY id DESC -- this file's tests share one persistent
    # test DB (conftest resets it once per session, not per test), so an
    # unordered SELECT would always return the FIRST "Acme"/"a@acme.com" row
    # ever inserted, letting one test's contact-state mutation (e.g.
    # replied=1) silently poison every later test's claim_and_record_attempt
    # eligibility re-check. Same pattern as tests/test_outreach_send.py.
    job_id = conn.execute("SELECT id FROM jobs WHERE company='Acme' ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.execute(
        "INSERT INTO contacts (job_id, name, email, contact_type) VALUES (?, 'A', 'a@acme.com', 'recruiter')",
        (job_id,),
    )
    contact_id = conn.execute("SELECT id FROM contacts WHERE email='a@acme.com' ORDER BY id DESC LIMIT 1").fetchone()["id"]
    conn.commit()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, date.today().isoformat(), "S", "B")
    # ponytail: unique per call -- outreach_send_attempts.idempotency_key is
    # UNIQUE and this file's tests share one persistent test DB (conftest
    # resets it once per session, not per test), so a literal fixed key
    # collides starting from the second test in this file.
    key = f"idem-{uuid.uuid4().hex}"
    db.claim_and_record_attempt(
        entry_id, key, expected_subject="S", expected_content="B", today=date.today().isoformat(),
        endpoint="send", reply_to_message_id=None, recipient_email="a@acme.com",
        subject="S", text_body="plain body", html_body="<p>html body</p>", inbox_id="inbox-1",
        cv_base64=cv_base64, cv_filename=cv_filename, inline_attachments_json=inline_attachments_json,
    )
    db.update_outreach_entry(entry_id, status="uncertain")
    conn.execute(
        "UPDATE outreach_log SET send_attempt_at = datetime('now', ?) WHERE id = ?",
        (f"-{attempt_age_hours} hours", entry_id),
    )
    conn.commit()
    return entry_id, key, contact_id


@patch("agentmail_client.send_email")
def test_check_status_replay_reuses_stored_inline_attachments(mock_send, client):
    """Regression for the AgentMail review's R2 finding: replay must pass the
    EXACT stored inline_attachments_json to send_email, never a freshly
    recomputed one -- same principle as cv_base64/cv_hash already being
    snapshot-stored rather than re-read from today's signature file."""
    import json
    db.init_db()
    stored_inline = [{"filename": "signature-0.png", "content_type": "image/png",
                       "content": "c3RvcmVk", "content_disposition": "inline",
                       "content_id": "signature-image-0@jobhunt.local"}]
    entry_id, key, _ = _make_uncertain_entry(inline_attachments_json=json.dumps(stored_inline))
    mock_send.return_value = {"message_id": "m1", "thread_id": "t1"}

    resp = client.post(f"/api/outreach/{entry_id}/check-status")

    assert resp.status_code == 200
    assert mock_send.call_args.kwargs["extra_attachments"] == stored_inline


@patch("agentmail_client.send_email")
def test_check_status_resolves_to_sent_on_replay_success(mock_send, client):
    db.init_db()
    entry_id, key, _ = _make_uncertain_entry()
    mock_send.return_value = {"message_id": "m1", "thread_id": "t1"}

    resp = client.post(f"/api/outreach/{entry_id}/check-status")

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "sent"
    row = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "sent"
    # replay must reuse the ORIGINAL idempotency key and the EXACT
    # snapshotted text_body/html_body/inbox_id -- not a re-derived version
    mock_send.assert_called_once()
    call = mock_send.call_args
    assert call.args[0] == key
    assert call.args[1] == "inbox-1"
    assert call.args[4] == "plain body"
    assert call.kwargs["html_body"] == "<p>html body</p>"


@patch("agentmail_client.send_email")
def test_check_status_replays_cv_attachment_for_email_1(mock_send, client):
    """Regression (Important 6): the replay path must decode and re-pass
    the snapshotted CV bytes/filename, not just subject/body -- otherwise a
    replayed Email 1 send would silently drop its CV attachment."""
    db.init_db()
    cv_bytes = b"dummy pdf bytes"
    entry_id, key, _ = _make_uncertain_entry(
        cv_base64=base64.b64encode(cv_bytes).decode(), cv_filename="JaneDoe_CV.pdf",
    )
    mock_send.return_value = {"message_id": "m1", "thread_id": "t1"}

    resp = client.post(f"/api/outreach/{entry_id}/check-status")

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "sent"
    mock_send.assert_called_once()
    call = mock_send.call_args
    assert call.kwargs["attachment_bytes"] == cv_bytes
    assert call.kwargs["attachment_filename"] == "JaneDoe_CV.pdf"


@patch("agentmail_client.send_email")
def test_check_status_on_replay_error_stays_uncertain_never_failed(mock_send, client):
    """Regression (critical, the bug review caught): an AgentMailError on
    the REPLAY call must never resolve to 'failed' -- unlike the original
    /send attempt's own error handling, an error on a replay (e.g. an
    authentication failure) proves nothing about whether the ORIGINAL
    attempt, made earlier, actually went through. Concluding 'failed' here
    would make the row Retry-eligible and risk a genuine duplicate send."""
    db.init_db()
    entry_id, key, _ = _make_uncertain_entry()
    mock_send.side_effect = agentmail_client.AgentMailError("401 Unauthorized")

    resp = client.post(f"/api/outreach/{entry_id}/check-status")

    assert resp.get_json()["status"] == "uncertain"
    row = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "uncertain"
    assert db.retry_failed_touchpoint(entry_id) is None  # not retryable -- still not 'failed'


@patch("agentmail_client.send_email")
def test_check_status_stays_uncertain_on_repeat_timeout(mock_send, client):
    db.init_db()
    entry_id, key, _ = _make_uncertain_entry()
    mock_send.side_effect = agentmail_client.AgentMailAmbiguous("still timing out")

    resp = client.post(f"/api/outreach/{entry_id}/check-status")

    assert resp.get_json()["status"] == "uncertain"
    row = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "uncertain"


@patch("agentmail_client.send_email")
def test_check_status_on_409_stays_uncertain_never_failed(mock_send, client):
    """Regression (critical): AgentMail's 409 means 'this replay doesn't
    match the original' -- it must NEVER be treated as proof of failure,
    since the original attempt may have actually succeeded. Must stay
    'uncertain' so a subsequent Retry (which requires 'failed') stays
    blocked -- Retry on a row that might already be sent is exactly the
    duplicate-send risk this whole design exists to prevent."""
    db.init_db()
    entry_id, key, _ = _make_uncertain_entry()
    mock_send.side_effect = agentmail_client.AgentMailReplayMismatch("content mismatch")

    resp = client.post(f"/api/outreach/{entry_id}/check-status")

    assert resp.get_json()["status"] == "uncertain"
    row = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "uncertain"
    assert db.retry_failed_touchpoint(entry_id) is None  # not retryable -- still not 'failed'


@patch("agentmail_client.send_email")
def test_check_status_refuses_replay_past_24_hours(mock_send, client):
    db.init_db()
    entry_id, key, _ = _make_uncertain_entry(attempt_age_hours=25)

    resp = client.post(f"/api/outreach/{entry_id}/check-status")

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "uncertain"
    assert "24" in resp.get_json()["message"]
    mock_send.assert_not_called()


@patch("agentmail_client.send_email")
def test_check_status_refuses_replay_if_contact_replied_since_attempt(mock_send, client):
    """Regression: a replay can itself send a brand-new email if the
    original request never reached AgentMail. If the contact has replied
    since the original attempt, replaying must be refused outright --
    sending a fresh email to someone who already responded is exactly the
    invariant this whole system exists to protect."""
    db.init_db()
    entry_id, key, contact_id = _make_uncertain_entry()
    db.update_contact(contact_id, replied=1)

    resp = client.post(f"/api/outreach/{entry_id}/check-status")

    assert resp.get_json()["status"] == "uncertain"
    assert "replied" in resp.get_json()["message"].lower()
    mock_send.assert_not_called()


@patch("agentmail_client.send_email")
def test_check_status_refuses_replay_if_contact_outreach_paused_since_attempt(mock_send, client):
    """Regression: the same risk applies to an explicit Skip or a confirmed
    cross-contact cascade, not just replies/bounces -- both stamp
    contacts.outreach_paused_at (Task 2) without necessarily touching this
    specific uncertain row (cancellation deliberately leaves non-draft rows
    alone, Task 2). A replay must respect that too."""
    db.init_db()
    entry_id, key, contact_id = _make_uncertain_entry()
    db._get_conn().execute("UPDATE contacts SET outreach_paused_at = CURRENT_TIMESTAMP WHERE id = ?", (contact_id,))
    db._get_conn().commit()

    resp = client.post(f"/api/outreach/{entry_id}/check-status")

    assert resp.get_json()["status"] == "uncertain"
    mock_send.assert_not_called()


def test_check_status_on_already_resolved_row_is_noop(client):
    db.init_db()
    entry_id, key, _ = _make_uncertain_entry()
    db.resolve_send_attempt(key, "sent", "m1", "t1")

    with patch("agentmail_client.send_email") as mock_send:
        resp = client.post(f"/api/outreach/{entry_id}/check-status")
        mock_send.assert_not_called()

    assert resp.get_json()["status"] == "sent"


@patch("agentmail_client.send_email")
def test_check_status_on_sending_row_persists_uncertain_to_db_not_just_response(mock_send, client):
    """Regression: a row stuck in 'sending' (e.g. a prior /send crashed
    mid-flight, before sweep_stale_sending caught it) must have its DB
    status actually written to 'uncertain' on a replay error -- not just
    reported as 'uncertain' in the HTTP response while the row silently
    stays 'sending' in outreach_log. A stuck 'sending' row is invisible to
    anything that filters on status='uncertain' (db.get_uncertain_outreach)
    until the separate sweep eventually fires."""
    db.init_db()
    entry_id, key, _ = _make_uncertain_entry()
    db._get_conn().execute("UPDATE outreach_log SET status = 'sending' WHERE id = ?", (entry_id,))
    db._get_conn().commit()
    mock_send.side_effect = agentmail_client.AgentMailError("401 Unauthorized")

    resp = client.post(f"/api/outreach/{entry_id}/check-status")

    assert resp.get_json()["status"] == "uncertain"
    row = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "uncertain"


def test_check_status_on_already_failed_row_reports_failed_without_replaying(client):
    """'failed' can still be REPORTED (a row that's already 'failed' from
    some other path, or from a prior call to this endpoint before this
    correction) -- it just can't be newly RESOLVED by this endpoint's own
    replay logic anymore. The early-return branch for a terminal status
    must still work."""
    db.init_db()
    entry_id, key, _ = _make_uncertain_entry()
    db._get_conn().execute("UPDATE outreach_log SET status = 'failed' WHERE id = ?", (entry_id,))
    db._get_conn().commit()

    with patch("agentmail_client.send_email") as mock_send:
        resp = client.post(f"/api/outreach/{entry_id}/check-status")
        mock_send.assert_not_called()

    assert resp.get_json()["status"] == "failed"
