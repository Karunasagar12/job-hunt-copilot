"""Shortlist API (job-sourcing spec sections 3 + 4)."""
import api.app as app_module

db = app_module.db
app_module.app.config["TESTING"] = True
client = app_module.app.test_client()


def _new_row(lid, **over):
    f = {"linkedin_job_id": lid, "title": "AI PM", "company": "Acme", "location": "Paris, France",
         "url": f"https://www.linkedin.com/jobs/view/{lid}/", "jd_text": "x" * 400, "geo": "eu",
         "search_location": "France", "is_agency": 0, "fit_score": 60, "reasons": ["r"], "concerns": [],
         "status": "new"}
    f.update(over)
    return db.insert_sourced_job(f)


def _reset():
    conn = db._get_conn()
    conn.execute("DELETE FROM sourced_jobs")
    conn.execute("DELETE FROM sourcing_runs")
    conn.commit()


def test_list_and_validation():
    _reset()
    _new_row("9400000001")
    _new_row("9400000002", geo="gcc")
    assert [r["linkedin_job_id"] for r in client.get("/api/sourced-jobs?geo=eu").get_json()] == ["9400000001"]
    assert len(client.get("/api/sourced-jobs").get_json()) == 2
    assert client.get("/api/sourced-jobs?status=bogus").status_code == 400
    assert client.get("/api/sourced-jobs?geo=us").status_code == 400


def test_latest_run_null_then_present():
    _reset()
    assert client.get("/api/sourced-jobs/runs/latest").get_json() is None
    rid = db.start_sourcing_run("past_24h")
    db.finish_sourcing_run(rid, "success", [{"location": "France", "status": "ok"}], 0.01)
    body = client.get("/api/sourced-jobs/runs/latest").get_json()
    assert body["id"] == rid and body["locations"][0]["location"] == "France"


def test_approve_dispatches_once_and_repeat_does_not(monkeypatch):
    _reset()
    calls = []
    monkeypatch.setattr(app_module, "run_pipeline_async", lambda job_id, **kw: calls.append((job_id, kw)))
    sid = _new_row("9400000003")
    first = client.post(f"/api/sourced-jobs/{sid}/approve")
    assert first.status_code == 200 and first.get_json()["created"] is True
    job_id = first.get_json()["job_id"]
    assert calls == [(job_id, {"jd_url": "https://www.linkedin.com/jobs/view/9400000003/", "geo": "eu",
                               "source_type": "company", "db_update_fn": db.update_job})]
    again = client.post(f"/api/sourced-jobs/{sid}/approve")
    assert again.get_json() == {"job_id": job_id, "created": False, "dispatch_failed": False}
    assert len(calls) == 1


def test_approve_existing_job_links_without_dispatch(monkeypatch):   # Review Focus 5
    _reset()
    calls = []
    monkeypatch.setattr(app_module, "run_pipeline_async", lambda job_id, **kw: calls.append(job_id))
    sid = _new_row("9400000004")
    existing = db.create_job("Acme", "PM", "eu", jd_url="https://www.linkedin.com/jobs/view/9400000004/")
    body = client.post(f"/api/sourced-jobs/{sid}/approve").get_json()
    assert body == {"job_id": existing, "created": False, "dispatch_failed": False} and calls == []


def test_approve_dispatch_failure_still_returns_job(monkeypatch):
    _reset()
    def boom(job_id, **kw):
        raise RuntimeError("thread start failed")
    monkeypatch.setattr(app_module, "run_pipeline_async", boom)
    sid = _new_row("9400000005")
    resp = client.post(f"/api/sourced-jobs/{sid}/approve")
    assert resp.status_code == 200 and resp.get_json()["dispatch_failed"] is True
    job_id = resp.get_json()["job_id"]
    assert db.get_job(job_id)["status"] == "new"
    assert job_id in [j["id"] for j in db.get_sourced_jobs_needing_recovery()]
    # Plan review item 5: Approve again retries the SAME job while the API keeps running.
    calls = []
    monkeypatch.setattr(app_module, "run_pipeline_async", lambda jid, **kw: calls.append(jid))
    retry = client.post(f"/api/sourced-jobs/{sid}/approve").get_json()
    assert retry == {"job_id": job_id, "created": False, "dispatch_failed": False} and calls == [job_id]
    client.post(f"/api/sourced-jobs/{sid}/approve")
    assert calls == [job_id]          # already dispatched in this process -> not again


def test_approve_404_and_409():
    _reset()
    assert client.post("/api/sourced-jobs/999999/approve").status_code == 404
    sid = _new_row("9400000006")
    client.post(f"/api/sourced-jobs/{sid}/pass", json={})
    assert client.post(f"/api/sourced-jobs/{sid}/approve").status_code == 409


def test_pass_reason_validation_and_409():
    _reset()
    sid = _new_row("9400000007")
    assert client.post(f"/api/sourced-jobs/{sid}/pass", json={"reason": "nope"}).status_code == 400
    assert client.post(f"/api/sourced-jobs/{sid}/pass", json={"reason": "wrong_seniority"}).status_code == 200
    assert client.post(f"/api/sourced-jobs/{sid}/pass", json={}).status_code == 409


def test_startup_recovery_redispatches_owned_unfinished(monkeypatch):
    _reset()
    calls = []
    monkeypatch.setattr(app_module, "run_pipeline_async", lambda job_id, **kw: calls.append(job_id))
    job_id = db.approve_sourced_job(_new_row("9400000008"))["job_id"]
    calls.clear()
    assert app_module.recover_sourced_generations() >= 1
    assert job_id in calls
