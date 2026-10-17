import db


def _make_job_and_contact(contact_type="hiring_manager"):
    job_id = db.create_job("Acme Corp", "PM", "india")
    contact_id = db.create_contact(job_id, "Jane Doe", contact_type)
    return job_id, contact_id


def test_is_gmail_message_processed_reflects_recorded_state():
    db.init_db()
    job_id, contact_id = _make_job_and_contact()
    assert db.is_gmail_message_processed("msg-processed-check") is False
    db.record_processed_gmail_message("msg-processed-check", contact_id, job_id, "other")
    assert db.is_gmail_message_processed("msg-processed-check") is True


def test_get_pending_draft_touchpoints_only_returns_draft_status():
    db.init_db()
    job_id, contact_id = _make_job_and_contact()
    draft_id = db.create_outreach_entry(contact_id, job_id, "email", 4, "2026-07-15", "Subject", "Body")
    sent_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-07-10", "Subject", "Body")
    db.update_outreach_entry(sent_id, status="sent")
    pending = db.get_pending_draft_touchpoints(contact_id)
    assert pending == [(draft_id, 4)]


def test_update_touchpoint_dates_bulk_updates_scheduled_date():
    db.init_db()
    job_id, contact_id = _make_job_and_contact()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 4, "2026-07-15", "Subject", "Body")
    db.update_touchpoint_dates([(entry_id, "2026-07-22")])
    entry = db._get_conn().execute("SELECT scheduled_date FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert entry["scheduled_date"] == "2026-07-22"
