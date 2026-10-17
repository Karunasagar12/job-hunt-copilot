"""sourced_jobs / sourcing_runs DB layer (job-sourcing spec sections 1 + 4)."""
import sqlite3

import pytest

import db

db.init_db()


def _fields(lid, **over):
    f = {
        "linkedin_job_id": lid, "run_id": None, "title": "AI Product Manager",
        "company": "Acme", "location": "Dubai, United Arab Emirates",
        "url": f"https://www.linkedin.com/jobs/view/{lid}/", "jd_text": "x" * 400,
        "geo": "gcc", "search_location": "United Arab Emirates", "posted_at": "2026-10-12",
        "is_agency": 0, "filter_reason": None, "fit_score": 70,
        "reasons": ["Healthcare AI"], "concerns": [], "status": "new",
    }
    f.update(over)
    return f


def _reset():
    conn = db._get_conn()
    conn.execute("DELETE FROM sourced_jobs")
    conn.execute("DELETE FROM sourcing_runs")
    conn.commit()


def test_run_lifecycle_and_latest():
    _reset()
    rid = db.start_sourcing_run("past_24h")
    db.finish_sourcing_run(rid, "partial", [{"location": "Qatar", "status": "failed"}], 0.0194)
    latest = db.get_latest_sourcing_run()
    assert latest["id"] == rid and latest["outcome"] == "partial"
    assert latest["date_window"] == "past_24h"
    assert latest["locations"] == [{"location": "Qatar", "status": "failed"}]
    assert latest["finished_at"] is not None
    assert db.last_good_finished_by_location() == {}   # Qatar failed


def test_failed_run_is_not_a_good_run():
    _reset()
    rid = db.start_sourcing_run("past_24h")
    db.finish_sourcing_run(rid, "failed", [], 0)
    assert db.last_good_finished_by_location() == {}
    assert db.get_latest_sourcing_run()["outcome"] == "failed"


def test_last_good_is_tracked_per_location():
    """Germany failing while France succeeds must not reset Germany's clock."""
    _reset()
    r1 = db.start_sourcing_run("past_24h")
    db.finish_sourcing_run(r1, "success", [{"location": "France", "status": "ok"},
                                           {"location": "Germany", "status": "ok"}], 0.04)
    first = db.get_latest_sourcing_run()["finished_at"]
    db._get_conn().execute("UPDATE sourcing_runs SET finished_at = '2026-10-11 00:40:00' WHERE id = ?", (r1,))
    db._get_conn().commit()
    r2 = db.start_sourcing_run("past_24h")
    db.finish_sourcing_run(r2, "partial", [{"location": "France", "status": "charge_limited"},
                                           {"location": "Germany", "status": "failed", "error": "x"}], 0.02)
    second = db.get_latest_sourcing_run()["finished_at"]
    assert first and second
    assert db.last_good_finished_by_location() == {"France": second, "Germany": "2026-10-11 00:40:00"}


def test_insert_is_idempotent_on_linkedin_id():
    _reset()
    assert db.insert_sourced_job(_fields("9100000001")) is not None
    assert db.insert_sourced_job(_fields("9100000001", title="Other")) is None


def test_insert_raises_on_non_duplicate_constraint_violation():
    """Only a duplicate LinkedIn ID is ignored; NOT NULL violations must surface."""
    _reset()
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_sourced_job(_fields("9100000006", title=None))


def test_seen_checks_sourced_jobs_queue_and_jobs():
    _reset()
    db.insert_sourced_job(_fields("9100000002"))
    assert db.sourced_job_seen("9100000002")
    db.queue_saved_job("https://www.linkedin.com/jobs/view/9100000003/", "9100000003", "company")
    assert db.sourced_job_seen("9100000003")
    db.create_job("Acme", "PM", "gcc", jd_url="https://www.linkedin.com/jobs/view/9100000004/")
    assert db.sourced_job_seen("9100000004")
    assert not db.sourced_job_seen("9100000005")


def test_list_orders_by_score_nulls_last_and_filters_geo():
    _reset()
    db.insert_sourced_job(_fields("9100000010", fit_score=40))
    db.insert_sourced_job(_fields("9100000011", fit_score=None, concerns=["scoring failed"]))
    db.insert_sourced_job(_fields("9100000012", fit_score=90))
    db.insert_sourced_job(_fields("9100000013", fit_score=99, geo="eu"))
    rows = db.get_sourced_jobs(["new"], geo="gcc")
    assert [r["linkedin_job_id"] for r in rows] == ["9100000012", "9100000010", "9100000011"]
    assert rows[0]["reasons"] == ["Healthcare AI"] and rows[2]["concerns"] == ["scoring failed"]
    assert rows[0]["job_status"] is None


def test_list_omits_jd_text_except_for_new_rows():
    _reset()
    db.insert_sourced_job(_fields("9100000030"))
    db.insert_sourced_job(_fields("9100000031", status="filtered", fit_score=None))
    rows = {r["linkedin_job_id"]: r for r in db.get_sourced_jobs(["new", "filtered"])}
    assert rows["9100000030"]["jd_text"] == "x" * 400
    assert rows["9100000031"]["jd_text"] is None


