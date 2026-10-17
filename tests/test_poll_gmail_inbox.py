import api.app as app_module
import db
import poll_gmail_inbox


def _make_job_contact_and_sent_entry(contact_type="hiring_manager", thread_id="thread1", email="jane@acme.com"):
    job_id = db.create_job("Acme Corp", "PM", "india")
    contact_id = db.create_contact(job_id, "Jane Doe", contact_type, email=email)
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-07-10", "Subject", "Body")
    db.update_outreach_entry(entry_id, status="sent", sent_at="2026-07-10T09:00:00", gmail_thread_id=thread_id)
    return job_id, contact_id


def _only_for_thread(thread_id, messages):
    """scan_reply_threads walks EVERY sent-with-thread row across the whole DB
    (not job-scoped), so other tests' threads are still present when this test
    runs. Only return this test's fixture messages for its own thread_id --
    otherwise get_thread_messages would hand the same fixture back for older
    tests' threads too and misattribute the message to the wrong contact."""
    return lambda tid: messages if tid == thread_id else []


def test_scan_reply_threads_classifies_and_records_new_message(monkeypatch):
    db.init_db()
    job_id, contact_id = _make_job_contact_and_sent_entry("peer", thread_id="thread-classify-record")
    monkeypatch.setattr(poll_gmail_inbox.gmail_client, "get_thread_messages", _only_for_thread(
        "thread-classify-record",
        [{"message_id": "msg-classify-record", "from": "jane@acme.com", "date": "", "body": "Sounds good, let's chat."}],
    ))
    monkeypatch.setattr(poll_gmail_inbox.inbox_classifier, "classify_message",
                         lambda body: {"classification": "genuine_reply", "extracted_date": None})

    poll_gmail_inbox.scan_reply_threads("me@mine.com")

    assert db.is_gmail_message_processed("msg-classify-record")
    contact = db._get_conn().execute("SELECT replied FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    assert contact["replied"] == 1


def test_scan_reply_threads_skips_already_processed_message(monkeypatch):
    db.init_db()
    job_id, contact_id = _make_job_contact_and_sent_entry("peer", thread_id="thread-already-processed")
    db.record_processed_gmail_message("msg-already-processed", contact_id, job_id, "other")
    monkeypatch.setattr(poll_gmail_inbox.gmail_client, "get_thread_messages", _only_for_thread(
        "thread-already-processed",
        [{"message_id": "msg-already-processed", "from": "jane@acme.com", "date": "", "body": "irrelevant"}],
    ))
    calls = []
    monkeypatch.setattr(poll_gmail_inbox.inbox_classifier, "classify_message",
                         lambda body: calls.append(body) or {"classification": "other", "extracted_date": None})

    poll_gmail_inbox.scan_reply_threads("me@mine.com")

    assert calls == []  # already-processed message must never be reclassified


def test_scan_reply_threads_skips_messages_authored_by_the_account_itself(monkeypatch):
    db.init_db()
    job_id, contact_id = _make_job_contact_and_sent_entry("peer", thread_id="thread-own-message")
    monkeypatch.setattr(poll_gmail_inbox.gmail_client, "get_thread_messages", _only_for_thread(
        "thread-own-message",
        [{"message_id": "msg-own-message", "from": "Me <me@mine.com>", "date": "", "body": "my own sent message"}],
    ))
    calls = []
    monkeypatch.setattr(poll_gmail_inbox.inbox_classifier, "classify_message",
                         lambda body: calls.append(body) or {"classification": "other", "extracted_date": None})

    poll_gmail_inbox.scan_reply_threads("me@mine.com")

    assert calls == []


def test_genuine_reply_from_hiring_manager_sets_cascade_confirmed_pending(monkeypatch):
    db.init_db()
    job_id, contact_id = _make_job_contact_and_sent_entry("hiring_manager", thread_id="thread-hm-cascade-pending")
    monkeypatch.setattr(poll_gmail_inbox.gmail_client, "get_thread_messages", _only_for_thread(
        "thread-hm-cascade-pending",
        [{"message_id": "msg-hm-cascade-pending", "from": "jane@acme.com", "date": "", "body": "Let's schedule a call."}],
    ))
    monkeypatch.setattr(poll_gmail_inbox.inbox_classifier, "classify_message",
                         lambda body: {"classification": "genuine_reply", "extracted_date": None})

    poll_gmail_inbox.scan_reply_threads("me@mine.com")

    row = db._get_conn().execute(
        "SELECT cascade_confirmed FROM processed_gmail_messages WHERE message_id = ?", ("msg-hm-cascade-pending",)
    ).fetchone()
    assert row["cascade_confirmed"] == 0


def test_genuine_reply_from_peer_never_sets_cascade_confirmed(monkeypatch):
    db.init_db()
    job_id, contact_id = _make_job_contact_and_sent_entry("peer", thread_id="thread-peer-no-cascade")
    monkeypatch.setattr(poll_gmail_inbox.gmail_client, "get_thread_messages", _only_for_thread(
        "thread-peer-no-cascade",
        [{"message_id": "msg-peer-no-cascade", "from": "jane@acme.com", "date": "", "body": "Happy to trade notes."}],
    ))
    monkeypatch.setattr(poll_gmail_inbox.inbox_classifier, "classify_message",
                         lambda body: {"classification": "genuine_reply", "extracted_date": None})

    poll_gmail_inbox.scan_reply_threads("me@mine.com")

    row = db._get_conn().execute(
        "SELECT cascade_confirmed FROM processed_gmail_messages WHERE message_id = ?", ("msg-peer-no-cascade",)
    ).fetchone()
    assert row["cascade_confirmed"] is None


def test_genuine_reply_from_agency_never_sets_cascade_confirmed(monkeypatch):
    db.init_db()
    job_id, contact_id = _make_job_contact_and_sent_entry("agency", thread_id="thread-agency-no-cascade")
    monkeypatch.setattr(poll_gmail_inbox.gmail_client, "get_thread_messages", _only_for_thread(
        "thread-agency-no-cascade",
        [{"message_id": "msg-agency-no-cascade", "from": "jane@acme.com", "date": "", "body": "I'd welcome a conversation about roles."}],
    ))
    monkeypatch.setattr(poll_gmail_inbox.inbox_classifier, "classify_message",
                         lambda body: {"classification": "genuine_reply", "extracted_date": None})

    poll_gmail_inbox.scan_reply_threads("me@mine.com")

    row = db._get_conn().execute(
        "SELECT cascade_confirmed FROM processed_gmail_messages WHERE message_id = ?", ("msg-agency-no-cascade",)
    ).fetchone()
    assert row["cascade_confirmed"] is None


def test_genuine_reply_does_not_cancel_other_contacts_until_confirmed(monkeypatch):
    db.init_db()
    job_id, contact_id = _make_job_contact_and_sent_entry("hiring_manager", thread_id="thread-hm-suggest-only")
    other_id = db.create_contact(job_id, "Peer Person", "peer")
    other_entry = db.create_outreach_entry(other_id, job_id, "email", 1, "2026-07-13", "Subject", "Body")
    db.update_outreach_entry(other_entry, status="draft")
    monkeypatch.setattr(poll_gmail_inbox.gmail_client, "get_thread_messages", _only_for_thread(
        "thread-hm-suggest-only",
        [{"message_id": "msg-hm-cascade-suggest-only", "from": "jane@acme.com", "date": "", "body": "Let's schedule a call."}],
    ))
    monkeypatch.setattr(poll_gmail_inbox.inbox_classifier, "classify_message",
                         lambda body: {"classification": "genuine_reply", "extracted_date": None})

    poll_gmail_inbox.scan_reply_threads("me@mine.com")

    other_status = db._get_conn().execute(
        "SELECT status FROM outreach_log WHERE id = ?", (other_entry,)
    ).fetchone()
    assert other_status["status"] == "draft"  # untouched — cascade is suggest-only until confirmed


def test_ooo_with_parsed_date_reschedules_pending_touchpoints(monkeypatch):
    db.init_db()
    job_id, contact_id = _make_job_contact_and_sent_entry("peer", thread_id="thread-ooo-with-date")
    email2_id = db.create_outreach_entry(contact_id, job_id, "email", 4, "2026-07-15", "Subject", "Body")
    db.update_outreach_entry(email2_id, status="draft")
    monkeypatch.setattr(poll_gmail_inbox.gmail_client, "get_thread_messages", _only_for_thread(
        "thread-ooo-with-date",
        [{"message_id": "msg-ooo-with-date", "from": "jane@acme.com", "date": "", "body": "Out of office until July 20th."}],
    ))
    monkeypatch.setattr(poll_gmail_inbox.inbox_classifier, "classify_message",
                         lambda body: {"classification": "ooo", "extracted_date": "2026-07-20"})

    poll_gmail_inbox.scan_reply_threads("me@mine.com")

    entry = db._get_conn().execute("SELECT scheduled_date FROM outreach_log WHERE id = ?", (email2_id,)).fetchone()
    assert entry["scheduled_date"] != "2026-07-15"


def test_ooo_with_no_extractable_date_takes_no_scheduling_action(monkeypatch):
    db.init_db()
    job_id, contact_id = _make_job_contact_and_sent_entry("peer", thread_id="thread-ooo-no-date")
    email2_id = db.create_outreach_entry(contact_id, job_id, "email", 4, "2026-07-15", "Subject", "Body")
    db.update_outreach_entry(email2_id, status="draft")
    monkeypatch.setattr(poll_gmail_inbox.gmail_client, "get_thread_messages", _only_for_thread(
        "thread-ooo-no-date",
        [{"message_id": "msg-ooo-no-date", "from": "jane@acme.com", "date": "", "body": "I am currently out of office."}],
    ))
    monkeypatch.setattr(poll_gmail_inbox.inbox_classifier, "classify_message",
                         lambda body: {"classification": "ooo", "extracted_date": None})

    poll_gmail_inbox.scan_reply_threads("me@mine.com")

    entry = db._get_conn().execute("SELECT scheduled_date FROM outreach_log WHERE id = ?", (email2_id,)).fetchone()
    assert entry["scheduled_date"] == "2026-07-15"


def test_rejection_cancels_outreach_but_does_not_touch_job_status(monkeypatch):
    db.init_db()
    job_id, contact_id = _make_job_contact_and_sent_entry("hiring_manager", thread_id="thread-rejection")
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 4, "2026-07-15", "Subject", "Body")
    db.update_outreach_entry(entry_id, status="draft")
    monkeypatch.setattr(poll_gmail_inbox.gmail_client, "get_thread_messages", _only_for_thread(
        "thread-rejection",
        [{"message_id": "msg-rejection", "from": "jane@acme.com", "date": "",
          "body": "We've decided to move forward with other candidates."}],
    ))
    monkeypatch.setattr(poll_gmail_inbox.inbox_classifier, "classify_message",
                         lambda body: {"classification": "rejection", "extracted_date": None})

    poll_gmail_inbox.scan_reply_threads("me@mine.com")

    entry = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert entry["status"] == "skipped"
    job = db.get_job(job_id)
    assert job["status"] != "rejected"


