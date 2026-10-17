#!/usr/bin/env python3
"""Nightly job sourcing (spec: docs/superpowers/specs/2026-10-12-job-sourcing-design.md).

Scrapes logged-out LinkedIn job listings via Apify (never user's
account), dedups on the LinkedIn job ID (Rule 24), pre-filters, ranks
survivors with GLM-5 via llm_client, and writes sourced_jobs rows for the
dashboard Shortlist page. Nothing is applied to automatically.

Runs from deploy/source-jobs.timer (00:30 UTC). Hand-run once on the VM
before enabling the timer (Testing & Deploy Protocol). Tests:
tests/test_source_jobs.py -- this file's __main__ only calls main() (Rule 27).
"""
import json
import settings
import re
import sys
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

import paths

PROJECT_ROOT = paths.repo_dir()
load_dotenv(paths.repo_dir() / ".env")
load_dotenv(paths.data(".env"))

import db  # noqa: E402
import llm_client  # noqa: E402
from generate import is_agency  # noqa: E402

CONFIG_PATH = PROJECT_ROOT / "sourcing_config.json"
APIFY_API = "https://api.apify.com/v2"
DATE_POSTED = {"past_24h": "r86400", "past_week": "r604800"}
MIN_JD_CHARS = 300

_ID_RE = re.compile(r"(?:/jobs/view/(?:[^/?#]*-)?|currentJobId=)(\d{6,})")
AGENCY_TEXT = re.compile(r"\b(on behalf of (?:our|a|an) client|our client,? (?:is|are|a|an|has|seeks|is seeking|is looking)|recruitment agency|staffing agency)\b", re.I)

# Matching contract (spec section 2 step 4): case-insensitive, whole words.
NEG_ALWAYS = re.compile(
    r"\b(junior|jr\.?|intern|internship|graduate|apprentice(ship)?|alternan(ce|t)|(?<!early[- ])(?<!growth[- ])(?<!late[- ])(?<!later[- ])(?<!seed[- ])(?<!scale[- ])(?<!scale-up[- ])stage|stagiaire|"
    r"working student|werkstudent|praktikum|sales|account (executive|manager)|business development|"
    r"software engineer(ing)?|data engineer|devops|front[- ]?end|back[- ]?end|qa|tester|"
    r"cyber|security|grc|servicenow|pre[- ]?sales|business process)\b", re.I)
NEG_UNLESS_ANCHOR = re.compile(r"\b(developer|solutions? architect)\b", re.I)
AI_DATA_ANCHOR = re.compile(r"\b(ai|genai|gen ai|ml|machine learning|artificial intelligence|ia|ki|llm|data)\b", re.I)
PRODUCT_ANCHOR = re.compile(r"\b(product (manager|owner|director)|director of product|head of product)\b", re.I)
POSITIVE = re.compile(
    r"\b(product (manager|owner|lead|director)|director of product|responsable produit|produktmanager\w*|chef de produit|head of (product|ai|data)|"
    r"data scien\w*|data lead|research scientist|applied scien\w*|ai|genai|ml|machine learning|"
    r"artificial intelligence|ia|ki|llm|clinical|digital health|health ?tech|transformation|"
    r"strateg\w*|analyst|analytics|forecast\w*)\b", re.I)
BOILERPLATE = re.compile(r"(equal (employment )?opportunit|we are an equal|reasonable accommodation|privacy notice)", re.I)


