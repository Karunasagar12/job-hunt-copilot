"""Tests for job deletion — specifically the two dependent tables that
reference jobs(id) without ON DELETE CASCADE (email_dedup.first_contact_job_id,
saved_jobs_queue.job_id), which used to raise an uncaught FK IntegrityError
and propagate as an unhandled 500."""

import sqlite3

import pytest

import api.app as app_module

db = app_module.db
app_module.app.config["TESTING"] = True


@pytest.fixture
def client():
    with app_module.app.test_client() as c:
        yield c


def test_delete_job_nulls_email_dedup_reference():
    db.init_db()
    job_id = db.create_job("Acme Corp", "PM", "india")
    db.record_email_sent("jane.dedup@acme.example", job_id)

    db.delete_job(job_id)

    row = db._get_conn().execute(
        "SELECT first_contact_job_id FROM email_dedup WHERE email = ?",
        ("jane.dedup@acme.example",),
    ).fetchone()
    assert row is not None, "email_dedup row must survive the job delete"
    assert row["first_contact_job_id"] is None


def test_delete_job_nulls_saved_jobs_queue_reference():
    db.init_db()
    job_id = db.create_job("Beta Inc", "Engineer", "eu")
    db.queue_saved_job("https://linkedin.com/jobs/view/998877", "998877", "company")
    pending = [r for r in db.get_pending_saved_jobs() if r["linkedin_job_id"] == "998877"]
    queue_id = pending[0]["id"]
    db.mark_saved_job_result(queue_id, "done", job_id=job_id)

    db.delete_job(job_id)

    row = db._get_conn().execute(
        "SELECT job_id, status FROM saved_jobs_queue WHERE id = ?", (queue_id,)
    ).fetchone()
    assert row is not None, "saved_jobs_queue row must survive the job delete"
    assert row["job_id"] is None
    assert row["status"] == "done", "only job_id is nulled, the rest of the row is untouched"


def test_delete_job_with_no_dependent_rows_still_works():
    db.init_db()
    job_id = db.create_job("Gamma LLC", "Analyst", "gcc")

    db.delete_job(job_id)

    assert db.get_job(job_id) is None


def test_delete_job_endpoint_returns_204(client):
    job_id = db.create_job("Delta Co", "Designer", "india")

    resp = client.delete(f"/api/jobs/{job_id}")

    assert resp.status_code == 204
    assert db.get_job(job_id) is None


def test_delete_job_endpoint_404_for_missing_job(client):
    resp = client.delete("/api/jobs/999999")
    assert resp.status_code == 404


def test_delete_job_endpoint_returns_409_on_unexpected_integrity_error(client, monkeypatch):
    job_id = db.create_job("Epsilon Ltd", "Recruiter", "eu")

    def _raise(_job_id):
        raise sqlite3.IntegrityError("FOREIGN KEY constraint failed")

    monkeypatch.setattr(app_module.db, "delete_job", _raise)

    resp = client.delete(f"/api/jobs/{job_id}")

    assert resp.status_code == 409
