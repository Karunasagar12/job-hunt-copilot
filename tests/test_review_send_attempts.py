import pytest

import db


@pytest.fixture(autouse=True)
def _isolated_db():
    # ponytail: this suite has no per-test DB reset (conftest.py only wipes
    # the file once per pytest process), and several tests below reuse the
    # literal idempotency key "key-1" -- which collides with
    # outreach_send_attempts.idempotency_key's UNIQUE constraint the moment
    # two test functions both successfully claim with it. Clearing out this
    # file's own 'Acme' jobs before every test restores real per-test
    # isolation instead of asking each test to mint unique keys/companies.
    # Scoped to company='Acme' (every fixture call in this file, default or
    # explicit) rather than wiping the whole jobs table -- other test files
    # sharing this same DB leave jobs referenced by email_dedup/
    # saved_jobs_queue, which don't cascade-delete (db.delete_job nulls
    # those out manually); an unscoped wipe would FK-fail against them.
    # contacts/outreach_log/outreach_send_attempts all cascade from jobs.
    db.init_db()
    conn = db._get_conn()
    conn.execute("DELETE FROM jobs WHERE company = 'Acme'")
    conn.commit()
    yield
    # Also clean up afterward: other test files (e.g.
    # test_review_send_schema.py) share this same DB and unluckily use the
    # identical unscoped "SELECT ... WHERE company='Acme'" pattern this file
    # used to have -- leaving a residual 'Acme' row here would make an
    # unrelated file in a later collection position pick up the wrong row.
    conn.execute("DELETE FROM jobs WHERE company = 'Acme'")
    conn.commit()


def _make_job_contact(company="Acme"):
    # ponytail: lastrowid instead of a re-SELECT-by-company -- same fix as
    # tests/test_review_send_db.py's _make_job_contact, see its comment.
    conn = db._get_conn()
    cur = conn.execute("INSERT INTO jobs (company, role, geography) VALUES (?, 'Eng', 'eu')", (company,))
    job_id = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO contacts (job_id, name, contact_type, email) VALUES (?, 'A', 'hiring_manager', ?)",
        (job_id, f"a@{company.lower()}.com"),
    )
    contact_id = cur.lastrowid
    conn.commit()
    return job_id, contact_id


def _make_job_contact_entry(status="sending"):
    job_id, contact_id = _make_job_contact()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-03", "S", "B")
    db.update_outreach_entry(entry_id, status=status, send_idempotency_key="key-1",
                              send_attempt_at="2026-10-03T00:00:00")
    return entry_id


def _claim(entry_id, key, subject="S", content="B", recipient="a@acme.com", today="2026-10-03",
           reply_to_message_id=None):
    """today defaults to match the "2026-10-03" scheduled_date used
    throughout this file's fixtures, so existing tests pass without having
    to think about dates; tests that specifically exercise the due-date
    check override it."""
    return db.claim_and_record_attempt(
        entry_id, key, expected_subject=subject, expected_content=content, today=today,
        endpoint="reply" if reply_to_message_id else "send", reply_to_message_id=reply_to_message_id,
        recipient_email=recipient,
        subject=subject, text_body="plain body", html_body="<p>html body</p>",
        inbox_id="inbox-1", cv_filename="cv.pdf", cv_base64="ZmFrZQ==", cv_file_hash="hash1",
    )


