"""source_jobs.py helpers (job-sourcing spec section 2). Network + LLM mocked."""
from datetime import datetime

import pytest

import source_jobs as sj

CFG = {
    'actor': 'automation-lab~linkedin-jobs-scraper', 'monthly_budget_usd': 5.0,
    'titles': ['Data Scientist', 'Senior Data Scientist', 'Machine Learning Engineer',
               'Data Science Manager', 'Analytics Engineer', 'AI Engineer', 'Product Manager', 'Product Owner'],
    'locations': [dict(linkedin_location=name, geo=geo, remote_only=remote, max_jobs=25,
                       max_charge_usd=0.02) for name, geo, remote in [
        ('United Arab Emirates', 'gcc', False), ('Saudi Arabia', 'gcc', False),
        ('Qatar', 'gcc', False), ('France', 'eu', False), ('European Union', 'eu', True),
        ('Germany', 'eu', False), ('Spain', 'eu', False), ('Ireland', 'eu', False)]],
}
COUNTRIES = [l["linkedin_location"].lower() for l in CFG["locations"] if not l["remote_only"]]
UAE = next(l for l in CFG["locations"] if l["linkedin_location"] == "United Arab Emirates")
EU_REMOTE = next(l for l in CFG["locations"] if l["remote_only"])
JD = "Responsibilities and requirements. " * 20


def reason(title, location="Dubai, United Arab Emirates", jd=JD, loc_cfg=UAE):
    return sj.filter_reason(title, location, jd, loc_cfg, COUNTRIES)


def test_linkedin_id_from_slug_plain_and_fallback():
    assert sj.linkedin_job_id("https://es.linkedin.com/jobs/view/senior-ai-research-engineer-at-biorce-4442812862") == "4442812862"
    assert sj.linkedin_job_id("https://www.linkedin.com/jobs/view/4469594256/?refId=x") == "4469594256"
    assert sj.linkedin_job_id("https://example.com/job", fallback_id="4469594256") == "4469594256"
    assert sj.linkedin_job_id(None, fallback_id="abc") is None


def test_canonical_url_matches_generate_fetch_pattern():
    import re
    url = sj.canonical_url("4442812862")
    assert url == "https://www.linkedin.com/jobs/view/4442812862/"
    assert re.search(r"/jobs/view/(\d+)", url).group(1) == "4442812862"


@pytest.mark.parametrize("title", [
    "Lead Software Engineer – AI Product Development (Data)",   # labelled no (#4)
    "Senior Systems Product Manager, GTM Systems (d/f/m)",       # labelled no (#6) -> see note below
    "Business Process Architect",                               # labelled no (#8)
    "Associate Director - Cyber Security",                      # labelled no (#20)
    "Technology GRC Manager - ServiceNow GRC/IRM",              # labelled no (#25)
    "Senior Solutions Architect",                               # labelled no (#34)
    "ICT Pre-Sales Engineer",                                   # labelled no (#40)
    "AI Software Engineer",                                     # software-engineer rule, per #4
    "Junior Data Scientist",
    "Stage - Chef de produit",
])
def test_labelled_and_rule_rejects(title):
    if "GTM Systems" in title:
        # #6 has a real product-manager anchor; the filter can't know it's off-domain.
        # It passes the filter and is left for GLM-5 to rank low (spike scored it 30).
        assert reason(title) is None
    else:
        assert reason(title) is not None


@pytest.mark.parametrize("title", [
    "Senior Full-Stack Tech Lead – with AI Adoption & Applied AI",   # was mis-rejected (full-stack)
    "Strategy Manager",                                             # was mis-rejected (no anchor)
    "Senior Forecasting Analyst",                                   # was mis-rejected (no anchor)
    "AI Engineer /  Forward Deployed Engineer",                     # was mis-rejected (Entry level)
    "International Product Manager",                                # \bintern\b must not hit
    "Produktmanager (m/w/d)",
    "Chef de produit IA",
    "GenAI Developer",
    "GenAI Solution Architect - BytePlus",
    "Founding Product Manager – Early Stage",                       # Review Focus 1
    "Product Owner",
])
def test_previously_wrong_and_review_fixtures_pass(title):
    assert reason(title) is None


