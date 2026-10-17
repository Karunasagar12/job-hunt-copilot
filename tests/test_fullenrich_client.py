import threading
from unittest.mock import Mock, patch

import fullenrich_client


def _submit_response(enrichment_id="enrich-1", status=200):
    resp = Mock()
    resp.status_code = status
    resp.text = "{}"
    resp.json.return_value = {"enrichment_id": enrichment_id}
    return resp


def _profile():
    return {
        "id": "fe-profile-1",
        "full_name": "Jane Doe",
        "headline": "VP Eng",
        "employment": {"current": {"title": "VP Eng", "company": {"name": "Acme"}}},
        "social_profiles": {"professional_network": {"url": "https://linkedin.com/in/jane"}},
    }


def _poll_response(email, email_status, status=200, poll_status="FINISHED"):
    resp = Mock()
    resp.status_code = status
    resp.text = "{}"
    most_probable = {"email": email, "status": email_status} if email is not None else None
    resp.json.return_value = {
        "status": poll_status,
        "data": [{
            "contact_info": {"most_probable_work_email": most_probable} if most_probable else {},
            "profile": _profile(),
        }],
    }
    return resp


def test_match_by_linkedin_returns_email_when_deliverable(monkeypatch):
    monkeypatch.setenv("FULLENRICH_API_KEY", "test-key")
    with patch("fullenrich_client.requests.post", return_value=_submit_response()), \
         patch("fullenrich_client.requests.get", return_value=_poll_response("jane@acme.com", "DELIVERABLE")):
        result = fullenrich_client.match_by_linkedin("https://linkedin.com/in/jane")
    assert result["email"] == "jane@acme.com"
    assert result["name"] == "Jane Doe"
    assert result["apollo_id"] == "fe-profile-1"


def test_match_by_linkedin_returns_email_when_catch_all(monkeypatch):
    # Deliberate: user made an informed call to accept catch-all despite its
    # higher bounce rate, treating this as a numbers game -- don't tighten this back up.
    monkeypatch.setenv("FULLENRICH_API_KEY", "test-key")
    with patch("fullenrich_client.requests.post", return_value=_submit_response()), \
         patch("fullenrich_client.requests.get", return_value=_poll_response("jane@acme.com", "CATCH_ALL")):
        result = fullenrich_client.match_by_linkedin("https://linkedin.com/in/jane")
    assert result["email"] == "jane@acme.com"


def test_match_by_linkedin_nulls_email_when_status_unaccepted(monkeypatch):
    monkeypatch.setenv("FULLENRICH_API_KEY", "test-key")
    with patch("fullenrich_client.requests.post", return_value=_submit_response()), \
         patch("fullenrich_client.requests.get", return_value=_poll_response("jane@acme.com", "UNKNOWN")):
        result = fullenrich_client.match_by_linkedin("https://linkedin.com/in/jane")
    assert result["email"] is None
    assert result["name"] == "Jane Doe"  # profile still comes through even without an accepted email


def test_match_by_linkedin_still_returns_profile_when_no_email_found(monkeypatch):
    monkeypatch.setenv("FULLENRICH_API_KEY", "test-key")
    with patch("fullenrich_client.requests.post", return_value=_submit_response()), \
         patch("fullenrich_client.requests.get", return_value=_poll_response(None, None)):
        result = fullenrich_client.match_by_linkedin("https://linkedin.com/in/jane")
    assert result["email"] is None
    assert result["apollo_id"] == "fe-profile-1"


def test_match_by_linkedin_returns_none_when_submit_fails(monkeypatch):
    monkeypatch.setenv("FULLENRICH_API_KEY", "test-key")
    resp = Mock(status_code=403, text='{"message":"billing"}')
    with patch("fullenrich_client.requests.post", return_value=resp):
        result = fullenrich_client.match_by_linkedin("https://linkedin.com/in/jane")
    assert result is None


def test_match_by_linkedin_returns_none_when_poll_ends_without_result(monkeypatch):
    monkeypatch.setenv("FULLENRICH_API_KEY", "test-key")
    with patch("fullenrich_client.requests.post", return_value=_submit_response()), \
         patch("fullenrich_client.requests.get", return_value=_poll_response(None, None, poll_status="CANCELED")):
        result = fullenrich_client.match_by_linkedin("https://linkedin.com/in/jane")
    assert result is None


def test_map_person_treats_hidden_last_name_as_unknown():
    profile = {
        "id": "fe-1",
        "first_name": "Jane",
        "last_name": "HIDDEN_ON_FREE_PLAN",
        "headline": "SWE Recruiter",
        "employment": {"current": {"title": "SWE Recruiter", "company": {"name": "Google"}}},
        "social_profiles": {"professional_network": {"url": "https://linkedin.com/in/jane"}},
    }
    mapped = fullenrich_client.map_person(profile)
    assert mapped["name"] == "Jane"  # redaction placeholder treated as unknown, not literal text
    assert mapped["email"] is None  # map_person never sets email -- resolved separately
    assert mapped["company"] == "Google"


def test_submit_enrichment_only_requests_work_emails(monkeypatch):
    monkeypatch.setenv("FULLENRICH_API_KEY", "test-key")
    with patch("fullenrich_client.requests.post", return_value=_submit_response()) as mocked_post:
        fullenrich_client.submit_enrichment("https://linkedin.com/in/jane")
    payload = mocked_post.call_args.kwargs["json"]
    assert payload["data"][0]["enrich_fields"] == ["contact.work_emails"]


def test_enrich_by_linkedin_async_invokes_callback_from_daemon_thread(monkeypatch):
    monkeypatch.setenv("FULLENRICH_API_KEY", "test-key")
    done = threading.Event()
    captured = {}

    def on_result(email, profile):
        captured["email"] = email
        captured["profile"] = profile
        done.set()

    with patch("fullenrich_client.requests.post", return_value=_submit_response()), \
         patch("fullenrich_client.requests.get", return_value=_poll_response("jane@acme.com", "DELIVERABLE")):
        enrichment_id = fullenrich_client.enrich_by_linkedin_async("https://linkedin.com/in/jane", on_result)

    assert enrichment_id == "enrich-1"
    assert done.wait(timeout=2), "on_result callback was never invoked"
    assert captured["email"] == "jane@acme.com"
    assert captured["profile"]["id"] == "fe-profile-1"


def test_enrich_by_linkedin_async_returns_none_when_submit_fails(monkeypatch):
    monkeypatch.setenv("FULLENRICH_API_KEY", "test-key")
    resp = Mock(status_code=403, text='{"message":"billing"}')
    with patch("fullenrich_client.requests.post", return_value=resp):
        enrichment_id = fullenrich_client.enrich_by_linkedin_async("https://linkedin.com/in/jane", lambda e, p: None)
    assert enrichment_id is None
