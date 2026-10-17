import db


def _make_job_contact():
    # ponytail: original helper re-SELECTed by company/email with no ORDER BY,
    # so every test (all inserting the same 'Acme'/'a@acme.com' values) got
    # back row id=1 -- SQLite's unordered first match -- once more than one
    # test had run. cur.lastrowid sidesteps that instead of adding ORDER BY id
    # DESC, which would still be fragile if the WHERE match ever widened.
    conn = db._get_conn()
    cur = conn.execute("INSERT INTO jobs (company, role, geography) VALUES ('ReviewSendCo', 'Eng', 'eu')")
    job_id = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO contacts (job_id, name, contact_type, email) VALUES (?, 'A', 'recruiter', 'a@reviewsendco.com')",
        (job_id,),
    )
    contact_id = cur.lastrowid
    conn.commit()
    return job_id, contact_id


def test_create_outreach_entry_defaults_to_agentmail_provider():
    db.init_db()
    job_id, contact_id = _make_job_contact()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-03", "Hi", "Body")
    row = db._get_conn().execute("SELECT provider FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["provider"] == "agentmail"


def test_get_preceding_email_skips_linkedin_touchpoints():
    """Regression test for the v2 bug: Email 2 (sequence_num=4)'s predecessor
    must resolve to Email 1 (sequence_num=1), not LinkedIn DM (sequence_num=3)."""
    db.init_db()
    job_id, contact_id = _make_job_contact()
    email1_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-03", "S1", "B1")
    db.create_outreach_entry(contact_id, job_id, "linkedin_connect", 2, "2026-10-03", None, "connect")
    db.create_outreach_entry(contact_id, job_id, "linkedin_dm", 3, "2026-10-04", None, "dm")
    db.create_outreach_entry(contact_id, job_id, "email", 4, "2026-10-08", "S2", "B2")

    preceding = db.get_preceding_email(contact_id, 4)
    assert preceding["id"] == email1_id
    assert preceding["sequence_num"] == 1


def test_get_preceding_email_returns_none_for_email_1():
    db.init_db()
    job_id, contact_id = _make_job_contact()
    db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-03", "S1", "B1")
    assert db.get_preceding_email(contact_id, 1) is None


def test_cancel_pending_touchpoints_skips_agentmail_sending_and_uncertain_rows():
    db.init_db()
    job_id, contact_id = _make_job_contact()
    draft_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-03", "S1", "B1")
    sending_id = db.create_outreach_entry(contact_id, job_id, "email", 4, "2026-10-08", "S2", "B2")
    db.update_outreach_entry(sending_id, status="sending")
    uncertain_id = db.create_outreach_entry(contact_id, job_id, "email", 5, "2026-10-15", "S3", "B3")
    db.update_outreach_entry(uncertain_id, status="uncertain")

    cancelled = db.cancel_pending_touchpoints(contact_id)

    cancelled_ids = {row["id"] for row in cancelled}
    assert cancelled_ids == {draft_id}
    conn = db._get_conn()
    assert conn.execute("SELECT status FROM outreach_log WHERE id = ?", (sending_id,)).fetchone()["status"] == "sending"
    assert conn.execute("SELECT status FROM outreach_log WHERE id = ?", (uncertain_id,)).fetchone()["status"] == "uncertain"
    assert conn.execute("SELECT status FROM outreach_log WHERE id = ?", (draft_id,)).fetchone()["status"] == "skipped"


def test_cancel_pending_touchpoints_still_cancels_gmail_draft_for_gmail_provider():
    """Existing Gmail-provider behavior (gmail_draft is cancellable) must be unchanged."""
    db.init_db()
    job_id, contact_id = _make_job_contact()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-03", "S1", "B1", provider="gmail")
    db.update_outreach_entry(entry_id, status="gmail_draft")
    cancelled = db.cancel_pending_touchpoints(contact_id)
    assert {row["id"] for row in cancelled} == {entry_id}


def test_cancel_pending_touchpoints_stamps_outreach_paused_at():
    db.init_db()
    job_id, contact_id = _make_job_contact()
    db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-03", "S1", "B1")

    db.cancel_pending_touchpoints(contact_id)

    row = db._get_conn().execute("SELECT outreach_paused_at FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    assert row["outreach_paused_at"] is not None


def test_cancel_pending_touchpoints_stamps_outreach_paused_at_even_with_nothing_to_cancel():
    """Regression (critical): a contact whose ONLY touchpoint is 'uncertain'
    (not 'draft') has nothing for cancel_pending_touchpoints to actually
    cancel -- by design, Task 2's own cancellation-preserves-evidence rule
    leaves that row alone. But Skip was still clicked, meaning the user
    does not want further contact -- and that 'uncertain' row is exactly
    the one a later /check-status replay (Task 8) could otherwise still
    send through. The stamp must happen regardless of whether anything
    was cancelled, or this column fails at the one job it exists for."""
    db.init_db()
    job_id, contact_id = _make_job_contact()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-03", "S1", "B1")
    db.update_outreach_entry(entry_id, status="uncertain")

    cancelled = db.cancel_pending_touchpoints(contact_id)

    assert cancelled == []  # nothing was draft, so nothing was cancelled...
    row = db._get_conn().execute("SELECT outreach_paused_at FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    assert row["outreach_paused_at"] is not None  # ...but the pause signal must still be set
    # and the uncertain row itself is untouched, per the existing evidence-preservation rule
    entry_row = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert entry_row["status"] == "uncertain"
