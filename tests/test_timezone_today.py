"""Calendar dates follow the profile timezone; event timestamps remain UTC."""

from datetime import date, datetime, timezone
from pathlib import Path
import re
import sqlite3

import pytest

import api.app as api
import db
import outreach_manager
import profile as prof


@pytest.fixture
def database(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    monkeypatch.setattr(db, "_get_conn", lambda: conn)
    db.init_db()
    yield conn
    conn.close()


def _entry(scheduled_date, provider="gmail"):
    job_id = db.create_job("Acme", "Engineer", "eu", source_type="company")
    contact_id = db.create_contact(job_id, "Alex Smith", "recruiter", email="alex@example.com")
    entry_id = db.create_outreach_entry(
        contact_id, job_id, "email", 4, scheduled_date, "Follow up", "Hello Alex",
        provider=provider,
    )
    return entry_id, job_id, contact_id


@pytest.fixture
def dubai_midnight(monkeypatch):
    p = prof.load_profile()
    p["timezone"] = "Asia/Dubai"
    monkeypatch.setattr(prof, "load_profile", lambda: p)
    today_local = prof.today_local
    # Monday evening UTC is already Tuesday in the configured profile.
    instant = datetime(2030, 6, 3, 22, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(prof, "today_local", lambda: today_local(now=instant))
    return date(2030, 6, 4)


def test_followups_default_queries_profile_day(database, monkeypatch):
    monkeypatch.setattr(prof, "today_local", lambda: date(2026, 10, 18))
    due, _, _ = _entry("2026-10-18")
    future, _, _ = _entry("2026-10-19")
    assert [item["id"] for item in db.get_followups_due()] == [due]
    assert future not in [item["id"] for item in db.get_followups_due()]


def test_due_and_brief_use_local_day_after_utc_midnight_boundary(database, dubai_midnight):
    due, _, _ = _entry("2030-06-04")
    _entry("2030-06-05")
    assert [item["id"] for item in db.get_followups_due()] == [due]
    assert [item["id"] for item in db.get_and_assign_followup_brief()] == [due]
    row = database.execute("SELECT brief_sent_date, brief_position FROM outreach_log WHERE id = ?", (due,)).fetchone()
    assert tuple(row) == ("2030-06-04", 1)


@pytest.mark.parametrize("query", [db.get_followups_due, db.get_and_assign_followup_brief])
def test_explicit_due_date_overrides_profile_day(database, dubai_midnight, query):
    due, _, _ = _entry("2030-06-03")
    _entry("2030-06-04")
    assert [item["id"] for item in query("2030-06-03")] == [due]


def test_followups_endpoint_reports_and_assigns_local_day(database, dubai_midnight, client, monkeypatch):
    monkeypatch.setenv("SAVED_JOBS_WEBHOOK_SECRET", "test-secret")
    due, _, _ = _entry("2030-06-04")
    _entry("2030-06-05")
    response = client.get("/api/followups/due", headers={"X-Webhook-Secret": "test-secret"})
    assert response.status_code == 200
    assert response.json["date"] == "2030-06-04"
    assert [item["touchpoint_id"] for item in response.json["followups"]] == [due]


def test_outreach_default_schedule_starts_on_profile_day(dubai_midnight):
    entries = outreach_manager.parse_and_schedule("", [{"id": 1, "name": "Alex Smith"}])
    assert [item["scheduled_date"] for item in entries] == [
        "2030-06-04", "2030-06-04", "2030-06-05", "2030-06-10", "2030-06-17",
    ]


@pytest.mark.parametrize("start", [date(2030, 6, 3), datetime(2030, 6, 3, 9)])
def test_explicit_schedule_base_overrides_profile_day(dubai_midnight, start):
    entries = outreach_manager.parse_and_schedule("", [{"id": 1, "name": "Alex Smith"}], start)
    assert [item["scheduled_date"] for item in entries] == [
        "2030-06-03", "2030-06-03", "2030-06-04", "2030-06-10", "2030-06-17",
    ]


def test_start_outreach_persists_profile_day_schedule(database, dubai_midnight, client):
    job_id = db.create_job("Acme", "Engineer", "eu", source_type="company")
    db.update_job(job_id, outreach_raw="CONTACT: Alex Smith\n")
    db.create_contact(job_id, "Alex Smith", "recruiter")
    response = client.post(f"/api/jobs/{job_id}/outreach/start")
    assert response.status_code == 200
    assert response.json["created"] == 5
    rows = database.execute("SELECT scheduled_date FROM outreach_log ORDER BY sequence_num").fetchall()
    assert [row[0] for row in rows] == [
        "2030-06-04", "2030-06-04", "2030-06-05", "2030-06-10", "2030-06-17",
    ]


def test_prepare_and_send_followup_due_on_local_day(database, dubai_midnight, client, monkeypatch):
    due, job_id, contact_id = _entry("2030-06-04", provider="agentmail")
    preceding = db.create_outreach_entry(contact_id, job_id, "email", 1, "2030-06-03", "Hello", "Hello Alex")
    db.update_outreach_entry(preceding, status="sent", agentmail_message_id="first-message")
    import gmail_client
    monkeypatch.setattr(gmail_client, "_get_signature", lambda geo: "")
    sends = []

    def send(*args, **kwargs):
        sends.append((args, kwargs))
        return {"message_id": "followup-message", "thread_id": "thread"}

    monkeypatch.setattr(api.agentmail_client, "send_email", send)
    prepared = client.post(f"/api/outreach/{due}/prepare")
    assert prepared.status_code == 200
    assert prepared.json["can_send"] is True
    response = client.post(f"/api/outreach/{due}/send", json={"fingerprint": prepared.json["fingerprint"]})
    assert response.status_code == 200
    assert response.json["status"] == "sent"
    assert len(sends) == 1
    assert database.execute("SELECT status FROM outreach_log WHERE id = ?", (due,)).fetchone()[0] == "sent"


@pytest.mark.parametrize("filename", ["api/app.py", "db.py", "outreach_manager.py"])
def test_scheduling_modules_have_no_machine_or_utc_calendar_today(filename):
    source = (Path(__file__).resolve().parents[1] / filename).read_text(encoding="utf-8")
    assert not re.search(r"utcnow\(\)\.date\(\)|utcnow\(\)\.strftime\([\"']%Y-%m-%d[\"']\)|date\.today\(\)", source)
