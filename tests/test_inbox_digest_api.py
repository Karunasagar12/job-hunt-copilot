import pytest

import api.app as app_module

db = app_module.db
app_module.app.config["TESTING"] = True


@pytest.fixture(autouse=True)
def _clean_inbox_state():
    # ponytail: same shared-session-DB pollution issue documented in
    # tests/test_inbox_digest_grouping.py -- several tests below assert
    # exact digest contents, so clear via cascade from jobs before each
    # test. Scoped to this file only.
    db.init_db()
    conn = db._get_conn()
    conn.execute("DELETE FROM jobs")
    conn.commit()
    yield


def _client():
    return app_module.app.test_client()


def _make_job_and_contact(contact_type="hiring_manager", name="Jane Doe"):
    job_id = db.create_job("Acme Corp", "PM", "india")
    contact_id = db.create_contact(job_id, name, contact_type)
    return job_id, contact_id


def test_inbox_digest_returns_grouped_buckets():
    client = _client()
    job_id, contact_id = _make_job_and_contact()
    db.record_processed_gmail_message("msg-api-bucket-1", contact_id, job_id, "rejection")

    resp = client.get("/api/inbox-digest")

    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body.keys()) == {"replies", "bounced", "rejected", "ooo", "uncertain"}
    assert body["rejected"]["count"] == 1
    assert body["rejected"]["items"][0]["message_id"] == "msg-api-bucket-1"


def test_inbox_digest_sets_cascade_pending_only_for_eligible_type():
    client = _client()
    job_id, hm_id = _make_job_and_contact("hiring_manager", "HM Contact")
    peer_id = db.create_contact(job_id, "Peer Contact", "peer")
    db.record_processed_gmail_message("msg-api-cascade-hm", hm_id, job_id, "genuine_reply", cascade_confirmed=0)
    db.record_processed_gmail_message("msg-api-cascade-peer", peer_id, job_id, "genuine_reply", cascade_confirmed=0)

    resp = client.get("/api/inbox-digest")

    replies = {r["contact_id"]: r for r in resp.get_json()["replies"]}
    assert replies[hm_id]["cascade_pending"] is True
    assert replies[peer_id]["cascade_pending"] is False


def test_confirm_cascade_by_contact_runs_cascade_and_flips_flag():
    client = _client()
    job_id, hm_id = _make_job_and_contact("hiring_manager")
    other_id = db.create_contact(job_id, "Peer Person", "peer")
    entry_id = db.create_outreach_entry(other_id, job_id, "email", 1, "2026-07-13", "Subject", "Body")
    db.update_outreach_entry(entry_id, status="draft")
    db.record_processed_gmail_message("msg-api-confirm-1", hm_id, job_id, "genuine_reply", cascade_confirmed=0)

    resp = client.post(f"/api/inbox-digest/contact/{hm_id}/confirm-cascade")

    assert resp.status_code == 200
    assert resp.get_json()["cascaded"] == [{"contact_id": other_id, "name": "Peer Person", "cancelled_count": 1}]
    entry = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert entry["status"] == "skipped"
    record = db._get_conn().execute(
        "SELECT cascade_confirmed FROM processed_gmail_messages WHERE message_id = ?", ("msg-api-confirm-1",)
    ).fetchone()
    assert record["cascade_confirmed"] == 1


def test_confirm_cascade_404s_for_contact_with_no_messages():
    client = _client()
    resp = client.post("/api/inbox-digest/contact/999999/confirm-cascade")
    assert resp.status_code == 404


def test_dismiss_contact_removes_it_from_digest():
    client = _client()
    job_id, contact_id = _make_job_and_contact()
    db.record_processed_gmail_message("msg-api-dismiss-contact", contact_id, job_id, "genuine_reply")

    resp = client.post(f"/api/inbox-digest/contact/{contact_id}/dismiss")

    assert resp.status_code == 200
    assert resp.get_json()["dismissed"] == 1
    digest = client.get("/api/inbox-digest").get_json()
    assert digest["replies"] == []


