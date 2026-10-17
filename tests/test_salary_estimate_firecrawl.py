import os
import tempfile
from pathlib import Path

os.environ.setdefault("FIRECRAWL_API_KEY", "fc-test-key-for-mocked-tests")

import api.app as app_module  # noqa: E402

db = app_module.db
app_module.app.config["TESTING"] = True


class _FakeFirecrawlResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return {"data": self._data}


def _install_fake_llm(monkeypatch, estimate):
    """Patches llm_client.call_llm and returns a dict recording the call args."""
    recorder = {}

    def _fake_call_llm(system_prompt, user_text, max_tokens=None, timeout=None):
        recorder["system_prompt"] = system_prompt
        recorder["prompt"] = user_text
        recorder["max_tokens"] = max_tokens
        recorder["timeout"] = timeout
        return estimate

    monkeypatch.setattr(app_module.llm_client, "call_llm", _fake_call_llm)
    return recorder


def _setup_knowledge_files(monkeypatch):
    tmp = Path(tempfile.mkdtemp())
    knowledge_dir = tmp / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "career-master.md").write_text("Career knowledge base", encoding="utf-8")
    (knowledge_dir / "employment-master.md").write_text("Employment knowledge base", encoding="utf-8")
    monkeypatch.setenv("DATA_DIR", str(tmp))


# ── _search_firecrawl_salary unit tests ───────────────────────────────────────

