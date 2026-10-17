from datetime import datetime

import api.app as app_module

db = app_module.db
app_module.app.config["TESTING"] = True


def _client(monkeypatch, secret="test-secret"):
    monkeypatch.setenv("SAVED_JOBS_WEBHOOK_SECRET", secret)
    return app_module.app.test_client()


def _touchpoint(scheduled_date, sequence_num=4):
    job_id = db.create_job("Acme", "PM", "eu", source_type="company")
    contact_id = db.create_contact(job_id, "Jane", "hiring_manager")
    return db.create_outreach_entry(
        contact_id, job_id, "email", sequence_num, scheduled_date, "Re: subject", "body",
        provider="gmail",
    )


def test_due_rejects_missing_secret(monkeypatch):
    client = _client(monkeypatch)
    resp = client.get("/api/followups/due")
    assert resp.status_code == 401


def test_due_rejects_wrong_secret(monkeypatch):
    client = _client(monkeypatch, secret="real-secret")
    resp = client.get("/api/followups/due", headers={"X-Webhook-Secret": "wrong"})
    assert resp.status_code == 401


def test_due_returns_numbered_eligible_followup(monkeypatch):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    entry_id = _touchpoint(today)
    client = _client(monkeypatch, secret="real-secret")
    resp = client.get("/api/followups/due", headers={"X-Webhook-Secret": "real-secret"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["date"] == today
    match = next(f for f in body["followups"] if f["touchpoint_id"] == entry_id)
    assert match["position"] >= 1
    assert match["contact_name"] == "Jane"
    assert match["company"] == "Acme"
    assert match["subject"] == "Re: subject"


def test_due_called_twice_does_not_duplicate_entries(monkeypatch):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    entry_id = _touchpoint(today)
    client = _client(monkeypatch, secret="real-secret")
    client.get("/api/followups/due", headers={"X-Webhook-Secret": "real-secret"})
    second = client.get("/api/followups/due", headers={"X-Webhook-Secret": "real-secret"})
    ids = [f["touchpoint_id"] for f in second.get_json()["followups"]]
    assert ids.count(entry_id) == 1