def test_dismiss_messages_removes_only_given_ids():
    client = _client()
    job_id, contact_id = _make_job_and_contact()
    db.record_processed_gmail_message("msg-api-dismiss-keep", contact_id, job_id, "bounce")
    db.record_processed_gmail_message("msg-api-dismiss-remove", contact_id, job_id, "bounce")

    resp = client.post("/api/inbox-digest/dismiss", json={"message_ids": ["msg-api-dismiss-remove"]})

    assert resp.status_code == 200
    assert resp.get_json()["dismissed"] == 1
    digest = client.get("/api/inbox-digest").get_json()
    remaining = {i["message_id"] for i in digest["bounced"]["items"]}
    assert remaining == {"msg-api-dismiss-keep"}


def test_dismiss_messages_requires_nonempty_list():
    client = _client()
    resp = client.post("/api/inbox-digest/dismiss", json={"message_ids": []})
    assert resp.status_code == 400


def test_thread_endpoint_falls_back_to_local_when_no_gmail_thread_id():
    client = _client()
    job_id, contact_id = _make_job_and_contact()
    db.record_processed_gmail_message("msg-api-thread-local", contact_id, job_id, "genuine_reply")
    # No outreach_log row created for this contact -> no gmail_thread_id exists to look up.

    resp = client.get(f"/api/inbox-digest/contact/{contact_id}/thread")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["source"] == "local"
    assert any(m["message_id"] == "msg-api-thread-local" for m in body["messages"])


# ── AgentMail-provider equivalents (R3b: replies were invisible to the ────────
# dashboard because digest/dismiss/cascade/thread only ever looked at
# processed_gmail_messages) ──────────────────────────────────────────────────

def test_inbox_digest_includes_agentmail_replies():
    client = _client()
    job_id, contact_id = _make_job_and_contact()
    db.record_processed_agentmail_message("msg-am-bucket-1", contact_id, job_id, "rejection")

    resp = client.get("/api/inbox-digest")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["rejected"]["count"] == 1
    assert body["rejected"]["items"][0]["message_id"] == "msg-am-bucket-1"


def test_confirm_cascade_works_for_agentmail_sourced_reply():
    client = _client()
    job_id, hm_id = _make_job_and_contact("hiring_manager")
    other_id = db.create_contact(job_id, "Peer Person", "peer")
    entry_id = db.create_outreach_entry(other_id, job_id, "email", 1, "2026-07-13", "Subject", "Body")
    db.update_outreach_entry(entry_id, status="draft")
    db.record_processed_agentmail_message("msg-am-confirm-1", hm_id, job_id, "genuine_reply", cascade_confirmed=0)

    resp = client.post(f"/api/inbox-digest/contact/{hm_id}/confirm-cascade")

    assert resp.status_code == 200
    assert resp.get_json()["cascaded"] == [{"contact_id": other_id, "name": "Peer Person", "cancelled_count": 1}]
    entry = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert entry["status"] == "skipped"
    record = db._get_conn().execute(
        "SELECT cascade_confirmed FROM processed_agentmail_messages WHERE message_id = ?", ("msg-am-confirm-1",)
    ).fetchone()
    assert record["cascade_confirmed"] == 1


def test_dismiss_contact_removes_agentmail_reply_from_digest():
    client = _client()
    job_id, contact_id = _make_job_and_contact()
    db.record_processed_agentmail_message("msg-am-dismiss-contact", contact_id, job_id, "genuine_reply")

    resp = client.post(f"/api/inbox-digest/contact/{contact_id}/dismiss")

    assert resp.status_code == 200
    assert resp.get_json()["dismissed"] == 1
    digest = client.get("/api/inbox-digest").get_json()
    assert digest["replies"] == []


