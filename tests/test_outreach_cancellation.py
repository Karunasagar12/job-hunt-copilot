import pytest

import api.app as app_module

db = app_module.db
import gmail_client
app_module.app.config["TESTING"] = True


def _client():
    return app_module.app.test_client()


def _make_job_and_contact(contact_type="hiring_manager"):
    job_id = db.create_job("Acme Corp", "PM", "india")
    contact_id = db.create_contact(job_id, "Jane Doe", contact_type)
    return job_id, contact_id


def _add_entry(contact_id, job_id, channel, seq, status, gmail_draft_id=None):
    # provider="gmail" explicit: this file tests Gmail-draft cancellation
    # behavior specifically (gmail_client mocking throughout) -- the
    # create_outreach_entry default flipped to "agentmail" in Task 2, so
    # without this these rows would no longer be gmail_draft-cancellable.
    eid = db.create_outreach_entry(contact_id, job_id, channel, seq, "2026-07-13", "Subject", "Body", provider="gmail")
    kwargs = {"status": status}
    if gmail_draft_id:
        kwargs["gmail_draft_id"] = gmail_draft_id
    db.update_outreach_entry(eid, **kwargs)
    return eid


def test_bounced_endpoint_sets_email_status_and_cancels_pending_touchpoints(monkeypatch):
    client = _client()
    job_id, contact_id = _make_job_and_contact()
    _add_entry(contact_id, job_id, "email", 1, "draft")
    deleted = []
    monkeypatch.setattr(gmail_client, "delete_draft", lambda draft_id: deleted.append(draft_id))

    resp = client.post(f"/api/contacts/{contact_id}/bounced")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["contact"]["email_status"] == "bounced"
    assert body["cancelled_count"] == 1
    assert deleted == []  # this entry had no gmail_draft_id, nothing to delete


def test_bounced_endpoint_deletes_live_gmail_drafts(monkeypatch):
    client = _client()
    job_id, contact_id = _make_job_and_contact()
    _add_entry(contact_id, job_id, "email", 4, "gmail_draft", gmail_draft_id="gdraft-xyz")
    deleted = []
    monkeypatch.setattr(gmail_client, "delete_draft", lambda draft_id: deleted.append(draft_id))

    resp = client.post(f"/api/contacts/{contact_id}/bounced")

    assert resp.status_code == 200
    assert deleted == ["gdraft-xyz"]


def test_bounced_endpoint_404s_for_unknown_contact():
    client = _client()
    resp = client.post("/api/contacts/999999/bounced")
    assert resp.status_code == 404


def test_skip_contact_endpoint_cancels_pending_touchpoints_without_setting_any_flag(monkeypatch):
    client = _client()
    job_id, contact_id = _make_job_and_contact()
    _add_entry(contact_id, job_id, "email", 1, "draft")
    monkeypatch.setattr(gmail_client, "delete_draft", lambda draft_id: None)

    resp = client.post(f"/api/contacts/{contact_id}/skip")

    assert resp.status_code == 200
    assert resp.get_json()["cancelled_count"] == 1
    contact = db._get_conn().execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    assert contact["email_status"] is None
    assert contact["replied"] == 0


def test_skip_contact_endpoint_404s_for_unknown_contact():
    client = _client()
    resp = client.post("/api/contacts/999999/skip")
    assert resp.status_code == 404


def test_replied_cascades_for_hiring_manager(monkeypatch):
    client = _client()
    job_id, hm_id = _make_job_and_contact("hiring_manager")
    peer_id = db.create_contact(job_id, "Peer Person", "peer")
    _add_entry(hm_id, job_id, "email", 1, "draft")
    _add_entry(peer_id, job_id, "email", 1, "draft")
    monkeypatch.setattr(gmail_client, "delete_draft", lambda draft_id: None)

    resp = client.post(f"/api/contacts/{hm_id}/replied")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["contact"]["replied"] == 1
    assert body["cancelled_count"] == 1
    assert body["cascaded"] == [{"contact_id": peer_id, "name": "Peer Person", "cancelled_count": 1}]
    peer_entries = db._get_conn().execute(
        "SELECT status FROM outreach_log WHERE contact_id = ?", (peer_id,)
    ).fetchall()
    assert all(row["status"] == "skipped" for row in peer_entries)


def test_replied_cascades_for_recruiter_and_executive(monkeypatch):
    client = _client()
    job_id, recruiter_id = _make_job_and_contact("recruiter")
    other_id = db.create_contact(job_id, "Someone Else", "executive")
    _add_entry(recruiter_id, job_id, "email", 1, "draft")
    _add_entry(other_id, job_id, "email", 1, "draft")
    monkeypatch.setattr(gmail_client, "delete_draft", lambda draft_id: None)

    resp = client.post(f"/api/contacts/{recruiter_id}/replied")

    assert resp.get_json()["cascaded"][0]["contact_id"] == other_id


