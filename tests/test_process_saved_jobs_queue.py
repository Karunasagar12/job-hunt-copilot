import unittest.mock as mock

import db
from process_saved_jobs_queue import drain_saved_jobs_queue

# ponytail: unique per-run URLs, not magic-shared "900000001"/"900000002" — avoids
# collisions with a lingering pending row from another test in the shared test DB.
URL_FAIL = "https://www.linkedin.com/jobs/view/900000101/"
URL_SUCCESS = "https://www.linkedin.com/jobs/view/900000102/"


def test_one_row_failure_does_not_block_the_rest():
    db.init_db()
    db.queue_saved_job(URL_FAIL, "900000101", "company")
    db.queue_saved_job(URL_SUCCESS, "900000102", "company")

    queued_ids = {
        row["id"]
        for row in db.get_pending_saved_jobs()
        if row["linkedin_job_id"] in ("900000101", "900000102")
    }
    assert len(queued_ids) == 2, "both rows just queued by this test must be pending"

    called_urls = []

    def fake_run_pipeline(job_id, **kwargs):
        called_urls.append(kwargs["jd_url"])
        # real generate.py subprocess transitions new -> generating before cv_ready/failed
        # (see generate.py's _write_db) — the mock must do the same or db.update_job's
        # VALID_TRANSITIONS guard rejects the direct new -> cv_ready/failed jump.
        kwargs["db_update_fn"](job_id, status="generating")
        if kwargs["jd_url"] == URL_FAIL:
            kwargs["db_update_fn"](job_id, status="failed", notes="simulated failure")
        else:
            kwargs["db_update_fn"](job_id, status="cv_ready", ats_score=40.0)

    with mock.patch("process_saved_jobs_queue.run_pipeline", side_effect=fake_run_pipeline):
        drain_saved_jobs_queue()

    # Identify by URL, not by call order/count — a pending row left behind by some
    # other test (alphabetically earlier, sharing the same physical DB_PATH for the
    # whole session) must not be able to shift which call is "first" or "second".
    assert URL_FAIL in called_urls, "row 1 must still be attempted even though it fails"
    assert URL_SUCCESS in called_urls, "a failure on row 1 must not stop row 2 from being attempted"

    still_pending = {row["id"] for row in db.get_pending_saved_jobs()}
    assert queued_ids.isdisjoint(still_pending), "both of this test's rows must be resolved, not left pending"
