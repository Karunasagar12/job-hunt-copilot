import os
import tempfile

import pytest

import api.app as app_module

db = app_module.db
app_module.app.config["TESTING"] = True


@pytest.fixture
def client():
    with app_module.app.test_client() as c:
        yield c


def test_get_stats_this_week_has_interviews_not_emails_drafted():
    db.init_db()
    jid = db.create_job("Acme Corp", "PM", "india")
    db.update_job(jid, status="generating")
    db.update_job(jid, status="cv_ready")
    db.update_job(jid, status="applied")
    db.update_job(jid, status="sent")
    db.update_job(jid, status="reply")
    db.update_job(jid, status="interview")

    stats = db.get_stats()

    assert "interviews" in stats["this_week"]
    assert "emails_drafted" not in stats["this_week"]
    assert stats["this_week"]["interviews"] >= 1


def test_get_stats_interviews_only_counts_interview_status():
    db.init_db()
    jid = db.create_job("Other Co", "Engineer", "eu")
    db.update_job(jid, status="generating")
    db.update_job(jid, status="cv_ready")
    db.update_job(jid, status="applied")

    stats = db.get_stats()
    before = stats["this_week"]["interviews"]

    jid2 = db.create_job("Third Co", "Analyst", "gcc")
    db.update_job(jid2, status="generating")
    db.update_job(jid2, status="cv_ready")
    db.update_job(jid2, status="applied")
    db.update_job(jid2, status="sent")
    db.update_job(jid2, status="reply")
    db.update_job(jid2, status="interview")

    stats_after = db.get_stats()
    assert stats_after["this_week"]["interviews"] == before + 1


def test_get_stats_response_rate_counts_replied_contact_with_gmail_draft_touchpoint():
    db.init_db()
    jid = db.create_job("Response Rate Co", "PM", "india")
    contact_id = db.create_contact(jid, "Jane Doe", "hiring_manager", email="jane.responserate@example.com")
    entry_id = db.create_outreach_entry(contact_id, jid, "email", 1, "2026-07-14", "Subject", "Body")
    db.update_outreach_entry(entry_id, status="gmail_draft")

    stats_before = db.get_stats()

    db.update_contact(contact_id, replied=1)

    stats_after = db.get_stats()

    assert stats_after["response_rate"] > stats_before["response_rate"], (
        "a replied contact on a job with a gmail_draft email touchpoint must move response_rate -- "
        "sent_count is now derived from outreach_log activity, not the never-advanced jobs.status field"
    )


def test_get_stats_response_rate_does_not_double_count_multiple_replied_contacts_same_job():
    db.init_db()
    jid = db.create_job("Double Reply Co", "Engineer", "eu")
    c1 = db.create_contact(jid, "Jane Doe", "hiring_manager", email="jane.double@example.com")
    entry_id = db.create_outreach_entry(c1, jid, "email", 1, "2026-07-14", "Subject", "Body")
    db.update_outreach_entry(entry_id, status="gmail_draft")
    db.update_contact(c1, replied=1)

    stats_one_reply = db.get_stats()

    c2 = db.create_contact(jid, "John Smith", "recruiter", email="john.double@example.com")
    db.update_contact(c2, replied=1)

    stats_two_replies = db.get_stats()

    assert stats_two_replies["response_rate"] == stats_one_reply["response_rate"], (
        "a second replied contact on the same already-counted job must not move response_rate again"
    )


def test_geo_stats_endpoint_counts_replied_contact_with_gmail_draft_touchpoint(client):
    jid = db.create_job("Geo Stats Co", "PM", "india")
    contact_id = db.create_contact(jid, "Jane Doe", "hiring_manager", email="jane.geo@example.com")
    entry_id = db.create_outreach_entry(contact_id, jid, "email", 1, "2026-07-14", "Subject", "Body")
    db.update_outreach_entry(entry_id, status="gmail_draft")

    rate_before = client.get("/api/stats/geo/india").get_json()["response_rate"]

    db.update_contact(contact_id, replied=1)

    rate_after = client.get("/api/stats/geo/india").get_json()["response_rate"]

    assert rate_after > rate_before, (
        "a replied contact on a job with a gmail_draft email touchpoint must move geo_stats response_rate too"
    )


def test_get_stats_sent_count_ignores_draft_only_touchpoint():
    db.init_db()
    stats_before = db.get_stats()

    jid = db.create_job("Draft Only Co", "Analyst", "gcc")
    contact_id = db.create_contact(jid, "Unsent Contact", "recruiter", email="unsent.draftonly@example.com")
    db.create_outreach_entry(contact_id, jid, "email", 1, "2026-07-14", "Subject", "Body")
    db.update_contact(contact_id, replied=1)

    stats_after = db.get_stats()

    assert stats_after["response_rate"] == stats_before["response_rate"], (
        "a status='draft' touchpoint (no Gmail draft created yet) must not count toward sent_count, "
        "so a replied contact on a draft-only job must not move response_rate"
    )


def test_get_stats_sent_count_ignores_linkedin_channel():
    db.init_db()
    stats_before = db.get_stats()

    jid = db.create_job("LinkedIn Only Co", "Consultant", "eu")
    contact_id = db.create_contact(jid, "LinkedIn Contact", "recruiter", email="linkedin.only@example.com")
    entry_id = db.create_outreach_entry(contact_id, jid, "linkedin_connect", 1, "2026-07-14", "", "Body")
    db.update_outreach_entry(entry_id, status="sent")
    db.update_contact(contact_id, replied=1)

    stats_after = db.get_stats()

    assert stats_after["response_rate"] == stats_before["response_rate"], (
        "a LinkedIn-channel touchpoint must not count toward sent_count -- "
        "channel='email' only, matching the existing sent_at_recent precedent"
    )


def test_get_stats_replied_contact_without_any_touchpoint_does_not_inflate_response_rate():
    db.init_db()
    stats_before = db.get_stats()

    jid = db.create_job("No Touchpoint Co", "Director", "india")
    contact_id = db.create_contact(jid, "Never Contacted", "executive", email="never.contacted@example.com")
    db.update_contact(contact_id, replied=1)

    stats_after = db.get_stats()

    assert stats_after["response_rate"] == stats_before["response_rate"], (
        "a replied contact on a job with zero outreach_log rows at all must not count -- "
        "replied_jobs' population must stay bounded by sent_count's population"
    )
