#!/usr/bin/env python3
"""Drain queued Telegram saved-job URLs into pipeline runs nightly.

Run on a schedule via systemd timer — see deploy/saved-jobs-queue.service +
deploy/saved-jobs-queue.timer. One row's failure never stops the rest of the batch.
"""
import db
from api.utils import run_pipeline


def drain_saved_jobs_queue() -> int:
    db.init_db()
    rows = db.get_pending_saved_jobs()
    processed = 0

    for row in rows:
        try:
            existing_id = db.job_exists_for_linkedin_id(row["linkedin_job_id"])
            if existing_id is not None:
                db.mark_saved_job_result(row["id"], "duplicate", job_id=existing_id)
                continue

            job_id = db.create_job(
                company="Pending",
                role="Pending",
                geography="gcc",
                source_type=row["source_type"],
                jd_url=row["url"],
            )

            run_pipeline(
                job_id,
                jd_url=row["url"],
                geo="auto",
                source_type=row["source_type"],
                db_update_fn=db.update_job,
            )

            job = db.get_job(job_id) or {}
            if job.get("status") == "cv_ready":
                db.mark_saved_job_result(row["id"], "processed", job_id=job_id)
                processed += 1
            else:
                db.mark_saved_job_result(
                    row["id"], "failed", job_id=job_id, error=job.get("notes")
                )
        except Exception as exc:
            try:
                db.mark_saved_job_result(row["id"], "failed", error=str(exc))
            except Exception as mark_exc:
                print(
                    "process_saved_jobs_queue: failed to mark saved job "
                    f"{row.get('id')} as failed: {mark_exc}"
                )

    return processed


if __name__ == "__main__":
    processed = drain_saved_jobs_queue()
    print(f"process_saved_jobs_queue: processed {processed} row(s)")
