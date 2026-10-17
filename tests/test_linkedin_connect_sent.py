"""POST /api/outreach/<id>/sent for LinkedIn connection requests (Touchpoint 2).
Spec: docs/superpowers/specs/2026-10-11-linkedin-connect-requests-design.md"""
import db


def _make_entry(channel="linkedin_connect", status="draft", provider="agentmail", seq=2):
    job_id = db.create_job("Acme", "PM", "eu")
    contact_id = db.create_contact(job_id, "Jane Doe", "hiring_manager")
    entry_id = db.create_outreach_entry(
        contact_id, job_id, channel, seq, "2026-10-12", "", "Hi Jane", provider=provider
    )
    if status != "draft":
        db.update_outreach_entry(entry_id, status=status)
    return entry_id


def _row(entry_id):
    return db._get_conn().execute(
        "SELECT status, sent_at FROM outreach_log WHERE id = ?", (entry_id,)
    ).fetchone()


def test_linkedin_connect_draft_marks_sent_despite_agentmail_provider(client):
    db.init_db()
    entry_id = _make_entry()
    resp = client.post(f"/api/outreach/{entry_id}/sent")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "sent"
    row = _row(entry_id)
    assert row["status"] == "sent"
    assert row["sent_at"]


def test_repeat_confirmation_keeps_original_sent_at(client):
    db.init_db()
    entry_id = _make_entry()
    first = client.post(f"/api/outreach/{entry_id}/sent").get_json()["sent_at"]
    second = client.post(f"/api/outreach/{entry_id}/sent")
    assert second.status_code == 200
    assert second.get_json()["sent_at"] == first
    assert _row(entry_id)["sent_at"] == first


def test_skipped_linkedin_connect_rejected(client):
    db.init_db()
    entry_id = _make_entry(status="skipped")
    resp = client.post(f"/api/outreach/{entry_id}/sent")
    assert resp.status_code == 409
    assert _row(entry_id)["status"] == "skipped"


def test_linkedin_dm_agentmail_still_rejected(client):
    # DMs are deferred -- only linkedin_connect gets the provider carve-out.
    db.init_db()
    entry_id = _make_entry(channel="linkedin_dm", seq=3)
    resp = client.post(f"/api/outreach/{entry_id}/sent")
    assert resp.status_code == 409
    assert _row(entry_id)["status"] == "draft"


def test_skipped_gmail_email_rejected(client):
    db.init_db()
    entry_id = _make_entry(channel="email", seq=1, provider="gmail", status="skipped")
    resp = client.post(f"/api/outreach/{entry_id}/sent")
    assert resp.status_code == 409
    assert _row(entry_id)["status"] == "skipped"