def test_precedence_short_description_first_then_location():
    assert reason("Junior Data Scientist", jd="short") == "short_description"
    # location is checked before title terms: a junior role outside our countries reports "location"
    assert reason("Junior Data Scientist", location="Amsterdam, Netherlands") == "location"
    # the EU-remote run is exempt from the country check
    assert reason("Data Scientist", location="Amsterdam, Netherlands", loc_cfg=EU_REMOTE) is None


def test_detect_agency_by_list_and_phrase():
    assert sj.detect_agency("Michael Page", "") is True
    assert sj.detect_agency("Acme", "We are hiring on behalf of our client, a leading bank") is True
    assert sj.detect_agency("Acme", "Join our team") is False


@pytest.mark.parametrize("text", ["work with our client-facing teams", "grow our client base",
                                  "manage our client portfolio", "serve our clients"])
def test_direct_employer_client_phrases_are_not_agency(text):
    assert sj.detect_agency("HSBC", text) is False


@pytest.mark.parametrize("text", ["Our client, a leading fintech, is hiring", "on behalf of our client",
                                  "Our client is a global bank"])
def test_recruiter_client_phrases_are_agency(text):
    assert sj.detect_agency("HSBC", text) is True


def test_parse_score_coerces_and_clamps():
    assert sj.parse_score('{"fit_score": "82", "reasons": ["a"], "concerns": []}')["fit_score"] == 82
    assert sj.parse_score('noise {"fit_score": 140, "reasons": [], "concerns": ["German"]} tail')["fit_score"] == 100
    with pytest.raises(ValueError):
        sj.parse_score("no json here")
    with pytest.raises(ValueError):
        sj.parse_score('{"reasons": []}')


def test_score_job_retries_then_falls_back():
    calls = []

    def flaky(system, user, max_tokens, timeout):
        calls.append(1)
        return "not json"

    out = sj.score_job("PM", "Acme", "Dubai", JD, "sys", call=flaky)
    assert len(calls) == 2
    assert out == {"fit_score": None, "reasons": [], "concerns": ["scoring failed"]}

    ok = sj.score_job("PM", "Acme", "Dubai", JD, "sys",
                      call=lambda *a, **k: '{"fit_score": 71, "reasons": ["fit"], "concerns": []}')
    assert ok["fit_score"] == 71


def test_choose_window():
    now = datetime(2026, 10, 13, 0, 30)
    assert sj.choose_window(None, now) == "past_week"
    assert sj.choose_window("2026-10-12 00:50:00", now) == "past_24h"
    assert sj.choose_window("2026-10-11 00:50:00", now) == "past_week"


def test_inline_config_fits_free_credit():
    assert sj.worst_case_monthly_usd(CFG) <= CFG["monthly_budget_usd"] == 5.0
    assert len(CFG["titles"]) == 8 and "AI Engineer" in CFG["titles"] and "Product Owner" in CFG["titles"]
    assert all(l["max_jobs"] == 25 for l in CFG["locations"])


def test_system_prompt_uses_knowledge_files(tmp_path, monkeypatch):
    for name in ('career-master.md', 'skills-master.md'):
        (tmp_path / name).write_text((name + ' relevant candidate knowledge\n') * 30, encoding='utf-8')
    monkeypatch.setattr(sj.paths, 'knowledge_dir', lambda: tmp_path)
    prompt = sj.build_system_prompt()
    assert "fit_score" in prompt and "JSON" in prompt
    assert '<!-- skill: job-ranker -->' in prompt
    assert 'career-master.md' in prompt and 'skills-master.md' in prompt
    assert len(prompt) > 1000   # career-master + skills-master content included


@pytest.mark.parametrize("title", [
    "Product Manager - Growth Stage", "Late-stage Product Manager", "Seed Stage Product Manager",
    "Technical Product Manager - Developer Platform",
    "Director of Product", "Head of Product", "Responsable produit",
])
def test_fix_round_1_passes(title):
    assert reason(title) is None


def test_fix_round_1_still_filtered():
    assert reason("Stage Data Scientist") is not None
    assert reason("Senior Solutions Architect") is not None


def test_parse_score_null_and_string_lists():
    with pytest.raises(ValueError):
        sj.parse_score('{"fit_score": null, "reasons": []}')
    out = sj.parse_score('{"fit_score": 50, "reasons": "good fit", "concerns": "German"}')
    assert out["reasons"] == ["good fit"] and out["concerns"] == ["German"]