def test_search_firecrawl_salary_india_builds_query_and_joins_snippets(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-india-key")
    calls = []

    def fake_post(url, *, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _FakeFirecrawlResponse([
            {"title": "AmbitionBox Example salaries", "description": "Project Manager salary is Rs 20L-Rs 30L."},
            {"title": "Empty snippet", "description": ""},
            {"title": "Example Health PM pay", "description": "Average total compensation is around Rs 28L."},
            {"title": "Missing description"},
        ])

    monkeypatch.setattr(app_module.requests, "post", fake_post)

    result = app_module._search_firecrawl_salary("Example Health", "Project Manager", "india")

    assert result == (
        "AmbitionBox Example salaries: Project Manager salary is Rs 20L-Rs 30L.\n"
        "Example Health PM pay: Average total compensation is around Rs 28L."
    )
    assert calls[0]["url"] == "https://api.firecrawl.dev/v1/search"
    assert calls[0]["headers"] == {
        "Authorization": "Bearer fc-india-key",
        "Content-Type": "application/json",
    }
    assert calls[0]["json"] == {
        "query": "AmbitionBox Example Health Project Manager salary India",
        "limit": 5,
    }
    assert "scrapeOptions" not in calls[0]["json"]
    assert calls[0]["timeout"] == 20


def test_search_firecrawl_salary_gcc_uses_bayt_and_uae(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-gcc-key")
    calls = []

    def fake_post(url, *, headers, json, timeout):
        calls.append({"json": json})
        return _FakeFirecrawlResponse([
            {"title": "Bayt Emirates NBD salary", "description": "Project Manager salary range AED 35k-45k monthly."}
        ])

    monkeypatch.setattr(app_module.requests, "post", fake_post)

    result = app_module._search_firecrawl_salary("Emirates NBD", "Project Manager", "gcc")

    assert result == "Bayt Emirates NBD salary: Project Manager salary range AED 35k-45k monthly."
    assert calls[0]["json"]["query"] == "Bayt Emirates NBD Project Manager salary UAE"


def test_search_firecrawl_salary_eu_uses_glassdoor_and_europe(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-eu-key")
    calls = []

    def fake_post(url, *, headers, json, timeout):
        calls.append({"json": json})
        return _FakeFirecrawlResponse([
            {"title": "Glassdoor Spotify salary", "description": "Engineering Manager total pay is EUR150k-EUR190k."}
        ])

    monkeypatch.setattr(app_module.requests, "post", fake_post)

    result = app_module._search_firecrawl_salary("Spotify", "Engineering Manager", "eu")

    assert result == "Glassdoor Spotify salary: Engineering Manager total pay is EUR150k-EUR190k."
    assert calls[0]["json"]["query"] == "Glassdoor Spotify Engineering Manager salary Europe"


def test_search_firecrawl_salary_unknown_geo_defaults_to_glassdoor_and_empty_geo_term(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-key")
    calls = []

    def fake_post(url, *, headers, json, timeout):
        calls.append({"json": json})
        return _FakeFirecrawlResponse([{"title": "T", "description": "D"}])

    monkeypatch.setattr(app_module.requests, "post", fake_post)

    result = app_module._search_firecrawl_salary("Acme", "Role", "us")
    assert calls[0]["json"]["query"] == "Glassdoor Acme Role salary"
    assert result == "T: D"


def test_search_firecrawl_salary_caps_result_at_2000_chars(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-key")
    long_desc = "A" * 1500
    data = [
        {"title": "Title1", "description": long_desc},
        {"title": "Title2", "description": long_desc},
    ]

    def fake_post(url, *, headers, json, timeout):
        return _FakeFirecrawlResponse(data)

    monkeypatch.setattr(app_module.requests, "post", fake_post)

    result = app_module._search_firecrawl_salary("Co", "Role", "eu")
    assert len(result) == 2000
    assert result.endswith("A")


def test_search_firecrawl_salary_empty_results_returns_empty_string(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-key")

    def fake_post(url, *, headers, json, timeout):
        return _FakeFirecrawlResponse([])

    monkeypatch.setattr(app_module.requests, "post", fake_post)

    assert app_module._search_firecrawl_salary("Co", "Role", "eu") == ""


def test_search_firecrawl_salary_all_empty_descriptions_returns_empty_string(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-key")

    def fake_post(url, *, headers, json, timeout):
        return _FakeFirecrawlResponse([{"title": "T1", "description": ""}, {"title": "T2"}])

    monkeypatch.setattr(app_module.requests, "post", fake_post)

    assert app_module._search_firecrawl_salary("Co", "Role", "eu") == ""


def test_search_firecrawl_salary_returns_empty_on_network_exception(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-key")

    def fake_post(url, *, headers, json, timeout):
        raise TimeoutError("simulated timeout")

    monkeypatch.setattr(app_module.requests, "post", fake_post)

    assert app_module._search_firecrawl_salary("Acme", "Director", "eu") == ""


def test_search_firecrawl_salary_logs_warning_on_failure(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-key")
    warnings = []

    def capture_warning(msg, *args):
        warnings.append((msg, args))

    monkeypatch.setattr(app_module.logger, "warning", capture_warning)

    def fake_post(url, *, headers, json, timeout):
        raise ConnectionError("simulated outage")

    monkeypatch.setattr(app_module.requests, "post", fake_post)

    result = app_module._search_firecrawl_salary("Acme", "Director", "eu")
    assert result == ""
    assert len(warnings) == 1
    assert "Firecrawl salary search failed for query" in warnings[0][0]
    assert "Glassdoor Acme Director salary " in warnings[0][1][0]


def test_search_firecrawl_salary_returns_empty_when_api_key_missing(monkeypatch):
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)

    def fake_post(url, *, headers, json, timeout):
        raise AssertionError("requests.post must not be called without FIRECRAWL_API_KEY")

    monkeypatch.setattr(app_module.requests, "post", fake_post)

    assert app_module._search_firecrawl_salary("Acme", "Director", "eu") == ""


# ── Endpoint integration tests ────────────────────────────────────────────────

def test_salary_estimate_endpoint_includes_salary_research_in_prompt(monkeypatch):
    _setup_knowledge_files(monkeypatch)
    salary_research = "AmbitionBox ExampleCo PM: Average salary is Rs 32L total compensation."
    estimate = "Base: Rs 28L-Rs 34L | Total: Rs 32L-Rs 40L"
    recorder = _install_fake_llm(monkeypatch, estimate)

    def fake_salary_research(company, role, geo):
        assert company == "ExampleCo"
        assert role == "Project Manager"
        assert geo == "india"
        return salary_research

    monkeypatch.setattr(app_module, "_search_firecrawl_salary", fake_salary_research)

    job_id = db.create_job("ExampleCo", "Project Manager", "india")
    response = app_module.app.test_client().get(f"/api/jobs/{job_id}/salary-estimate")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload == {"estimate": estimate, "cached": False}
    assert salary_research in recorder["prompt"]
    assert "SALARY RESEARCH (Glassdoor/Bayt/AmbitionBox, live search results):" in recorder["prompt"]
    assert "prioritize the live salary research above when present" in recorder["prompt"]


def test_salary_estimate_cache_skips_firecrawl_on_second_call(monkeypatch):
    _setup_knowledge_files(monkeypatch)
    estimate = "Base: AED 420k-500k | Total: AED 480k-620k"
    _install_fake_llm(monkeypatch, estimate)

    search_calls = {"count": 0}

    def fake_salary_research(company, role, geo):
        search_calls["count"] += 1
        return "Bayt CacheCo Director: AED 45k monthly total compensation."

    monkeypatch.setattr(app_module, "_search_firecrawl_salary", fake_salary_research)

    job_id = db.create_job("CacheCo", "Director of Product", "gcc")
    client = app_module.app.test_client()

    first_response = client.get(f"/api/jobs/{job_id}/salary-estimate")
    assert first_response.status_code == 200
    assert first_response.get_json() == {"estimate": estimate, "cached": False}
    assert search_calls["count"] == 1

    def fail_if_called(company, role, geo):
        raise AssertionError("_search_firecrawl_salary must not be called for cached salary estimates")

    monkeypatch.setattr(app_module, "_search_firecrawl_salary", fail_if_called)

    second_response = client.get(f"/api/jobs/{job_id}/salary-estimate")
    assert second_response.status_code == 200
    assert second_response.get_json() == {"estimate": estimate, "cached": True}


def test_salary_estimate_endpoint_gracefully_degrades_when_firecrawl_fails(monkeypatch):
    _setup_knowledge_files(monkeypatch)
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test-key")
    estimate = "Base: EUR120k-EUR145k | Total: EUR140k-EUR175k"
    _install_fake_llm(monkeypatch, estimate)

    def fake_post(url, *, headers, json, timeout):
        raise ConnectionError("simulated Firecrawl outage")

    monkeypatch.setattr(app_module.requests, "post", fake_post)

    job_id = db.create_job("EuroCo", "Engineering Manager", "eu")
    response = app_module.app.test_client().get(f"/api/jobs/{job_id}/salary-estimate")

    assert response.status_code == 200
    assert response.get_json() == {"estimate": estimate, "cached": False}
