import pytest

import db


@pytest.fixture(autouse=True)
def _clean_inbox_state():
    # ponytail: db._conn is one connection for the whole pytest session (no
    # per-test reset in conftest.py), and several tests below assert exact
    # digest contents (not just membership) -- clear via cascade from jobs
    # before each test so this file's tests don't pollute each other or get
    # polluted by rows other test files left behind. Scoped to this file only.
    db.init_db()
    conn = db._get_conn()
    conn.execute("DELETE FROM jobs")
    conn.commit()
    yield


def _make_job_and_contact(contact_type="hiring_manager", name="Jane Doe"):
    job_id = db.create_job("Acme Corp", "PM", "india")
    contact_id = db.create_contact(job_id, name, contact_type)
    return job_id, contact_id


def test_replies_grouped_by_contact_not_by_message():
    db.init_db()
    job_id, contact_id = _make_job_and_contact()
    db.record_processed_gmail_message("msg-group-1", contact_id, job_id, "genuine_reply")
    db.record_processed_gmail_message("msg-group-2", contact_id, job_id, "genuine_reply")
    db.record_processed_gmail_message("msg-group-3", contact_id, job_id, "genuine_reply")

    digest = db.get_inbox_digest()

    matching = [r for r in digest["replies"] if r["contact_id"] == contact_id]
    assert len(matching) == 1, "three messages from the same contact must collapse into one entry"
    assert matching[0]["message_count"] == 3
    assert set(matching[0]["message_ids"]) == {"msg-group-1", "msg-group-2", "msg-group-3"}


def test_cascade_pending_reflects_unconfirmed_flag():
    db.init_db()
    job_id, confirmed_contact = _make_job_and_contact(name="Confirmed Contact")
    _, unconfirmed_contact = (job_id, db.create_contact(job_id, "Unconfirmed Contact", "recruiter"))
    db.record_processed_gmail_message("msg-cascade-confirmed", confirmed_contact, job_id, "genuine_reply", cascade_confirmed=1)
    db.record_processed_gmail_message("msg-cascade-unconfirmed", unconfirmed_contact, job_id, "genuine_reply", cascade_confirmed=0)

    digest = db.get_inbox_digest()

    confirmed_entry = next(r for r in digest["replies"] if r["contact_id"] == confirmed_contact)
    unconfirmed_entry = next(r for r in digest["replies"] if r["contact_id"] == unconfirmed_contact)
    assert confirmed_entry["has_unconfirmed_cascade"] is False
    assert unconfirmed_entry["has_unconfirmed_cascade"] is True


def test_bounced_rejected_ooo_buckets_separate_from_replies():
    db.init_db()
    job_id, contact_id = _make_job_and_contact()
    db.record_processed_gmail_message("msg-bucket-bounce", contact_id, job_id, "bounce")
    db.record_processed_gmail_message("msg-bucket-rejection", contact_id, job_id, "rejection")
    db.record_processed_gmail_message("msg-bucket-ooo", contact_id, job_id, "ooo", extracted_date="2026-07-20")
    db.record_processed_gmail_message("msg-bucket-other", contact_id, job_id, "other")

    digest = db.get_inbox_digest()

    assert digest["bounced"]["count"] == 1
    assert digest["bounced"]["items"][0]["message_id"] == "msg-bucket-bounce"
    assert digest["rejected"]["count"] == 1
    assert digest["rejected"]["items"][0]["message_id"] == "msg-bucket-rejection"
    assert digest["ooo"]["count"] == 1
    assert digest["ooo"]["items"][0]["extracted_date"] == "2026-07-20"
    assert digest["replies"] == []
    all_ids = {i["message_id"] for b in ("bounced", "rejected", "ooo") for i in digest[b]["items"]}
    assert "msg-bucket-other" not in all_ids


def test_dismissed_rows_excluded_from_all_buckets():
    db.init_db()
    job_id, contact_id = _make_job_and_contact()
    db.record_processed_gmail_message("msg-dismiss-check", contact_id, job_id, "genuine_reply")
    db.dismiss_contact_digest(contact_id)

    digest = db.get_inbox_digest()

    assert digest["replies"] == []


def test_dismiss_contact_digest_scopes_to_contact_only():
    db.init_db()
    job_id, contact_a = _make_job_and_contact(name="Contact A")
    contact_b = db.create_contact(job_id, "Contact B", "peer")
    db.record_processed_gmail_message("msg-scope-a", contact_a, job_id, "genuine_reply")
    db.record_processed_gmail_message("msg-scope-b", contact_b, job_id, "genuine_reply")

    dismissed = db.dismiss_contact_digest(contact_a)

    assert dismissed == 1
    digest = db.get_inbox_digest()
    remaining_contacts = {r["contact_id"] for r in digest["replies"]}
    assert remaining_contacts == {contact_b}


def test_dismiss_digest_messages_scopes_to_given_ids_only():
    db.init_db()
    job_id, contact_id = _make_job_and_contact()
    db.record_processed_gmail_message("msg-dismiss-keep", contact_id, job_id, "bounce")
    db.record_processed_gmail_message("msg-dismiss-remove", contact_id, job_id, "bounce")

    dismissed = db.dismiss_digest_messages(["msg-dismiss-remove"])

    assert dismissed == 1
    digest = db.get_inbox_digest()
    remaining_ids = {i["message_id"] for i in digest["bounced"]["items"]}
    assert remaining_ids == {"msg-dismiss-keep"}


def test_confirm_cascade_for_contact_flips_all_rows_and_returns_job_id():
    db.init_db()
    job_id, contact_id = _make_job_and_contact()
    db.record_processed_gmail_message("msg-confirm-1", contact_id, job_id, "genuine_reply", cascade_confirmed=0)
    db.record_processed_gmail_message("msg-confirm-2", contact_id, job_id, "genuine_reply", cascade_confirmed=0)

    result = db.confirm_cascade_for_contact(contact_id)

    assert result == job_id
    rows = db._get_conn().execute(
        "SELECT cascade_confirmed FROM processed_gmail_messages WHERE contact_id = ?", (contact_id,)
    ).fetchall()
    assert all(r["cascade_confirmed"] == 1 for r in rows)


def test_confirm_cascade_for_contact_returns_none_for_unknown_contact():
    db.init_db()
    assert db.confirm_cascade_for_contact(999999) is None
