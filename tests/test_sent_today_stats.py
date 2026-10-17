from datetime import datetime, timedelta

import db


def test_sent_at_recent_includes_recent_email_and_excludes_others():
    db.init_db()
    baseline_count = len(db.get_stats()["sent_at_recent"])
    job_id = db.create_job("Acme Corp", "PM", "india")
    contact_id = db.create_contact(job_id, "Jane Doe", "hiring_manager")

    recent_email_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-07-12", "Subject", "Body")
    recent_sent_at = datetime.utcnow().isoformat()
    db.update_outreach_entry(recent_email_id, status="sent", sent_at=recent_sent_at)

    recent_linkedin_id = db.create_outreach_entry(contact_id, job_id, "linkedin_connect", 2, "2026-07-12", None, "Body")
    db.update_outreach_entry(recent_linkedin_id, status="sent", sent_at=datetime.utcnow().isoformat())

    old_email_id = db.create_outreach_entry(contact_id, job_id, "email", 4, "2026-07-05", "Subject", "Body")
    old_sent_at = (datetime.utcnow() - timedelta(days=5)).isoformat()
    db.update_outreach_entry(old_email_id, status="sent", sent_at=old_sent_at)

    db.create_outreach_entry(contact_id, job_id, "email", 5, "2026-07-19", "Subject", "Body")
    # left at status='draft' — sent_at stays NULL, must never appear

    stats = db.get_stats()
    recent = stats["sent_at_recent"]

    assert all(ts.endswith("Z") for ts in recent), "every timestamp must be unambiguously UTC-tagged"
    assert any(ts.startswith(recent_sent_at) for ts in recent), "recently sent email must be included"
    assert len(recent) == baseline_count + 1, "linkedin channel, old email, and un-sent draft must all be excluded"
