"""FullEnrich REST API client for contact search and email enrichment.

Search is synchronous (people/search). Email enrichment is asynchronous on
FullEnrich's side (submit, then poll ~30-90s for a result) -- see
match_by_linkedin() for a synchronous submit+poll convenience wrapper used by
callers with no DB row to defer an async result into, and
enrich_by_linkedin_async() for callers that do have one.
"""

from __future__ import annotations

import settings
import threading
import time
from typing import Any

import requests

FULLENRICH_API_BASE_URL = "https://app.fullenrich.com/api/v2"
FULLENRICH_ENRICH_BULK_URL = f"{FULLENRICH_API_BASE_URL}/contact/enrich/bulk"

# Confirmed live against FullEnrich's own docs: "Valid"/"Probably Valid" bounce
# ~1-9%, plain "Catch-all" bounces ~26-40%. user made an explicit,
# informed call to accept catch-all anyway (treats this as a numbers game) --
# don't quietly tighten this back up.
_ACCEPTED_WORK_EMAIL_STATUSES = {"DELIVERABLE", "CATCH_ALL"}
_IN_PROGRESS_STATUSES = {"CREATED", "IN_PROGRESS"}
_HIDDEN_ON_FREE_PLAN = "HIDDEN_ON_FREE_PLAN"


def _get_api_key() -> str | None:
    api_key = settings.get("integrations.fullenrich.api_key")
    if not api_key:
        print("Warning: FULLENRICH_API_KEY is not set. FullEnrich requests will be skipped.")
        return None
    return api_key


def _build_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def check_credentials() -> tuple[bool, str]:
    """Read account credits without submitting an enrichment."""
    api_key = _get_api_key()
    if not api_key:
        return False, 'Not configured yet'
    try:
        response = requests.get(f'{FULLENRICH_API_BASE_URL}/account/credits',
                                headers=_build_headers(api_key), timeout=15)
    except requests.RequestException:
        return False, 'Connection test failed. Check your credentials and try again.'
    if response.status_code == 200:
        return True, 'Connected successfully'
    return False, 'Connection test failed. Check your credentials and try again.'


def clean_name_part(value: Any) -> str | None:
    """Normalize a FullEnrich name field, treating the free-plan redaction placeholder as unknown."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or stripped == _HIDDEN_ON_FREE_PLAN:
        return None
    return stripped


def map_person(person: dict[str, Any]) -> dict[str, Any]:
    """Map a FullEnrich person/profile object to the app's contact shape. Email is always
    None here -- it's resolved separately via submit_enrichment/poll_enrichment."""
    employment = person.get("employment")
    current = employment.get("current") if isinstance(employment, dict) else None
    current = current if isinstance(current, dict) else {}

    company = current.get("company")
    company_name = company.get("name") if isinstance(company, dict) else None

    name = clean_name_part(person.get("full_name"))
    if not name:
        first_name = clean_name_part(person.get("first_name"))
        last_name = clean_name_part(person.get("last_name"))
        name = " ".join(part for part in (first_name, last_name) if part) or None

    linkedin_url = None
    social_profiles = person.get("social_profiles")
    if isinstance(social_profiles, dict):
        professional_network = social_profiles.get("professional_network")
        if isinstance(professional_network, dict):
            linkedin_url = professional_network.get("url")

    return {
        "name": name,
        "title": current.get("title") or person.get("headline"),
        "email": None,
        "linkedin_url": linkedin_url,
        # Reuses the existing `apollo_id` DB column to avoid a schema migration --
        # holds FullEnrich's profile id now, not an Apollo id.
        "apollo_id": person.get("id"),
        "company": company_name,
    }


def submit_enrichment(linkedin_url: str, name: str = "job-hunt-system enrich") -> str | None:
    """Submit an asynchronous FullEnrich work-email enrichment request for a LinkedIn URL.
    Never requests personal emails or phone numbers -- work email only (1 credit vs
    3/10 for personal email/phone), per an explicit cost-control decision."""
    api_key = _get_api_key()
    if not api_key:
        return None

    payload = {
        "name": name,
        "data": [{"linkedin_url": linkedin_url, "enrich_fields": ["contact.work_emails"]}],
    }

    try:
        response = requests.post(FULLENRICH_ENRICH_BULK_URL, headers=_build_headers(api_key), json=payload, timeout=10)
    except requests.RequestException as exc:
        print(f"FullEnrich API network error during enrichment submit: {exc}")
        return None

    if response.status_code != 200:
        print(f"FullEnrich API error during enrichment submit: status={response.status_code}, body={response.text}")
        return None

    try:
        data = response.json()
    except ValueError as exc:
        print(f"FullEnrich API returned invalid JSON during enrichment submit: {exc}")
        return None

    enrichment_id = data.get("enrichment_id")
    if not isinstance(enrichment_id, str) or not enrichment_id.strip():
        print(f"FullEnrich API enrichment submit missing enrichment_id: body={data}")
        return None

    return enrichment_id