def test_sweep_expires_new_and_deletes_old_rows():
    _reset()
    conn = db._get_conn()
    db.insert_sourced_job(_fields("9100000020"))                          # old new -> expired
    db.insert_sourced_job(_fields("9100000021", status="filtered"))       # old filtered -> deleted
    db.insert_sourced_job(_fields("9100000022"))                          # fresh new -> untouched
    conn.execute("UPDATE sourced_jobs SET created_at = datetime('now','-8 days') WHERE linkedin_job_id = '9100000020'")
    conn.execute("UPDATE sourced_jobs SET created_at = datetime('now','-31 days'), updated_at = datetime('now','-31 days') "
                 "WHERE linkedin_job_id = '9100000021'")
    old_run = db.start_sourcing_run("past_24h")
    conn.execute("UPDATE sourcing_runs SET started_at = datetime('now','-91 days') WHERE id = ?", (old_run,))
    conn.commit()
    out = db.sweep_sourced_jobs()
    assert out == {"expired": 1, "deleted": 1, "runs_deleted": 1}
    statuses = {r["linkedin_job_id"]: r["status"] for r in conn.execute("SELECT * FROM sourced_jobs")}
    assert statuses == {"9100000020": "expired", "9100000022": "new"}


def _job_count():
    return db._get_conn().execute("SELECT COUNT(*) FROM jobs").fetchone()[0]


def test_approve_creates_job_with_row_geo_and_canonical_url():
    _reset()
    sid = db.insert_sourced_job(_fields("9200000001", geo="eu"))
    out = db.approve_sourced_job(sid)
    assert out["created"] is True
    job = db.get_job(out["job_id"])
    assert job["geography"] == "eu" and job["source_type"] == "company"
    assert job["jd_url"] == "https://www.linkedin.com/jobs/view/9200000001/"
    assert job["company"] == "Pending" and job["status"] == "new"
    row = db.get_sourced_jobs(["approved"])[0]
    assert row["job_id"] == out["job_id"] and row["owns_job"] == 1


def test_approve_agency_becomes_recruiter():
    _reset()
    sid = db.insert_sourced_job(_fields("9200000002", is_agency=1))
    job = db.get_job(db.approve_sourced_job(sid)["job_id"])
    assert job["source_type"] == "recruiter"


def test_repeat_approve_returns_same_job_without_creating():
    _reset()
    sid = db.insert_sourced_job(_fields("9200000003"))
    first = db.approve_sourced_job(sid)
    before = _job_count()
    second = db.approve_sourced_job(sid)
    assert second == {"job_id": first["job_id"], "created": False}
    assert _job_count() == before


def test_approve_links_existing_job_from_another_entry_path():
    _reset()
    sid = db.insert_sourced_job(_fields("9200000004"))
    existing = db.create_job("Acme", "PM", "gcc", jd_url="https://www.linkedin.com/jobs/view/9200000004/")
    before = _job_count()
    out = db.approve_sourced_job(sid)
    assert out == {"job_id": existing, "created": False}
    assert _job_count() == before
    assert db.get_sourced_jobs(["approved"])[0]["owns_job"] == 0


def test_approve_rejects_passed_and_missing_rows():
    _reset()
    sid = db.insert_sourced_job(_fields("9200000005"))
    assert db.pass_sourced_job(sid, "wrong_domain") is True
    with pytest.raises(ValueError):
        db.approve_sourced_job(sid)
    with pytest.raises(LookupError):
        db.approve_sourced_job(999999)


def test_failure_between_insert_and_update_commits_nothing():
    _reset()
    sid = db.insert_sourced_job(_fields("9200000006"))
    conn = db._get_conn()
    conn.execute("CREATE TEMP TRIGGER fail_approve BEFORE UPDATE ON sourced_jobs "
                 "BEGIN SELECT RAISE(ABORT, 'boom'); END")
    before = _job_count()
    with pytest.raises(sqlite3.DatabaseError):
        db.approve_sourced_job(sid)
    conn.execute("DROP TRIGGER fail_approve")
    assert _job_count() == before
    assert db.get_sourced_jobs(["new"])[0]["id"] == sid
    out = db.approve_sourced_job(sid)
    assert out["created"] is True and _job_count() == before + 1


def test_pass_stores_reason_and_only_from_new():
    _reset()
    sid = db.insert_sourced_job(_fields("9200000007"))
    assert db.pass_sourced_job(sid, "language") is True
    assert db.get_sourced_jobs(["passed"])[0]["pass_reason"] == "language"
    assert db.pass_sourced_job(sid, None) is False


def test_recovery_lists_only_owned_unfinished_jobs():
    _reset()
    owned = db.approve_sourced_job(db.insert_sourced_job(_fields("9200000008")))["job_id"]
    db.create_job("Acme", "PM", "gcc", jd_url="https://www.linkedin.com/jobs/view/9200000009/")
    db.approve_sourced_job(db.insert_sourced_job(_fields("9200000009")))   # linked, not owned
    done = db.approve_sourced_job(db.insert_sourced_job(_fields("9200000010")))["job_id"]
    db.update_job(done, status="generating")
    db.update_job(done, status="cv_ready")
    ids = [j["id"] for j in db.get_sourced_jobs_needing_recovery()]
    assert ids == [owned]


def test_delete_job_nulls_sourced_link():
    _reset()
    sid = db.insert_sourced_job(_fields("9200000011"))
    job_id = db.approve_sourced_job(sid)["job_id"]
    db.delete_job(job_id)
    assert db.get_sourced_jobs(["approved"])[0]["job_id"] is None


def test_stats_counts_shortlist_new():
    _reset()
    db.insert_sourced_job(_fields("9200000012"))
    db.insert_sourced_job(_fields("9200000013", status="filtered"))
    assert db.get_stats()["shortlist_new"] == 1
