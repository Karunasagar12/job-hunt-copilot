import os
import tempfile

import api.app as app_module  # noqa: E402

db = app_module.db
app_module.app.config["TESTING"] = True


def _client(monkeypatch, secret="test-secret"):
    monkeypatch.setenv("SAVED_JOBS_WEBHOOK_SECRET", secret)
    return app_module.app.test_client()


def _make_job():
    return db.create_job("Whatfix", "AI Product Manager", "india", source_type="company")


def test_needs_contacts_rejects_missing_secret(monkeypatch):
    client = _client(monkeypatch)
    resp = client.get("/api/saved-jobs/needs-contacts")
    assert resp.status_code == 401


def test_needs_contacts_lists_pending_jobs(monkeypatch):
    client = _client(monkeypatch)
    job_id = _make_job()
    db.update_job(job_id, contacts_discovery_status="pending")
    resp = client.get("/api/saved-jobs/needs-contacts", headers={"X-Webhook-Secret": "test-secret"})
    assert resp.status_code == 200
    assert any(j["id"] == job_id for j in resp.get_json()["jobs"])


def test_deliver_discovered_contacts_rejects_missing_secret(monkeypatch):
    client = _client(monkeypatch)
    job_id = _make_job()
    resp = client.post(f"/api/jobs/{job_id}/discovered-contacts", json={"candidates": []})
    assert resp.status_code == 401


def test_deliver_discovered_contacts_skips_invalid_contact_type(monkeypatch):
    client = _client(monkeypatch)
    job_id = _make_job()
    monkeypatch.setattr(app_module.fullenrich_client, "match_by_linkedin", lambda url: None)
    resp = client.post(
        f"/api/jobs/{job_id}/discovered-contacts",
        json={"candidates": [{"name": "Bad Type", "contact_type": "ceo", "linkedin_url": "https://linkedin.com/in/bad"}]},
        headers={"X-Webhook-Secret": "test-secret"},
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"added": 0, "skipped": 1}


def test_deliver_discovered_contacts_adds_valid_candidate_with_no_apollo_match(monkeypatch):
    client = _client(monkeypatch)
    job_id = _make_job()
    monkeypatch.setattr(app_module.fullenrich_client, "match_by_linkedin", lambda url: None)
    resp = client.post(
        f"/api/jobs/{job_id}/discovered-contacts",
        json={"candidates": [{
            "name": "Nitin Chauhan", "title": "Lead PM", "contact_type": "peer",
            "linkedin_url": "https://in.linkedin.com/in/thinkdiscovery",
        }]},
        headers={"X-Webhook-Secret": "test-secret"},
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"added": 1, "skipped": 0}
    contacts = db.get_contacts(job_id)
    assert len(contacts) == 1
    assert contacts[0]["source"] == "hermes_discovered"
    assert contacts[0]["email"] is None


def test_deliver_discovered_contacts_uses_apollo_match_when_found(monkeypatch):
    client = _client(monkeypatch)
    job_id = _make_job()
    monkeypatch.setattr(
        app_module.fullenrich_client, "match_by_linkedin",
        lambda url: {"name": "Saurabh Mehta", "title": "Product Lead", "email": "saurabh@whatfix.com",
                     "linkedin_url": url, "apollo_id": "apollo123"},
    )
    resp = client.post(
        f"/api/jobs/{job_id}/discovered-contacts",
        json={"candidates": [{
            "name": "Saurabh Mehta", "title": "Product Lead", "contact_type": "hiring_manager",
            "linkedin_url": "https://www.linkedin.com/in/saurabhmehta2/",
        }]},
        headers={"X-Webhook-Secret": "test-secret"},
    )
    assert resp.status_code == 200
    contacts = db.get_contacts(job_id)
    assert contacts[0]["email"] == "saurabh@whatfix.com"
    assert contacts[0]["apollo_id"] == "apollo123"


