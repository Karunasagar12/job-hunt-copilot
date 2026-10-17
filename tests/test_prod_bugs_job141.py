"""Regressions for the three job #141 (ExampleCo, Vienna) production bugs, October 2026."""
import api.app as app_module
import generate

db = app_module.db
app_module.app.config["TESTING"] = True


def test_detect_geo_vienna_austria_is_eu():
    # Job #141's JD said "Vienna, Austria" and matched no keyword, so it
    # fell through to the "gcc" default.
    assert generate.detect_geo("Growth PM\nExampleCo\nVienna, Austria\n", "auto") == "eu"


def test_start_outreach_concurrent_second_request_rejected(monkeypatch):
    # Job #141: a second /outreach/start arrived during the first one's
    # ~20s LLM generation, passed the "already started?" check, and every
    # touchpoint got created twice.
    client = app_module.app.test_client()
    job_id = db.create_job("ExampleCo", "PM", "eu")
    contact_id = db.create_contact(job_id, "Alex", "executive")
    touchpoint = {
        "contact_id": contact_id, "channel": "email", "sequence_num": 1,
        "scheduled_date": "2026-10-12", "subject": "S", "content": "B",
    }
    inner = []

    def slow_unmatched(raw, contacts):
        # Simulates the second request landing mid-generation.
        inner.append(client.post(f"/api/jobs/{job_id}/outreach/start").status_code)
        return []

    monkeypatch.setattr(app_module.outreach_manager, "get_unmatched_contacts", slow_unmatched)
    monkeypatch.setattr(app_module.outreach_manager, "parse_and_schedule", lambda raw, contacts: [touchpoint])

    resp = client.post(f"/api/jobs/{job_id}/outreach/start")

    assert resp.status_code == 200
    assert inner == [409]
    count = db._get_conn().execute(
        "SELECT COUNT(*) FROM outreach_log WHERE job_id = ?", (job_id,)
    ).fetchone()[0]
    assert count == 1
