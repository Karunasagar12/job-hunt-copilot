from datetime import date

import pytest

import db


@pytest.fixture(autouse=True)
def _clean_inbox_state():
    # ponytail: same shared-session-DB pollution issue documented in
    # tests/test_inbox_digest_api.py -- these tests assert exact digest
    # bucket counts, so clear via cascade from jobs before each test.
    db.init_db()
    conn = db._get_conn()
    conn.execute("DELETE FROM jobs")
    conn.commit()
    yield


def _make_entry(status="uncertain"):
    conn = db._get_conn()
    conn.execute("INSERT INTO jobs (company, role, geography) VALUES ('Acme', 'Eng', 'eu')")
    job_id = conn.execute("SELECT id FROM jobs WHERE company='Acme'").fetchone()["id"]
    conn.execute(
        "INSERT INTO contacts (job_id, name, email, contact_type) VALUES (?, 'A', 'a@acme.com', 'recruiter')",
        (job_id,),
    )
    contact_id = conn.execute("SELECT id FROM contacts WHERE email='a@acme.com'").fetchone()["id"]
    conn.commit()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, date.today().isoformat(), "S", "B")
    kwargs = {"status": status}
    if status == "sending":
        # sweep_stale_sending's race-safe UPDATE matches on
        # send_idempotency_key -- in production a 'sending' row always has
        # one set by claim_and_record_attempt (see test_review_send_attempts.py's
        # _make_job_contact_entry). NULL = NULL never matches in SQL, so a
        # 'sending' fixture needs a real key for the sweep to find it.
        kwargs["send_idempotency_key"] = "key-1"
    db.update_outreach_entry(entry_id, **kwargs)
    return entry_id


def test_inbox_digest_includes_uncertain_bucket(client):
    db.init_db()
    entry_id = _make_entry(status="uncertain")

    resp = client.get("/api/inbox-digest")

    data = resp.get_json()
    assert "uncertain" in data
    assert data["uncertain"]["count"] == 1
    assert data["uncertain"]["items"][0]["id"] == entry_id


def test_inbox_digest_sweeps_stale_sending_rows_first(client):
    db.init_db()
    entry_id = _make_entry(status="sending")
    db._get_conn().execute(
        "UPDATE outreach_log SET send_attempt_at = datetime('now', '-10 minutes') WHERE id = ?", (entry_id,)
    )
    db._get_conn().commit()

    resp = client.get("/api/inbox-digest")

    data = resp.get_json()
    assert data["uncertain"]["count"] == 1
    row = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "uncertain"


def test_dismiss_uncertain_removes_from_digest_not_status(client):
    db.init_db()
    entry_id = _make_entry(status="uncertain")

    resp = client.post(f"/api/outreach/{entry_id}/dismiss-uncertain")
    assert resp.status_code == 200

    digest = client.get("/api/inbox-digest").get_json()
    assert digest["uncertain"]["count"] == 0
    row = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "uncertain"