def test_deliver_discovered_contacts_dedupes_existing_linkedin_url(monkeypatch):
    client = _client(monkeypatch)
    job_id = _make_job()
    db.create_contact(job_id, "Existing Person", "hiring_manager", linkedin_url="https://linkedin.com/in/existing")
    monkeypatch.setattr(app_module.fullenrich_client, "match_by_linkedin", lambda url: None)
    resp = client.post(
        f"/api/jobs/{job_id}/discovered-contacts",
        json={"candidates": [{
            "name": "Existing Person", "contact_type": "hiring_manager",
            "linkedin_url": "https://linkedin.com/in/existing",
        }]},
        headers={"X-Webhook-Secret": "test-secret"},
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"added": 0, "skipped": 1}
    assert len(db.get_contacts(job_id)) == 1


def test_deliver_discovered_contacts_dedupes_differently_formatted_url_against_existing(monkeypatch):
    client = _client(monkeypatch)
    job_id = _make_job()
    db.create_contact(job_id, "Nagaraj K P", "hiring_manager", linkedin_url="https://www.linkedin.com/in/nagaraj-kp/")
    monkeypatch.setattr(app_module.fullenrich_client, "match_by_linkedin", lambda url: None)
    resp = client.post(
        f"/api/jobs/{job_id}/discovered-contacts",
        json={"candidates": [{
            "name": "Nagaraj K P", "contact_type": "hiring_manager",
            "linkedin_url": "https://in.linkedin.com/in/nagaraj-kp?trk=job_poster",
        }]},
        headers={"X-Webhook-Secret": "test-secret"},
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"added": 0, "skipped": 1}
    assert len(db.get_contacts(job_id)) == 1


def test_deliver_discovered_contacts_dedupes_differently_formatted_url_within_same_batch(monkeypatch):
    client = _client(monkeypatch)
    job_id = _make_job()
    monkeypatch.setattr(app_module.fullenrich_client, "match_by_linkedin", lambda url: None)
    resp = client.post(
        f"/api/jobs/{job_id}/discovered-contacts",
        json={"candidates": [
            {"name": "Sandeep M", "contact_type": "peer", "linkedin_url": "https://www.linkedin.com/in/majumdersandeep"},
            {"name": "Sandeep M", "contact_type": "peer", "linkedin_url": "https://in.linkedin.com/in/majumdersandeep/"},
        ]},
        headers={"X-Webhook-Secret": "test-secret"},
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"added": 1, "skipped": 1}
    assert len(db.get_contacts(job_id)) == 1


def test_deliver_discovered_contacts_marks_status_complete(monkeypatch):
    client = _client(monkeypatch)
    job_id = _make_job()
    db.update_job(job_id, contacts_discovery_status="pending")
    monkeypatch.setattr(app_module.fullenrich_client, "match_by_linkedin", lambda url: None)
    client.post(
        f"/api/jobs/{job_id}/discovered-contacts",
        json={"candidates": []},
        headers={"X-Webhook-Secret": "test-secret"},
    )
    assert db.get_job(job_id)["contacts_discovery_status"] == "complete"


def test_deliver_discovered_contacts_rejects_non_list_candidates(monkeypatch):
    client = _client(monkeypatch)
    job_id = _make_job()
    resp = client.post(
        f"/api/jobs/{job_id}/discovered-contacts",
        json={"candidates": "not_a_list"},
        headers={"X-Webhook-Secret": "test-secret"},
    )
    assert resp.status_code == 400


def test_contact_lookup_rejects_missing_secret(monkeypatch):
    client = _client(monkeypatch)
    resp = client.get("/api/saved-jobs/contact-lookup?linkedin_url=https://linkedin.com/in/jane")
    assert resp.status_code == 401


def test_contact_lookup_requires_linkedin_url(monkeypatch):
    client = _client(monkeypatch)
    resp = client.get("/api/saved-jobs/contact-lookup", headers={"X-Webhook-Secret": "test-secret"})
    assert resp.status_code == 400