import db


class FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class FakeHttp:
    """Minimal stand-in for `requests`: run start -> run polls -> dataset items."""
    def __init__(self, statuses, usd=0.0056, items=None):   # 1 job: $0.005 start + $0.000575
        self.statuses = list(statuses)
        self.usd = usd
        self.items = items or []

    def post(self, url, params=None, json=None, timeout=None, headers=None):
        assert headers == {"Authorization": "Bearer tok"} and "token" not in params
        self.posted = json
        self.params = params
        return FakeResp({"data": {"id": "r1", "status": self.statuses.pop(0), "defaultDatasetId": "d1",
                                  "usageTotalUsd": self.usd}})

    def get(self, url, params=None, timeout=None, headers=None):
        assert headers == {"Authorization": "Bearer tok"} and "token" not in (params or {})
        if "/datasets/" in url:
            return FakeResp(self.items)
        status = self.statuses.pop(0) if self.statuses else "SUCCEEDED"
        return FakeResp({"data": {"id": "r1", "status": status, "defaultDatasetId": "d1", "usageTotalUsd": self.usd}})


def _item(lid, title="AI Product Manager", location="Dubai, United Arab Emirates", company="Acme", jd=JD):
    return {"id": lid, "title": title, "url": f"https://ae.linkedin.com/jobs/view/x-at-acme-{lid}",
            "companyName": company, "location": location, "descriptionText": jd, "postedAtDate": "2026-10-12"}


def test_fetch_location_ok_sends_caps_and_window():
    http = FakeHttp(["RUNNING", "SUCCEEDED"], items=[_item("9300000001")])
    items, stat = sj.fetch_location(UAE, CFG["titles"], "past_week", "tok", CFG["actor"], http=http, poll_limit=3)
    assert stat == {"location": "United Arab Emirates", "status": "ok", "scraped": 1, "usd": 0.0056}
    assert http.posted["datePosted"] == "r604800" and http.posted["maxJobs"] == 25
    assert http.params["maxTotalChargeUsd"] == 0.02 and http.params["maxItems"] == 25


def test_fetch_location_never_finishes_is_failed_not_hang():   # Review Focus 2
    http = FakeHttp(["RUNNING"] * 50)
    items, stat = sj.fetch_location(UAE, CFG["titles"], "past_24h", "tok", CFG["actor"], http=http, poll_limit=3)
    assert items == [] and stat["status"] == "failed" and "did not finish" in stat["error"]


def test_fetch_location_charge_limited():
    http = FakeHttp(["SUCCEEDED"], usd=0.0199, items=[_item("9300000002")])
    _, stat = sj.fetch_location(UAE, CFG["titles"], "past_24h", "tok", CFG["actor"], http=http)
    assert stat["status"] == "charge_limited"


def test_fetch_location_http_error_is_failed():
    class Boom:
        def post(self, *a, **k):
            raise ConnectionError("down")
    _, stat = sj.fetch_location(UAE, CFG["titles"], "past_24h", "tok", CFG["actor"], http=Boom())
    assert stat["status"] == "failed" and "down" in stat["error"]


def _reset_sourcing():
    conn = db._get_conn()
    conn.execute("DELETE FROM sourced_jobs")
    conn.execute("DELETE FROM sourcing_runs")
    conn.commit()


def _one_location_cfg():
    return {"actor": CFG["actor"], "titles": CFG["titles"], "monthly_budget_usd": 5.0, "locations": [UAE, EU_REMOTE]}


NO_USAGE = lambda token: 0.0   # noqa: E731 -- budget untouched; never hits the network


def test_apify_cycle_usage_reads_current_usage():
    class Http:
        def get(self, url, params=None, timeout=None, headers=None):
            assert url.endswith("/users/me/limits") and not params and headers == {"Authorization": "Bearer tok"}
            return FakeResp({"data": {"limits": {"maxMonthlyUsageUsd": 5}, "current": {"monthlyUsageUsd": 0.47}}})
    assert sj.apify_cycle_usage_usd("tok", http=Http()) == 0.47


