"""Regression for the duplicate-send race: two concurrent calls into
claim_and_record_attempt() on the SAME shared connection must never both
succeed (see db.py's _write_lock and SPRINT_LOG.md's AgentMail review entry).
"""
import threading
import uuid
from datetime import date, timedelta

import db


def _make_claimable_entry(conn):
    unique = uuid.uuid4().hex
    recipient_email = f"recipient-{unique}@example.com"
    subject = f"Subject {unique}"
    content = f"Content {unique}"

    job_id = conn.execute(
        "INSERT INTO jobs (company, role, geography) VALUES (?, ?, ?)",
        (f"Co {unique}", "Role", "eu"),
    ).lastrowid
    contact_id = conn.execute(
        "INSERT INTO contacts (job_id, name, contact_type, email) VALUES (?, ?, ?, ?)",
        (job_id, "Test Contact", "recruiter", recipient_email),
    ).lastrowid
    entry_id = conn.execute(
        "INSERT INTO outreach_log (contact_id, job_id, channel, sequence_num, status, "
        "scheduled_date, subject, content) VALUES (?, ?, 'email', 1, 'draft', ?, ?, ?)",
        (contact_id, job_id, (date.today() - timedelta(days=1)).isoformat(), subject, content),
    ).lastrowid
    conn.commit()
    return entry_id, recipient_email, subject, content


def _claim(entry_id, key, recipient_email, subject, content, today):
    return db.claim_and_record_attempt(
        entry_id, key, subject, content, today,
        endpoint="send", reply_to_message_id=None, recipient_email=recipient_email,
        subject=subject, text_body=content, html_body=None, inbox_id="inbox-1",
    )


def test_concurrent_claims_on_same_row_only_one_succeeds():
    db.init_db()
    conn = db._get_conn()
    entry_id, recipient_email, subject, content = _make_claimable_entry(conn)
    today = date.today().isoformat()

    barrier = threading.Barrier(2)
    results = {}

    def worker(key):
        barrier.wait(timeout=5)
        results[key] = _claim(entry_id, key, recipient_email, subject, content, today)

    key_a, key_b = f"key-a-{uuid.uuid4().hex}", f"key-b-{uuid.uuid4().hex}"
    threads = [threading.Thread(target=worker, args=(k,)) for k in (key_a, key_b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert sorted(results.values()) == [False, True]
    winning_key = key_a if results[key_a] else key_b

    row = conn.execute(
        "SELECT status, send_idempotency_key FROM outreach_log WHERE id = ?", (entry_id,)
    ).fetchone()
    assert row["status"] == "sending"
    assert row["send_idempotency_key"] == winning_key

    attempt_count = conn.execute(
        "SELECT COUNT(*) AS n FROM outreach_send_attempts WHERE outreach_log_id = ?", (entry_id,)
    ).fetchone()["n"]
    assert attempt_count == 1


def test_failed_claim_rollback_never_erases_a_concurrent_reply_update():
    """Regression for the round-2 review's R1b finding: a failed claim's
    conn.rollback() must never wipe out another thread's uncommitted write
    (e.g. the inbound-reply scanner's db.update_contact(replied=1)) just
    because both share db.py's one connection. Reproduction: thread A writes
    replied=1 but hasn't committed yet; thread B's claim fails (wrong
    subject) and rolls back. Both must now be serialized by _write_lock, so
    A's write is never caught mid-transaction by B's rollback."""
    db.init_db()
    conn = db._get_conn()
    entry_id, recipient_email, subject, content = _make_claimable_entry(conn)
    contact_id = conn.execute(
        "SELECT contact_id FROM outreach_log WHERE id = ?", (entry_id,)
    ).fetchone()["contact_id"]
    today = date.today().isoformat()

    barrier = threading.Barrier(2)
    errors = []

    def reply_writer():
        try:
            barrier.wait(timeout=5)
            db.update_contact(contact_id, replied=1)
        except BaseException as exc:
            errors.append(exc)

    def failing_claim():
        try:
            barrier.wait(timeout=5)
            # Wrong subject -> rowcount=0 -> conn.rollback() inside the lock.
            _claim(entry_id, f"key-{uuid.uuid4().hex}", recipient_email, "WRONG SUBJECT", content, today)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=reply_writer), threading.Thread(target=failing_claim)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors
    contact = conn.execute("SELECT replied FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    assert contact["replied"] == 1, "reply_writer's commit must survive the concurrent failed claim's rollback"


def test_single_threaded_claim_still_works():
    db.init_db()
    conn = db._get_conn()
    entry_id, recipient_email, subject, content = _make_claimable_entry(conn)
    today = date.today().isoformat()
    key = f"key-{uuid.uuid4().hex}"

    assert _claim(entry_id, key, recipient_email, subject, content, today) is True
    # A second claim attempt against the now-'sending' row must fail cleanly.
    assert _claim(entry_id, f"key2-{uuid.uuid4().hex}", recipient_email, subject, content, today) is False


if __name__ == "__main__":
    test_concurrent_claims_on_same_row_only_one_succeeds()
    test_single_threaded_claim_still_works()
    print("test_claim_concurrency: all checks passed")