def test_replied_does_not_cascade_for_peer(monkeypatch):
    client = _client()
    job_id, peer_id = _make_job_and_contact("peer")
    other_id = db.create_contact(job_id, "Someone Else", "hiring_manager")
    _add_entry(peer_id, job_id, "email", 1, "draft")
    _add_entry(other_id, job_id, "email", 1, "draft")
    monkeypatch.setattr(gmail_client, "delete_draft", lambda draft_id: None)

    resp = client.post(f"/api/contacts/{peer_id}/replied")

    assert resp.get_json()["cascaded"] == []
    other_entries = db._get_conn().execute(
        "SELECT status FROM outreach_log WHERE contact_id = ?", (other_id,)
    ).fetchall()
    assert all(row["status"] == "draft" for row in other_entries)


def test_replied_does_not_cascade_for_agency(monkeypatch):
    client = _client()
    job_id, agency_id = _make_job_and_contact("agency")
    other_id = db.create_contact(job_id, "Someone Else", "hiring_manager")
    _add_entry(agency_id, job_id, "email", 1, "draft")
    _add_entry(other_id, job_id, "email", 1, "draft")
    monkeypatch.setattr(gmail_client, "delete_draft", lambda draft_id: None)

    resp = client.post(f"/api/contacts/{agency_id}/replied")

    assert resp.get_json()["cascaded"] == []
    other_entries = db._get_conn().execute(
        "SELECT status FROM outreach_log WHERE contact_id = ?", (other_id,)
    ).fetchall()
    assert all(row["status"] == "draft" for row in other_entries)


def test_replied_deletes_live_gmail_drafts_for_the_replying_contact(monkeypatch):
    client = _client()
    job_id, contact_id = _make_job_and_contact("hiring_manager")
    _add_entry(contact_id, job_id, "email", 4, "gmail_draft", gmail_draft_id="gdraft-replied")
    deleted = []
    monkeypatch.setattr(gmail_client, "delete_draft", lambda draft_id: deleted.append(draft_id))

    client.post(f"/api/contacts/{contact_id}/replied")

    assert deleted == ["gdraft-replied"]


def test_gmail_delete_failure_does_not_prevent_db_cancellation_from_completing(monkeypatch):
    # gmail_client.delete_draft itself never raises in production (Task 2 wraps
    # every failure in try/except) — this simulates what would happen if it
    # somehow did, to prove the DB-side cancellation is unaffected either way.
    # _cancel_contact_touchpoints calls db.cancel_pending_touchpoints (which
    # commits) BEFORE calling gmail_client.delete_draft, so the DB write has
    # already landed by the time any exception could occur.
    client = _client()
    job_id, contact_id = _make_job_and_contact("hiring_manager")
    eid = _add_entry(contact_id, job_id, "email", 4, "gmail_draft", gmail_draft_id="gdraft-fails")

    def _raise(draft_id):
        raise RuntimeError("simulated Gmail API failure")
    monkeypatch.setattr(gmail_client, "delete_draft", _raise)

    with pytest.raises(RuntimeError):
        client.post(f"/api/contacts/{contact_id}/replied")

    entry = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (eid,)).fetchone()
    assert entry["status"] == "skipped"


def test_start_outreach_now_defaults_to_agentmail_and_skip_still_cancels(monkeypatch):
    """Cutover (October 2026): api/app.py's /outreach/start no longer overrides
    provider="gmail" at its create_outreach_entry call site -- real AgentMail
    credentials are in production .env, poll_agentmail_inbox.py is on a
    systemd timer, and new outreach now takes db.create_outreach_entry's own
    default (provider='agentmail'). This replaces the old regression test
    that pinned the opposite behavior (provider="gmail" was deliberate before
    the cutover; now the inherited default is deliberate). Confirms Skip
    still cancels a fresh agentmail-provider 'draft' row via
    cancel_pending_touchpoints's agentmail branch, with no Gmail draft
    involved at all (no gmail_client.delete_draft call expected)."""
    client = _client()
    job_id, contact_id = _make_job_and_contact()
    db.update_contact(contact_id, email="jane@acme.com")

    touchpoint = {
        "contact_id": contact_id, "channel": "email", "sequence_num": 4,
        "scheduled_date": "2026-07-13", "subject": "Subject", "content": "Body",
    }
    monkeypatch.setattr(app_module.outreach_manager, "get_unmatched_contacts", lambda raw, contacts: [])
    monkeypatch.setattr(app_module.outreach_manager, "parse_and_schedule", lambda raw, contacts: [touchpoint])

    start_resp = client.post(f"/api/jobs/{job_id}/outreach/start")
    assert start_resp.status_code == 200
    row = db._get_conn().execute(
        "SELECT id, provider, status FROM outreach_log WHERE contact_id = ?", (contact_id,)
    ).fetchone()
    assert row["provider"] == "agentmail"
    assert row["status"] == "draft"
    eid = row["id"]

    deleted = []
    monkeypatch.setattr(gmail_client, "delete_draft", lambda draft_id: deleted.append(draft_id))
    skip_resp = client.post(f"/api/contacts/{contact_id}/skip")

    assert skip_resp.status_code == 200
    assert skip_resp.get_json()["cancelled_count"] == 1
    assert deleted == []
    status = db._get_conn().execute("SELECT status FROM outreach_log WHERE id = ?", (eid,)).fetchone()["status"]
    assert status == "skipped"