def test_run_end_to_end_with_mocks():
    _reset_sourcing()
    db.create_job("Acme", "PM", "gcc", jd_url="https://www.linkedin.com/jobs/view/9300000013/")
    by_loc = {
        "United Arab Emirates": [
            _item("9300000010"),                                   # kept + scored
            _item("9300000011", title="Junior Data Scientist"),    # filtered
            _item("9300000012", company="Michael Page"),           # kept, agency flag
            _item("9300000013"),                                   # already a job -> duplicate
            {"title": "AI PM", "url": "https://example.com/x"},    # no LinkedIn id -> skipped (Review Focus 4)
        ],
        "European Union": [_item("9300000010")],                   # same posting again -> duplicate
    }

    def fake_fetch(loc_cfg, titles, window, token, actor):
        return by_loc[loc_cfg["linkedin_location"]], {
            "location": loc_cfg["linkedin_location"], "status": "ok",
            "scraped": len(by_loc[loc_cfg["linkedin_location"]]), "usd": 0.01}

    out = sj.run(token="tok", usage=NO_USAGE, fetch=fake_fetch, now=datetime(2026, 10, 13, 0, 30), config=_one_location_cfg(),
                 call=lambda *a, **k: '{"fit_score": 77, "reasons": ["fit"], "concerns": []}')
    assert out["outcome"] == "success"
    uae = out["locations"][0]
    assert (uae["new"], uae["filtered"], uae["duplicates"], uae["skipped"], uae["scored"]) == (2, 1, 1, 1, 2)
    assert out["locations"][1]["duplicates"] == 1
    rows = {r["linkedin_job_id"]: r for r in db.get_sourced_jobs(["new", "filtered"])}
    assert rows["9300000010"]["fit_score"] == 77 and rows["9300000010"]["geo"] == "gcc"
    assert rows["9300000010"]["url"] == "https://www.linkedin.com/jobs/view/9300000010/"
    assert rows["9300000012"]["is_agency"] == 1
    assert rows["9300000011"]["status"] == "filtered" and rows["9300000011"]["fit_score"] is None
    latest = db.get_latest_sourcing_run()
    assert latest["outcome"] == "success" and latest["date_window"] == "past_week" and latest["total_usd"] == 0.02


def test_run_all_duplicates_is_still_a_recorded_success():
    _reset_sourcing()
    db.create_job("Acme", "PM", "gcc", jd_url="https://www.linkedin.com/jobs/view/9300000020/")
    fetch = lambda loc_cfg, *a: ([_item("9300000020")], {"location": loc_cfg["linkedin_location"], "status": "ok", "scraped": 1, "usd": 0.0})
    out = sj.run(token="tok", usage=NO_USAGE, fetch=fetch, now=datetime(2026, 10, 13), config=_one_location_cfg(),
                 call=lambda *a, **k: "unused")
    assert out["outcome"] == "success"
    assert db.get_latest_sourcing_run()["locations"][0]["new"] == 0


def test_run_partial_and_failed_outcomes():
    _reset_sourcing()

    def half(loc_cfg, *a):
        ok = loc_cfg["linkedin_location"] == "United Arab Emirates"
        return [], {"location": loc_cfg["linkedin_location"], "status": "ok" if ok else "failed",
                    "scraped": 0, "usd": 0.0, **({} if ok else {"error": "x"})}
    assert sj.run(token="tok", usage=NO_USAGE, fetch=half, config=_one_location_cfg(), call=None)["outcome"] == "partial"

    def none_ok(loc_cfg, *a):
        return [], {"location": loc_cfg["linkedin_location"], "status": "failed", "scraped": 0, "usd": 0.0, "error": "x"}
    assert sj.run(token="tok", usage=NO_USAGE, fetch=none_ok, config=_one_location_cfg(), call=None)["outcome"] == "failed"

    def capped(loc_cfg, *a):
        return [], {"location": loc_cfg["linkedin_location"], "status": "charge_limited", "scraped": 0, "usd": 0.02}
    assert sj.run(token="tok", usage=NO_USAGE, fetch=capped, config=_one_location_cfg(), call=None)["outcome"] == "partial"


def test_run_without_token_records_failed_and_main_exits_1(monkeypatch):
    _reset_sourcing()
    monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
    assert sj.run(token=None, fetch=None, config=_one_location_cfg())["outcome"] == "failed"
    assert db.get_latest_sourcing_run()["outcome"] == "failed"
    monkeypatch.setattr(sj, "run", lambda: {"run_id": 1, "outcome": "failed", "locations": []})
    assert sj.main() == 1


