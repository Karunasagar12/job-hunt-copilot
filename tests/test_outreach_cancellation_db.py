import db


def _make_job_contact_and_entries(entry_statuses):
    """entry_statuses: list of (channel, sequence_num, status, gmail_draft_id)."""
    job_id = db.create_job("Acme Corp", "PM", "india")
    contact_id = db.create_contact(job_id, "Jane Doe", "hiring_manager")
    entry_ids = []
    for channel, seq, status, draft_id in entry_statuses:
        # provider="gmail" explicit: this file tests Gmail-draft cancellation
        # behavior specifically (gmail_draft_id param throughout) -- the
        # create_outreach_entry default flipped to "agentmail" in Task 2, so
        # without this these rows would no longer be gmail_draft-cancellable.
        eid = db.create_outreach_entry(contact_id, job_id, channel, seq, "2026-07-13", "Subject", "Body", provider="gmail")
        db.update_outreach_entry(eid, status=status, **({"gmail_draft_id": draft_id} if draft_id else {}))
        entry_ids.append(eid)
    return job_id, contact_id, entry_ids


def test_cancel_pending_touchpoints_cancels_draft_and_gmail_draft_rows():
    db.init_db()
    _, contact_id, entry_ids = _make_job_contact_and_entries([
        ("email", 1, "draft", None),
        ("email", 4, "gmail_draft", "gdraft-123"),
    ])
    cancelled = db.cancel_pending_touchpoints(contact_id)
    assert len(cancelled) == 2
    entries = {row["id"]: row for row in db._get_conn().execute(
        "SELECT id, status FROM outreach_log WHERE contact_id = ?", (contact_id,)
    ).fetchall()}
    assert entries[entry_ids[0]]["status"] == "skipped"
    assert entries[entry_ids[1]]["status"] == "skipped"


def test_cancel_pending_touchpoints_leaves_sent_and_skipped_rows_alone():
    db.init_db()
    _, contact_id, entry_ids = _make_job_contact_and_entries([
        ("email", 1, "sent", None),
        ("email", 5, "skipped", None),
        ("email", 4, "draft", None),
    ])
    cancelled = db.cancel_pending_touchpoints(contact_id)
    assert len(cancelled) == 1
    assert cancelled[0]["id"] == entry_ids[2]
    entries = {row["id"]: row["status"] for row in db._get_conn().execute(
        "SELECT id, status FROM outreach_log WHERE contact_id = ?", (contact_id,)
    ).fetchall()}
    assert entries[entry_ids[0]] == "sent"
    assert entries[entry_ids[1]] == "skipped"


def test_cancel_pending_touchpoints_returns_gmail_draft_ids_for_caller_to_delete():
    db.init_db()
    _, contact_id, _ = _make_job_contact_and_entries([
        ("email", 4, "gmail_draft", "gdraft-abc"),
        ("linkedin_dm", 3, "draft", None),
    ])
    cancelled = db.cancel_pending_touchpoints(contact_id)
    draft_ids = [row["gmail_draft_id"] for row in cancelled if row["gmail_draft_id"]]
    assert draft_ids == ["gdraft-abc"]


def test_email_status_column_settable_via_update_contact():
    db.init_db()
    job_id = db.create_job("Acme Corp", "PM", "india")
    contact_id = db.create_contact(job_id, "Jane Doe", "hiring_manager")
    updated = db.update_contact(contact_id, email_status="bounced")
    assert updated["email_status"] == "bounced"