def load_config(path=CONFIG_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def linkedin_job_id(url, fallback_id=None):
    m = _ID_RE.search(url or "")
    if m:
        return m.group(1)
    fb = str(fallback_id or "")
    return fb if fb.isdigit() and len(fb) >= 6 else None


def canonical_url(linkedin_job_id):
    return f"https://www.linkedin.com/jobs/view/{linkedin_job_id}/"


def detect_agency(company, jd_text):
    return is_agency(company or "") or bool(AGENCY_TEXT.search(jd_text or ""))


def filter_reason(title, location, jd_text, location_cfg, countries):
    """First matching rule wins (spec precedence). None = keep."""
    title = title or ""
    if len(jd_text or "") < MIN_JD_CHARS:
        return "short_description"
    if not location_cfg.get("remote_only") and not any(c in (location or "").lower() for c in countries):
        return "location"
    m = NEG_ALWAYS.search(title)
    if m:
        return "negative_title:" + m.group(0).lower()
    m = NEG_UNLESS_ANCHOR.search(title)
    if m and not (AI_DATA_ANCHOR.search(title) or PRODUCT_ANCHOR.search(title)):
        return "negative_title:" + m.group(0).lower()
    if not POSITIVE.search(title):
        return "no_positive_anchor"
    return None


def clean_jd(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    m = BOILERPLATE.search(text)
    if m and m.start() > 500:
        text = text[:m.start()]
    return text[:4000]


def build_system_prompt():
    knowledge = "\n\n".join(
        (paths.knowledge_dir() / name).read_text(encoding="utf-8")
        for name in ("career-master.md", "skills-master.md")
    )
    return (
        "<!-- skill: job-ranker -->\n"
        "You rank job postings for one candidate. Their profile:\n\n"
        f"{knowledge}\n\n"
        "Rank, don't gatekeep: every posting reaching you passed a filter and will be shown; your score "
        "orders the list. Judge role type, seniority, domain fit and realistic hiring odds. "
        "Lower the score (don't zero it) when the role requires fluency in a language other than English, "
        "and say which language in concerns. If it is a recruitment-agency posting, say so in concerns. "
        'Reply with ONLY a JSON object: {"fit_score": <int 0-100>, "reasons": [<short str>], '
        '"concerns": [<short str>]}'
    )


def parse_score(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError("no JSON object in LLM reply")
    data = json.loads(m.group(0))
    if "fit_score" not in data:
        raise ValueError("fit_score missing")
    try:
        score = max(0, min(100, int(float(data["fit_score"]))))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"bad fit_score: {data['fit_score']!r}") from exc

    def as_list(v):
        if isinstance(v, str):
            v = [v]
        return [str(x) for x in v or []]

    return {"fit_score": score, "reasons": as_list(data.get("reasons")), "concerns": as_list(data.get("concerns"))}


def score_job(title, company, location, jd_text, system_prompt, call=None):
    call = call or llm_client.call_llm
    user = f"Title: {title}\nCompany: {company}\nLocation: {location}\n\n{clean_jd(jd_text)}"
    for _ in range(2):
        try:
            return parse_score(call(system_prompt, user, max_tokens=600, timeout=120))
        except Exception as exc:
            print(f"  scoring error for {title!r}: {str(exc)[:150]}", flush=True)
    return {"fit_score": None, "reasons": [], "concerns": ["scoring failed"]}


def choose_window(last_good_finished_at, now):
    """Called per location with that location's last good scrape.
    past_week after a missed night (>30h), so postings aren't silently lost.
    Best-effort recovery only: the same 25-job cap applies, so a busy
    location's week can't be fully recovered (spec section 2, accepted)."""
    if not last_good_finished_at:
        return "past_week"
    last = datetime.strptime(last_good_finished_at[:19], "%Y-%m-%d %H:%M:%S")
    return "past_week" if now - last > timedelta(hours=30) else "past_24h"


def worst_case_monthly_usd(config):
    return round(sum(l["max_charge_usd"] for l in config["locations"]) * 31, 4)


def fetch_location(loc_cfg, titles, date_window, token, actor, http=requests, poll_limit=15):
    """One Apify run for one location. Never raises -- a failure becomes a
    'failed' stat so the other locations still run (spec section 5)."""
    name = loc_cfg["linkedin_location"]
    hdr = {"Authorization": f"Bearer {token}"}
    stat = {"location": name, "status": "failed", "scraped": 0, "usd": 0.0}
    payload = {
        "searchQueries": titles, "searchQuery": "", "location": name,
        "maxJobs": loc_cfg["max_jobs"], "datePosted": DATE_POSTED[date_window], "sortBy": "DD",
        "scrapeJobDetails": True, "workplaceType": "2" if loc_cfg.get("remote_only") else "all",
    }
    try:
        run = http.post(
            f"{APIFY_API}/acts/{actor}/runs",
            params={"waitForFinish": 60, "maxItems": loc_cfg["max_jobs"],
                    "maxTotalChargeUsd": loc_cfg["max_charge_usd"]},
            json=payload, timeout=90, headers=hdr,
        )
        run.raise_for_status()
        run = run.json()["data"]
        polls = 0
        while run["status"] in ("READY", "RUNNING"):
            if polls >= poll_limit:
                stat["error"] = f"run did not finish after {poll_limit} polls"
                return [], stat
            r = http.get(f"{APIFY_API}/actor-runs/{run['id']}",
                         params={"waitForFinish": 60}, timeout=90, headers=hdr)
            r.raise_for_status()
            run = r.json()["data"]
            polls += 1
        stat["usd"] = float(run.get("usageTotalUsd") or 0.0)
        if run["status"] != "SUCCEEDED":
            stat["error"] = f"actor run {run['status']}"
            return [], stat
        r = http.get(f"{APIFY_API}/datasets/{run['defaultDatasetId']}/items",
                     params={"clean": 1}, timeout=60, headers=hdr)
        r.raise_for_status()
        items = r.json()
    except Exception as exc:
        stat["error"] = str(exc)[:300]
        return [], stat
    stat["scraped"] = len(items)
    hit_charge_cap = stat["usd"] >= 0.95 * loc_cfg["max_charge_usd"] and len(items) < loc_cfg["max_jobs"]
    stat["status"] = "charge_limited" if hit_charge_cap else "ok"
    return items, stat


def _outcome(stats):
    good = [s for s in stats if s["status"] in ("ok", "charge_limited")]
    if not good:
        return "failed"
    return "success" if all(s["status"] == "ok" for s in stats) else "partial"


def apify_cycle_usage_usd(token, http=requests):
    """Apify's own usage for the current billing cycle -- every run on the
    account (nightly, hand-runs, other actors), not just ours."""
    r = http.get(f"{APIFY_API}/users/me/limits", headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    data = r.json()["data"]
    return float(data["current"]["monthlyUsageUsd"])


def _process_item(item, loc_cfg, countries, run_id, system_prompt, call, stat):
    lid = linkedin_job_id(item.get("url"), fallback_id=item.get("id"))
    if not lid:
        stat["skipped"] += 1
        return
    if db.sourced_job_seen(lid):
        stat["duplicates"] += 1
        return
    title, location, jd = item.get("title") or "", item.get("location") or "", item.get("descriptionText") or ""
    reason = filter_reason(title, location, jd, loc_cfg, countries)
    fields = {
        "linkedin_job_id": lid, "run_id": run_id, "title": title, "company": item.get("companyName"),
        "location": location, "url": canonical_url(lid), "jd_text": jd, "geo": loc_cfg["geo"],
        "search_location": loc_cfg["linkedin_location"], "posted_at": item.get("postedAtDate"),
        "is_agency": 1 if detect_agency(item.get("companyName"), jd) else 0, "filter_reason": reason,
    }
    if reason:
        fields.update(status="filtered", fit_score=None)
        stat["filtered"] += 1
    else:
        score = score_job(title, item.get("companyName"), location, jd, system_prompt, call=call)
        fields.update(status="new", **score)
        stat["new"] += 1
        stat["scored"] += 1 if score["fit_score"] is not None else 0
    db.insert_sourced_job(fields)


def _safe_sweep():
    """Retention on early-failure paths; an error here must not mask the recorded failure."""
    try:
        db.sweep_sourced_jobs()
    except Exception as exc:
        print(f"source_jobs: sweep failed: {exc}", flush=True)


def run(token=None, fetch=fetch_location, call=None, now=None, config=None, usage=apify_cycle_usage_usd):
    paths.ensure_dirs()
    db.init_db()
    config = config or load_config()
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    token = token or settings.get("integrations.apify.api_token")
    last_good = db.last_good_finished_by_location()
    windows = {l["linkedin_location"]: choose_window(last_good.get(l["linkedin_location"]), now)
               for l in config["locations"]}
    run_id = db.start_sourcing_run("past_week" if "past_week" in windows.values() else "past_24h")
    if not token:
        print("source_jobs: APIFY_API_TOKEN missing", flush=True)
        db.finish_sourcing_run(run_id, "failed", [], 0.0)
        _safe_sweep()
        return {"run_id": run_id, "outcome": "failed", "locations": []}

    stats = []
    current = None   # the location being processed, so a crash keeps its audit record
    try:
        system_prompt = build_system_prompt()   # before any paid call: no profile, no scrape
        try:
            remaining = config["monthly_budget_usd"] - usage(token)
        except Exception as exc:   # fail closed -- this is the money guard
            stats.append({"location": "(budget check)", "status": "failed", "scraped": 0, "usd": 0.0,
                          "error": str(exc)[:300]})
            print(f"source_jobs: budget check failed: {exc}", flush=True)
            db.finish_sourcing_run(run_id, "failed", stats, 0.0)
            _safe_sweep()
            return {"run_id": run_id, "outcome": "failed", "locations": stats}

        countries = [l["linkedin_location"].lower() for l in config["locations"] if not l.get("remote_only")]
        # Every launch reserves its full cap up front: the charge Apify reports right after a
        # run can be preliminary ($0 or missing), so it must never free budget for later launches.
        reserved = 0.0
        for loc_cfg in config["locations"]:
            name, window = loc_cfg["linkedin_location"], windows[loc_cfg["linkedin_location"]]
            if reserved + loc_cfg["max_charge_usd"] > remaining:
                stat = {"location": name, "status": "budget_exhausted", "scraped": 0, "usd": 0.0,
                        "error": f"${remaining - reserved:.3f} left of ${config['monthly_budget_usd']} this Apify cycle"}
                items = []
            else:
                reserved += loc_cfg["max_charge_usd"]
                items, stat = fetch(loc_cfg, config["titles"], window, token, config["actor"])
                if stat["status"] == "failed":   # a failed run may still have billed up to its cap
                    stat["usd"] = loc_cfg["max_charge_usd"]
            stat.update({"date_window": window, "duplicates": 0, "skipped": 0, "new": 0, "filtered": 0, "scored": 0})
            stats.append(stat)
            current = stat
            for item in items:
                try:
                    _process_item(item, loc_cfg, countries, run_id, system_prompt, call, stat)
                except (AttributeError, TypeError, KeyError, ValueError) as exc:   # one malformed item never sinks the location
                    stat["skipped"] += 1
                    print(f"  skipped malformed item: {str(exc)[:150]}", flush=True)
            print(f"source_jobs: {json.dumps(stat)}", flush=True)
            current = None

        db.sweep_sourced_jobs()
    except Exception as exc:
        if current is not None:   # crashed mid-location: keep its charge + progress, mark it failed
            current.update(status="failed", error=f"processing aborted: {str(exc)[:300]}")
        else:
            stats.append({"location": "(run)", "status": "failed", "scraped": 0, "usd": 0.0, "error": str(exc)[:300]})
        db.finish_sourcing_run(run_id, _outcome(stats), stats, round(sum(s["usd"] for s in stats), 4))
        raise
    outcome = _outcome(stats)
    db.finish_sourcing_run(run_id, outcome, stats, round(sum(s["usd"] for s in stats), 4))
    return {"run_id": run_id, "outcome": outcome, "locations": stats}


def main():
    result = run()
    print(f"source_jobs: run {result['run_id']} {result['outcome']}", flush=True)
    return 1 if result["outcome"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