def test_token_missing_run_still_expires_stale_new_rows(monkeypatch):
    _reset_sourcing()
    monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
    sid = db.insert_sourced_job({
        "linkedin_job_id": "9100000090", "run_id": None, "title": "PM", "company": "Acme", "location": "Dubai",
        "url": "https://www.linkedin.com/jobs/view/9100000090/", "jd_text": "x" * 400, "geo": "gcc",
        "search_location": "United Arab Emirates", "posted_at": "2026-10-01", "is_agency": 0,
        "filter_reason": None, "fit_score": 50, "reasons": [], "concerns": [], "status": "new"})
    conn = db._get_conn()
    conn.execute("UPDATE sourced_jobs SET created_at = datetime('now','-8 days') WHERE id = ?", (sid,))
    conn.commit()
    assert sj.run(token=None, fetch=None, config=_one_location_cfg())["outcome"] == "failed"
    assert conn.execute("SELECT status FROM sourced_jobs WHERE id = ?", (sid,)).fetchone()[0] == "expired"
    monkeypatch.setattr(db, "sweep_sourced_jobs", lambda: 1 / 0)   # a sweep error must not mask the failed run
    assert sj.run(token=None, fetch=None, config=_one_location_cfg())["outcome"] == "failed"
    assert db.get_latest_sourcing_run()["outcome"] == "failed"


def _ok_fetch(launched=None, usd=0.0):
    def fetch(loc_cfg, titles, window, token, actor):
        if launched is not None:
            launched.append((loc_cfg["linkedin_location"], window))
        return [], {"location": loc_cfg["linkedin_location"], "status": "ok", "scraped": 0, "usd": usd}
    return fetch


def test_catch_up_window_is_per_location():
    """Plan review item 2: EU failed last night, UAE didn't -> only EU widens."""
    _reset_sourcing()
    rid = db.start_sourcing_run("past_24h")
    db.finish_sourcing_run(rid, "partial", [
        {"location": "United Arab Emirates", "status": "ok"},
        {"location": "European Union", "status": "failed", "error": "x"}], 0.02)
    conn = db._get_conn()
    conn.execute("UPDATE sourcing_runs SET finished_at = '2026-10-12 00:50:00' WHERE id = ?", (rid,))
    conn.commit()
    launched = []
    out = sj.run(token="tok", usage=NO_USAGE, fetch=_ok_fetch(launched), now=datetime(2026, 10, 13, 0, 30),
                 config=_one_location_cfg(), call=None)
    assert launched == [("United Arab Emirates", "past_24h"), ("European Union", "past_week")]
    assert [s["date_window"] for s in out["locations"]] == ["past_24h", "past_week"]
    assert db.get_latest_sourcing_run()["date_window"] == "past_week"   # widest window used


def test_budget_stops_launching_locations():
    """Plan review item 1: Apify's real cycle usage (hand-runs included) gates each launch."""
    _reset_sourcing()
    launched = []
    out = sj.run(token="tok", usage=lambda token: 4.97, fetch=_ok_fetch(launched, usd=0.02),
                 config=_one_location_cfg(), call=None)
    assert [l for l, _ in launched] == ["United Arab Emirates"]    # 4.97 + 0.02 fits; a second 0.02 would not
    assert [s["status"] for s in out["locations"]] == ["ok", "budget_exhausted"]
    assert out["outcome"] == "partial"


def test_usage_check_error_fails_closed_without_scraping():
    _reset_sourcing()
    launched = []

    def down(token):
        raise ConnectionError("apify down")
    out = sj.run(token="tok", usage=down, fetch=_ok_fetch(launched), config=_one_location_cfg(), call=None)
    assert launched == [] and out["outcome"] == "failed"
    assert "apify down" in db.get_latest_sourcing_run()["locations"][0]["error"]


