import db


def _make_failed_entry():
    conn = db._get_conn()
    conn.execute("INSERT INTO jobs (company, role, geography) VALUES ('Acme', 'Eng', 'eu')")
    job_id = conn.execute("SELECT id FROM jobs WHERE company='Acme'").fetchone()["id"]
    conn.execute(
        "INSERT INTO contacts (job_id, name, email, contact_type) VALUES (?, 'A', 'a@acme.com', 'recruiter')",
        (job_id,),
    )
    contact_id = conn.execute("SELECT id FROM contacts WHERE email='a@acme.com'").fetchone()["id"]
    conn.commit()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-01", "S", "B")
    db.update_outreach_entry(entry_id, status="failed", send_idempotency_key="old-key")
    return entry_id


def test_retry_resets_to_draft(client):
    db.init_db()
    entry_id = _make_failed_entry()

    resp = client.post(f"/api/outreach/{entry_id}/retry")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "draft"
    assert data["send_idempotency_key"] is None


def test_retry_rejects_non_failed_row(client):
    db.init_db()
    entry_id = _make_failed_entry()
    db.update_outreach_entry(entry_id, status="uncertain")

    resp = client.post(f"/api/outreach/{entry_id}/retry")

    assert resp.status_code == 409
