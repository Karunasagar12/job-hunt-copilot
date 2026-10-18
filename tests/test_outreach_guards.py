from unittest.mock import patch

import db


def _make_entry(status="sending", provider="agentmail"):
    conn = db._get_conn()
    conn.execute("INSERT INTO jobs (company, role, geography) VALUES ('Acme', 'Eng', 'eu')")
    job_id = conn.execute("SELECT id FROM jobs WHERE company='Acme'").fetchone()["id"]
    conn.execute(
        "INSERT INTO contacts (job_id, name, email, contact_type) VALUES (?, 'A', 'a@acme.com', 'recruiter')",
        (job_id,),
    )
    contact_id = conn.execute("SELECT id FROM contacts WHERE email='a@acme.com'").fetchone()["id"]
    conn.commit()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-01", "S", "B", provider=provider)
    db.update_outreach_entry(entry_id, status=status)
    return entry_id


def test_edit_outreach_rejects_non_draft_agentmail_row(client):
    db.init_db()
    entry_id = _make_entry(status="sending")
    resp = client.patch(f"/api/outreach/{entry_id}", json={"subject": "Changed"})
    assert resp.status_code == 409
    row = db._get_conn().execute("SELECT subject FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["subject"] == "S"


def test_edit_outreach_allows_draft_agentmail_row(client):
    db.init_db()
    entry_id = _make_entry(status="draft")
    resp = client.patch(f"/api/outreach/{entry_id}", json={"subject": "Changed"})
    assert resp.status_code == 200
    row = db._get_conn().execute("SELECT subject FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["subject"] == "Changed"


def test_edit_outreach_still_works_unconditionally_for_gmail_provider_row(client):
    db.init_db()
    entry_id = _make_entry(status="gmail_draft", provider="gmail")
    resp = client.patch(f"/api/outreach/{entry_id}", json={"subject": "Changed"})
    assert resp.status_code == 200
    row = db._get_conn().execute("SELECT subject FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["subject"] == "Changed"


def test_redraft_rejects_non_draft_agentmail_row(client):
    db.init_db()
    entry_id = _make_entry(status="uncertain")
    resp = client.post(f"/api/outreach/{entry_id}/redraft", json={"feedback": ""})
    assert resp.status_code == 409


def test_redraft_rejects_if_content_edited_during_the_llm_call_without_overwriting_it(client):
    """Regression (same class as Task 6's placeholder-fix fix): status=
    'draft' alone doesn't guard this write -- a concurrent PATCH edit can
    land while the LLM call is in flight without ever changing status.
    Must verify subject/content still match the pre-redraft snapshot too,
    or it silently clobbers the concurrent edit."""
    db.init_db()
    entry_id = _make_entry(status="draft")
    db.update_outreach_entry(entry_id, subject="Original subject", content="Original content")

    def racy_redraft(*args, **kwargs):
        db._get_conn().execute(
            "UPDATE outreach_log SET content = ? WHERE id = ?",
            ("Edited by a concurrent request while the LLM call was running", entry_id),
        )
        db._get_conn().commit()
        return "Redrafted subject", "Redrafted body"  # computed from the now-stale original content

    with patch("api.app._llm_redraft", side_effect=racy_redraft):
        resp = client.post(f"/api/outreach/{entry_id}/redraft", json={"feedback": ""})

    assert resp.status_code == 409
    row = db._get_conn().execute("SELECT status, subject, content FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "draft"
    assert row["content"] == "Edited by a concurrent request while the LLM call was running"
    assert row["subject"] == "Original subject"  # the stale redraft never got written over it


def test_skip_rejects_non_draft_agentmail_row(client):
    db.init_db()
    entry_id = _make_entry(status="sent")
    resp = client.post(f"/api/outreach/{entry_id}/skip")
    assert resp.status_code == 409
    row = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "sent"


def test_mark_sent_rejects_agentmail_row(client):
    """Manual 'Mark Sent' is the deliberately-not-built override for
    agentmail rows -- must always 409, regardless of status, since only
    /send or /check-status may set status='sent'."""
    db.init_db()
    entry_id = _make_entry(status="draft")
    resp = client.post(f"/api/outreach/{entry_id}/sent")
    assert resp.status_code == 409


def test_skip_still_works_unconditionally_for_gmail_provider_row(client):
    db.init_db()
    entry_id = _make_entry(status="gmail_draft", provider="gmail")
    resp = client.post(f"/api/outreach/{entry_id}/skip")
    assert resp.status_code == 200


def test_mark_sent_still_works_unconditionally_for_gmail_provider_row(client):
    db.init_db()
    entry_id = _make_entry(status="gmail_draft", provider="gmail")
    resp = client.post(f"/api/outreach/{entry_id}/sent")
    assert resp.status_code == 200
    row = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "sent"


# ── Extension: create_gmail_draft / batch_draft must reject agentmail-provider rows ──
# Not in the brief's literal file list, but flagged during Task 2's review as a latent
# gap: nothing stops these two Gmail-draft-creation routes from being called on an
# agentmail-provider row, which would flip it to status='gmail_draft' -- a state this
# plan's cancellation/send/retry logic can never recover from (permanently stuck).

def test_create_gmail_draft_rejects_agentmail_row(client, gmail_credentials):
    db.init_db()
    entry_id = _make_entry(status="draft", provider="agentmail")
    resp = client.post(f"/api/outreach/{entry_id}/gmail-draft")
    assert resp.status_code == 409
    row = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "draft"


def test_batch_draft_rejects_agentmail_row(client, gmail_credentials):
    db.init_db()
    entry_id = _make_entry(status="draft", provider="agentmail")
    resp = client.post("/api/outreach/batch-draft", json={"ids": [entry_id]})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["created"] == 0
    assert any(e["id"] == entry_id for e in body["errors"])
    row = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "draft"