def test_claim_and_record_attempt_succeeds_and_snapshots_both_bodies():
    db.init_db()
    job_id, contact_id = _make_job_contact()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-03", "S", "B")

    claimed = _claim(entry_id, "key-1")

    assert claimed is True
    row = db._get_conn().execute("SELECT status, send_idempotency_key FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "sending"
    assert row["send_idempotency_key"] == "key-1"
    attempt = db.get_send_attempt("key-1")
    assert attempt["text_body"] == "plain body"
    assert attempt["html_body"] == "<p>html body</p>"
    assert attempt["inbox_id"] == "inbox-1"
    assert attempt["cv_base64"] == "ZmFrZQ=="


def test_claim_and_record_attempt_fails_if_content_changed_since_review():
    """Regression: the claim must re-check subject/content at claim time,
    not trust an earlier, separate validation -- a concurrent edit landing
    between /prepare and /send must make the claim itself fail."""
    db.init_db()
    job_id, contact_id = _make_job_contact()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-03", "S", "B")
    db.update_outreach_entry(entry_id, content="Changed by a concurrent redraft")

    claimed = _claim(entry_id, "key-1", content="B")  # stale content, as reviewed before the edit

    assert claimed is False
    row = db._get_conn().execute("SELECT status, send_idempotency_key FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "draft"
    assert row["send_idempotency_key"] is None
    assert db.get_send_attempt("key-1") is None  # no orphaned attempt row on a failed claim


def test_claim_and_record_attempt_is_atomic_double_claim_fails():
    db.init_db()
    job_id, contact_id = _make_job_contact()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-03", "S", "B")

    first = _claim(entry_id, "key-1")
    second = _claim(entry_id, "key-2")  # same row, already 'sending' -- must not also claim

    assert first is True
    assert second is False
    # invariant: a row in 'sending' always has exactly one attempt matching its current key
    row = db._get_conn().execute("SELECT send_idempotency_key FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["send_idempotency_key"] == "key-1"
    assert db.get_send_attempt("key-2") is None


def test_claim_and_record_attempt_fails_before_due_date():
    """Regression: the due date is now re-checked INSIDE the atomic claim,
    not only by an earlier, separate Python check in /send -- a race where
    the date check passes and the row's scheduled_date somehow changes (or
    simply where the earlier check and the claim run far enough apart to
    disagree) must not let an early send through."""
    db.init_db()
    job_id, contact_id = _make_job_contact()
    # Follow-up, not Email 1 -- Email 1 is exempt from the date gate (job #141).
    # Email 1 confirmed sent so the predecessor check passes and only the date can fail.
    email1 = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-03", "S", "B")
    db.update_outreach_entry(email1, status="sent", agentmail_message_id="m1")
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 4, "2026-10-10", "S", "B")

    claimed = _claim(entry_id, "key-1", today="2026-10-03", reply_to_message_id="m1")  # before the 2026-10-10 due date

    assert claimed is False
    row = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "draft"


def test_claim_and_record_attempt_fails_if_contact_replied():
    db.init_db()
    job_id, contact_id = _make_job_contact()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-03", "S", "B")
    db.update_contact(contact_id, replied=1)

    assert _claim(entry_id, "key-1") is False


def test_claim_and_record_attempt_fails_if_contact_bounced():
    db.init_db()
    job_id, contact_id = _make_job_contact()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-03", "S", "B")
    db.update_contact(contact_id, email_status="bounced")

    assert _claim(entry_id, "key-1") is False


def test_claim_and_record_attempt_fails_if_contact_outreach_paused():
    """Regression: an explicit contact-level Skip (or a confirmed
    cross-contact cascade) stamps contacts.outreach_paused_at (Task 2) even
    though it doesn't touch THIS row if this row wasn't 'draft' at the time
    -- the claim must still refuse to send to a paused contact."""
    db.init_db()
    job_id, contact_id = _make_job_contact()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-03", "S", "B")
    db._get_conn().execute("UPDATE contacts SET outreach_paused_at = CURRENT_TIMESTAMP WHERE id = ?", (contact_id,))
    db._get_conn().commit()

    assert _claim(entry_id, "key-1") is False


def test_claim_and_record_attempt_fails_for_email_2_if_email_1_not_confirmed_sent():
    db.init_db()
    job_id, contact_id = _make_job_contact()
    db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-03", "S1", "B1")  # Email 1 still 'draft'
    email2_id = db.create_outreach_entry(contact_id, job_id, "email", 4, "2026-10-08", "S2", "B2")

    assert _claim(email2_id, "key-1", subject="S2", content="B2", reply_to_message_id="m1") is False


def test_claim_and_record_attempt_succeeds_for_email_2_once_email_1_confirmed_sent():
    db.init_db()
    job_id, contact_id = _make_job_contact()
    email1_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-03", "S1", "B1")
    db.update_outreach_entry(email1_id, status="sent", agentmail_message_id="m1")
    email2_id = db.create_outreach_entry(contact_id, job_id, "email", 4, "2026-10-08", "S2", "B2")

    # today must be overridden to be on/after email2's own 2026-10-08
    # scheduled_date -- the _claim() helper's default "2026-10-03" is only
    # guaranteed to satisfy fixtures using the default scheduled_date.
    assert _claim(email2_id, "key-1", subject="S2", content="B2", reply_to_message_id="m1",
                  today="2026-10-08") is True


def test_claim_and_record_attempt_fails_if_reply_to_message_id_does_not_match_predecessors_current_one():
    """Regression: the claim must tie the SPECIFIC reply_to_message_id
    being used to the predecessor's CURRENT agentmail_message_id, not just
    verify 'some predecessor is sent'. A stale/mismatched message id (e.g.
    computed from an earlier, now-outdated read) must fail the claim
    rather than reply to the wrong message."""
    db.init_db()
    job_id, contact_id = _make_job_contact()
    email1_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-03", "S1", "B1")
    db.update_outreach_entry(email1_id, status="sent", agentmail_message_id="m1")
    email2_id = db.create_outreach_entry(contact_id, job_id, "email", 4, "2026-10-08", "S2", "B2")

    claimed = _claim(email2_id, "key-1", subject="S2", content="B2", reply_to_message_id="stale-m0")

    assert claimed is False


def test_claim_and_record_attempt_fails_if_recipient_email_does_not_match_contacts_current_email():
    """Regression: the claim must tie recipient_email to the contact's
    CURRENT email, not merely the value computed by an earlier, separate
    read (the fingerprint) -- a concurrent contact-email edit landing
    between /prepare and the claim must not get silently sent to the old
    address."""
    db.init_db()
    job_id, contact_id = _make_job_contact()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-03", "S", "B")
    db.update_contact(contact_id, email="changed@acme.com")

    claimed = _claim(entry_id, "key-1", recipient="a@acme.com")  # stale, pre-edit address

    assert claimed is False


def test_record_immediate_send_failure_does_not_downgrade_a_sent_attempt():
    """Regression: record_immediate_send_failure's attempt-row write needs
    the same monotonic guard as resolve_send_attempt -- a 'sent' audit
    record must never be overwritten by a later 'failed'."""
    db.init_db()
    job_id, contact_id = _make_job_contact()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-03", "S", "B")
    _claim(entry_id, "key-1")
    db.resolve_send_attempt("key-1", "sent", agentmail_message_id="m1", agentmail_thread_id="t1")

    db.record_immediate_send_failure("key-1")  # late/out-of-order -- must not downgrade

    attempt = db.get_send_attempt("key-1")
    assert attempt["resolved_status"] == "sent"
    assert attempt["agentmail_message_id"] == "m1"


def test_resolve_send_attempt_updates_current_attempt():
    db.init_db()
    job_id, contact_id = _make_job_contact()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-03", "S", "B")
    _claim(entry_id, "key-1")

    resolved = db.resolve_send_attempt("key-1", "sent", agentmail_message_id="m1", agentmail_thread_id="t1")

    assert resolved is True
    row = db._get_conn().execute("SELECT * FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "sent"
    assert row["agentmail_message_id"] == "m1"
    attempt = db.get_send_attempt("key-1")
    assert attempt["resolved_status"] == "sent"


def test_resolve_send_attempt_is_monotonic_sent_cannot_be_overwritten():
    """Regression: once an attempt's audit record says 'sent', nothing may
    overwrite it with 'failed' or 'uncertain' -- a late, out-of-order, or
    duplicate resolution call (e.g. two check-status clicks racing, or a
    stray error after the real outcome was already recorded) must never
    corrupt a confirmed-sent record into looking unresolved or failed."""
    db.init_db()
    job_id, contact_id = _make_job_contact()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-03", "S", "B")
    _claim(entry_id, "key-1")
    db.resolve_send_attempt("key-1", "sent", agentmail_message_id="m1", agentmail_thread_id="t1")

    db.resolve_send_attempt("key-1", "failed")  # late/out-of-order -- must not downgrade

    attempt = db.get_send_attempt("key-1")
    assert attempt["resolved_status"] == "sent"
    assert attempt["agentmail_message_id"] == "m1"


def test_resolve_send_attempt_allows_upgrading_failed_to_sent():
    """A later resolution discovering the attempt actually succeeded (e.g.
    AgentMail processed it despite an earlier apparent rejection) may
    upgrade a non-'sent' resolved_status to 'sent' -- only 'sent' itself is
    protected as a floor, not every prior resolution."""
    db.init_db()
    job_id, contact_id = _make_job_contact()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-10-03", "S", "B")
    _claim(entry_id, "key-1")
    db.resolve_send_attempt("key-1", "failed")

    db.resolve_send_attempt("key-1", "sent", agentmail_message_id="m1", agentmail_thread_id="t1")

    attempt = db.get_send_attempt("key-1")
    assert attempt["resolved_status"] == "sent"
    assert attempt["agentmail_message_id"] == "m1"


def test_resolve_send_attempt_is_noop_for_superseded_key():
    """A late resolution for an OLD attempt (superseded by a retry's new key)
    must never touch outreach_log, only its own attempt row."""
    db.init_db()
    entry_id = _make_job_contact_entry(status="failed")
    db.update_outreach_entry(entry_id, status="failed", send_idempotency_key="old-key")
    db.retry_failed_touchpoint(entry_id)  # clears send_idempotency_key, status -> draft
    _claim(entry_id, "new-key")
    # simulate the OLD attempt (abandoned by the retry) still existing for audit
    db._get_conn().execute(
        "INSERT INTO outreach_send_attempts (outreach_log_id, idempotency_key, endpoint, recipient_email, "
        "subject, text_body, inbox_id) VALUES (?, 'old-key', 'send', 'a@acme.com', 'S', 'B', 'inbox-1')",
        (entry_id,),
    )
    db._get_conn().commit()

    resolved = db.resolve_send_attempt("old-key", "sent", agentmail_message_id="m-old")

    assert resolved is False
    row = db._get_conn().execute("SELECT status, send_idempotency_key FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "sending"
    assert row["send_idempotency_key"] == "new-key"
    old_attempt = db.get_send_attempt("old-key")
    assert old_attempt["resolved_status"] == "sent"  # still recorded, for audit


def test_record_immediate_send_failure_reverts_to_draft_not_failed():
    """Regression: an immediate, definitive failure at the original /send
    call must go straight back to 'draft' (nothing to reconcile) -- it must
    NOT become 'failed', which is reserved for a failure discovered later
    via reconciliation. Calling the generic resolve_send_attempt(..., 'failed')
    for this case was the original bug: it flips outreach_log.status to
    'failed' itself, so a subsequent 'WHERE status = sending' reset matches
    nothing."""
    db.init_db()
    entry_id = _make_job_contact_entry(status="draft")
    db.update_outreach_entry(entry_id, status="draft", send_idempotency_key=None)
    _claim(entry_id, "key-1")

    db.record_immediate_send_failure("key-1")

    row = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "draft"
    attempt = db.get_send_attempt("key-1")
    assert attempt["resolved_status"] == "failed"  # audit trail still records it


def test_sweep_stale_sending_moves_old_rows_to_uncertain():
    db.init_db()
    entry_id = _make_job_contact_entry(status="sending")
    db._get_conn().execute(
        "UPDATE outreach_log SET send_attempt_at = datetime('now', '-10 minutes') WHERE id = ?", (entry_id,)
    )
    db._get_conn().commit()

    swept = db.sweep_stale_sending(grace_seconds=120)

    assert entry_id in swept
    row = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "uncertain"


def test_sweep_stale_sending_ignores_recent_rows():
    db.init_db()
    entry_id = _make_job_contact_entry(status="sending")
    db._get_conn().execute(
        "UPDATE outreach_log SET send_attempt_at = datetime('now') WHERE id = ?", (entry_id,)
    )
    db._get_conn().commit()
    swept = db.sweep_stale_sending(grace_seconds=120)
    assert entry_id not in swept


def test_retry_failed_touchpoint_resets_for_fresh_review():
    db.init_db()
    entry_id = _make_job_contact_entry(status="failed")
    db.update_outreach_entry(entry_id, uncertain_dismissed_at="2026-10-03T00:00:00")

    retried = db.retry_failed_touchpoint(entry_id)

    assert retried["status"] == "draft"
    assert retried["send_idempotency_key"] is None
    assert retried["uncertain_dismissed_at"] is None


def test_retry_failed_touchpoint_rejects_non_failed_row():
    db.init_db()
    entry_id = _make_job_contact_entry(status="uncertain")
    assert db.retry_failed_touchpoint(entry_id) is None


def test_dismiss_and_list_uncertain_outreach():
    db.init_db()
    entry_id = _make_job_contact_entry(status="uncertain")
    visible_before = db.get_uncertain_outreach()
    assert any(row["id"] == entry_id for row in visible_before)

    dismissed = db.dismiss_uncertain_outreach(entry_id)

    assert dismissed is True
    visible_after = db.get_uncertain_outreach()
    assert all(row["id"] != entry_id for row in visible_after)
    # dismissal never touches status -- still 'uncertain' on the row itself
    row = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert row["status"] == "uncertain"
