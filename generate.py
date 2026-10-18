#!/usr/bin/env python3
"""
generate.py — Job Hunt System main engine

CLI usage:
  python generate.py --jd "paste JD text here" --geo auto
  python generate.py --jd-url "https://linkedin.com/jobs/view/123" --geo auto
  python generate.py --jd-url "..." --person-info "Name|Title|Company|email"
  python generate.py --batch-file jobs.json          # up to 3 jobs in parallel
"""
import argparse
import ast
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

import paths
import profile as prof
import skill_loader

load_dotenv(paths.repo_dir() / ".env")
load_dotenv(paths.data(".env"))

# Database configuration is captured on import, after both dotenv files.
import db
import llm_client

paths.ensure_dirs()
db.init_db()

REQUIRED_KNOWLEDGE = (
    "career-master.md", "employment-master.md", "education-master.md",
    "skills-master.md", "identity.md",
)


def setup_missing() -> list[str]:
    missing = [] if llm_client.is_configured() else ["llm"]
    try:
        prof.load_profile()
    except prof.ProfileError:
        missing.append("profile")
    if ((paths.knowledge_dir() / '.profile-source-save-incomplete').exists()
            or not all((paths.knowledge_dir() / name).is_file() for name in REQUIRED_KNOWLEDGE)):
        missing.append("knowledge")
    return missing


def _preflight() -> None:
    skill_dir = paths.skills_dir()
    if not skill_dir.is_dir():
        sys.exit(f"Required directory not found: {skill_dir}/ - configure DATA_DIR and repository assets.")
    missing = setup_missing()
    if missing:
        sys.exit(f"Setup incomplete ({', '.join(missing)}). Finish setup in the dashboard (Profile).")

LLM_TIMEOUT = 300

# ── Known recruitment agencies ────────────────────────────────────────────────
KNOWN_AGENCIES = {
    # UK / Global
    "la fosse", "michael page", "page executive", "robert half", "robert walters", "hays", "harvey nash",
    "korn ferry", "spencer stuart", "randstad", "adecco", "manpowergroup", "reed",
    "antal international", "antal", "austin fraser", "eames consulting",
    "marks sattin", "finatal", "gartner", "selby jennings", "green park",
    "odgers berndtson", "russell reynolds", "egon zehnder",
    # Regional agencies
    "charterhouse", "tiger recruitment", "bayt", "inspire selection",
    "black pearl", "guildhall", "cooper fitch", "mackenzie jones",
    "nadia", "transearch", "gulftalent", "talentmate",
    # Additional confirmed agencies
    "boundless", "stanton chase", "cpl", "talentedge", "sthree", "ten",
    "kershaw leonard", "naukrigulf", "dubizzle", "khazna", "nsearch",
}

# ── Thread-safe logging ───────────────────────────────────────────────────────
_print_lock = threading.Lock()

def _log(label: str, msg: str) -> None:
    prefix = f"[{label}] " if label else ""
    with _print_lock:
        print(f"{prefix}{msg}")


# ─────────────────────────────────────────────────────────────────────────────
#  SHARED LLM HELPER
# ─────────────────────────────────────────────────────────────────────────────

def call_llm(skill_name: str, input_text: str, knowledge: str | None = None) -> str:
    instructions = skill_loader.load_skill(skill_name)
    if knowledge:
        instructions += "\n\n---\n\n# KNOWLEDGE BASE\n" + knowledge
    try:
        return llm_client.call_llm(instructions, input_text, max_tokens=4096, timeout=LLM_TIMEOUT)
    except Exception as e:
        raise RuntimeError(f"LLM call failed ({skill_name}): {e}")


# ─────────────────────────────────────────────────────────────────────────────
#  INPUT FETCHING
# ─────────────────────────────────────────────────────────────────────────────

