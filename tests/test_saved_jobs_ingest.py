import os
import tempfile

import api.app as app_module  # noqa: E402

app_module.app.config["TESTING"] = True


def _client(monkeypatch, secret="test-secret"):
    monkeypatch.setenv("SAVED_JOBS_WEBHOOK_SECRET", secret)
    return app_module.app.test_client()


def test_ingest_rejects_missing_secret(monkeypatch):
    client = _client(monkeypatch)
    resp = client.post("/api/saved-jobs/ingest", json={"url": "https://www.linkedin.com/jobs/view/123/"})
    assert resp.status_code == 401


def test_ingest_rejects_wrong_secret(monkeypatch):
    client = _client(monkeypatch)
    resp = client.post(
        "/api/saved-jobs/ingest",
        json={"url": "https://www.linkedin.com/jobs/view/123/"},
        headers={"X-Webhook-Secret": "wrong"},
    )
    assert resp.status_code == 401


def test_ingest_rejects_non_linkedin_url(monkeypatch):
    client = _client(monkeypatch)
    resp = client.post(
        "/api/saved-jobs/ingest",
        json={"url": "https://example.com/not-a-job"},
        headers={"X-Webhook-Secret": "test-secret"},
    )
    assert resp.status_code == 400


def test_ingest_queues_new_url(monkeypatch):
    client = _client(monkeypatch)
    resp = client.post(
        "/api/saved-jobs/ingest",
        json={"url": "https://www.linkedin.com/jobs/view/555666777/", "source_type": "company"},
        headers={"X-Webhook-Secret": "test-secret"},
    )
    assert resp.status_code == 202
    assert resp.get_json()["status"] == "queued"


def test_ingest_flags_duplicate(monkeypatch):
    client = _client(monkeypatch)
    headers = {"X-Webhook-Secret": "test-secret"}
    client.post(
        "/api/saved-jobs/ingest",
        json={"url": "https://www.linkedin.com/jobs/view/888999000/", "source_type": "company"},
        headers=headers,
    )
    resp = client.post(
        "/api/saved-jobs/ingest",
        json={"url": "https://www.linkedin.com/jobs/view/888999000/?utm_source=li_share", "source_type": "company"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "duplicate"


def test_ingest_rejects_missing_source_type(monkeypatch):
    client = _client(monkeypatch)
    resp = client.post(
        "/api/saved-jobs/ingest",
        json={"url": "https://www.linkedin.com/jobs/view/222333444/"},
        headers={"X-Webhook-Secret": "test-secret"},
    )
    assert resp.status_code == 400


def test_ingest_rejects_invalid_source_type(monkeypatch):
    client = _client(monkeypatch)
    resp = client.post(
        "/api/saved-jobs/ingest",
        json={"url": "https://www.linkedin.com/jobs/view/222333555/", "source_type": "bogus"},
        headers={"X-Webhook-Secret": "test-secret"},
    )
    assert resp.status_code == 400
