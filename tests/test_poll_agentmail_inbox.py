import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import db
import poll_agentmail_inbox


@pytest.mark.parametrize("inherited_key", [None, "inherited-test-key"])
def test_standalone_import_loads_dotenv_before_client(tmp_path, inherited_key):
    """Use a fresh interpreter so pytest's pre-imported client cannot mask the bug."""
    project = Path(__file__).resolve().parents[1]
    for filename in ("poll_agentmail_inbox.py", "agentmail_client.py"):
        shutil.copyfile(project / filename, tmp_path / filename)
    (tmp_path / ".env").write_text(
        "AGENTMAIL_API_KEY=dotenv-test-key\nAGENTMAIL_INBOX_ID=dotenv-test@example.com\n",
        encoding="utf-8",
    )
    # Keep dependency imports isolated from the real app, credentials, and DB.
    (tmp_path / "db.py").write_text("def init_db(): pass\n", encoding="utf-8")
    (tmp_path / "inbox_classifier.py").write_text("", encoding="utf-8")
    (tmp_path / "poll_gmail_inbox.py").write_text("def _act_on_classification(*args): pass\n", encoding="utf-8")
    environment = os.environ.copy()
    environment.pop("AGENTMAIL_API_KEY", None)
    environment.pop("AGENTMAIL_INBOX_ID", None)
    if inherited_key:
        environment["AGENTMAIL_API_KEY"] = inherited_key
    expected_key = inherited_key or "dotenv-test-key"
    script = """
import os, socket
from unittest.mock import patch
def deny(*args, **kwargs):
    raise AssertionError('Network forbidden in startup regression')
socket.socket.connect = deny
socket.create_connection = deny
import poll_agentmail_inbox as scanner
assert scanner.agentmail_client.AGENTMAIL_API_KEY == os.environ['EXPECTED_TEST_KEY']
with patch.object(scanner, 'scan_reply_threads', return_value=1) as scan:
    assert scanner.run_agentmail_inbox_scan() == 1
    scan.assert_called_once_with('dotenv-test@example.com')
"""
    environment["EXPECTED_TEST_KEY"] = expected_key
    result = subprocess.run([sys.executable, "-c", script], cwd=tmp_path,
                            env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def _make_job_contact_and_sent_agentmail_entry(contact_type="hiring_manager", thread_id="am-thread1",
                                                email="jane@acme.com"):
    job_id = db.create_job("Acme Corp", "PM", "india")
    contact_id = db.create_contact(job_id, "Jane Doe", contact_type, email=email)
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-07-10", "Subject", "Body")
    db.update_outreach_entry(entry_id, status="sent", provider="agentmail", agentmail_thread_id=thread_id)
    return job_id, contact_id


def _only_for_thread(thread_id, messages):
    def _get(inbox_id, tid):
        return messages if tid == thread_id else []
    return _get


def test_genuine_reply_marks_contact_replied(monkeypatch):
    db.init_db()
    job_id, contact_id = _make_job_contact_and_sent_agentmail_entry("peer", thread_id="am-thread-genuine")
    monkeypatch.setattr(poll_agentmail_inbox.agentmail_client, "get_thread_messages", _only_for_thread(
        "am-thread-genuine",
        [{"message_id": "am-msg-genuine", "from": "jane@acme.com", "text": "Sounds good, let's chat."}],
    ))
    monkeypatch.setattr(poll_agentmail_inbox.inbox_classifier, "classify_message",
                         lambda body: {"classification": "genuine_reply", "extracted_date": None})

    processed = poll_agentmail_inbox.scan_reply_threads("me@mine.agentmail.to")

    assert processed == 1
    assert db.is_agentmail_message_processed("am-msg-genuine")
    contact = db._get_conn().execute("SELECT replied FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    assert contact["replied"] == 1


def test_scan_ignores_non_agentmail_and_null_thread_rows(monkeypatch):
    db.init_db()
    # Gmail-provider row (default provider from create_outreach_entry) with no agentmail_thread_id.
    job_id = db.create_job("Other Co", "Eng", "eu")
    contact_id = db.create_contact(job_id, "Gmail Contact", "peer", email="g@other.com")
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-07-10", "Subject", "Body")
    db.update_outreach_entry(entry_id, status="sent", gmail_thread_id="gmail-thread-1")

    def fail_if_called(inbox_id, thread_id):
        raise AssertionError("get_thread_messages should not be called for non-agentmail rows")

    monkeypatch.setattr(poll_agentmail_inbox.agentmail_client, "get_thread_messages", fail_if_called)

    assert poll_agentmail_inbox.scan_reply_threads("me@mine.agentmail.to") == 0


def test_message_from_own_inbox_is_skipped(monkeypatch):
    db.init_db()
    _make_job_contact_and_sent_agentmail_entry("peer", thread_id="am-thread-own")
    monkeypatch.setattr(poll_agentmail_inbox.agentmail_client, "get_thread_messages", _only_for_thread(
        "am-thread-own",
        [{"message_id": "am-msg-own", "from": "Me <me@mine.agentmail.to>", "text": "my own sent message"}],
    ))
    calls = []
    monkeypatch.setattr(poll_agentmail_inbox.inbox_classifier, "classify_message",
                         lambda body: calls.append(body) or {"classification": "other", "extracted_date": None})

    processed = poll_agentmail_inbox.scan_reply_threads("me@mine.agentmail.to")

    assert processed == 0
    assert calls == []


def test_already_processed_message_is_skipped(monkeypatch):
    db.init_db()
    job_id, contact_id = _make_job_contact_and_sent_agentmail_entry("peer", thread_id="am-thread-dedup")
    db.record_processed_agentmail_message("am-msg-dedup", contact_id, job_id, "other")
    monkeypatch.setattr(poll_agentmail_inbox.agentmail_client, "get_thread_messages", _only_for_thread(
        "am-thread-dedup",
        [{"message_id": "am-msg-dedup", "from": "jane@acme.com", "text": "irrelevant"}],
    ))
    calls = []
    monkeypatch.setattr(poll_agentmail_inbox.inbox_classifier, "classify_message",
                         lambda body: calls.append(body) or {"classification": "other", "extracted_date": None})

    processed = poll_agentmail_inbox.scan_reply_threads("me@mine.agentmail.to")

    assert processed == 0
    assert calls == []


def test_run_scan_returns_zero_when_not_configured(monkeypatch):
    monkeypatch.delenv("AGENTMAIL_INBOX_ID", raising=False)
    monkeypatch.setattr(poll_agentmail_inbox.agentmail_client, "AGENTMAIL_API_KEY", "")

    def fail_if_called(inbox_id, thread_id):
        raise AssertionError("get_thread_messages should not be called when unconfigured")

    monkeypatch.setattr(poll_agentmail_inbox.agentmail_client, "get_thread_messages", fail_if_called)

    assert poll_agentmail_inbox.run_agentmail_inbox_scan() == 0


def test_one_failing_thread_does_not_stop_the_rest(monkeypatch):
    db.init_db()
    _make_job_contact_and_sent_agentmail_entry("peer", thread_id="am-thread-bad")
    job_id2, contact_id2 = _make_job_contact_and_sent_agentmail_entry("peer", thread_id="am-thread-good")

    def mixed(inbox_id, thread_id):
        if thread_id == "am-thread-bad":
            raise RuntimeError("temporary AgentMail failure")
        return [{"message_id": "am-msg-good", "from": "jane@acme.com", "text": "Got it."}]

    monkeypatch.setattr(poll_agentmail_inbox.agentmail_client, "get_thread_messages", mixed)
    monkeypatch.setattr(poll_agentmail_inbox.inbox_classifier, "classify_message",
                         lambda body: {"classification": "other", "extracted_date": None})

    processed = poll_agentmail_inbox.scan_reply_threads("me@mine.agentmail.to")

    assert processed == 1
