import db


def test_outreach_log_has_agentmail_columns():
    db.init_db()
    conn = db._get_conn()
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(outreach_log)").fetchall()}
    for col in ("provider", "agentmail_message_id", "agentmail_thread_id",
                "send_idempotency_key", "send_attempt_at", "uncertain_dismissed_at"):
        assert col in cols, f"missing column {col}"


def test_contacts_has_outreach_paused_at_column():
    db.init_db()
    conn = db._get_conn()
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(contacts)").fetchall()}
    assert "outreach_paused_at" in cols


def test_existing_rows_backfill_as_gmail_provider():
    db.init_db()
    conn = db._get_conn()
    conn.execute(
        "INSERT INTO jobs (company, role, geography) VALUES ('Acme', 'Eng', 'eu')"
    )
    job_id = conn.execute("SELECT id FROM jobs WHERE company='Acme'").fetchone()["id"]
    conn.execute(
        "INSERT INTO contacts (job_id, name, email, contact_type) VALUES (?, 'A', 'a@acme.com', 'recruiter')",
        (job_id,),
    )
    contact_id = conn.execute("SELECT id FROM contacts WHERE email='a@acme.com'").fetchone()["id"]
    # Simulate a pre-migration row inserted before `provider` had a default by
    # inserting without specifying it -- it must come back 'gmail', not NULL
    # or 'agentmail', since ALTER TABLE ... DEFAULT 'gmail' backfills history.
    conn.execute(
        "INSERT INTO outreach_log (contact_id, job_id, channel, sequence_num) VALUES (?, ?, 'email', 1)",
        (contact_id, job_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT provider FROM outreach_log WHERE contact_id = ?", (contact_id,)
    ).fetchone()
    assert row["provider"] == "gmail"


def test_outreach_send_attempts_table_exists():
    db.init_db()
    conn = db._get_conn()
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(outreach_send_attempts)").fetchall()}
    for col in ("id", "outreach_log_id", "idempotency_key", "attempt_at", "endpoint",
                "reply_to_message_id", "recipient_email", "subject", "text_body", "html_body",
                "inbox_id", "cv_filename", "cv_base64", "cv_file_hash", "resolved_status", "resolved_at",
                "agentmail_message_id", "agentmail_thread_id"):
        assert col in cols, f"missing column {col}"
