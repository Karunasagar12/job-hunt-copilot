import base64
import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
import sys
import threading
import uuid
import requests
from logging.handlers import RotatingFileHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import paths
from dotenv import load_dotenv
load_dotenv(paths.repo_dir() / ".env")
load_dotenv(paths.data(".env"))

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS

import fullenrich_client
import db
import gmail_client
import agentmail_client
import llm_client
import outreach_manager
from api.utils import run_pipeline_async

app = Flask(__name__)
CORS(app)

paths.ensure_dirs()
db.init_db()

PROJECT_ROOT = paths.repo_dir()

LOG_DIR = paths.logs_dir()
LOG_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("jhc")
logger.setLevel(logging.INFO)
logger.propagate = False
if not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
    _handler = RotatingFileHandler(LOG_DIR / "app.log", maxBytes=10 * 1024 * 1024, backupCount=5)
    _handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(_handler)


def err(msg, status=400):
    return jsonify({"error": msg, "status": status}), status


@app.after_request
def log_request(response):
    logger.info(f"{request.method} {request.path} → {response.status_code}")
    return response


# ── JOBS ──────────────────────────────────────────────────────────────────────

@app.get("/api/jobs")
def list_jobs():
    status = request.args.get("status")
    geo = request.args.get("geo")
    sort = request.args.get("sort", "date")
    order = request.args.get("order", "desc")
    if status:
        status = [s.strip() for s in status.split(",") if s.strip()]
    if geo:
        geo = [g.strip() for g in geo.split(",") if g.strip()]
    return jsonify(db.get_jobs(status=status or None, geo=geo or None, sort=sort, order=order))


@app.get("/api/jobs/<int:job_id>")
def get_job(job_id):
    job = db.get_job(job_id)
    if not job:
        return err("Job not found", 404)
    contacts = db.get_contacts(job_id)
    total_outreach = sum(len(c["outreach_entries"]) for c in contacts)
    sent = sum(
        1 for c in contacts for o in c["outreach_entries"] if o["status"] in ("sent", "gmail_draft")
    )
    due_today = sum(
        1 for c in contacts for o in c["outreach_entries"]
        if o["status"] == "draft" and o.get("scheduled_date")
    )
    job["contacts"] = contacts
    job["outreach_summary"] = {"total": total_outreach, "sent": sent, "drafted": sent, "due_today": due_today}
    return jsonify(job)


@app.get("/api/jobs/<int:job_id>/status")
def job_status(job_id):
    job = db.get_job(job_id)
    if not job:
        return err("Job not found", 404)
    return jsonify({"status": job["status"], "ats_score": job.get("ats_score")})


@app.post("/api/jobs")
def create_job():
    data = request.json or {}
    jd_url = data.get("jd_url")
    jd_text = data.get("jd_text")
    source_type = data.get("source_type", "company")
    geo = data.get("geography") or data.get("geo") or "auto"
    company_override = data.get("company")
    contacts_data = data.get("contacts", [])
    recruiter_agency = data.get("recruiter_agency")

    if not jd_url and not jd_text:
        return err("jd_url or jd_text is required")
    if source_type not in ("company", "recruiter"):
        return err("source_type must be 'company' or 'recruiter'")

    job_id = db.create_job(
        company=company_override or "Pending",
        role="Pending",
        geography=geo if geo != "auto" else "gcc",
        source_type=source_type,
        recruiter_agency=recruiter_agency,
        jd_url=jd_url,
        jd_text=jd_text,
    )

    logger.info(
        f"[PIPELINE job_id={job_id}] queued | source={'url' if jd_url else 'text'} geo={geo} contacts={len(contacts_data)}"
    )

    for c in contacts_data[:3]:
        if not c.get("name") or not c.get("contact_type"):
            continue
        db.create_contact(
            job_id,
            name=c["name"],
            contact_type=c["contact_type"],
            title=c.get("title"),
            company=c.get("company"),
            email=c.get("email"),
            linkedin_url=c.get("linkedin_url"),
        )

    person_infos = [
        f"{c['name']}|{c.get('title','')}|{c.get('company','')}|{c.get('email','')}"
        for c in contacts_data[:3] if c.get("name")
    ]

    run_pipeline_async(
        job_id,
        jd_url=jd_url,
        jd_text=jd_text,
        geo=geo,
        source_type=source_type,
        person_infos=person_infos,
        company=company_override,
        db_update_fn=db.update_job,
    )

    return jsonify({"job_id": job_id, "status": "generating"}), 202


@app.patch("/api/jobs/<int:job_id>")
def update_job(job_id):
    job = db.get_job(job_id)
    if not job:
        return err("Job not found", 404)
    data = request.json or {}
    allowed = {"status", "notes", "company", "role", "geography", "source_type",
               "recruiter_agency", "jd_url", "ats_score", "cover_letter", "outreach_raw",
               "salary_estimate"}
    kwargs = {k: v for k, v in data.items() if k in allowed}
    if not kwargs:
        return err("No updatable fields provided")
    try:
        updated = db.update_job(job_id, **kwargs)
    except ValueError as e:
        return err(str(e))
    return jsonify(updated)


@app.delete("/api/jobs/<int:job_id>")
def delete_job(job_id):
    job = db.get_job(job_id)
    if not job:
        return err("Job not found", 404)
    try:
        db.delete_job(job_id)
    except sqlite3.IntegrityError as e:
        return err(f"Could not delete job: {e}", 409)
    return "", 204


def _find_cv_pdf(job):
    cv_path = job.get("cv_path")
    if not cv_path:
        return None
    job_dir = paths.data_dir() / cv_path
    pdfs = list(job_dir.glob("*.pdf")) if job_dir.is_dir() else []
    return str(pdfs[0]) if pdfs else None


@app.get("/api/jobs/<int:job_id>/cv")
def download_cv(job_id):
    job = db.get_job(job_id)
    if not job:
        return err("Job not found", 404)
    pdf_path = _find_cv_pdf(job)
    if not pdf_path:
        return err("CV not yet generated" if not job.get("cv_path") else "CV PDF not found on disk", 404)
    return send_file(pdf_path, as_attachment=True)


@app.get("/api/jobs/<int:job_id>/cover-letter/pdf")
def download_cover_letter(job_id):
    from io import BytesIO
    import re

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.enums import TA_LEFT, TA_JUSTIFY

    def _to_reportlab_markup(line):
        escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)

    def _split_nonblank_groups(text):
        groups, current = [], []
        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if stripped:
                current.append(stripped)
            elif current:
                groups.append(current)
                current = []
        if current:
            groups.append(current)
        return groups

    job = db.get_job(job_id)
    if not job:
        return err("Job not found", 404)
    cover_letter = (job.get("cover_letter") or "").strip()
    if not cover_letter:
        return err("Cover letter not yet generated", 404)

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                             leftMargin=2.5 * cm, rightMargin=2.5 * cm,
                             topMargin=2.5 * cm, bottomMargin=2.5 * cm)
    styles = getSampleStyleSheet()
    name_style = ParagraphStyle(
        "Name", parent=styles["Normal"],
        fontName="Helvetica-Bold", fontSize=15,
        spaceAfter=2, alignment=TA_LEFT,
    )
    contact_style = ParagraphStyle(
        "Contact", parent=styles["Normal"],
        fontName="Helvetica", fontSize=9,
        textColor=colors.HexColor("#555555"),
        spaceAfter=14, alignment=TA_LEFT,
    )
    title_style = ParagraphStyle(
        "Title", parent=styles["Normal"],
        fontName="Helvetica-Bold", fontSize=12,
        spaceAfter=2, alignment=TA_LEFT,
    )
    company_date_style = ParagraphStyle(
        "CompanyDate", parent=styles["Normal"],
        fontName="Helvetica-Oblique", fontSize=10,
        textColor=colors.HexColor("#555555"),
        spaceAfter=16, alignment=TA_LEFT,
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["Normal"],
        fontName="Helvetica", fontSize=11, leading=16,
        spaceAfter=10, alignment=TA_JUSTIFY,
    )
    bullet_style = ParagraphStyle(
        "Bullet", parent=styles["Normal"],
        fontName="Helvetica", fontSize=11, leading=16,
        spaceAfter=6, alignment=TA_LEFT,
        leftIndent=14, firstLineIndent=-14,
    )

    groups = _split_nonblank_groups(cover_letter)
    header_lines, title_lines, body_groups = [], [], []

    if len(groups) > 1 and len(groups[0]) >= 2:
        header_lines = groups[0][:2]
        if len(groups[0]) > 2:
            body_groups.extend([line] for line in groups[0][2:])

        next_idx = 1
        if (len(groups) > next_idx and len(groups[next_idx]) >= 2
                and groups[next_idx][0].startswith("Cover Letter:")):
            title_lines = groups[next_idx][:2]
            if len(groups[next_idx]) > 2:
                body_groups.extend([line] for line in groups[next_idx][2:])
            next_idx += 1

        body_groups.extend(groups[next_idx:])
    else:
        body_groups = groups

    story = []
    if header_lines:
        story.append(Paragraph(_to_reportlab_markup(header_lines[0]), name_style))
        story.append(Paragraph(_to_reportlab_markup(header_lines[1]), contact_style))

    if title_lines:
        story.append(Paragraph(_to_reportlab_markup(title_lines[0]), title_style))
        story.append(Paragraph(_to_reportlab_markup(title_lines[1]), company_date_style))

    if title_lines and body_groups:
        story.append(Spacer(1, 4))

    previous_was_bullet = False
    for group in body_groups:
        for line in group:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("•"):
                if previous_was_bullet:
                    story.append(Spacer(1, 6))
                bullet_text = stripped[1:].lstrip()
                story.append(Paragraph("• " + _to_reportlab_markup(bullet_text), bullet_style))
                previous_was_bullet = True
            else:
                story.append(Paragraph(_to_reportlab_markup(stripped), body_style))
                previous_was_bullet = False

    doc.build(story)
    buf.seek(0)

    def _safe_filename_part(s):
        for ch in '"\r\n\\/:*?<>|':
            s = s.replace(ch, "")
        return s

    company = _safe_filename_part((job.get("company") or "Company").replace(" ", "_"))
    role = _safe_filename_part((job.get("role") or "Role").replace(" ", "_"))
    filename = f"JaneDoe_{company}_{role}_CoverLetter.pdf"
    from flask import make_response
    response = make_response(buf.read())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ── CONTACTS ─────────────────────────────────────────────────────────────────