def test_dismiss_messages_removes_agentmail_message_by_id():
    client = _client()
    job_id, contact_id = _make_job_and_contact()
    db.record_processed_agentmail_message("msg-am-dismiss-keep", contact_id, job_id, "bounce")
    db.record_processed_agentmail_message("msg-am-dismiss-remove", contact_id, job_id, "bounce")

    resp = client.post("/api/inbox-digest/dismiss", json={"message_ids": ["msg-am-dismiss-remove"]})

    assert resp.status_code == 200
    assert resp.get_json()["dismissed"] == 1
    digest = client.get("/api/inbox-digest").get_json()
    remaining = {i["message_id"] for i in digest["bounced"]["items"]}
    assert remaining == {"msg-am-dismiss-keep"}


def test_thread_endpoint_uses_agentmail_source_for_agentmail_provider_row(monkeypatch):
    client = _client()
    job_id, contact_id = _make_job_and_contact()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-07-13", "Subject", "Body")
    db.update_outreach_entry(entry_id, status="sent", provider="agentmail", agentmail_thread_id="am-thread-xyz")
    monkeypatch.setenv("AGENTMAIL_INBOX_ID", "inbox-1")
    monkeypatch.setattr(
        app_module.agentmail_client, "get_thread_messages",
        lambda inbox_id, thread_id: [{"message_id": "am-msg-1"}] if thread_id == "am-thread-xyz" else [],
    )

    resp = client.get(f"/api/inbox-digest/contact/{contact_id}/thread")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["source"] == "agentmail"
    assert body["messages"] == [{"message_id": "am-msg-1", "body": "", "date": ""}]


@pytest.mark.parametrize("message_content, expected_body", [
    ({"text": "Let's discuss the role", "extracted_text": "Fallback"}, "Let's discuss the role"),
    ({"text": "", "extracted_text": "Reply without quoted history"}, "Reply without quoted history"),
    ({"html": "<p>HTML only</p>"}, ""),
])
def test_agentmail_thread_content_matches_viewer_contract(monkeypatch, message_content, expected_body):
    client = _client()
    job_id, contact_id = _make_job_and_contact()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-07-13", "Subject", "Body")
    db.update_outreach_entry(entry_id, status="sent", provider="agentmail", agentmail_thread_id="am-thread-content")
    monkeypatch.setenv("AGENTMAIL_INBOX_ID", "inbox-1")
    message = {"message_id": "am-content", "from": "Jane <jane@example.com>",
               "timestamp": "2026-10-04T00:00:00Z", **message_content}
    monkeypatch.setattr(app_module.agentmail_client, "get_thread_messages", lambda inbox, thread: [message])

    response = client.get(f"/api/inbox-digest/contact/{contact_id}/thread")

    assert response.status_code == 200
    returned = response.get_json()["messages"][0]
    assert returned["body"] == expected_body
    assert returned["date"] == message["timestamp"]
    assert returned["from"] == message["from"]
    assert returned["message_id"] == message["message_id"]
    assert "body" not in message  # Normalization leaves the provider response untouched.


def test_thread_endpoint_falls_back_to_local_when_agentmail_fetch_fails(monkeypatch):
    client = _client()
    job_id, contact_id = _make_job_and_contact()
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", 1, "2026-07-13", "Subject", "Body")
    db.update_outreach_entry(entry_id, status="sent", provider="agentmail", agentmail_thread_id="am-thread-fail")
    db.record_processed_agentmail_message("msg-am-thread-local", contact_id, job_id, "genuine_reply")
    monkeypatch.setenv("AGENTMAIL_INBOX_ID", "inbox-1")

    def _raise(inbox_id, thread_id):
        raise RuntimeError("AgentMail unreachable")

    monkeypatch.setattr(app_module.agentmail_client, "get_thread_messages", _raise)

    resp = client.get(f"/api/inbox-digest/contact/{contact_id}/thread")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["source"] == "local"
    assert any(m["message_id"] == "msg-am-thread-local" for m in body["messages"])