def test_contact_lookup_finds_existing_url_on_a_different_job_and_skips_apollo(monkeypatch):
    client = _client(monkeypatch)
    other_job_id = _make_job()
    db.create_contact(other_job_id, "Existing Person", "hiring_manager", linkedin_url="https://linkedin.com/in/existing")
    calls = []
    monkeypatch.setattr(app_module.fullenrich_client, "match_by_linkedin", lambda url: calls.append(url) or None)

    resp = client.get(
        "/api/saved-jobs/contact-lookup?linkedin_url=https://linkedin.com/in/existing",
        headers={"X-Webhook-Secret": "test-secret"},
    )

    assert resp.status_code == 200
    assert resp.get_json() == {"already_exists": True, "email": None}
    assert calls == []  # Apollo must never be called once a DB URL match is found


def test_contact_lookup_returns_verified_email_for_new_candidate(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(
        app_module.fullenrich_client, "match_by_linkedin",
        lambda url: {"name": "Jane Doe", "title": "VP Eng", "email": "jane@acme.com",
                     "linkedin_url": url, "apollo_id": "apollo1"},
    )

    resp = client.get(
        "/api/saved-jobs/contact-lookup?linkedin_url=https://linkedin.com/in/jane",
        headers={"X-Webhook-Secret": "test-secret"},
    )

    assert resp.status_code == 200
    assert resp.get_json() == {"already_exists": False, "email": "jane@acme.com"}


def test_contact_lookup_returns_null_email_when_apollo_match_is_unverified(monkeypatch):
    client = _client(monkeypatch)
    # match_by_linkedin (Task 1) already nulls the email for unverified matches — this
    # test proves contact-lookup passes that behavior through rather than re-deriving it.
    monkeypatch.setattr(app_module.fullenrich_client, "match_by_linkedin", lambda url: {
        "name": "Jane Doe", "title": "VP Eng", "email": None, "linkedin_url": url, "apollo_id": "apollo1",
    })

    resp = client.get(
        "/api/saved-jobs/contact-lookup?linkedin_url=https://linkedin.com/in/jane",
        headers={"X-Webhook-Secret": "test-secret"},
    )

    assert resp.status_code == 200
    assert resp.get_json() == {"already_exists": False, "email": None}


def test_contact_lookup_flags_already_exists_when_resolved_email_matches_a_different_url(monkeypatch):
    client = _client(monkeypatch)
    other_job_id = _make_job()
    db.create_contact(other_job_id, "Jane Doe", "hiring_manager",
                       email="jane@acme.com", linkedin_url="https://linkedin.com/in/jane-old-vanity-url")
    monkeypatch.setattr(
        app_module.fullenrich_client, "match_by_linkedin",
        lambda url: {"name": "Jane Doe", "title": "VP Eng", "email": "jane@acme.com",
                     "linkedin_url": url, "apollo_id": "apollo1"},
    )

    resp = client.get(
        "/api/saved-jobs/contact-lookup?linkedin_url=https://linkedin.com/in/jane-new-vanity-url",
        headers={"X-Webhook-Secret": "test-secret"},
    )

    assert resp.status_code == 200
    assert resp.get_json() == {"already_exists": True, "email": None}


def test_deliver_discovered_contacts_dedupes_url_against_a_different_job(monkeypatch):
    client = _client(monkeypatch)
    other_job_id = _make_job()
    db.create_contact(other_job_id, "Existing Person", "hiring_manager", linkedin_url="https://linkedin.com/in/existing")
    job_id = _make_job()
    monkeypatch.setattr(app_module.fullenrich_client, "match_by_linkedin", lambda url: None)

    resp = client.post(
        f"/api/jobs/{job_id}/discovered-contacts",
        json={"candidates": [{
            "name": "Existing Person", "contact_type": "hiring_manager",
            "linkedin_url": "https://linkedin.com/in/existing",
        }]},
        headers={"X-Webhook-Secret": "test-secret"},
    )

    assert resp.get_json() == {"added": 0, "skipped": 1}
    assert len(db.get_contacts(job_id)) == 0


def test_deliver_discovered_contacts_dedupes_by_resolved_email_across_different_urls(monkeypatch):
    client = _client(monkeypatch)
    other_job_id = _make_job()
    db.create_contact(other_job_id, "Jane Doe", "hiring_manager",
                       email="jane@acme.com", linkedin_url="https://linkedin.com/in/jane-old-vanity-url")
    job_id = _make_job()
    monkeypatch.setattr(
        app_module.fullenrich_client, "match_by_linkedin",
        lambda url: {"name": "Jane Doe", "title": "VP Eng", "email": "jane@acme.com",
                     "linkedin_url": url, "apollo_id": "apollo1"},
    )

    resp = client.post(
        f"/api/jobs/{job_id}/discovered-contacts",
        json={"candidates": [{
            "name": "Jane Doe", "contact_type": "hiring_manager",
            "linkedin_url": "https://linkedin.com/in/jane-new-vanity-url",
        }]},
        headers={"X-Webhook-Secret": "test-secret"},
    )

    assert resp.get_json() == {"added": 0, "skipped": 1}
    assert len(db.get_contacts(job_id)) == 0


def test_deliver_discovered_contacts_discards_unverified_apollo_match_when_email_absent(monkeypatch):
    client = _client(monkeypatch)
    job_id = _make_job()
    # No "email" field on the candidate, so this falls back to match_by_linkedin —
    # which (Task 1) already returns email=None for an unverified match.
    monkeypatch.setattr(app_module.fullenrich_client, "match_by_linkedin", lambda url: {
        "name": "Jane Doe", "title": "VP Eng", "email": None, "linkedin_url": url, "apollo_id": "apollo1",
    })

    resp = client.post(
        f"/api/jobs/{job_id}/discovered-contacts",
        json={"candidates": [{
            "name": "Jane Doe", "contact_type": "hiring_manager",
            "linkedin_url": "https://linkedin.com/in/jane",
        }]},
        headers={"X-Webhook-Secret": "test-secret"},
    )

    assert resp.get_json() == {"added": 1, "skipped": 0}
    contacts = db.get_contacts(job_id)
    assert contacts[0]["email"] is None
    assert contacts[0]["apollo_id"] == "apollo1"


def test_deliver_discovered_contacts_uses_candidate_supplied_email_without_calling_apollo(monkeypatch):
    client = _client(monkeypatch)
    job_id = _make_job()
    calls = []
    monkeypatch.setattr(app_module.fullenrich_client, "match_by_linkedin", lambda url: calls.append(url) or None)

    resp = client.post(
        f"/api/jobs/{job_id}/discovered-contacts",
        json={"candidates": [{
            "name": "Priya Nair", "contact_type": "hiring_manager",
            "linkedin_url": "https://linkedin.com/in/priya-nair-supplied", "email": "priya-supplied@acme.com",
        }]},
        headers={"X-Webhook-Secret": "test-secret"},
    )

    assert resp.get_json() == {"added": 1, "skipped": 0}
    assert calls == []  # Apollo must not be called when the candidate already supplied an email
    contacts = db.get_contacts(job_id)
    assert contacts[0]["email"] == "priya-supplied@acme.com"


def test_needs_contacts_includes_company_size_when_profile_exists(monkeypatch):
    client = _client(monkeypatch)
    job_id = db.create_job("Whatfix", "AI Product Manager", "india", source_type="company")
    db.update_job(job_id, contacts_discovery_status="pending")
    db.save_company_profile("Whatfix", company_size="51-200")

    resp = client.get("/api/saved-jobs/needs-contacts", headers={"X-Webhook-Secret": "test-secret"})

    job = next(j for j in resp.get_json()["jobs"] if j["id"] == job_id)
    assert job["company_size"] == "51-200"


def test_needs_contacts_company_size_is_null_when_no_profile(monkeypatch):
    client = _client(monkeypatch)
    # Deliberately NOT using _make_job() here -- it always creates a "Whatfix" job,
    # and a different test in this file already gives "Whatfix" a company_profiles
    # row, which would falsely satisfy this "no profile exists" case.
    job_id = db.create_job("Zorbex Never Profiled Inc", "AI Product Manager", "india", source_type="company")
    db.update_job(job_id, contacts_discovery_status="pending")

    resp = client.get("/api/saved-jobs/needs-contacts", headers={"X-Webhook-Secret": "test-secret"})

    job = next(j for j in resp.get_json()["jobs"] if j["id"] == job_id)
    assert job["company_size"] is None