def test_malformed_items_are_skipped_not_fatal():
    _reset_sourcing()
    items = [None, "garbage", {"url": None, "id": None}, _item("9300000030")]
    fetch = lambda loc_cfg, *a: (items, {"location": loc_cfg["linkedin_location"], "status": "ok", "scraped": 4, "usd": 0.0})
    out = sj.run(token="tok", usage=NO_USAGE, fetch=fetch, config={**_one_location_cfg(), "locations": [UAE]},
                 call=lambda *a, **k: '{"fit_score": 50, "reasons": [], "concerns": []}')
    assert out["outcome"] == "success"
    assert (out["locations"][0]["skipped"], out["locations"][0]["new"]) == (3, 1)


def test_unexpected_error_finishes_run_and_keeps_done_locations(monkeypatch):
    """Plan review item 3: a crash outside fetch/score never leaves the run unfinished."""
    _reset_sourcing()

    def disk_full():
        raise RuntimeError("disk full")
    monkeypatch.setattr(sj.db, "sweep_sourced_jobs", disk_full)
    with pytest.raises(RuntimeError):
        sj.run(token="tok", usage=NO_USAGE, fetch=_ok_fetch(usd=0.01), config=_one_location_cfg(), call=None)
    latest = db.get_latest_sourcing_run()
    assert latest["finished_at"] is not None and latest["outcome"] == "partial"
    assert [l["location"] for l in latest["locations"]] == ["United Arab Emirates", "European Union", "(run)"]
    assert "disk full" in latest["locations"][2]["error"] and latest["total_usd"] == 0.02


def test_profile_load_failure_records_failed_run_before_scraping(monkeypatch):
    _reset_sourcing()
    launched = []

    def missing():
        raise FileNotFoundError("knowledge/career-master.md")
    monkeypatch.setattr(sj, "build_system_prompt", missing)
    with pytest.raises(FileNotFoundError):
        sj.run(token="tok", usage=NO_USAGE, fetch=_ok_fetch(launched), config=_one_location_cfg(), call=None)
    assert launched == [] and db.get_latest_sourcing_run()["outcome"] == "failed"


def test_failed_fetch_counts_full_cap_against_budget():
    _reset_sourcing()
    launched = []

    def fetch(loc_cfg, *a):
        launched.append(loc_cfg["linkedin_location"])
        return [], {"location": loc_cfg["linkedin_location"], "status": "failed", "scraped": 0, "usd": 0.0, "error": "x"}
    out = sj.run(token="tok", usage=lambda t: 4.97, fetch=fetch, config=_one_location_cfg(), call=None)
    assert launched == ["United Arab Emirates"]
    assert [s["status"] for s in out["locations"]] == ["failed", "budget_exhausted"]
    assert out["locations"][0]["usd"] == UAE["max_charge_usd"]


def test_db_error_on_item_propagates_and_finishes_run(monkeypatch):
    import sqlite3
    _reset_sourcing()

    def locked(fields):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(sj.db, "insert_sourced_job", locked)
    fetch = lambda loc_cfg, *a: ([_item("9300000040")], {"location": loc_cfg["linkedin_location"], "status": "ok", "scraped": 1, "usd": 0.019})
    with pytest.raises(sqlite3.OperationalError):
        sj.run(token="tok", usage=NO_USAGE, fetch=fetch, config={**_one_location_cfg(), "locations": [UAE]},
               call=lambda *a, **k: '{"fit_score": 50, "reasons": [], "concerns": []}')
    latest = db.get_latest_sourcing_run()
    # Deployment review 2: the paid location keeps its audit record, marked failed.
    assert latest["finished_at"] is not None and latest["outcome"] == "failed"
    [loc] = latest["locations"]
    assert loc["location"] == "United Arab Emirates" and loc["status"] == "failed"
    assert "database is locked" in loc["error"] and loc["scraped"] == 1 and loc["usd"] == 0.019
    assert latest["total_usd"] == 0.019


def test_preliminary_zero_charge_cannot_release_budget():
    """Deployment review 1: Apify's first post-run figure can be preliminary ($0 / missing).
    Every launch reserves its full cap, so a $0 report never frees budget for more launches."""
    _reset_sourcing()
    launched = []
    out = sj.run(token="tok", usage=lambda token: 4.97, fetch=_ok_fetch(launched, usd=0.0),
                 config=CFG, call=None)          # all 8 locations, $0.03 left
    assert [l for l, _ in launched] == ["United Arab Emirates"]
    assert [s["status"] for s in out["locations"]][1:] == ["budget_exhausted"] * 7