def fetch_linkedin_job(url: str) -> str:
    job_id_match = re.search(r"/jobs/view/(\d+)", url)
    if not job_id_match:
        raise RuntimeError(f"Not a valid LinkedIn job URL (expected /jobs/view/JOBID/): {url}")
    job_id = job_id_match.group(1)
    guest_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
    try:
        resp = requests.get(
            guest_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=15,
        )
    except requests.exceptions.ConnectionError:
        raise RuntimeError("LinkedIn fetch failed — check internet connectivity.")
    except requests.exceptions.Timeout:
        raise RuntimeError("LinkedIn job fetch timed out.")
    if resp.status_code == 404:
        raise RuntimeError(f"LinkedIn job not found (expired or invalid URL): {url}")
    if not resp.ok:
        raise RuntimeError(f"LinkedIn returned {resp.status_code} for job URL: {url}")

    soup = BeautifulSoup(resp.text, "html.parser")

    title_el = soup.find("h2", class_=re.compile(r"topcard__title"))
    title = title_el.get_text(strip=True) if title_el else ""

    company_el = soup.find("a", class_=re.compile(r"topcard__org-name-link"))
    if not company_el:
        company_el = soup.find("span", class_="topcard__flavor")
    company = company_el.get_text(strip=True) if company_el else ""

    location_el = soup.find("span", class_=re.compile(r"topcard__flavor--bullet"))
    location = location_el.get_text(strip=True) if location_el else ""

    desc_el = soup.find("div", class_=re.compile(r"show-more-less-html|description__text"))
    description = desc_el.get_text(separator="\n", strip=True) if desc_el else ""

    parts = [p for p in [title, company, location, description] if p]
    if not parts:
        raise RuntimeError(f"Could not extract job details from LinkedIn URL: {url}")
    return "\n".join(parts)


def is_agency(company_name: str) -> bool:
    return company_name.lower().strip() in KNOWN_AGENCIES or prof.is_extra_agency(company_name)