@app.get("/api/jobs/<int:job_id>/contacts")
def list_contacts(job_id):
    if not db.get_job(job_id):
        return err("Job not found", 404)
    return jsonify(db.get_contacts(job_id))


@app.post("/api/jobs/<int:job_id>/contacts")
def add_contact(job_id):
    if not db.get_job(job_id):
        return err("Job not found", 404)
    data = request.json or {}
    name = data.get("name", "").strip()
    contact_type = data.get("contact_type", "").strip()
    if not name:
        return err("name is required")
    if not contact_type:
        return err("contact_type is required")

    email = data.get("email", "").strip() or None
    dedup_warning = None
    if email:
        dedup_warning = db.check_email_dedup(email, job_id)

    contact_id = db.create_contact(
        job_id,
        name=name,
        contact_type=contact_type,
        title=data.get("title"),
        company=data.get("company"),
        email=email,
        linkedin_url=data.get("linkedin_url"),
        source=data.get("source", "manual"),
    )
    contact = db._get_conn().execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    result = dict(contact)
    if dedup_warning:
        result["dedup_warning"] = dedup_warning
    return jsonify(result), 201


@app.patch("/api/contacts/<int:contact_id>")
def update_contact(contact_id):
    data = request.json or {}
    allowed = {"name", "title", "company", "email", "linkedin_url", "contact_type",
               "source", "outreach_sent", "replied"}
    kwargs = {k: v for k, v in data.items() if k in allowed}
    if not kwargs:
        return err("No updatable fields provided")
    updated = db.update_contact(contact_id, **kwargs)
    if not updated:
        return err("Contact not found", 404)
    return jsonify(updated)


@app.delete("/api/contacts/<int:contact_id>")
def delete_contact(contact_id):
    db.delete_contact(contact_id)
    return "", 204


@app.get("/api/contacts/all")
def all_contacts():
    return jsonify(db.get_all_contacts())


_CASCADE_CONTACT_TYPES = {"hiring_manager", "recruiter", "executive"}


def _cascade_cancel_for_job(job_id, except_contact_id):
    """Cancel pending touchpoints for every OTHER contact on this job.
    Returns a list of {"contact_id", "name", "cancelled_count"} for each
    contact that actually had something cancelled."""
    conn = db._get_conn()
    other_contacts = conn.execute(
        "SELECT id, name FROM contacts WHERE job_id = ? AND id != ?",
        (job_id, except_contact_id),
    ).fetchall()
    cascaded = []
    for other in other_contacts:
        other_cancelled = _cancel_contact_touchpoints(other["id"])
        if other_cancelled:
            cascaded.append({
                "contact_id": other["id"],
                "name": other["name"],
                "cancelled_count": other_cancelled,
            })
    return cascaded


@app.post("/api/contacts/<int:contact_id>/replied")
def mark_replied(contact_id):
    updated = db.update_contact(contact_id, replied=1)
    if not updated:
        return err("Contact not found", 404)
    cancelled_count = _cancel_contact_touchpoints(contact_id)

    cascaded = []
    if updated["contact_type"] in _CASCADE_CONTACT_TYPES:
        cascaded = _cascade_cancel_for_job(updated["job_id"], contact_id)

    return jsonify({"contact": updated, "cancelled_count": cancelled_count, "cascaded": cascaded})


def _cancel_contact_touchpoints(contact_id):
    """Cancel a contact's pending touchpoints and delete any live Gmail
    drafts. Returns the number of touchpoints cancelled."""
    cancelled = db.cancel_pending_touchpoints(contact_id)
    for row in cancelled:
        if row["gmail_draft_id"]:
            gmail_client.delete_draft(row["gmail_draft_id"])
    return len(cancelled)


@app.get("/api/inbox-digest")
def inbox_digest():
    db.sweep_stale_sending()
    digest = db.get_inbox_digest()
    for entry in digest["replies"]:
        entry["cascade_pending"] = (
            entry.pop("has_unconfirmed_cascade") and entry["contact_type"] in _CASCADE_CONTACT_TYPES
        )
    uncertain_items = db.get_uncertain_outreach()
    digest["uncertain"] = {"count": len(uncertain_items), "items": uncertain_items}
    return jsonify(digest)


@app.post("/api/outreach/<int:entry_id>/dismiss-uncertain")
def dismiss_uncertain(entry_id):
    dismissed = db.dismiss_uncertain_outreach(entry_id)
    if not dismissed:
        return err("Entry not found or not uncertain/failed", 404)
    return jsonify({"dismissed": True})


@app.get("/api/inbox-digest/contact/<int:contact_id>/thread")
def inbox_digest_thread(contact_id):
    conn = db._get_conn()
    email1 = conn.execute(
        "SELECT provider, gmail_thread_id, agentmail_thread_id FROM outreach_log "
        "WHERE contact_id=? AND sequence_num=1 AND channel='email' LIMIT 1",
        (contact_id,),
    ).fetchone()
    if email1 and email1["provider"] == "agentmail" and email1["agentmail_thread_id"]:
        inbox_id = os.getenv("AGENTMAIL_INBOX_ID", "")
        if inbox_id:
            try:
                messages = agentmail_client.get_thread_messages(inbox_id, email1["agentmail_thread_id"])
                return jsonify({
                    "source": "agentmail",
                    "messages": [
                        {**message,
                         "body": message.get("text") or message.get("extracted_text") or "",
                         "date": message.get("timestamp") or ""}
                        for message in messages
                    ],
                })
            except Exception:
                pass  # fall through to the local fallback below
    elif email1 and email1["gmail_thread_id"]:
        try:
            return jsonify({"source": "gmail", "messages": gmail_client.get_thread_messages(email1["gmail_thread_id"])})
        except Exception:
            pass  # fall through to the local fallback below
    local_rows = conn.execute(
        "SELECT message_id, classification, processed_at FROM processed_gmail_messages WHERE contact_id = ? "
        "UNION ALL "
        "SELECT message_id, classification, processed_at FROM processed_agentmail_messages WHERE contact_id = ? "
        "ORDER BY processed_at ASC",
        (contact_id, contact_id),
    ).fetchall()
    return jsonify({"source": "local", "messages": [dict(r) for r in local_rows]})


@app.post("/api/inbox-digest/contact/<int:contact_id>/dismiss")
def dismiss_inbox_digest_contact(contact_id):
    return jsonify({"dismissed": db.dismiss_contact_digest(contact_id)})


@app.post("/api/inbox-digest/dismiss")
def dismiss_inbox_digest_messages():
    message_ids = (request.json or {}).get("message_ids", [])
    if not message_ids:
        return err("message_ids list is required")
    return jsonify({"dismissed": db.dismiss_digest_messages(message_ids)})


@app.post("/api/inbox-digest/contact/<int:contact_id>/confirm-cascade")
def confirm_inbox_cascade(contact_id):
    job_id = db.confirm_cascade_for_contact(contact_id)
    if job_id is None:
        return err("No recorded inbox messages for this contact", 404)
    cascaded = _cascade_cancel_for_job(job_id, contact_id)
    return jsonify({"cascaded": cascaded})


@app.post("/api/contacts/<int:contact_id>/bounced")
def mark_bounced(contact_id):
    updated = db.update_contact(contact_id, email_status="bounced")
    if not updated:
        return err("Contact not found", 404)
    cancelled_count = _cancel_contact_touchpoints(contact_id)
    return jsonify({"contact": updated, "cancelled_count": cancelled_count})


@app.post("/api/contacts/<int:contact_id>/skip")
def skip_contact_outreach(contact_id):
    contact = db._get_conn().execute(
        "SELECT * FROM contacts WHERE id = ?", (contact_id,)
    ).fetchone()
    if not contact:
        return err("Contact not found", 404)
    cancelled_count = _cancel_contact_touchpoints(contact_id)
    return jsonify({"cancelled_count": cancelled_count})


@app.post("/api/contacts/<int:contact_id>/get-email")
def get_contact_email(contact_id):
    conn = db._get_conn()
    row = conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
    if not row:
        return err("Contact not found", 404)
    contact = dict(row)

    linkedin_url = contact.get("linkedin_url")
    if not linkedin_url:
        return err("FullEnrich could not find this contact", 404)

    def _on_result(email, profile):
        updates = {}
        if profile:
            mapped = fullenrich_client.map_person(profile)
            if mapped.get("title"):
                updates["title"] = mapped["title"]
            if mapped.get("company"):
                updates["company"] = mapped["company"]
            if mapped.get("apollo_id"):
                updates["apollo_id"] = mapped["apollo_id"]
            if mapped.get("name") and not contact.get("name"):
                updates["name"] = mapped["name"]
        if email:
            updates["email"] = email
        if updates:
            db.update_contact(contact_id, **updates)

    enrichment_id = fullenrich_client.enrich_by_linkedin_async(
        linkedin_url, _on_result, name=contact.get("name") or "job-hunt-system enrich"
    )
    if not enrichment_id:
        return err("FullEnrich could not find this contact", 404)

    return jsonify({"status": "pending", "contact": contact}), 202


@app.post("/api/contacts/match-linkedin")
def match_linkedin():
    linkedin_url = (request.json or {}).get("linkedin_url", "").strip()
    if not linkedin_url:
        return err("linkedin_url is required")
    result = fullenrich_client.match_by_linkedin(linkedin_url)
    if not result:
        return err("No match found for that LinkedIn URL", 404)
    return jsonify(result)


# ── OUTREACH ─────────────────────────────────────────────────────────────────

