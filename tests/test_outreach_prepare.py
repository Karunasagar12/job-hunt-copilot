import base64
from unittest.mock import patch

import db
import api.app as app_module


def _setup_job_contact(cv_path=None):
    # Uses each INSERT's own lastrowid rather than re-querying by
    # company/email -- every test inserts a row with the same 'Acme' /
    # 'a@acme.com' values, so a plain SELECT without ORDER BY/lastrowid
    # would nondeterministically (in practice: always) resolve to the
    # first such row ever inserted in the whole test session, not the
    # one this call just created.
    conn = db._get_conn()
    job_cur = conn.execute(
        "INSERT INTO jobs (company, role, geography, cv_path) VALUES ('Acme', 'Eng', 'eu', ?)",
        (cv_path,),
    )
    job_id = job_cur.lastrowid
    contact_cur = conn.execute(
        "INSERT INTO contacts (job_id, name, email, contact_type) VALUES (?, 'A', 'a@acme.com', 'recruiter')",
        (job_id,),
    )
    contact_id = contact_cur.lastrowid
    conn.commit()
    return job_id, contact_id


def test_prepare_returns_finalized_body_and_fingerprint(client, tmp_path):
    db.init_db()
    # Critical Rule 13: Email 1 always requires a resolvable CV -- give this
    # job a real one. pathlib's `/` discards the left operand when the right
    # side is absolute, so passing tmp_path's absolute string as cv_path
    # makes _find_cv_pdf's `PROJECT_ROOT / cv_path` resolve straight to it.
    (tmp_path / "cv.pdf").write_bytes(b"%PDF-1.4 fake")
    job_id, contact_id = _setup_job_contact(cv_path=str(tmp_path))
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-01", "Hi", "Body text\n\nRegards,\nJane")

    with patch("gmail_client._get_signature", return_value="<p>Sig</p>"):
        resp = client.post(f"/api/outreach/{entry_id}/prepare")

    assert resp.status_code == 200
    data = resp.get_json()
    assert "Sig" in data["body"]
    assert data["fingerprint"]
    assert data["cv_filename"] == "cv.pdf"
    assert data["scheduled_date"] == "2026-10-01"
    assert "from_address" in data
    assert data["can_send"] is True  # scheduled_date is in the past, nothing else blocks it


def test_cid_to_preview_html_substitutes_data_url_for_matching_content_id():
    attachments = [{"content_id": "signature-image-0@jobhunt.local", "content_type": "image/png", "content": "aW1n"}]
    html = '<img src="cid:signature-image-0@jobhunt.local">'

    preview = app_module._cid_to_preview_html(html, attachments)

    assert preview == '<img src="data:image/png;base64,aW1n">'


def test_cid_to_preview_html_passthrough_when_no_attachments():
    assert app_module._cid_to_preview_html("<p>no images</p>", []) == "<p>no images</p>"
    assert app_module._cid_to_preview_html(None, [{"content_id": "x"}]) is None


def test_prepare_resolves_cid_signature_images_to_data_urls_for_preview(client, tmp_path):
    """Regression for the round-2 review's R2b finding: the drawer renders
    prepared.body with dangerouslySetInnerHTML, and browsers cannot resolve
    cid: URIs outside a real mail client -- the preview showed four broken
    images. /prepare must substitute data: URLs built from the SAME stored
    attachment bytes used for the real send, never re-fetching or
    regenerating them."""
    (tmp_path / "cv.pdf").write_bytes(b"%PDF-1.4 fake")
    job_id, contact_id = _setup_job_contact(cv_path=str(tmp_path))
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-01", "Hi", "Body text")
    image_bytes = base64.b64encode(b"signature-image").decode("ascii")
    signature_html = f'<img src="data:image/png;base64,{image_bytes}">'

    with patch("gmail_client._get_signature", return_value=signature_html):
        resp = client.post(f"/api/outreach/{entry_id}/prepare")

    assert resp.status_code == 200
    body = resp.get_json()["body"]
    assert "cid:" not in body
    assert f"data:image/png;base64,{image_bytes}" in body


def test_prepare_reports_can_send_false_before_due_date(client, tmp_path):
    db.init_db()
    (tmp_path / "cv.pdf").write_bytes(b"%PDF-1.4 fake")
    job_id, contact_id = _setup_job_contact(cv_path=str(tmp_path))
    future_date = "2099-01-01"
    # Follow-up, not Email 1 -- Email 1 is exempt from the date gate (job #141).
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 4, future_date, "Hi", "Body")

    with patch("gmail_client._get_signature", return_value=""):
        resp = client.post(f"/api/outreach/{entry_id}/prepare")

    data = resp.get_json()
    assert data["can_send"] is False
    assert future_date in data["cannot_send_reason"]