def extract_actual_company(jd_text: str) -> str | None:
    patterns = [
        r"on behalf of\s+([A-Z][A-Za-z0-9&'\-\. ]{1,50})",
        r"our client[,\s]+([A-Z][A-Za-z0-9&'\-\. ]{1,50})",
        r"our client is\s+([A-Z][A-Za-z0-9&'\-\. ]{1,50})",
        r"recruiting (?:on behalf of |for )\s*([A-Z][A-Za-z0-9&'\-\. ]{1,50})",
        r"sourcing on behalf of\s+([A-Z][A-Za-z0-9&'\-\. ]{1,50})",
        r"hired by\s+([A-Z][A-Za-z0-9&'\-\. ]{1,50})",
        r"About (?:the )?(?:Company|Client|Role at)[:\s]+([A-Z][A-Za-z0-9&'\-\. ]{1,50})",
        r"Client:\s*([A-Z][A-Za-z0-9&'\-\. ]{1,50})",
    ]
    _not_company_starts = {"the", "a", "an", "our", "their", "its", "this", "is", "are",
                           "was", "we", "they", "he", "she", "it", "be", "been"}
    for pattern in patterns:
        match = re.search(pattern, jd_text, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip().rstrip(".,;")
            first_word = candidate.split()[0].lower() if candidate else ""
            if first_word in _not_company_starts:
                continue
            if len(candidate.split()) > 5:
                continue
            return candidate
    return None


def resolve_company(
    jd_text: str,
    scraped_company: str,
    company_override: str | None,
    force_agency: bool = False,
) -> str | None:
    if company_override:
        print(f"  Company override: {company_override}")
        return company_override
    if force_agency or is_agency(scraped_company):
        extracted = extract_actual_company(jd_text)
        if extracted:
            print(f"  Agency detected ({scraped_company or 'user-flagged'}). Actual company extracted: {extracted}")
            return extracted
        print(f"  Agency detected ({scraped_company or 'user-flagged'}). Client company is confidential.")
        print(f"  Tip: re-run with --company 'Company Name' if you know the client.")
        return None
    # Content-based fallback: catch unknown agencies that name their client in the JD
    if scraped_company:
        extracted = extract_actual_company(jd_text)
        if extracted and extracted.lower() != scraped_company.lower():
            print(f"  Agency signals in JD text (scraped: {scraped_company}). Using actual company: {extracted}")
            return extracted
    return scraped_company


def fetch_jd(jd_text: str | None, jd_url: str | None) -> str:
    if jd_text:
        return jd_text
    print("  Fetching JD from LinkedIn...")
    return fetch_linkedin_job(jd_url)



def parse_person_info(info_str: str) -> dict:
    """Parse 'Name|Title|Company' or 'Name|Title|Company|email'"""
    parts = [p.strip() for p in info_str.split("|")]
    name    = parts[0] if len(parts) > 0 else "Unknown"
    title   = parts[1] if len(parts) > 1 else ""
    company = parts[2] if len(parts) > 2 else ""
    email   = parts[3] if len(parts) > 3 else ""
    return {
        "full_name": name,
        "headline":  f"{title} at {company}" if title and company else title,
        "email":     email,
        "summary":   "",
        "experiences": [
            {"title": title, "company": company, "starts_at": {}, "ends_at": None}
        ] if title else [],
    }


def format_person_profile(person: dict) -> str:
    lines = [
        f"Name: {person.get('full_name', 'Unknown')}",
        f"Headline: {person.get('headline', '')}",
    ]
    if person.get("email"):
        lines.append(f"Email: {person['email']}")
    lines += [f"Summary: {person.get('summary', '')}", "Recent Experience:"]
    for exp in (person.get("experiences") or [])[:3]:
        start = (exp.get("starts_at") or {}).get("year", "")
        end_raw = exp.get("ends_at")
        end = end_raw.get("year", "") if end_raw else "present"
        lines.append(
            f"  - {exp.get('title', '')} at {exp.get('company', '')} ({start}–{end})"
        )
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
#  GEO DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def detect_geo(jd_text: str, geo_flag: str) -> str:
    if geo_flag != "auto":
        known = prof.region_ids()
        if geo_flag not in known:
            raise ValueError(f"Unknown region: {geo_flag}. Known regions: {', '.join(known)}")
        return geo_flag
    return prof.detect_region(jd_text)


# ─────────────────────────────────────────────────────────────────────────────
#  KNOWLEDGE BASE
# ─────────────────────────────────────────────────────────────────────────────

def load_knowledge(files: list[str] | None = None) -> str:
    if files is None:
        files = [
            "career-master.md",
            "employment-master.md",
            "education-master.md",
            "skills-master.md",
            "identity.md",
        ]
    parts = []
    for fname in files:
        text = (paths.knowledge_dir() / fname).read_text(encoding="utf-8")
        parts.append(f"# {fname}\n{text}")
    return "\n\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
#  PIPELINE STEPS
# ─────────────────────────────────────────────────────────────────────────────

def call_cv_writer(
    jd_text: str, geo: str, knowledge: str, corrections: str | None = None
) -> str:
    input_text = (
        f"Generate a tailored CV data module for this JD:\n\n{jd_text}"
        f"\n\nDetected geography: {prof.get_region(geo)['label']}"
    )
    if corrections:
        input_text += (
            "\n\nCORRECTION FEEDBACK FROM PREVIOUS ATTEMPT — fix these issues and "
            "regenerate the complete data module:\n\n" + corrections
        )
    input_text += (
        "\n\nOUTPUT CONTRACT: Return only the complete Python CV data module in a single "
        "```python fenced block. Do not include a walkthrough, analysis, word counts, "
        "or a verification report. Include all required fields and finish the module "
        "and closing fence within the response budget."
    )
    raw = call_llm("cv-writer", input_text, knowledge)
    match = re.search(r"```python\s*\n(.*?)```", raw, re.DOTALL)
    code = match.group(1).strip() if match else raw.strip()
    try:
        ast.parse(code)
    except SyntaxError as exc:
        raise RuntimeError(
            "CV writer returned an incomplete or invalid Python data module; "
            "no CV can be scored or rendered from this response."
        ) from exc
    if not code:
        raise RuntimeError("CV writer returned an empty Python data module.")
    return code


def call_ats_scorer(data_module_code: str, jd_text: str) -> tuple[int, str, str]:
    # Load full knowledge base so scorer can verify education, skills, certs, and projects
    # (not just employment-master — that caused false FAILs on education/skills claims)
    full_knowledge = load_knowledge()
    input_text = (
        "Score and verify this CV data module against the JD below.\n\n"
        f"## CV DATA MODULE\n```python\n{data_module_code}\n```\n\n"
        f"## JOB DESCRIPTION\n{jd_text}"
        "\n\nOUTPUT CONTRACT: Complete factual verification before writing the result. "
        "Begin your response with the final SCORE: XX/50 and VERDICT: PASS or FAIL. "
        "Then give a concise scoring summary and every unsupported claim or required correction. "
        "Omit per-keyword tables and lists of verified claims so the complete result fits "
        "within the response budget."
    )
    report = call_llm("ats-scorer", input_text, full_knowledge)
    # Case-insensitive and tolerant of an "ATS " prefix -- the skill instructs the exact
    # literal "SCORE: XX/50" / "VERDICT: PASS", but the LLM doesn't always comply exactly
    # (observed real output: "**ATS Score: 42/50**", "### Verdict: PASS"), which silently
    # defaulted a genuine PASS to a false 0/FAIL under the old strict regex.
    score_match = re.search(r"(?:ATS\s+)?SCORE:\s*(\d+)(?:\.\d+)?/50", report, re.IGNORECASE)
    verdict_match = re.search(r"(?:ATS\s+)?VERDICT:\s*(PASS|FAIL)", report, re.IGNORECASE)
    score = int(score_match.group(1)) if score_match else 0
    verdict = verdict_match.group(1).upper() if verdict_match else "FAIL"
    return score, verdict, report


def verify_ats_parseability(
    pdf_path: str,
    name: str,
    email: str,
    agency_name: str | None = None,
) -> list[str]:
    """Extract text from the rendered PDF and check it's genuinely ATS-parseable.

    Mechanical check, not an LLM judgment — inspects the actual output file
    the way a real ATS text-extraction step would. Never raises for expected
    failure modes; returns an empty list when everything checks out.
    """
    from pypdf import PdfReader

    issues = []
    try:
        reader = PdfReader(pdf_path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        return [f"Could not open/parse the rendered PDF at all: {exc}"]

    if len(text.strip()) < 200:
        issues.append(
            "PDF text extraction returned suspiciously little text — may be "
            "image-based or corrupted rather than real selectable text."
        )
        return issues  # further checks are meaningless against near-empty text

    if email and email not in text:
        issues.append(f"Contact email '{email}' not found in extracted PDF text.")
    if name and name not in text:
        issues.append(f"Candidate name '{name}' not found in extracted PDF text.")

    # resume_design_base.py renders section headers via text.upper() for visual styling
    # (see _section_header) -- match case-insensitively against the extracted text, which
    # genuinely reads clean (confirmed: PDF text extraction is not corrupted by the
    # renderer's letter-spacing). A case-sensitive match here always failed, on every CV.
    required_sections = ["Professional Summary", "Professional Experience", "Education", "Skills"]
    text_upper = text.upper()
    positions = {}
    for section in required_sections:
        idx = text_upper.find(section.upper())
        if idx == -1:
            issues.append(f"Expected section header '{section}' not found in extracted PDF text.")
        else:
            positions[section] = idx

    found_in_order = [s for s in required_sections if s in positions]
    for earlier, later in zip(found_in_order, found_in_order[1:]):
        if positions[earlier] >= positions[later]:
            issues.append(
                f"Section '{later}' appears before or at the same position as '{earlier}' "
                f"in the extracted text — may indicate a layout/column issue that scrambles "
                f"reading order for a real ATS parser."
            )

    if len(reader.pages) > 2:
        issues.append(
            f"PDF is {len(reader.pages)} pages long; ATS-friendly resumes should be no more "
            f"than 2 pages."
        )

    if "→" in text:
        issues.append(
            "Extracted PDF text contains an arrow glyph '→', which may not parse cleanly "
            "in some ATS systems."
        )

    if agency_name and agency_name.lower() in text.lower():
        issues.append(f"Possible agency leak: agency name '{agency_name}' found in extracted PDF text.")

    return issues


def render_pdf(data_module_code: str, output_path: str, agency_name: str | None = None) -> list[str]:
    with tempfile.NamedTemporaryFile(
        suffix=".py", delete=False, mode="w", encoding="utf-8"
    ) as f:
        f.write(data_module_code)
        tmp_path = f.name
    try:
        spec = importlib.util.spec_from_file_location("resume_data", tmp_path)
        data = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(data)
        photo = prof.photo_path()
        data.PHOTO = str(photo) if photo else None
        from design.resume_design_base import build
        build(data, output_path)
        return verify_ats_parseability(output_path, getattr(data, "NAME", ""), getattr(data, "EMAIL", ""), agency_name)
    except PermissionError:
        raise RuntimeError(f"Cannot write PDF — close {output_path} in your PDF viewer and retry.")
    finally:
        os.unlink(tmp_path)


def call_cover_letter(jd_text: str, knowledge: str) -> str:
    return call_llm(
        "cover-letter-writer",
        f"Write a cover letter for this JD:\n\n{jd_text}",
        knowledge,
    )


def call_outreach(jd_text: str, person_profile: dict, knowledge: str) -> str:
    profile_text = format_person_profile(person_profile)
    input_text = (
        "Draft outreach for this contact. Follow the output format exactly as specified in the skill.\n\n"
        f"## CONTACT PROFILE\n{profile_text}\n\n"
        f"## JOB DESCRIPTION\n{jd_text}"
    )
    return call_llm("outreach-drafter", input_text, knowledge)


def call_outreach_template(jd_text: str, company: str, role: str, knowledge: str) -> str:
    input_text = (
        f"Draft the General Template section (no specific contact known) for this job.\n\n"
        f"Company: {company}\n"
        f"Role: {role}\n\n"
        f"Produce TWO sub-sections: one for Hiring Manager, one for Recruiter.\n"
        f"Follow the output format exactly as specified in the skill.\n\n"
        f"## JOB DESCRIPTION\n{jd_text}"
    )
    return call_llm("outreach-drafter", input_text, knowledge)


def call_humanizer(outreach_text: str) -> str:
    return call_llm(
        "humanizer",
        outreach_text,
        knowledge=None,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def make_slug(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[\s-]+", "_", slug.strip())


def output_base(company: str, role: str) -> str:
    return f"{prof.load_profile()['file_prefix']}_{make_slug(company)}_{make_slug(role)}"


def extract_job_meta(data_module_code: str) -> tuple[str, str]:
    company_match = re.search(r'JOB_COMPANY\s*=\s*["\'](.+?)["\']', data_module_code)
    title_match = re.search(r'JOB_TITLE\s*=\s*["\'](.+?)["\']', data_module_code)
    company = company_match.group(1) if company_match else "Company"
    title = title_match.group(1) if title_match else "Role"
    return company, title


# ─────────────────────────────────────────────────────────────────────────────
#  DB WRITE (step 12)
# ─────────────────────────────────────────────────────────────────────────────

def _write_db(
    *,
    job_id: int | None,
    company: str,
    role: str,
    geo: str,
    jd_url: str | None,
    jd_text: str,
    source_type: str,
    score: int,
    cover_letter: str,
    humanized: str,
    data_path: str,
    label: str = "",
    ats_parse_warning: str | None = None,
) -> int:
    """Create or update the pipeline.db record. Returns the job_id."""
    try:
        if job_id is None:
            job_id = db.create_job(
                company=company,
                role=role,
                geography=geo,
                source_type=source_type,
                jd_url=jd_url,
                jd_text=jd_text,
            )
            db.update_job(job_id, status="generating")
        update_kwargs = dict(
            status="cv_ready",
            company=company,
            role=role,
            geography=geo,
            ats_score=float(score),
            cv_path=data_path,
            cover_letter=cover_letter,
            outreach_raw=humanized,
            jd_text=jd_text,
            ats_parse_warning=ats_parse_warning,
        )
        if source_type == "company" and not is_agency(company):
            update_kwargs["contacts_discovery_status"] = "pending"
        db.update_job(job_id, **update_kwargs)
        if not is_agency(company):
            db.queue_company_profile(company)
        _log(label, f"  DB updated: job_id={job_id}")
    except Exception as e:
        _log(label, f"  [DB] Error: {e}")
    return job_id


# ─────────────────────────────────────────────────────────────────────────────
#  SINGLE-JOB PIPELINE (called directly or by batch executor / webhook)
# ─────────────────────────────────────────────────────────────────────────────

def run_single_job(
    jd: str | None = None,
    jd_url: str | None = None,
    geo: str = "auto",
    company_override: str | None = None,
    person_infos: list | None = None,
    job_id: int | None = None,
    source_type: str = "company",
    label: str = "",
) -> dict:
    """Run the full pipeline for one job. Returns result dict with success/error info."""
    person_infos = person_infos or []

    def log(msg: str) -> None:
        _log(label, msg)

    _start = time.time()
    _step = "init"

    if job_id is not None:
        try:
            db.update_job(job_id, status="generating")
        except Exception:
            pass

    try:
        log(f"[START] job_id={job_id} source={'url' if jd_url else 'text'}")

        # 1. Fetch JD ─────────────────────────────────────────────────────────
        _step = "fetch_jd"
        jd_text = fetch_jd(jd, jd_url)

        # 1b. Agency detection ────────────────────────────────────────────────
        scraped_company = ""
        if jd_url:
            lines = [l.strip() for l in jd_text.splitlines() if l.strip()]
            scraped_company = lines[1] if len(lines) > 1 else ""
        actual_company = resolve_company(jd_text, scraped_company, company_override, force_agency=(source_type == "recruiter"))
        if actual_company and actual_company != scraped_company:
            jd_text = f"ACTUAL HIRING COMPANY: {actual_company}\n\n" + jd_text
        elif actual_company is None:
            jd_text = (
                f"AGENCY POST: This role is listed by {scraped_company} (recruitment agency). "
                f"The actual hiring company is confidential. "
                f"Do NOT reference {scraped_company} as the target company in the CV summary — "
                f"write the summary targeting the role and industry without naming a specific company.\n\n"
                + jd_text
            )

        # 2. Geo detection ────────────────────────────────────────────────────
        _step = "geo_detection"
        geo = detect_geo(jd_text, geo)
        log(f"Geography: {geo.upper()}")

        # 3. Knowledge base ───────────────────────────────────────────────────
        _step = "load_knowledge"
        log("Loading knowledge base...")
        knowledge = load_knowledge()

        # 1b (recall) — scraped_company and actual_company already exist earlier in this
        # function (agency detection, unchanged). Use them to decide whether the
        # agency-leak check applies to this job:
        agency_for_check = scraped_company if (scraped_company and actual_company != scraped_company) else None

        # 4. CV generation loop ───────────────────────────────────────────────
        data_module_code = ""
        corrections = None
        score, verdict, ats_report = 0, "FAIL", ""
        mechanical_issues: list[str] = []
        last_attempt_pdf: str | None = None

        for attempt in range(3):
            log(f"Generating CV (attempt {attempt + 1}/3)...")
            _step = "cv_writer"
            data_module_code = call_cv_writer(jd_text, geo, knowledge, corrections)

            log("  Scoring...")
            _step = "ats_scorer"
            score, verdict, ats_report = call_ats_scorer(data_module_code, jd_text)
            log(f"  ATS Score: {score}/50  Verdict: {verdict}")

            log("  Rendering for quality gate...")
            _step = "render_gate"
            previous_attempt_pdf: str | None = last_attempt_pdf
            attempt_pdf_path: str | None = None
            fd: int | None = None
            render_succeeded = False

            try:
                fd, attempt_pdf_path = tempfile.mkstemp(suffix=".pdf")
                os.close(fd)
                fd = None
                mechanical_issues = render_pdf(data_module_code, attempt_pdf_path, agency_for_check)
                last_attempt_pdf = attempt_pdf_path
                render_succeeded = True
            except Exception as exc:
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass

                if attempt_pdf_path and os.path.exists(attempt_pdf_path):
                    try:
                        os.unlink(attempt_pdf_path)
                    except OSError:
                        pass

                log(f"  Render failed: {exc}")
                mechanical_issues = [f"PDF render failed: {exc}"]

            if render_succeeded and previous_attempt_pdf:
                os.unlink(previous_attempt_pdf)

            ats_ok = score >= 35 and verdict == "PASS"
            if ats_ok and not mechanical_issues:
                break

            correction_parts = []
            if not ats_ok:
                correction_parts.append("## ATS Scorer Feedback\n" + ats_report)
            if mechanical_issues:
                correction_parts.append(
                    "## Mechanical Rendering Issues (MUST fix)\n"
                    + "\n".join(f"- {issue}" for issue in mechanical_issues)
                )
            corrections = "\n\n".join(correction_parts)

            if attempt < 2:
                log("  Retrying with corrections...")
        else:
            log("  Warning: max retries reached, proceeding with last output")

        # 5. Extract meta, create folder ──────────────────────────────────────
        company, role = extract_job_meta(data_module_code)
        base = output_base(company, role)
        job_dir = paths.output_dir() / f"{make_slug(company)}_{make_slug(role)}"
        job_dir.mkdir(parents=True, exist_ok=True)

        # 6. Save ATS report ──────────────────────────────────────────────────
        if corrections:
            ats_debug = job_dir / "ats_report_debug.txt"
            ats_debug.write_text(ats_report, encoding="utf-8")
            log(f"  ATS report: {ats_debug}")

        # 7. Save data module ─────────────────────────────────────────────────
        data_path = job_dir / f"{base}_data.py"
        data_path.write_text(data_module_code, encoding="utf-8")

        # 8. Finalize gate-checked PDF ────────────────────────────────────────
        log("Finalizing PDF...")
        _step = "finalize_pdf"
        pdf_path = str(job_dir / f"{base}.pdf")
        if last_attempt_pdf is None:
            raise RuntimeError("CV render failed on all 3 attempts — see logs for details")
        shutil.move(last_attempt_pdf, pdf_path)
        ats_issues = mechanical_issues

        # 9. Cover letter ─────────────────────────────────────────────────────
        log("Generating cover letter...")
        _step = "cover_letter"
        cover_letter = call_cover_letter(jd_text, knowledge)
        cl_path = job_dir / f"{base}_CoverLetter.txt"
        cl_path.write_text(cover_letter, encoding="utf-8")

        # 10. Outreach ────────────────────────────────────────────────────────
        outreach_sections = []
        for person_info_str in person_infos:
            person = parse_person_info(person_info_str)
            log(f"  Drafting outreach for {person.get('full_name', 'Contact')}...")
            _step = "outreach_drafter"
            outreach_sections.append(call_outreach(jd_text, person, knowledge))
        log("Generating general outreach template...")
        _step = "outreach_drafter"
        outreach_sections.append(call_outreach_template(jd_text, company, role, knowledge))

        # 11. Humanize ────────────────────────────────────────────────────────
        log("Humanizing outreach...")
        _step = "humanizer"
        humanized = call_humanizer("\n\n".join(outreach_sections))
        outreach_path = job_dir / f"{base}_Outreach.txt"
        outreach_path.write_text(humanized, encoding="utf-8")

        # 12. DB write ────────────────────────────────────────────────────────
        _step = "db_write"
        job_id = _write_db(
            job_id=job_id,
            company=company,
            role=role,
            geo=geo,
            jd_url=jd_url,
            jd_text=jd_text,
            source_type=source_type,
            score=score,
            cover_letter=cover_letter,
            humanized=humanized,
            data_path=str(job_dir),
            label=label,
            ats_parse_warning=("; ".join(ats_issues) if ats_issues else None),
        )

        log(f"Done. Files saved to: {job_dir}")
        log(f"[DONE] {round(time.time() - _start)}s | {company}/{role} ATS={score}/{verdict}")
        return {
            "success": True,
            "job_id": job_id,
            "company": company,
            "role": role,
            "geography": geo,
            "ats_score": score,
            "verdict": verdict,
            "cv_path": str(job_dir),
        }

    except Exception as e:
        _log(label, f"[FAILED at {_step}] {round(time.time() - _start)}s | {e}")
        if job_id is not None:
            try:
                db.update_job(job_id, status="failed", notes=str(e))
            except Exception:
                pass
        return {"success": False, "error": str(e), "job_id": job_id, "company": "", "role": "", "ats_score": 0, "verdict": ""}


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────

def build_arg_parser() -> argparse.ArgumentParser:
    try:
        geo_choices = prof.region_ids() + ["auto"]
    except prof.ProfileError:
        geo_choices = None
    parser = argparse.ArgumentParser(
        description="Generate a tailored CV, cover letter, and outreach for a job"
    )
    parser.add_argument("--jd", help="Job description text (paste directly)")
    parser.add_argument("--jd-file", help="Path to a .txt file containing the JD")
    parser.add_argument("--jd-url", help="LinkedIn job posting URL")
    parser.add_argument(
        "--geo", choices=geo_choices, default="auto",
        help="Target geography (default: auto-detect from JD)"
    )
    parser.add_argument(
        "--company", default=None, metavar="NAME",
        help="Actual hiring company (use when JD is posted by a recruitment agency)"
    )
    parser.add_argument(
        "--person-info", action="append", dest="person_infos", default=[],
        metavar="INFO", help="Manual person info: 'Name|Title|Company|email' (repeatable, max 3)"
    )
    parser.add_argument(
        "--batch-file", default=None, metavar="FILE",
        help="JSON file with multiple jobs — run up to 3 in parallel. See jobs.json.example"
    )
    parser.add_argument(
        "--job-id", type=int, default=None, metavar="ID",
        help="Update this existing pipeline.db job record (used by Flask API)"
    )
    parser.add_argument(
        "--source-type", choices=["company", "recruiter"], default="company",
        help="Whether this is a direct company post or recruiter post (default: company)"
    )
    parser.add_argument(
        "--json-output", action="store_true",
        help="Print result as JSON to stdout (used by Flask API subprocess)"
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    # ── Batch mode ───────────────────────────────────────────────────────────
    if args.batch_file:
        _preflight()
        paths.output_dir().mkdir(parents=True, exist_ok=True)
        jobs = json.loads(Path(args.batch_file).read_text(encoding="utf-8"))
        print(f"Batch mode: {len(jobs)} jobs, max 3 parallel")

        start = datetime.now()
        results: list[dict] = []

        with ThreadPoolExecutor(max_workers=min(3, len(jobs))) as pool:
            futures = {
                pool.submit(
                    run_single_job,
                    jd=job.get("jd"),
                    jd_url=job.get("jd_url"),
                    geo=job.get("geo", "auto"),
                    company_override=job.get("company"),
                    person_infos=job.get("persons", []),
                    label=job.get("label", f"job{i + 1}"),
                ): job.get("label", f"job{i + 1}")
                for i, job in enumerate(jobs)
            }
            for future in as_completed(futures):
                result = future.result()
                result["label"] = futures[future]
                results.append(result)

        elapsed = int((datetime.now() - start).total_seconds())
        print(f"\n{'━' * 60}")
        print(f"BATCH COMPLETE — {len(jobs)} jobs in {elapsed}s")
        print(f"{'━' * 60}")
        for r in sorted(results, key=lambda x: x.get("label", "")):
            if r["success"]:
                print(f"  OK  {r['company']}_{r['role']}   ATS {r['score']}/50  {r['verdict']}")
            else:
                print(f"  ERR {r.get('label', '?')}   {r.get('error', 'unknown')}")
        print(f"{'━' * 60}")
        return

    # ── Single-job mode ───────────────────────────────────────────────────────
    _preflight()
    if args.jd_file:
        args.jd = Path(args.jd_file).read_text(encoding="utf-8")
    if not args.jd and not args.jd_url:
        parser.error("one of --jd, --jd-file, --jd-url, or --batch-file is required")
    if sum(bool(x) for x in [args.jd, args.jd_url]) > 1:
        parser.error("--jd, --jd-file, and --jd-url are mutually exclusive")
    if len(args.person_infos) > 3:
        parser.error("maximum 3 person infos supported")

    paths.output_dir().mkdir(parents=True, exist_ok=True)

    result = run_single_job(
        jd=args.jd,
        jd_url=args.jd_url,
        geo=args.geo,
        company_override=args.company,
        person_infos=args.person_infos,
        job_id=args.job_id,
        source_type=args.source_type,
    )

    if args.json_output:
        print(json.dumps(result))
        if not result["success"]:
            sys.exit(1)
        return

    if not result["success"]:
        sys.exit(f"Pipeline failed: {result.get('error', 'unknown error')}")

    print(f"\nDone. All files saved to: {result['cv_path']}")


if __name__ == "__main__":
    main()