def _extract_finished_result(data: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    """Extract (accepted_email, profile) from a FINISHED enrichment response body."""
    results = data.get("data")
    if not isinstance(results, list) or not results:
        return None, None

    first_result = results[0]
    if not isinstance(first_result, dict):
        return None, None

    profile = first_result.get("profile")
    profile = profile if isinstance(profile, dict) else None

    email = None
    contact_info = first_result.get("contact_info")
    if isinstance(contact_info, dict):
        most_probable = contact_info.get("most_probable_work_email")
        if isinstance(most_probable, dict):
            candidate_email = most_probable.get("email")
            status = most_probable.get("status")
            if isinstance(candidate_email, str) and status in _ACCEPTED_WORK_EMAIL_STATUSES:
                email = candidate_email

    return email, profile


def poll_enrichment(enrichment_id: str, poll_interval_seconds: float = 10.0, timeout_seconds: float = 120.0) -> tuple[str | None, dict[str, Any] | None]:
    """Poll a FullEnrich enrichment until FINISHED, terminally failed, or timed out.
    Returns (accepted_email_or_None, profile_or_None)."""
    api_key = _get_api_key()
    if not api_key:
        return None, None

    url = f"{FULLENRICH_ENRICH_BULK_URL}/{enrichment_id}"
    deadline = time.monotonic() + timeout_seconds

    while True:
        try:
            response = requests.get(url, headers=_build_headers(api_key), timeout=15)
        except requests.RequestException as exc:
            print(f"FullEnrich API network error during enrichment poll: {exc}")
            return None, None

        if response.status_code != 200:
            print(f"FullEnrich API error during enrichment poll: status={response.status_code}, body={response.text}")
            return None, None

        try:
            data = response.json()
        except ValueError as exc:
            print(f"FullEnrich API returned invalid JSON during enrichment poll: {exc}")
            return None, None

        status = data.get("status")
        if status == "FINISHED":
            return _extract_finished_result(data)

        if status not in _IN_PROGRESS_STATUSES:
            print(f"FullEnrich enrichment ended without result: enrichment_id={enrichment_id}, status={status}")
            return None, None

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(f"FullEnrich enrichment timed out: enrichment_id={enrichment_id}")
            return None, None
        time.sleep(min(poll_interval_seconds, remaining))


def match_by_linkedin(linkedin_url: str) -> dict[str, Any] | None:
    """Synchronous submit+poll convenience -- same call contract as the old
    apollo_client.match_by_linkedin(url) -> dict|None. For callers with no DB row to
    defer an async result into (match_linkedin, saved_jobs_contact_lookup,
    deliver_discovered_contacts): they accept the ~30-90s in-request wait by design,
    same tolerance the app already has for CV-generation waits."""
    enrichment_id = submit_enrichment(linkedin_url)
    if not enrichment_id:
        return None

    email, profile = poll_enrichment(enrichment_id)
    if not profile:
        return None

    mapped = map_person(profile)
    mapped["email"] = email
    return mapped


def enrich_by_linkedin_async(linkedin_url: str, on_result, name: str = "job-hunt-system enrich") -> str | None:
    """Submit a LinkedIn enrichment and invoke on_result(email, profile) from a daemon
    polling thread once it completes. For callers with an existing DB contact row to
    update once the result lands (get_contact_email)."""
    enrichment_id = submit_enrichment(linkedin_url, name=name)
    if not enrichment_id:
        return None

    def _worker() -> None:
        try:
            email, profile = poll_enrichment(enrichment_id)
            on_result(email, profile)
        except Exception as exc:  # daemon worker must never crash the process
            print(f"FullEnrich async enrichment callback failed: {exc}")

    threading.Thread(target=_worker, daemon=True).start()
    return enrichment_id


if __name__ == "__main__":
    sample_match = match_by_linkedin("https://www.linkedin.com/in/satyanadella")
    print(sample_match)
