import pytest
import api.app as app_module

db = app_module.db
app_module.app.config["TESTING"] = True


@pytest.fixture(autouse=True)
def _cleanup():
    """Clear outreach_log before each test to ensure isolation."""
    conn = db._get_conn()
    conn.execute("DELETE FROM outreach_log")
    conn.commit()
    yield
    conn.execute("DELETE FROM outreach_log")
    conn.commit()


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


def test_resolve_rejects_missing_secret(monkeypatch):
    client = _client(monkeypatch)
    resp = client.get("/api/followups/resolve?date=2030-07-01&positions=1")
    assert resp.status_code == 401


def test_resolve_rejects_wrong_secret(monkeypatch):
    client = _client(monkeypatch, secret="real-secret")
    resp = client.get(
        "/api/followups/resolve?date=2030-07-01&positions=1",
        headers={"X-Webhook-Secret": "wrong"},
    )
    assert resp.status_code == 401


def test_resolve_requires_date_and_positions(monkeypatch):
    client = _client(monkeypatch, secret="real-secret")
    resp = client.get(
        "/api/followups/resolve?date=2030-07-01",
        headers={"X-Webhook-Secret": "real-secret"},
    )
    assert resp.status_code == 400


def test_resolve_rejects_non_integer_positions(monkeypatch):
    client = _client(monkeypatch, secret="real-secret")
    resp = client.get(
        "/api/followups/resolve?date=2030-07-01&positions=abc",
        headers={"X-Webhook-Secret": "real-secret"},
    )
    assert resp.status_code == 400


def test_resolve_returns_matching_position(monkeypatch):
    date = "2030-07-02"
    entry_id = _touchpoint(date)
    db.get_and_assign_followup_brief(date)
    client = _client(monkeypatch, secret="real-secret")
    resp = client.get(
        f"/api/followups/resolve?date={date}&positions=1",
        headers={"X-Webhook-Secret": "real-secret"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["followups"]) == 1
    assert body["followups"][0]["touchpoint_id"] == entry_id
    assert body["followups"][0]["position"] == 1


def test_resolve_omits_position_no_longer_draft(monkeypatch):
    date = "2030-07-03"
    entry_id = _touchpoint(date)
    db.get_and_assign_followup_brief(date)
    db.update_outreach_entry(entry_id, status="sent")
    client = _client(monkeypatch, secret="real-secret")
    resp = client.get(
        f"/api/followups/resolve?date={date}&positions=1",
        headers={"X-Webhook-Secret": "real-secret"},
    )
    assert resp.get_json()["followups"] == []
