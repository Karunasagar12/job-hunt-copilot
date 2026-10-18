import generate


def test_setup_status_complete_with_fixture(client):
    assert client.get("/api/setup/status").get_json() == {"llm": True, "profile": True, "knowledge": True,
                                                          "complete": True}


def test_job_create_409_when_incomplete(client, monkeypatch):
    monkeypatch.setattr(generate, "setup_missing", lambda: ["knowledge"])
    response = client.post("/api/jobs", json={"jd_text": "x"})
    assert response.status_code == 409 and response.get_json() == {"error": "setup_incomplete", "missing": ["knowledge"],
                                                                  "status": 409}


def test_sourced_job_approve_409_when_incomplete(client, monkeypatch):
    monkeypatch.setattr(generate, "setup_missing", lambda: ["llm", "profile"])
    response = client.post("/api/sourced-jobs/999999/approve")
    assert response.status_code == 409 and response.get_json() == {"error": "setup_incomplete", "missing": ["llm", "profile"],
                                                                  "status": 409}