def test_prepare_rejects_non_draft_row(client):
    db.init_db()
    job_id, contact_id = _setup_job_contact()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-01", "Hi", "Body")
    db.update_outreach_entry(entry_id, status="sending")

    resp = client.post(f"/api/outreach/{entry_id}/prepare")

    assert resp.status_code == 409


def test_prepare_is_idempotent_no_double_signature(client, tmp_path):
    db.init_db()
    (tmp_path / "cv.pdf").write_bytes(b"%PDF-1.4 fake")
    job_id, contact_id = _setup_job_contact(cv_path=str(tmp_path))
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-01", "Hi", "Body text")

    with patch("gmail_client._get_signature", return_value="<p>Jane Sig</p>"):
        first = client.post(f"/api/outreach/{entry_id}/prepare").get_json()
        second = client.post(f"/api/outreach/{entry_id}/prepare").get_json()

    assert first["body"].count("Jane Sig") == 1
    assert second["body"].count("Jane Sig") == 1
    assert first["body"] == second["body"]


def test_prepare_rejects_missing_cv_for_email_1(client, tmp_path):
    db.init_db()
    job_id, contact_id = _setup_job_contact(cv_path="nonexistent_dir")
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-01", "Hi", "Body")

    resp = client.post(f"/api/outreach/{entry_id}/prepare")

    assert resp.status_code == 422


def test_prepare_placeholder_fix_rejects_if_status_changes_during_the_llm_call(client):
    """Regression: the placeholder auto-fix write (inside the shared
    _prepare_agentmail_content, called from both /prepare and /send) needs
    the same conditional draft/content guard as the explicit redraft
    endpoint (Task 10) -- a concurrent request could move the row off
    'draft' while the LLM call for the fix is in flight. Simulated
    deterministically by making the patched _llm_redraft itself perform
    the race, the same technique used for Task 7's claim-value races."""
    db.init_db()
    job_id, contact_id = _setup_job_contact()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-01", "Hi [First Name]", "Body")

    def racy_redraft(*args, **kwargs):
        db._get_conn().execute("UPDATE outreach_log SET status = 'sending' WHERE id = ?", (entry_id,))
        db._get_conn().commit()
        return "Hi Fixed", "Fixed body"

    with patch("api.app._llm_redraft", side_effect=racy_redraft):
        resp = client.post(f"/api/outreach/{entry_id}/prepare")

    assert resp.status_code == 409
    row = db._get_conn().execute("SELECT subject, content FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["subject"] == "Hi [First Name]"  # the race's fix never committed
    assert row["content"] == "Body"


def test_prepare_placeholder_fix_rejects_if_content_edited_during_the_llm_call_without_overwriting_it(client):
    """Regression: status='draft' alone isn't enough to guard this write --
    a concurrent PATCH /api/outreach/<id> edit (itself guarded to require
    status='draft') can land while the LLM call is in flight WITHOUT ever
    changing status. The placeholder-fix write must also verify the row's
    subject/content still match what the redraft was computed from, or it
    silently clobbers the concurrent edit with a redraft based on stale,
    pre-edit content. Same race-simulation technique as the status-change
    test above, but this time the race is a content edit, not a status
    change -- status stays 'draft' throughout, which is exactly the case
    a status-only guard would miss."""
    db.init_db()
    job_id, contact_id = _setup_job_contact()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-01", "Hi [First Name]", "Body")

    def racy_redraft(*args, **kwargs):
        db._get_conn().execute(
            "UPDATE outreach_log SET content = ? WHERE id = ?",
            ("Edited by a concurrent request while the LLM call was running", entry_id),
        )
        db._get_conn().commit()
        return "Hi Fixed", "Fixed body"  # computed from the now-stale pre-edit content

    with patch("api.app._llm_redraft", side_effect=racy_redraft):
        resp = client.post(f"/api/outreach/{entry_id}/prepare")

    assert resp.status_code == 409
    row = db._get_conn().execute("SELECT status, subject, content FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "draft"  # never left draft -- a status-only guard would have missed this race entirely
    assert row["content"] == "Edited by a concurrent request while the LLM call was running"  # concurrent edit survives
    assert row["subject"] == "Hi [First Name]"  # the stale "Hi Fixed" redraft never got written over it