def test_classification_failure_result_is_recorded_and_scan_completes(monkeypatch):
    db.init_db()
    job_id, contact_id = _make_job_contact_and_sent_entry("peer", thread_id="thread-classify-failure")
    monkeypatch.setattr(poll_gmail_inbox.gmail_client, "get_thread_messages", _only_for_thread(
        "thread-classify-failure",
        [{"message_id": "msg-classify-failure", "from": "jane@acme.com", "date": "", "body": "some message"}],
    ))
    # inbox_classifier.classify_message already never raises in production
    # (Task 4 falls back to "other" on any internal failure) — this proves
    # the scan completes and records that fallback rather than crashing.
    monkeypatch.setattr(poll_gmail_inbox.inbox_classifier, "classify_message",
                         lambda body: {"classification": "other", "extracted_date": None})

    poll_gmail_inbox.scan_reply_threads("me@mine.com")

    row = db._get_conn().execute(
        "SELECT classification FROM processed_gmail_messages WHERE message_id = ?", ("msg-classify-failure",)
    ).fetchone()
    assert row["classification"] == "other"


def test_scan_bounces_matches_delivery_failure_to_correct_contact(monkeypatch):
    db.init_db()
    job_id, contact_id = _make_job_contact_and_sent_entry(
        "peer", thread_id="thread-bounce-match", email="bounce-target@acme.com"
    )
    monkeypatch.setattr(poll_gmail_inbox.gmail_client, "search_messages", lambda query: [
        {"message_id": "bounce-matched", "from": "mailer-daemon@acme.com", "date": "",
         "body": "Delivery to the following recipient failed permanently: bounce-target@acme.com"}
    ])

    processed = poll_gmail_inbox.scan_bounces()

    assert processed == 1
    contact = db._get_conn().execute("SELECT email_status FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    assert contact["email_status"] == "bounced"


def test_scan_bounces_ignores_messages_matching_no_known_contact(monkeypatch):
    db.init_db()
    monkeypatch.setattr(poll_gmail_inbox.gmail_client, "search_messages", lambda query: [
        {"message_id": "bounce-unmatched", "from": "mailer-daemon@example.com", "date": "",
         "body": "Delivery to the following recipient failed permanently: nobody-has-this-email@nowhere.com"}
    ])

    processed = poll_gmail_inbox.scan_bounces()

    assert processed == 0
    assert not db.is_gmail_message_processed("bounce-unmatched")


def test_scan_bounces_uses_widened_query_matching_exchange_undeliverable_format(monkeypatch):
    db.init_db()
    job_id = db.create_job("Amgen", "Data Science Manager", "india")
    contact_id = db.create_contact(job_id, "Palisetti Radhika", "hiring_manager", email="pradhika-exchange-test@amgen.com")
    captured_query = {}

    def _fake_search(query):
        captured_query["value"] = query
        return [{
            "message_id": "msg-exchange-undeliverable",
            "from": "MicrosoftExchange@amgen.onmicrosoft.com",
            "date": "",
            "body": "Your message to pradhika-exchange-test@amgen.com couldn't be delivered.",
        }]

    monkeypatch.setattr(poll_gmail_inbox.gmail_client, "search_messages", _fake_search)

    processed = poll_gmail_inbox.scan_bounces()

    assert processed == 1
    assert "Undeliverable" in captured_query["value"]
    assert "postmaster" in captured_query["value"]
    contact = db._get_conn().execute("SELECT email_status FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    assert contact["email_status"] == "bounced"


def test_scan_bounces_query_retains_original_terms(monkeypatch):
    captured_query = {}

    def _fake_search(query):
        captured_query["value"] = query
        return []

    monkeypatch.setattr(poll_gmail_inbox.gmail_client, "search_messages", _fake_search)
    poll_gmail_inbox.scan_bounces()

    assert "mailer-daemon" in captured_query["value"]
    assert "Delivery Status Notification" in captured_query["value"]


def test_scan_bounces_handles_postmaster_sender(monkeypatch):
    db.init_db()
    job_id = db.create_job("TestCo", "Engineer", "remote")
    contact_id = db.create_contact(job_id, "Test User", "hiring_manager", email="test-postmaster@example.com")
    captured_query = {}

    def _fake_search(query):
        captured_query["value"] = query
        return [{
            "message_id": "msg-postmaster",
            "from": "postmaster@example.com",
            "date": "",
            "body": "The user test-postmaster@example.com does not exist.",
        }]

    monkeypatch.setattr(poll_gmail_inbox.gmail_client, "search_messages", _fake_search)

    processed = poll_gmail_inbox.scan_bounces()

    assert processed == 1
    assert "postmaster" in captured_query["value"]
    contact = db._get_conn().execute("SELECT email_status FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    assert contact["email_status"] == "bounced"