# ponytail: in-process guard -- job-hunt-api is a single python process. Needs
# a DB-level claim if this ever runs under multiple workers.
_outreach_starting = set()
_outreach_starting_lock = threading.Lock()


@app.post("/api/jobs/<int:job_id>/outreach/start")
def start_outreach(job_id):
    # Job #141: a second request landing during the first one's ~20s LLM
    # generation passed the "already started?" check and duplicated every
    # touchpoint. Reject it while the first is still in flight.
    with _outreach_starting_lock:
        if job_id in _outreach_starting:
            return err("Outreach start already in progress for this job", 409)
        _outreach_starting.add(job_id)
    try:
        return _start_outreach(job_id)
    finally:
        with _outreach_starting_lock:
            _outreach_starting.discard(job_id)


def _start_outreach(job_id):
    job = db.get_job(job_id)
    if not job:
        return err("Job not found", 404)

    conn = db._get_conn()
    existing = conn.execute(
        "SELECT 1 FROM outreach_log WHERE job_id = ? LIMIT 1", (job_id,)
    ).fetchone()
    if existing:
        return err("Outreach already started for this job", 400)

    contacts = db.get_contacts(job_id)
    if not contacts:
        return err("No contacts found for this job")

    created, warnings = 0, []
    for contact in contacts:
        email = contact.get("email")
        dedup = db.check_email_dedup(email, job_id) if email else None
        if dedup:
            warnings.append({
                "contact_name": contact["name"],
                "warning": f"Email {email} previously used for {dedup['previous_job_company']} - {dedup['previous_job_role']}"
            })

    outreach_raw = job.get("outreach_raw", "") or ""
    unmatched_contacts = outreach_manager.get_unmatched_contacts(outreach_raw, contacts)
    outreach_generated = len(unmatched_contacts)

    if unmatched_contacts:
        previous_cwd = os.getcwd()
        generated_sections = []
        try:
            os.chdir(PROJECT_ROOT)
            import generate

            knowledge = generate.load_knowledge()
            jd_text = job.get("jd_text") or (
                f"Company: {job.get('company', '')}\nRole: {job.get('role', '')}"
            )

            for contact in unmatched_contacts:
                contact_name = contact.get("name") or ""
                title = contact.get("title") or ""
                company = contact.get("company") or ""
                headline = f"{title} at {company}" if title and company else (title or company)
                person_profile = {
                    "full_name": contact_name,
                    "headline": headline,
                    "email": contact.get("email") or "",
                    "summary": "",
                    "experiences": [{"title": title, "company": company, "starts_at": {}, "ends_at": None}],
                }
                try:
                    generated = generate.call_outreach(jd_text, person_profile, knowledge)
                except Exception as exc:
                    print(f"[outreach] Failed to generate for contact {contact.get('id')} ({contact_name}): {exc}")
                    continue
                if generated and generated.strip():
                    generated_sections.append(generated.strip())

            if generated_sections:
                combined = "\n\n".join(generated_sections)
                try:
                    humanized = generate.call_humanizer(combined)
                except Exception as exc:
                    print(f"[outreach] Humanizer failed, using raw sections: {exc}")
                    humanized = combined

                if humanized and humanized.strip():
                    outreach_raw = (
                        f"{outreach_raw.rstrip()}\n\n{humanized.strip()}"
                        if outreach_raw.strip() else humanized.strip()
                    )
                    db.update_job(job_id, outreach_raw=outreach_raw)
        finally:
            os.chdir(previous_cwd)

    touchpoints = outreach_manager.parse_and_schedule(outreach_raw, contacts)
    for tp in touchpoints:
        db.create_outreach_entry(
            contact_id=tp["contact_id"],
            job_id=job_id,
            channel=tp["channel"],
            sequence_num=tp["sequence_num"],
            scheduled_date=tp["scheduled_date"],
            subject=tp["subject"],
            content=tp["content"],
            # Cutover (October 2026): real AgentMail credentials are wired
            # into production .env, poll_agentmail_inbox.py is hand-run and
            # on a systemd timer, and this project is no longer bound to
            # Gmail drafts -- new outreach now defaults to db.py's
            # provider="agentmail" (not overridden here anymore).
        )
        created += 1

    return jsonify({"created": created, "warnings": warnings, "outreach_generated": outreach_generated})


@app.get("/api/outreach/due")
def outreach_due():
    date = request.args.get("date")
    return jsonify(db.get_followups_due(date))


def _get_thread_params(conn, entry):
    """Return (thread_id, reply_to_message_id) for follow-up emails, sourced from the persisted
    columns captured when Email 1's draft was created — never calls the Gmail API, so it keeps
    working after Email 1 has been sent (a sent message is no longer in the drafts collection)."""
    if entry["sequence_num"] not in (4, 5):
        return None, None
    email1 = conn.execute(
        "SELECT gmail_thread_id, gmail_message_id FROM outreach_log "
        "WHERE contact_id=? AND sequence_num=1 AND channel='email' LIMIT 1",
        (entry["contact_id"],),
    ).fetchone()
    if not email1 or not email1["gmail_thread_id"]:
        return None, None
    return email1["gmail_thread_id"], email1["gmail_message_id"]


@app.post("/api/outreach/<int:entry_id>/gmail-draft")
def create_gmail_draft(entry_id):
    conn = db._get_conn()
    entry = conn.execute("SELECT * FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    if not entry:
        return err("Outreach entry not found", 404)
    if entry["provider"] == "agentmail":
        # ponytail: latent gap flagged in Task 2's review -- nothing stopped
        # this Gmail-draft-creation route from flipping an agentmail-provider
        # row to status='gmail_draft', a state this plan's cancellation/
        # send/retry logic can never recover from. Reject outright, same
        # pattern as mark_sent's unconditional agentmail rejection.
        return err("Gmail drafts cannot be created for AgentMail-managed entries", 409)
    if entry["channel"] != "email":
        return err("Gmail drafts only supported for email touchpoints", 400)
    contact = conn.execute("SELECT * FROM contacts WHERE id = ?", (entry["contact_id"],)).fetchone()
    if not contact or not contact["email"]:
        return err("Contact has no email address", 400)
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (entry["job_id"],)).fetchone()
    geo = (job["geography"] or "eu") if job else "eu"
    attachment_path = _find_cv_pdf(dict(job)) if job and entry["sequence_num"] == 1 else None

    subject, content = entry["subject"] or "", entry["content"] or ""
    if _PLACEHOLDER_RE.search(f"{subject}\n{content}"):
        try:
            subject, content = _llm_redraft(
                entry, contact, job,
                feedback="Replace every literal placeholder bracket (e.g. [First Name]) with the real value — never output a literal bracket placeholder.",
            )
        except Exception as exc:
            return err("Automatic placeholder fix failed: " + str(exc), 502)
        if _PLACEHOLDER_RE.search(f"{subject}\n{content}"):
            return err(f"Outreach content for entry {entry_id} still contains a placeholder after an automatic fix attempt — redraft manually.", 502)
        db.update_outreach_entry(entry_id, subject=subject, content=content)

    body = gmail_client.strip_signature(content)
    thread_id, reply_to_message_id = _get_thread_params(conn, entry)
    try:
        draft_id = gmail_client.create_draft(
            to_email=contact["email"],
            subject=subject,
            body=body,
            thread_id=thread_id,
            reply_to_message_id=reply_to_message_id,
            geo=geo,
            attachment_path=attachment_path,
        )
    except FileNotFoundError:
        return err("Gmail credentials not configured", 503)
    except RuntimeError as exc:
        return err(f"Gmail API error: {str(exc)}", 502)
    thread_info = gmail_client.get_draft_thread_info(draft_id)
    update_fields = {"status": "gmail_draft", "gmail_draft_id": draft_id}
    if thread_info:
        update_fields["gmail_thread_id"] = thread_info["thread_id"]
        update_fields["gmail_message_id"] = thread_info["message_id"]
    updated = db.update_outreach_entry(entry_id, **update_fields)
    return jsonify({"gmail_draft_id": draft_id, "status": "gmail_draft", "entry": updated})


def _resolve_cv(job):
    """Returns (path, raw_bytes, sha256_hash) or (None, None, None) if no CV
    PDF resolves. Reads the file exactly once -- callers derive both the
    hash (for staleness checks) and the base64 snapshot (for sending/
    storage) from the same in-memory bytes, never a second disk read."""
    path = _find_cv_pdf(job)
    if not path:
        return None, None, None
    with open(path, "rb") as f:
        raw = f.read()
    return path, raw, hashlib.sha256(raw).hexdigest()


