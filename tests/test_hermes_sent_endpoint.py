import api.app as app_module

db = app_module.db
app_module.app.config["TESTING"] = True


def _client(monkeypatch, secret="test-secret"):
    monkeypatch.setenv("SAVED_JOBS_WEBHOOK_SECRET", secret)
    return app_module.app.test_client()


def _make_touchpoint():
    job_id = db.create_job("Acme", "PM", "eu", source_type="company")
    contact_id = db.create_contact(job_id, "Jane", "hiring_manager")
    return db.create_outreach_entry(
        contact_id, job_id, "email", 4, "2026-08-09", "Re: subject", "body",
        provider="gmail",
    )


def test_hermes_sent_rejects_missing_secret(monkeypatch):
    client = _client(monkeypatch)
    entry_id = _make_touchpoint()
    resp = client.post(f"/api/outreach/{entry_id}/hermes-sent", json={"gmail_message_id": "m1"})
    assert resp.status_code == 401


def test_hermes_sent_rejects_wrong_secret(monkeypatch):
    client = _client(monkeypatch, secret="real-secret")
    entry_id = _make_touchpoint()
    resp = client.post(
        f"/api/outreach/{entry_id}/hermes-sent",
        json={"gmail_message_id": "m1"},
        headers={"X-Webhook-Secret": "wrong-secret"},
    )
    assert resp.status_code == 401


def test_hermes_sent_requires_gmail_message_id(monkeypatch):
    client = _client(monkeypatch, secret="real-secret")
    entry_id = _make_touchpoint()
    resp = client.post(
        f"/api/outreach/{entry_id}/hermes-sent",
        json={},
        headers={"X-Webhook-Secret": "real-secret"},
    )
    assert resp.status_code == 400


def test_hermes_sent_404s_for_unknown_touchpoint(monkeypatch):
    client = _client(monkeypatch, secret="real-secret")
    resp = client.post(
        "/api/outreach/999999/hermes-sent",
        json={"gmail_message_id": "m1", "gmail_thread_id": "t1"},
        headers={"X-Webhook-Secret": "real-secret"},
    )
    assert resp.status_code == 404


def test_hermes_sent_marks_touchpoint_sent_with_message_and_thread_id(monkeypatch):
    client = _client(monkeypatch, secret="real-secret")
    entry_id = _make_touchpoint()
    resp = client.post(
        f"/api/outreach/{entry_id}/hermes-sent",
        json={"gmail_message_id": "m1", "gmail_thread_id": "t1"},
        headers={"X-Webhook-Secret": "real-secret"},
    )
    assert resp.status_code == 200
    updated = db._get_conn().execute(
        "SELECT * FROM outreach_log WHERE id = ?", (entry_id,)
    ).fetchone()
    assert updated["status"] == "sent"
    assert updated["gmail_message_id"] == "m1"
    assert updated["gmail_thread_id"] == "t1"
    assert updated["sent_at"] is not None


def test_hermes_sent_is_idempotent_on_repeated_calls(monkeypatch):
    client = _client(monkeypatch, secret="real-secret")
    entry_id = _make_touchpoint()
    headers = {"X-Webhook-Secret": "real-secret"}
    body = {"gmail_message_id": "m1", "gmail_thread_id": "t1"}
    first = client.post(f"/api/outreach/{entry_id}/hermes-sent", json=body, headers=headers)
    second = client.post(f"/api/outreach/{entry_id}/hermes-sent", json=body, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200


def test_hermes_sent_clears_brief_assignment(monkeypatch):
    client = _client(monkeypatch, secret="real-secret")
    entry_id = _make_touchpoint()
    db.update_outreach_entry(entry_id, brief_sent_date="2030-08-01", brief_position=1)
    resp = client.post(
        f"/api/outreach/{entry_id}/hermes-sent",
        json={"gmail_message_id": "m1", "gmail_thread_id": "t1"},
        headers={"X-Webhook-Secret": "real-secret"},
    )
    assert resp.status_code == 200
    row = db._get_conn().execute(
        "SELECT brief_sent_date, brief_position FROM outreach_log WHERE id = ?", (entry_id,)
    ).fetchone()
    assert row["brief_sent_date"] is None
    assert row["brief_position"] is None