def _build_fingerprint(subject, body, recipient_email, inbox_id, reply_to_message_id, cv_hash,
                        inline_attachments_json=None):
    raw = "|".join([
        subject or "", body or "", recipient_email or "", inbox_id or "",
        reply_to_message_id or "", cv_hash or "", inline_attachments_json or "",
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class _PrepareError(Exception):
    def __init__(self, message, status):
        super().__init__(message)
        self.message = message
        self.status = status


_SIGNATURE_IMAGE_RE = re.compile(r'src="data:(image/(?:png|jpeg|gif));base64,([^"]+)"')
_SIGNATURE_IMAGE_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif"}


def _signature_to_cid(signature_html):
    """Convert embedded data:image URIs in signature HTML into cid: references
    plus a list of AgentMail-ready inline attachment dicts. Mirrors the
    validated pilot/agentmail_pilot.py inline_signature() logic -- AgentMail's
    transport does not render data: image URIs the way Gmail's own draft
    rendering does, so without this the signature's portrait/LinkedIn/GitHub/
    booking images are silently dropped (see SPRINT_LOG.md's AgentMail review
    entry, finding R2). Returns (html_with_cid_refs, attachments_list);
    attachments_list is [] if the signature has no embedded images."""
    attachments = []

    def _replace(match):
        content_type, content = match.group(1), match.group(2)
        index = len(attachments)
        content_id = f"signature-image-{index}@jobhunt.local"
        normalized = base64.b64encode(base64.b64decode(content, validate=True)).decode("ascii")
        attachments.append({
            "filename": f"signature-{index}.{_SIGNATURE_IMAGE_EXT[content_type]}",
            "content_type": content_type,
            "content": normalized,
            "content_disposition": "inline",
            "content_id": content_id,
        })
        return f'src="cid:{content_id}"'

    html = _SIGNATURE_IMAGE_RE.sub(_replace, signature_html)
    return html, attachments


def _cid_to_preview_html(html_body, inline_attachments):
    """Reverse of _signature_to_cid, for the /prepare response ONLY -- browsers
    cannot resolve cid: URIs outside a real email client, so the Review-and-Send
    drawer rendered blank where the signature images should be (SPRINT_LOG.md's
    AgentMail review entry, finding R2b). Substitutes each cid:<content_id>
    reference back to a data: URI built from the SAME stored attachment bytes
    used for sending, so the preview and the real email always match. Never
    used for the actual send/replay payload -- that keeps the real cid:
    references and separate inline attachments, unchanged."""
    if not html_body or not inline_attachments:
        return html_body
    preview = html_body
    for attachment in inline_attachments:
        content_id = attachment.get("content_id")
        if not content_id:
            continue
        data_url = f"data:{attachment['content_type']};base64,{attachment['content']}"
        preview = preview.replace(f"cid:{content_id}", data_url)
    return preview


def _prepare_agentmail_content(conn, entry, contact, job):
    """Shared by /prepare and /send -- returns a dict with finalized
    subject/text/html bodies, CV bytes (Email 1 only, read exactly once),
    reply target (Email 2/3 only), the inbox_id used, and a fingerprint.
    Raises _PrepareError for the caller to turn into an HTTP error
    response."""
    inbox_id = os.getenv("AGENTMAIL_INBOX_ID", "")
    if not inbox_id or not agentmail_client.AGENTMAIL_API_KEY:
        raise _PrepareError("AgentMail is not configured (missing AGENTMAIL_INBOX_ID or AGENTMAIL_API_KEY).", 500)

    geo = (job["geography"] or "eu") if job else "eu"
    original_subject, original_content = entry["subject"] or "", entry["content"] or ""
    subject, content = original_subject, original_content

    if _PLACEHOLDER_RE.search(f"{subject}\n{content}"):
        subject, content = _llm_redraft(
            entry, contact, job,
            feedback="Replace every literal placeholder bracket (e.g. [First Name]) with the real value — never output a literal bracket placeholder.",
        )
        if _PLACEHOLDER_RE.search(f"{subject}\n{content}"):
            raise _PrepareError("Outreach content still contains a placeholder after an automatic fix attempt — redraft manually.", 502)
        # Guard has TWO parts, not just status='draft'. status alone isn't
        # enough: a concurrent EDIT (PATCH /api/outreach/<id>, still
        # guarded to require status='draft' itself) can land while this
        # LLM call is in flight without ever changing status away from
        # 'draft' -- the row stays 'draft' throughout. Without also
        # checking subject/content against what this redraft was actually
        # computed FROM (original_subject/original_content, captured
        # before the LLM call), the write below would silently clobber
        # that concurrent edit with a redraft based on stale, pre-edit
        # content. Re-checking status alone would let that straight
        # through -- this is the same TOCTOU class as Task 7's claim fix,
        # just one level shallower (a plain UPDATE here, not a claim that
        # also needs to transition status).
        with db._write_lock:
            cur = conn.execute(
                "UPDATE outreach_log SET subject = ?, content = ? "
                "WHERE id = ? AND status = 'draft' AND subject = ? AND content = ?",
                (subject, content, entry["id"], original_subject, original_content),
            )
            conn.commit()
        if cur.rowcount == 0:
            raise _PrepareError("Entry changed while the automatic placeholder fix was running — reopen and review again.", 409)

    plain_body = gmail_client.strip_signature(content)
    signature_html, inline_attachments = _signature_to_cid(gmail_client._get_signature(geo))
    html_body = gmail_client.compose_html_body(plain_body, signature_html)

    cv_path, cv_bytes, cv_hash = None, None, None
    if entry["sequence_num"] == 1:
        cv_path, cv_bytes, cv_hash = _resolve_cv(dict(job)) if job else (None, None, None)
        if not cv_path:
            raise _PrepareError("CV not found for this job.", 422)

    reply_to_message_id = None
    if entry["sequence_num"] != 1:
        preceding = db.get_preceding_email(entry["contact_id"], entry["sequence_num"])
        if preceding and preceding["status"] == "sent":
            reply_to_message_id = preceding["agentmail_message_id"]

    inline_attachments_json = json.dumps(inline_attachments) if inline_attachments else None
    fingerprint = _build_fingerprint(
        subject, html_body or plain_body, contact["email"], inbox_id,
        reply_to_message_id, cv_hash, inline_attachments_json,
    )
    return {
        "subject": subject, "plain_body": plain_body, "html_body": html_body,
        "cv_path": cv_path, "cv_bytes": cv_bytes,
        "cv_base64": base64.b64encode(cv_bytes).decode("ascii") if cv_bytes else None,
        "cv_filename": os.path.basename(cv_path) if cv_path else None,
        "cv_hash": cv_hash, "reply_to_message_id": reply_to_message_id,
        "inbox_id": inbox_id, "fingerprint": fingerprint,
        "inline_attachments": inline_attachments, "inline_attachments_json": inline_attachments_json,
    }


def _compute_send_eligibility(entry, contact):
    """The single source of truth for 'can this be sent right now', used by
    both /prepare (informational, shown in the drawer) and /send (a
    fast-path check before the atomic claim, which remains the actual
    enforcement -- see Task 3/7). Returns (can_send: bool, reason: str|None).
    Deliberately does NOT check content/fingerprint staleness or the
    predecessor's thread id -- those are checked separately where they're
    already handled (fingerprint comparison, predecessor lookup)."""
    if contact["replied"] or contact["email_status"] == "bounced" or contact["outreach_paused_at"]:
        return False, "Contact state has changed since this was reviewed."
    from datetime import datetime
    today = datetime.utcnow().date().isoformat()
    # Email 1 is Day 0 -- whenever the human starts. Only follow-ups wait
    # for their date (job #141: a Saturday start locked Email 1 till Monday).
    if entry["sequence_num"] != 1 and (not entry["scheduled_date"] or entry["scheduled_date"] > today):
        return False, f"Not due until {entry['scheduled_date']}."
    if entry["sequence_num"] != 1:
        preceding = db.get_preceding_email(entry["contact_id"], entry["sequence_num"])
        if not preceding or preceding["status"] != "sent" or not preceding["agentmail_message_id"]:
            return False, "The preceding email isn't confirmed sent yet."
    return True, None


@app.post("/api/outreach/<int:entry_id>/prepare")
def prepare_outreach(entry_id):
    conn = db._get_conn()
    entry = conn.execute("SELECT * FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    if not entry:
        return err("Outreach entry not found", 404)
    if entry["channel"] != "email":
        return err("Only email touchpoints can be prepared", 400)
    if entry["provider"] != "agentmail":
        return err("This endpoint only prepares AgentMail-provider entries", 400)
    if entry["status"] != "draft":
        return err(f"Entry is '{entry['status']}', not 'draft' — cannot prepare", 409)
    contact = conn.execute("SELECT * FROM contacts WHERE id = ?", (entry["contact_id"],)).fetchone()
    if not contact or not contact["email"]:
        return err("Contact has no email address", 400)
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (entry["job_id"],)).fetchone()

    try:
        prepared = _prepare_agentmail_content(conn, entry, contact, job)
    except _PrepareError as exc:
        return err(exc.message, exc.status)

    can_send, cannot_send_reason = _compute_send_eligibility(entry, contact)

    return jsonify({
        "subject": prepared["subject"],
        "body": _cid_to_preview_html(prepared["html_body"], prepared["inline_attachments"]) or prepared["plain_body"],
        "cv_filename": prepared["cv_filename"],
        "fingerprint": prepared["fingerprint"],
        "from_address": prepared["inbox_id"],
        "scheduled_date": entry["scheduled_date"],
        "can_send": can_send,
        "cannot_send_reason": cannot_send_reason,
    })


@app.post("/api/outreach/<int:entry_id>/send")
def send_outreach(entry_id):
    conn = db._get_conn()
    # This is THE validated snapshot for the rest of the request. Every
    # later step -- the fingerprint, the eligibility pre-check, and
    # critically the atomic claim's expected_subject/expected_content --
    # must read from THIS object, never re-query the row. A fresh SELECT
    # issued later in the request would silently pick up whatever a
    # concurrent edit left behind and treat it as "what was validated",
    # defeating the whole point of re-checking at claim time (see Task 3).
    entry = conn.execute("SELECT * FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    if not entry:
        return err("Outreach entry not found", 404)
    if entry["provider"] != "agentmail":
        return err("This entry is not AgentMail-managed", 400)
    if entry["channel"] != "email":
        return err("Only email touchpoints can be sent", 400)
    if entry["status"] != "draft":
        return err(f"Entry is '{entry['status']}', not 'draft' — cannot send", 409)

    contact = conn.execute("SELECT * FROM contacts WHERE id = ?", (entry["contact_id"],)).fetchone()
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (entry["job_id"],)).fetchone()
    if not contact or not contact["email"]:
        return err("Contact has no email address", 400)

    try:
        prepared = _prepare_agentmail_content(conn, entry, contact, job)
    except _PrepareError as exc:
        return err(exc.message, exc.status)

    fingerprint = (request.json or {}).get("fingerprint")
    if fingerprint != prepared["fingerprint"]:
        return err("Content changed since review — reopen and review again.", 409)

    # Fast-path only, for a specific, friendly error message in the common
    # (non-racing) case -- _compute_send_eligibility is the SAME function
    # /prepare used to compute can_send, so this can never disagree with
    # what the drawer displayed. The actual enforcement is the atomic
    # claim below, which re-checks all of this itself at the moment of
    # claiming, not trusting this earlier read.
    can_send, cannot_send_reason = _compute_send_eligibility(entry, contact)
    if not can_send:
        status_code = 403 if "Not due" in cannot_send_reason else 409
        return err(cannot_send_reason, status_code)

    from datetime import datetime
    today = datetime.utcnow().date().isoformat()
    idempotency_key = str(uuid.uuid4())
    claimed = db.claim_and_record_attempt(
        entry_id, idempotency_key,
        expected_subject=entry["subject"], expected_content=entry["content"], today=today,
        endpoint="reply" if prepared["reply_to_message_id"] else "send",
        reply_to_message_id=prepared["reply_to_message_id"], recipient_email=contact["email"],
        subject=prepared["subject"], text_body=prepared["plain_body"], html_body=prepared["html_body"],
        inbox_id=prepared["inbox_id"], cv_filename=prepared["cv_filename"],
        cv_base64=prepared["cv_base64"], cv_file_hash=prepared["cv_hash"],
        inline_attachments_json=prepared["inline_attachments_json"],
    )
    if not claimed:
        # The fast-path check above passed, so reaching here means
        # something changed in the gap between that check and this atomic
        # claim -- a genuine race, not a normal rejection. Deliberately
        # generic: pinpointing exactly which condition changed would need
        # another round of queries for a case that should be rare.
        return err("Entry changed since it was reviewed — someone else edited it, it's no longer due, the contact's state changed, or it's already being sent. Reopen and review again.", 409)

    try:
        result = agentmail_client.send_email(
            idempotency_key, prepared["inbox_id"], contact["email"], prepared["subject"], prepared["plain_body"],
            html_body=prepared["html_body"], reply_to_message_id=prepared["reply_to_message_id"],
            attachment_bytes=prepared["cv_bytes"], attachment_filename=prepared["cv_filename"],
            extra_attachments=prepared["inline_attachments"],
        )
    except agentmail_client.AgentMailError as exc:
        db.record_immediate_send_failure(idempotency_key)
        return err(f"AgentMail rejected the send: {exc}", 502)
    except agentmail_client.AgentMailReplayMismatch:
        # Should be unreachable on a brand-new key with a fresh snapshot --
        # if it happens anyway, treat it exactly like an ambiguous outcome:
        # we cannot conclude failure, so stay 'uncertain', never 'failed'.
        with db._write_lock:
            conn.execute(
                "UPDATE outreach_log SET status = 'uncertain' WHERE id = ? AND send_idempotency_key = ? AND status = 'sending'",
                (entry_id, idempotency_key),
            )
            conn.commit()
        return jsonify({"status": "uncertain"}), 202
    except agentmail_client.AgentMailAmbiguous:
        with db._write_lock:
            conn.execute(
                "UPDATE outreach_log SET status = 'uncertain' WHERE id = ? AND send_idempotency_key = ? AND status = 'sending'",
                (entry_id, idempotency_key),
            )
            conn.commit()
        return jsonify({"status": "uncertain"}), 202

    db.resolve_send_attempt(idempotency_key, "sent", result["message_id"], result["thread_id"])
    updated = conn.execute("SELECT * FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    return jsonify({"status": "sent", "entry": dict(updated)})


@app.post("/api/outreach/<int:entry_id>/check-status")
def check_outreach_status(entry_id):
    conn = db._get_conn()
    entry = conn.execute("SELECT * FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    if not entry:
        return err("Outreach entry not found", 404)
    if entry["status"] in ("sent", "failed"):
        return jsonify({"status": entry["status"]})
    if entry["status"] not in ("sending", "uncertain"):
        return err(f"Entry is '{entry['status']}' — nothing to check", 409)

    attempt = db.get_send_attempt(entry["send_idempotency_key"])
    if not attempt:
        return err("No recorded send attempt for this entry", 500)
    if attempt["resolved_status"]:
        # Already resolved (e.g. by a concurrent check-status) but
        # outreach_log hadn't reflected it yet -- surface the attempt's own
        # answer without a network call.
        db.resolve_send_attempt(attempt["idempotency_key"], attempt["resolved_status"],
                                  attempt["agentmail_message_id"], attempt["agentmail_thread_id"])
        return jsonify({"status": attempt["resolved_status"]})

    from datetime import datetime, timedelta
    attempt_age = datetime.utcnow() - datetime.fromisoformat(entry["send_attempt_at"])
    if attempt_age > timedelta(hours=24):
        return jsonify({
            "status": "uncertain",
            "message": "This attempt is more than 24 hours old — AgentMail's idempotency key has expired, so it can no longer be safely re-checked. Manual investigation required.",
        })

    # A replay can itself SEND a brand-new email if the original request
    # never reached AgentMail at all (no prior record of this key means no
    # dedup). Re-validate the contact hasn't replied/bounced since the
    # original attempt before risking that -- this is the one case where
    # "just checking" is not actually side-effect-free.
    contact = conn.execute("SELECT * FROM contacts WHERE id = ?", (entry["contact_id"],)).fetchone()
    if contact and (contact["replied"] or contact["email_status"] == "bounced" or contact["outreach_paused_at"]):
        return jsonify({
            "status": "uncertain",
            "message": "Contact has replied, bounced, or been explicitly paused (skipped, or a confirmed cross-contact cancellation) since this attempt — refusing to check automatically, since checking can itself send a new email if the original never reached AgentMail. Resolve manually.",
        })

    cv_bytes = base64.b64decode(attempt["cv_base64"]) if attempt["cv_base64"] else None
    inline_attachments = json.loads(attempt["inline_attachments_json"]) if attempt["inline_attachments_json"] else None
    try:
        result = agentmail_client.send_email(
            attempt["idempotency_key"], attempt["inbox_id"], attempt["recipient_email"],
            attempt["subject"], attempt["text_body"], html_body=attempt["html_body"],
            reply_to_message_id=attempt["reply_to_message_id"],
            attachment_bytes=cv_bytes, attachment_filename=attempt["cv_filename"],
            extra_attachments=inline_attachments,
        )
    except agentmail_client.AgentMailReplayMismatch:
        # 409: AgentMail says this doesn't match the original request. This
        # should be unreachable if the snapshot is byte-identical (Task 7) --
        # if it happens anyway, we cannot conclude failure, since the
        # original attempt may have actually succeeded. Stays 'uncertain'
        # forever via this path; only manual investigation or (once built)
        # the inbound webhook sub-project can settle it. NEVER resolves to
        # 'failed' here, which would wrongly make it Retry-eligible.
        with db._write_lock:
            conn.execute(
                "UPDATE outreach_log SET status = 'uncertain' WHERE id = ? AND send_idempotency_key = ? AND status = 'sending'",
                (entry_id, attempt["idempotency_key"]),
            )
            conn.commit()
        return jsonify({
            "status": "uncertain",
            "message": "AgentMail reports this replay doesn't match the original attempt — cannot safely conclude the outcome. Leaving unresolved; investigate manually.",
        })
    except agentmail_client.AgentMailError as exc:
        # Unlike the ORIGINAL /send attempt (a brand-new idempotency key,
        # where this same exception means nothing was sent), an error on a
        # REPLAY proves nothing about whether the original attempt
        # actually went through -- it only proves THIS call failed, for
        # reasons that may be entirely unrelated to history (expired
        # credentials, a transient auth hiccup, rate limiting). Resolving
        # to 'failed' here would make the row Retry-eligible and risk a
        # genuine duplicate send. Stays 'uncertain' -- same posture as
        # AgentMailReplayMismatch and AgentMailAmbiguous below. See Task 8's
        # "Correction from review" note for the full reasoning.
        with db._write_lock:
            conn.execute(
                "UPDATE outreach_log SET status = 'uncertain' WHERE id = ? AND send_idempotency_key = ? AND status = 'sending'",
                (entry_id, attempt["idempotency_key"]),
            )
            conn.commit()
        return jsonify({
            "status": "uncertain",
            "message": f"Re-check failed ({exc}) — this does not prove the original send failed, so the attempt stays unresolved. Try again later, or investigate manually.",
        })
    except agentmail_client.AgentMailAmbiguous:
        with db._write_lock:
            conn.execute(
                "UPDATE outreach_log SET status = 'uncertain' WHERE id = ? AND send_idempotency_key = ? AND status = 'sending'",
                (entry_id, attempt["idempotency_key"]),
            )
            conn.commit()
        return jsonify({"status": "uncertain"})

    db.resolve_send_attempt(attempt["idempotency_key"], "sent", result["message_id"], result["thread_id"])
    return jsonify({"status": "sent"})


@app.post("/api/outreach/<int:entry_id>/retry")
def retry_outreach(entry_id):
    updated = db.retry_failed_touchpoint(entry_id)
    if not updated:
        return err("Entry not found or not in 'failed' status", 409)
    return jsonify(updated)


@app.post("/api/outreach/batch-draft")
def batch_draft():
    ids = (request.json or {}).get("ids", [])
    if not ids:
        return err("ids list is required")
    created, errors = 0, []
    conn = db._get_conn()
    for eid in ids:
        entry = conn.execute("SELECT * FROM outreach_log WHERE id = ?", (eid,)).fetchone()
        if not entry:
            errors.append({"id": eid, "error": "not found"})
            continue
        if entry["provider"] == "agentmail":
            errors.append({"id": eid, "error": "Gmail drafts cannot be created for AgentMail-managed entries"})
            continue
        if entry["channel"] != "email":
            app.logger.info("Skipping non-email outreach entry %s during Gmail batch draft", eid)
            continue
        contact = conn.execute("SELECT * FROM contacts WHERE id = ?", (entry["contact_id"],)).fetchone()
        if not contact or not contact["email"]:
            errors.append({"id": eid, "error": "Contact has no email address"})
            continue
        job = conn.execute("SELECT * FROM jobs WHERE id = ?", (entry["job_id"],)).fetchone()
        geo = (job["geography"] or "eu") if job else "eu"
        attachment_path = _find_cv_pdf(dict(job)) if job and entry["sequence_num"] == 1 else None

        subject, content = entry["subject"] or "", entry["content"] or ""
        if _PLACEHOLDER_RE.search(f"{subject}\n{content}"):
            try:
                subject, content = _llm_redraft(
                    entry, contact, job,
                    feedback="Replace every literal placeholder bracket (e.g. [First Name]) with the real value — never output a literal bracket placeholder.",
                )
            except Exception as exc:
                errors.append({"id": eid, "error": "Automatic placeholder fix failed: " + str(exc)})
                continue
            if _PLACEHOLDER_RE.search(f"{subject}\n{content}"):
                errors.append({"id": eid, "error": f"Outreach content for entry {eid} still contains a placeholder after an automatic fix attempt — redraft manually."})
                continue
            db.update_outreach_entry(eid, subject=subject, content=content)

        body = gmail_client.strip_signature(content)
        thread_id, reply_to_message_id = _get_thread_params(conn, entry)
        try:
            draft_id = gmail_client.create_draft(
                to_email=contact["email"],
                subject=subject,
                body=body,
                thread_id=thread_id,
                reply_to_message_id=reply_to_message_id,
                geo=geo,
                attachment_path=attachment_path,
            )
        except FileNotFoundError:
            errors.append({"id": eid, "error": "Gmail credentials not configured"})
            continue
        except RuntimeError as exc:
            errors.append({"id": eid, "error": f"Gmail API error: {str(exc)}"})
            continue
        thread_info = gmail_client.get_draft_thread_info(draft_id)
        update_fields = {"status": "gmail_draft", "gmail_draft_id": draft_id}
        if thread_info:
            update_fields["gmail_thread_id"] = thread_info["thread_id"]
            update_fields["gmail_message_id"] = thread_info["message_id"]
        db.update_outreach_entry(eid, **update_fields)
        created += 1
    return jsonify({"created": created, "errors": errors})


@app.post("/api/outreach/<int:entry_id>/skip")
def skip_outreach(entry_id):
    conn = db._get_conn()
    entry = conn.execute("SELECT * FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    if not entry:
        return err("Outreach entry not found", 404)
    if entry["provider"] == "agentmail":
        with db._write_lock:
            cur = conn.execute(
                "UPDATE outreach_log SET status = 'skipped' WHERE id = ? AND status = 'draft'",
                (entry_id,),
            )
            conn.commit()
        if cur.rowcount == 0:
            return err(f"Entry is '{entry['status']}' — cannot skip a row that may already be in flight or sent", 409)
    else:
        db.update_outreach_entry(entry_id, status="skipped")
    return jsonify({"status": "skipped"})


@app.post("/api/outreach/<int:entry_id>/sent")
def mark_sent(entry_id):
    from datetime import datetime
    conn = db._get_conn()
    entry = conn.execute("SELECT * FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    if not entry:
        return err("Outreach entry not found", 404)
    is_connect = entry["channel"] == "linkedin_connect"
    # LinkedIn connection requests are sent by hand on linkedin.com whatever
    # the row's provider label says; every other AgentMail row can only be
    # marked sent by /send or /check-status (Rule 30).
    if entry["provider"] == "agentmail" and not is_connect:
        return err("AgentMail-managed entries can only be marked sent by /send or /check-status", 409)
    if entry["status"] == "sent":
        # Repeat confirmation is harmless and keeps the original timestamp.
        return jsonify({"status": "sent", "sent_at": entry["sent_at"]})
    allowed = ("draft",) if is_connect else ("draft", "gmail_draft")
    if entry["status"] not in allowed:
        return err(f"Entry is '{entry['status']}' — cannot mark sent", 409)
    with db._write_lock:
        # Conditional on the status just checked, so a concurrent
        # confirm/skip can't be overwritten.
        conn.execute(
            f"UPDATE outreach_log SET status = 'sent', sent_at = ? "
            f"WHERE id = ? AND status IN ({','.join('?' * len(allowed))})",
            (datetime.utcnow().isoformat(), entry_id, *allowed),
        )
        conn.commit()
    row = conn.execute("SELECT status, sent_at FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    if row["status"] != "sent":
        return err(f"Entry is '{row['status']}' — cannot mark sent", 409)
    return jsonify({"status": "sent", "sent_at": row["sent_at"]})


@app.post("/api/outreach/<int:touchpoint_id>/hermes-sent")
def hermes_mark_sent(touchpoint_id):
    if not _check_saved_jobs_webhook_secret():
        return err("Unauthorized", 401)

    from datetime import datetime
    data = request.json or {}
    gmail_message_id = data.get("gmail_message_id")
    if not gmail_message_id:
        return err("gmail_message_id is required", 400)

    conn = db._get_conn()
    entry = conn.execute("SELECT * FROM outreach_log WHERE id = ?", (touchpoint_id,)).fetchone()
    if not entry:
        return err("Outreach entry not found", 404)
    if entry["provider"] == "agentmail":
        return err("AgentMail-managed entries can only be marked sent by /send or /check-status", 409)

    updated = db.update_outreach_entry(
        touchpoint_id,
        status="sent",
        sent_at=datetime.utcnow().isoformat(),
        gmail_message_id=gmail_message_id,
        gmail_thread_id=data.get("gmail_thread_id"),
        brief_sent_date=None,
        brief_position=None,
    )
    if not updated:
        return err("Outreach entry not found", 404)
    return jsonify({"status": "sent", "sent_at": updated["sent_at"]})


@app.get("/api/followups/due")
def followups_due():
    if not _check_saved_jobs_webhook_secret():
        return err("Unauthorized", 401)
    from datetime import datetime
    today = datetime.utcnow().strftime("%Y-%m-%d")
    items = db.get_and_assign_followup_brief(today)
    followups = [
        {
            "touchpoint_id": item["id"],
            "position": item["position"],
            "contact_name": item["contact_name"],
            "company": item["company"],
            "role": item["role"],
            "subject": item["subject"],
            "content": item["content"],
            "gmail_thread_id": item["gmail_thread_id"],
        }
        for item in items
    ]
    return jsonify({"date": today, "followups": followups})


@app.get("/api/followups/resolve")
def followups_resolve():
    if not _check_saved_jobs_webhook_secret():
        return err("Unauthorized", 401)
    date = request.args.get("date", "")
    positions_param = request.args.get("positions", "")
    if not date or not positions_param:
        return err("date and positions are required", 400)
    try:
        positions = [int(p) for p in positions_param.split(",") if p.strip()]
    except ValueError:
        return err("positions must be a comma-separated list of integers", 400)
    if not positions:
        return err("positions must be a comma-separated list of integers", 400)

    items = db.get_followup_brief_items(date, positions)
    followups = [
        {
            "touchpoint_id": item["id"],
            "position": item["brief_position"],
            "contact_name": item["contact_name"],
            "company": item["company"],
            "role": item["role"],
            "subject": item["subject"],
            "content": item["content"],
            "gmail_thread_id": item["gmail_thread_id"],
        }
        for item in items
    ]
    return jsonify({"date": date, "followups": followups})


@app.patch("/api/outreach/<int:entry_id>")
def edit_outreach(entry_id):
    conn = db._get_conn()
    entry = conn.execute("SELECT * FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    if not entry:
        return err("Outreach entry not found", 404)
    data = request.json or {}
    kwargs = {k: v for k, v in data.items() if k in ("subject", "content")}
    if not kwargs:
        return err("Only subject and content are editable")
    if entry["provider"] == "agentmail":
        cols = ", ".join(f"{k} = ?" for k in kwargs)
        with db._write_lock:
            cur = conn.execute(
                f"UPDATE outreach_log SET {cols} WHERE id = ? AND status = 'draft'",
                (*kwargs.values(), entry_id),
            )
            conn.commit()
        if cur.rowcount == 0:
            return err(f"Entry is '{entry['status']}' — cannot edit", 409)
        updated = dict(conn.execute("SELECT * FROM outreach_log WHERE id = ?", (entry_id,)).fetchone())
    else:
        updated = db.update_outreach_entry(entry_id, **kwargs)
    return jsonify(updated)


_PLACEHOLDER_RE = re.compile(r"\[(First Name|Full Name|Name|Title|Company)\]")


def _llm_redraft(entry, contact, job, feedback: str) -> tuple[str, str]:
    """Returns (new_subject, new_body). Raises on LLM/API failure — callers
    translate the exception to their own error response."""
    knowledge_files = ["career-master.md", "employment-master.md", "education-master.md", "skills-master.md", "identity.md"]
    knowledge_base = "\n\n".join((paths.knowledge_dir() / f).read_text(encoding="utf-8") for f in knowledge_files)
    skill_content = paths.skill("outreach-drafter").read_text(encoding="utf-8")

    jd_text = job["jd_text"] or ""
    user_feedback = feedback or "Please improve the tone and make it more personalized."
    user_msg = (
        "You are redrafting a specific outreach email. Do NOT generate a full CONTACT section — just return the improved email body.\n\n"
        f"JOB CONTEXT:\nCompany: {job['company']}\nRole: {job['role']}\n"
        f"Job Description: {jd_text[:2000] if jd_text else 'Not available'}\n\n"
        f"CONTACT:\nName: {contact['name']}\nTitle: {contact['title'] or 'Unknown'}\nCompany: {contact['company'] or job['company']}\n\n"
        f"EXISTING EMAIL (sequence {entry['sequence_num']}):\nSubject: {entry['subject'] or ''}\n{entry['content'] or ''}\n\n"
        f"USER FEEDBACK: {user_feedback}\n\n"
        "Return ONLY the improved email in this exact format:\nSubject: [subject line here]\n[email body here — no other headers or labels]"
    )

    response_text = (llm_client.call_llm(
        skill_content + "\n\n" + knowledge_base, user_msg, max_tokens=1000, timeout=120,
    ) or "").strip()

    new_subject = entry["subject"] or ""
    new_body = response_text
    lines = response_text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("subject:"):
            new_subject = line.strip()[len("Subject:"):].strip()
            new_body = "\n".join(lines[i + 1:]).strip()
            break
    return new_subject, new_body


@app.post("/api/outreach/<int:entry_id>/redraft")
def redraft_outreach(entry_id):
    conn = db._get_conn()
    entry = conn.execute("SELECT * FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    if not entry:
        return err("Outreach entry not found", 404)
    if entry["channel"] != "email":
        return err("Redraft is only available for email outreach", 400)
    if entry["provider"] == "agentmail" and entry["status"] != "draft":
        # Cheap, non-authoritative pre-check -- skip the slow LLM call
        # entirely when the row obviously isn't draft. The conditional
        # UPDATE below (not this check) is what actually enforces
        # correctness, since the row can still change in the gap while
        # the LLM call runs.
        return err(f"Entry is '{entry['status']}' — cannot redraft", 409)
    contact = conn.execute("SELECT * FROM contacts WHERE id = ?", (entry["contact_id"],)).fetchone()
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (entry["job_id"],)).fetchone()
    if not contact:
        return err("Contact not found", 404)
    if not job:
        return err("Job not found", 404)

    feedback = ((request.json or {}).get("feedback") or "").strip()

    try:
        knowledge_files = ["career-master.md", "employment-master.md", "education-master.md", "skills-master.md", "identity.md"]
        for f in knowledge_files:
            (paths.knowledge_dir() / f).read_text(encoding="utf-8")
        paths.skill("outreach-drafter").read_text(encoding="utf-8")
    except OSError as exc:
        return err(f"Failed to load redraft context: {exc}", 500)

    try:
        new_subject, new_body = _llm_redraft(entry, contact, job, feedback)
    except Exception as exc:
        return err("LLM redraft failed: " + str(exc), 502)

    if entry["provider"] == "agentmail":
        # Same two-part guard as _prepare_agentmail_content's placeholder
        # fix (Task 6) and for the identical reason: status='draft' alone
        # doesn't rule out a concurrent edit landing while this LLM call
        # was in flight, since that edit (also guarded to status='draft')
        # never changes status itself. Tying the write to entry["subject"]/
        # entry["content"] -- the exact pre-redraft snapshot this redraft
        # was computed from -- closes that gap instead of silently
        # clobbering whatever the concurrent edit left behind.
        with db._write_lock:
            cur = conn.execute(
                "UPDATE outreach_log SET subject = ?, content = ? "
                "WHERE id = ? AND status = 'draft' AND subject = ? AND content = ?",
                (new_subject, new_body, entry_id, entry["subject"], entry["content"]),
            )
            conn.commit()
        if cur.rowcount == 0:
            return err("Entry changed while redrafting — reopen and review again", 409)
        updated = dict(conn.execute("SELECT * FROM outreach_log WHERE id = ?", (entry_id,)).fetchone())
    else:
        try:
            updated = db.update_outreach_entry(entry_id, subject=new_subject, content=new_body)
        except Exception as exc:
            return err("Failed to save redrafted content: " + str(exc), 500)
    return jsonify(updated)


# ── DEDUP ─────────────────────────────────────────────────────────────────────

@app.post("/api/dedup/check")
def dedup_check():
    email = (request.json or {}).get("email", "").strip()
    if not email:
        return err("email is required")
    result = db.check_email_dedup(email, job_id=-1)
    if result is None:
        return jsonify({"duplicate": False})
    return jsonify(result)


# ── STATS ─────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
def stats():
    return jsonify(db.get_stats())


@app.get("/api/stats/funnel")
def funnel():
    s = db.get_stats()
    by_status = s["by_status"]
    stages = ["cv_ready", "applied", "sent", "reply", "interview", "offer"]
    result = []
    prev_count = None
    for stage in stages:
        count = by_status.get(stage, 0)
        conversion = round(count / prev_count, 2) if prev_count else None
        result.append({"name": stage, "count": count, "conversion_from_previous": conversion})
        prev_count = count or None
    return jsonify({"stages": result})


@app.get("/api/stats/geo/<geo>")
def geo_stats(geo):
    jobs = db.get_jobs(geo=geo)
    by_status = {}
    scores = []
    job_ids = [j["id"] for j in jobs]
    for j in jobs:
        by_status[j["status"]] = by_status.get(j["status"], 0) + 1
        if j.get("ats_score"):
            scores.append(j["ats_score"])
    sent_count = 0
    replied_jobs = 0
    if job_ids:
        conn = db._get_conn()
        placeholders = ",".join("?" * len(job_ids))
        sent_count = conn.execute(
            f"""SELECT COUNT(DISTINCT job_id) FROM outreach_log
                WHERE channel = 'email' AND status IN ('gmail_draft', 'sent')
                  AND job_id IN ({placeholders})""",
            job_ids,
        ).fetchone()[0]
        replied_jobs = conn.execute(
            f"""SELECT COUNT(DISTINCT c.job_id) FROM contacts c
                WHERE c.replied = 1 AND c.job_id IN ({placeholders})
                  AND c.job_id IN (
                      SELECT job_id FROM outreach_log
                      WHERE channel = 'email' AND status IN ('gmail_draft', 'sent')
                  )""",
            job_ids,
        ).fetchone()[0]
    return jsonify({
        "total": len(jobs),
        "by_status": by_status,
        "avg_ats_score": round(sum(scores) / len(scores), 1) if scores else None,
        "response_rate": round(replied_jobs / sent_count, 2) if sent_count else 0.0,
    })


# ── COMPANY PROFILES ───────────────────────────────────────────────────────────

def _check_webhook_secret():
    secret = os.getenv("WEBHOOK_SECRET")
    header = request.headers.get("X-Webhook-Secret")
    if not secret or not header:
        return False
    return secrets.compare_digest(header, secret)


@app.get("/api/company-profiles/pending")
def pending_company_profiles():
    if not _check_webhook_secret():
        return err("Unauthorized", 401)
    return jsonify({"companies": db.get_pending_company_profiles()})


@app.post("/api/company-profiles/<path:company>")
def deliver_company_profile(company):
    if not _check_webhook_secret():
        return err("Unauthorized", 401)
    data = request.json or {}
    fields = {k: v for k, v in data.items() if k in db._VALID_COMPANY_PROFILE_COLS}
    try:
        profile = db.save_company_profile(company, **fields)
    except ValueError as e:
        return err(str(e), 400)
    return jsonify(profile)


# ── SAVED JOBS QUEUE ────────────────────────────────────────────────────────

def _check_saved_jobs_webhook_secret():
    secret = os.getenv("SAVED_JOBS_WEBHOOK_SECRET")
    header = request.headers.get("X-Webhook-Secret")
    if not secret or not header:
        return False
    return secrets.compare_digest(header, secret)


@app.post("/api/saved-jobs/ingest")
def ingest_saved_job():
    if not _check_saved_jobs_webhook_secret():
        return err("Unauthorized", 401)
    data = request.json or {}
    url = data.get("url", "")
    source_type = data.get("source_type")
    if source_type not in ("company", "recruiter"):
        return err("source_type must be 'company' or 'recruiter'", 400)
    match = re.search(r"/jobs/view/(\d+)", url)
    if not match:
        return err("not a linkedin job url", 400)
    linkedin_job_id = match.group(1)
    result = db.queue_saved_job(url, linkedin_job_id, source_type)
    if result == "duplicate":
        return jsonify({"status": "duplicate"}), 200
    return jsonify({"status": "queued"}), 202


@app.get("/api/saved-jobs/needs-contacts")
def saved_jobs_needing_contacts():
    if not _check_saved_jobs_webhook_secret():
        return err("Unauthorized", 401)
    return jsonify({"jobs": db.get_jobs_needing_contacts()})


_VALID_DISCOVERED_CONTACT_TYPES = {"hiring_manager", "recruiter", "agency", "executive", "peer"}


def _normalize_linkedin_url(url):
    """Strip protocol/subdomain/trailing-slash/query so profile URLs compare
    equal regardless of regional subdomain (in./www.) or tracking params."""
    if not url:
        return None
    match = re.search(r"linkedin\.com/(.*?)(?:\?|$)", url.lower())
    path = match.group(1) if match else url.lower()
    return path.rstrip("/")


@app.get("/api/saved-jobs/contact-lookup")
def saved_jobs_contact_lookup():
    if not _check_saved_jobs_webhook_secret():
        return err("Unauthorized", 401)
    linkedin_url = request.args.get("linkedin_url", "")
    if not linkedin_url:
        return err("linkedin_url is required", 400)

    normalized = _normalize_linkedin_url(linkedin_url)
    existing_urls = {_normalize_linkedin_url(u) for u in db.get_all_contact_linkedin_urls()}
    if normalized in existing_urls:
        return jsonify({"already_exists": True, "email": None})

    match = fullenrich_client.match_by_linkedin(linkedin_url)
    email = match.get("email") if match else None
    if email and email in db.get_all_contact_emails():
        return jsonify({"already_exists": True, "email": None})

    return jsonify({"already_exists": False, "email": email})


@app.post("/api/jobs/<int:job_id>/discovered-contacts")
def deliver_discovered_contacts(job_id):
    if not _check_saved_jobs_webhook_secret():
        return err("Unauthorized", 401)
    job = db.get_job(job_id)
    if not job:
        return err("Job not found", 404)
    data = request.json or {}
    candidates = data.get("candidates", [])
    if not isinstance(candidates, list):
        return err("candidates must be a list", 400)
    existing_urls = {_normalize_linkedin_url(u) for u in db.get_all_contact_linkedin_urls()}
    existing_emails = db.get_all_contact_emails()
    added, skipped = 0, 0
    for cand in candidates:
        contact_type = cand.get("contact_type")
        linkedin_url = cand.get("linkedin_url")
        if contact_type not in _VALID_DISCOVERED_CONTACT_TYPES or not linkedin_url:
            skipped += 1
            continue
        if _normalize_linkedin_url(linkedin_url) in existing_urls:
            skipped += 1
            continue

        candidate_email = cand.get("email")
        apollo_id = None
        if candidate_email:
            email = candidate_email
        else:
            match = fullenrich_client.match_by_linkedin(linkedin_url)
            email = match.get("email") if match else None
            apollo_id = match.get("apollo_id") if match else None

        if email and email in existing_emails:
            skipped += 1
            continue

        db.create_contact(
            job_id,
            name=cand.get("name", ""),
            contact_type=contact_type,
            title=cand.get("title"),
            email=email,
            linkedin_url=linkedin_url,
            source="hermes_discovered",
            apollo_id=apollo_id,
        )
        existing_urls.add(_normalize_linkedin_url(linkedin_url))
        if email:
            existing_emails.add(email)
        added += 1
    db.update_job(job_id, contacts_discovery_status="complete")
    return jsonify({"added": added, "skipped": skipped})


@app.get("/api/jobs/<int:job_id>/company-profile")
def job_company_profile(job_id):
    job = db.get_job(job_id)
    if not job:
        return err("Job not found", 404)
    company = job.get("company")
    if not company or company == "Pending":
        return err("Job company not yet resolved", 400)
    profile = db.get_company_profile(company)
    if not profile:
        return jsonify({"profile_status": "not_found", "company": company})
    return jsonify(profile)


# ── SALARY ESTIMATOR ───────────────────────────────────────────────────────────

def _format_company_profile_for_prompt(profile):
    if not profile or profile.get("profile_status") != "complete":
        return ""
    fields = ["sector", "company_size", "funding_stage", "tech_stack", "geography",
              "recent_news", "competitors", "hiring_for",
              "mission_values_culture", "employer_rating"]
    lines = [f"{f.replace('_', ' ').title()}: {profile[f]}" for f in fields if profile.get(f)]
    return "\n".join(lines)


def _search_firecrawl_salary(company, role, geo):
    api_key = os.getenv("FIRECRAWL_API_KEY")
    if not api_key:
        return ""
    source = {"gcc": "Bayt", "india": "AmbitionBox"}.get(geo, "Glassdoor")
    geo_term = {"gcc": "UAE", "india": "India", "eu": "Europe"}.get(geo, "")
    query = f"{source} {company} {role} salary {geo_term}".strip()
    try:
        resp = requests.post(
            "https://api.firecrawl.dev/v1/search",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"query": query, "limit": 5},
            timeout=20,
        )
        resp.raise_for_status()
        results = resp.json().get("data", [])
    except Exception as exc:
        logger.warning("Firecrawl salary search failed for query %r: %s", query, exc)
        return ""
    lines = [
        f"{r.get('title', '')}: {r.get('description', '')}"
        for r in results if r.get("description")
    ]
    return "\n".join(lines)[:2000]


@app.get("/api/jobs/<int:job_id>/salary-estimate")
def salary_estimate(job_id):
    job = db.get_job(job_id)
    if not job:
        return err("Job not found", 404)

    force_refresh = request.args.get("refresh") == "true"
    cached = (job.get("salary_estimate") or "").strip()
    if cached and not force_refresh:
        return jsonify({"estimate": cached, "cached": True})

    if not job.get("role") or job.get("role") == "Pending":
        return err("Job must be fully generated before estimating salary", 400)

    try:
        knowledge_files = ["career-master.md", "employment-master.md"]
        knowledge_base = "\n\n".join(
            (paths.knowledge_dir() / f).read_text(encoding="utf-8") for f in knowledge_files
        )
    except OSError as exc:
        return err(f"Failed to load knowledge base: {exc}", 500)

    geo = job.get("geography") or "gcc"
    geo_label = {"gcc": "GCC / UAE (Dubai)", "india": "India", "eu": "Europe"}.get(geo, geo)
    ats = job.get("ats_score")
    profile_note = f"ATS score for this application: {ats}/50." if ats else ""

    company_profile = db.get_company_profile(job.get("company") or "")
    company_context = _format_company_profile_for_prompt(company_profile)
    company_block = (
        f"\n\nCOMPANY PROFILE (verified research):\n{company_context}"
        if company_context else ""
    )
    salary_research = _search_firecrawl_salary(job.get("company") or "", job["role"], geo)
    salary_research_block = (
        f"\n\nSALARY RESEARCH (Glassdoor/Bayt/AmbitionBox, live search results):\n{salary_research}\n"
        if salary_research else ""
    )

    prompt = (
        f"You are a compensation advisor helping a senior candidate negotiate salary.\n\n"
        f"ROLE: {job['role']}\n"
        f"COMPANY: {job.get('company', 'Unknown')}\n"
        f"GEOGRAPHY: {geo_label}\n"
        f"{profile_note}"
        f"{company_block}"
        f"{salary_research_block}\n"
        f"CANDIDATE PROFILE:\n{knowledge_base[:4000]}\n\n"
        f"Based on the role, company, geography, candidate profile, company profile, and live salary research (if provided) above, provide:\n"
        f"1. **Market range** — the typical total compensation range for this role and location (prioritize the live salary research above when present; otherwise use your knowledge of 2024-2025 compensation data, adjusted for company size/funding stage if given). Format as: Base: X-Y {{currency}} | Total: X-Y {{currency}}\n"
        f"2. **Recommended quote** — what this specific candidate should quote given their profile strength. Give a single number or tight range, not a wide band.\n"
        f"3. **Reasoning** — 3-4 bullet points explaining the recommendation (leverage points: co-founder background, specific metrics, ATS fit, geo premium/discount, company funding stage if known).\n"
        f"4. **Negotiation notes** — one paragraph on when and how to bring up compensation for this role type.\n\n"
        f"Currency: use the most common currency for {geo_label} compensation. Be specific and concrete — no hedging phrases like 'it depends'."
    )

    try:
        estimate = (llm_client.call_llm("", prompt, max_tokens=800, timeout=120) or "").strip()
    except Exception as exc:
        return err("LLM salary estimate failed: " + str(exc), 502)

    try:
        db.update_job(job_id, salary_estimate=estimate)
    except Exception:
        pass

    return jsonify({"estimate": estimate, "cached": False})


# ── JOB SOURCING (Shortlist) ──────────────────────────────────────────────────

_SOURCED_STATUSES = {"new", "approved", "passed", "filtered", "expired"}


# ponytail: per-process memory of what this API process already dispatched.
# A restart forgets it, which is exactly when startup recovery takes over.
_dispatched_jobs = set()
_dispatch_lock = threading.Lock()


def _dispatch_generation(job):
    """At most once per job per process. Returns False if the thread could not
    be started; the job stays 'new' and Approve-again (or startup recovery)
    retries it -- same job id, never a new job."""
    with _dispatch_lock:
        if job["id"] in _dispatched_jobs:
            return True
        _dispatched_jobs.add(job["id"])
    try:
        run_pipeline_async(
            job["id"], jd_url=job["jd_url"], geo=job["geography"],
            source_type=job["source_type"], db_update_fn=db.update_job,
        )
        return True
    except Exception:
        logger.exception(f"[SOURCING] dispatch for job {job['id']} failed")
        with _dispatch_lock:
            _dispatched_jobs.discard(job["id"])
        return False


@app.get("/api/sourced-jobs")
def list_sourced_jobs():
    statuses = [s for s in (request.args.get("status") or "new").split(",") if s]
    if not statuses or set(statuses) - _SOURCED_STATUSES:
        return err("status must be a comma list of: " + ", ".join(sorted(_SOURCED_STATUSES)))
    geo = request.args.get("geo") or None
    if geo not in (None, "gcc", "eu"):
        return err("geo must be gcc or eu")
    return jsonify(db.get_sourced_jobs(statuses, geo))


@app.get("/api/sourced-jobs/runs/latest")
def latest_sourcing_run():
    return jsonify(db.get_latest_sourcing_run())


@app.post("/api/sourced-jobs/<int:sourced_id>/approve")
def approve_sourced_job(sourced_id):
    try:
        result = db.approve_sourced_job(sourced_id)
    except LookupError:
        return err("Sourced job not found", 404)
    except ValueError as exc:
        return err(str(exc), 409)
    except Exception as exc:
        logger.exception(f"[SOURCING] approve {sourced_id} failed")
        return err(f"Approve failed: {exc}", 500)
    # First approve dispatches; a repeat approve re-dispatches only an owned job
    # still waiting at new/generating that this process hasn't dispatched (the
    # live retry path after a dispatch failure -- no restart needed).
    pending = next((j for j in db.get_sourced_jobs_needing_recovery() if j["id"] == result["job_id"]), None)
    dispatched = _dispatch_generation(pending) if pending else True
    return jsonify({**result, "dispatch_failed": not dispatched})


@app.post("/api/sourced-jobs/<int:sourced_id>/pass")
def pass_sourced_job(sourced_id):
    reason = (request.json or {}).get("reason") if request.is_json else None
    if reason is not None and reason not in db.SOURCED_PASS_REASONS:
        return err("reason must be one of: " + ", ".join(sorted(db.SOURCED_PASS_REASONS)))
    if not db.pass_sourced_job(sourced_id, reason):
        return err("Only a new posting can be passed", 409)
    return jsonify({"ok": True})


def recover_sourced_generations():
    """Re-dispatch Shortlist-created jobs whose generation never finished
    (waiting for a slot, or killed by the restart). Same job id, never a new
    job; scoped to owns_job=1 so the saved-jobs drain's jobs are untouched."""
    jobs = [j for j in db.get_sourced_jobs_needing_recovery() if _dispatch_generation(j)]
    if jobs:
        logger.info(f"[SOURCING] recovered {len(jobs)} generation(s): {[j['id'] for j in jobs]}")
    return len(jobs)


if __name__ == "__main__":
    try:
        recover_sourced_generations()
    except Exception:   # best-effort; must never crash-loop the API
        logger.exception("[SOURCING] startup recovery failed")
    port = int(os.getenv("WEBHOOK_PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
