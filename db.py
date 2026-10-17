import json
import os
import sqlite3
import threading
from datetime import date, datetime

DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "pipeline.db"))

VALID_TRANSITIONS = {
    "new":        ["generating"],
    "generating": ["cv_ready", "failed"],
    "cv_ready":   ["applied"],
    "applied":    ["sent"],
    "sent":       ["reply"],
    "reply":      ["interview"],
    "interview":  ["offer"],
    # rejected/withdrawn/failed are terminal — no outgoing transitions.
    # rejected/withdrawn are reachable from any ACTIVE_STATUS (see update_job) —
    # not listed per-status here since real rejections happen at any stage,
    # not just after an interview.
}
ACTIVE_STATUSES = {"new", "generating", "cv_ready", "applied", "sent", "reply", "interview", "offer"}

_VALID_JOB_COLS = {
    "company", "role", "geography", "source_type", "recruiter_agency",
    "jd_url", "jd_text", "status", "ats_score", "cv_path", "cover_letter",
    "outreach_raw", "notes", "salary_estimate", "updated_at", "applied_at",
    "ats_parse_warning", "contacts_discovery_status",
}
_VALID_CONTACT_COLS = {
    "name", "title", "company", "email", "linkedin_url", "contact_type",
    "source", "apollo_id", "enrichment_status", "outreach_sent", "replied",
    "email_status", "outreach_paused_at",
}
_VALID_OUTREACH_COLS = {
    "status", "scheduled_date", "sent_at", "subject", "content",
    "gmail_draft_id", "gmail_message_id", "gmail_thread_id",
    "brief_sent_date", "brief_position",
    "provider", "agentmail_message_id", "agentmail_thread_id",
    "send_idempotency_key", "send_attempt_at", "uncertain_dismissed_at",
}

_conn = None
# Guards every multi-statement transaction below against the shared connection
# (_get_conn()) having its rollback()/commit() apply to the connection as a
# whole rather than to "whichever call started it" -- without this, two
# concurrent calls can interleave and one's rollback silently erases the
# other's uncommitted claim (see claim_and_record_attempt's docstring and
# SPRINT_LOG.md's AgentMail review entry for the reproduced duplicate-send).
_write_lock = threading.Lock()


def _get_conn():
    # One shared connection, reused across requests. db.claim_and_record_attempt's
    # atomic claim (the Review-and-Send feature's whole duplicate-send guarantee --
    # see SPRINT_LOG.md's "Known constraint" entry) depends on this connection
    # never being touched from more than one thread concurrently. True today
    # (api/app.py runs single-threaded, no threaded=True anywhere) but NOT
    # enforced here -- a future threaded/multi-worker WSGI swap would silently
    # break it with no test catching it.
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
    return _conn


def init_db():
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            company          TEXT NOT NULL,
            role             TEXT NOT NULL,
            geography        TEXT NOT NULL,
            source_type      TEXT NOT NULL DEFAULT 'company',
            recruiter_agency TEXT,
            jd_url           TEXT,
            jd_text          TEXT,
            status           TEXT NOT NULL DEFAULT 'new',
            ats_score        REAL,
            cv_path          TEXT,
            cover_letter     TEXT,
            outreach_raw     TEXT,
            notes            TEXT,
            salary_estimate  TEXT,
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS contacts (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id            INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            name              TEXT NOT NULL,
            title             TEXT,
            company           TEXT,
            email             TEXT,
            linkedin_url      TEXT,
            contact_type      TEXT NOT NULL,
            source            TEXT DEFAULT 'manual',
            apollo_id         TEXT,
            enrichment_status TEXT DEFAULT 'pending',
            outreach_sent     INTEGER DEFAULT 0,
            replied           INTEGER DEFAULT 0,
            created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS outreach_log (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id       INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
            job_id           INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            channel          TEXT NOT NULL,
            sequence_num     INTEGER NOT NULL,
            status           TEXT DEFAULT 'draft',
            scheduled_date   DATE,
            sent_at          TIMESTAMP,
            subject          TEXT,
            content          TEXT,
            gmail_draft_id   TEXT,
            gmail_message_id TEXT,
            gmail_thread_id  TEXT,
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS email_dedup (
            email                TEXT PRIMARY KEY,
            first_contact_job_id INTEGER REFERENCES jobs(id),
            first_contact_date   TIMESTAMP,
            contact_count        INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS company_profiles (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            company        TEXT NOT NULL UNIQUE,
            profile_status TEXT NOT NULL DEFAULT 'pending',
            sector         TEXT,
            company_size   TEXT,
            funding_stage  TEXT,
            tech_stack     TEXT,
            geography      TEXT,
            recent_news    TEXT,
            competitors    TEXT,
            hiring_for     TEXT,
            mission_values_culture TEXT,
            employer_rating TEXT,
            created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS saved_jobs_queue (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            url              TEXT NOT NULL,
            linkedin_job_id  TEXT NOT NULL UNIQUE,
            status           TEXT NOT NULL DEFAULT 'pending',
            job_id           INTEGER REFERENCES jobs(id),
            error            TEXT,
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at     TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS processed_gmail_messages (
            message_id        TEXT PRIMARY KEY,
            contact_id        INTEGER REFERENCES contacts(id) ON DELETE CASCADE,
            job_id            INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
            classification    TEXT NOT NULL,
            extracted_date    DATE,
            cascade_confirmed INTEGER,
            processed_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS processed_agentmail_messages (
            message_id        TEXT PRIMARY KEY,
            contact_id        INTEGER REFERENCES contacts(id) ON DELETE CASCADE,
            job_id            INTEGER REFERENCES jobs(id) ON DELETE CASCADE,
            classification    TEXT NOT NULL,
            extracted_date    DATE,
            cascade_confirmed INTEGER,
            processed_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS outreach_send_attempts (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            outreach_log_id     INTEGER NOT NULL REFERENCES outreach_log(id) ON DELETE CASCADE,
            idempotency_key     TEXT NOT NULL UNIQUE,
            attempt_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            endpoint            TEXT NOT NULL,
            reply_to_message_id TEXT,
            recipient_email     TEXT NOT NULL,
            subject             TEXT NOT NULL,
            text_body           TEXT NOT NULL,
            html_body           TEXT,
            inbox_id            TEXT NOT NULL,
            cv_filename         TEXT,
            cv_base64           TEXT,
            cv_file_hash        TEXT,
            inline_attachments_json TEXT,
            resolved_status     TEXT,
            resolved_at         TIMESTAMP,
            agentmail_message_id TEXT,
            agentmail_thread_id  TEXT
        );

        CREATE TABLE IF NOT EXISTS sourcing_runs (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finished_at    TIMESTAMP,
            date_window    TEXT NOT NULL,
            outcome        TEXT,
            locations_json TEXT,
            total_usd      REAL
        );

        CREATE TABLE IF NOT EXISTS sourced_jobs (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            linkedin_job_id  TEXT NOT NULL UNIQUE,
            run_id           INTEGER REFERENCES sourcing_runs(id) ON DELETE SET NULL,
            title            TEXT NOT NULL,
            company          TEXT,
            location         TEXT,
            url              TEXT NOT NULL,
            jd_text          TEXT,
            geo              TEXT NOT NULL,
            search_location  TEXT,
            posted_at        TEXT,
            is_agency        INTEGER NOT NULL DEFAULT 0,
            filter_reason    TEXT,
            fit_score        INTEGER,
            reasons_json     TEXT,
            concerns_json    TEXT,
            status           TEXT NOT NULL DEFAULT 'new',
            pass_reason      TEXT,
            job_id           INTEGER REFERENCES jobs(id),
            owns_job         INTEGER NOT NULL DEFAULT 0,
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_status       ON jobs(status);
        CREATE INDEX IF NOT EXISTS idx_jobs_geography    ON jobs(geography);
        CREATE INDEX IF NOT EXISTS idx_contacts_job      ON contacts(job_id);
        CREATE INDEX IF NOT EXISTS idx_contacts_email    ON contacts(email);
        CREATE INDEX IF NOT EXISTS idx_outreach_scheduled ON outreach_log(scheduled_date, status);
        CREATE INDEX IF NOT EXISTS idx_outreach_contact  ON outreach_log(contact_id);
        CREATE INDEX IF NOT EXISTS idx_outreach_job      ON outreach_log(job_id);
        CREATE INDEX IF NOT EXISTS idx_company_profiles_status ON company_profiles(profile_status);
        CREATE INDEX IF NOT EXISTS idx_saved_jobs_queue_status ON saved_jobs_queue(status);
        CREATE INDEX IF NOT EXISTS idx_processed_gmail_messages_processed_at ON processed_gmail_messages(processed_at);
        CREATE INDEX IF NOT EXISTS idx_send_attempts_outreach ON outreach_send_attempts(outreach_log_id);
        CREATE INDEX IF NOT EXISTS idx_sourced_jobs_status ON sourced_jobs(status);
    """)
    # Live-DB migration: add applied_at if missing
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN applied_at TIMESTAMP")
    except Exception:
        pass  # already exists
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN salary_estimate TEXT")
    except Exception:
        pass  # already exists
    try:
        conn.execute("ALTER TABLE outreach_log ADD COLUMN gmail_thread_id TEXT")
    except Exception:
        pass  # already exists
    try:
        conn.execute("ALTER TABLE company_profiles ADD COLUMN mission_values_culture TEXT")
    except Exception:
        pass  # already exists
    try:
        conn.execute("ALTER TABLE company_profiles ADD COLUMN employer_rating TEXT")
    except Exception:
        pass  # already exists
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN ats_parse_warning TEXT")
    except Exception:
        pass  # already exists
    try:
        conn.execute("ALTER TABLE saved_jobs_queue ADD COLUMN source_type TEXT NOT NULL DEFAULT 'company'")
    except Exception:
        pass  # already exists
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN contacts_discovery_status TEXT")
    except Exception:
        pass  # already exists
    try:
        conn.execute("ALTER TABLE contacts ADD COLUMN email_status TEXT")
    except Exception:
        pass  # already exists
    try:
        conn.execute("ALTER TABLE processed_gmail_messages ADD COLUMN digest_dismissed INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass  # already exists
    try:
        conn.execute("ALTER TABLE processed_agentmail_messages ADD COLUMN digest_dismissed INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass  # already exists
    try:
        conn.execute("ALTER TABLE outreach_log ADD COLUMN brief_sent_date TEXT")
    except Exception:
        pass  # already exists
    try:
        conn.execute("ALTER TABLE outreach_log ADD COLUMN brief_position INTEGER")
    except Exception:
        pass  # already exists
    try:
        conn.execute("ALTER TABLE outreach_log ADD COLUMN provider TEXT NOT NULL DEFAULT 'gmail'")
    except Exception:
        pass  # already exists
    try:
        conn.execute("ALTER TABLE outreach_log ADD COLUMN agentmail_message_id TEXT")
    except Exception:
        pass  # already exists
    try:
        conn.execute("ALTER TABLE outreach_log ADD COLUMN agentmail_thread_id TEXT")
    except Exception:
        pass  # already exists
    try:
        conn.execute("ALTER TABLE outreach_log ADD COLUMN send_idempotency_key TEXT")
    except Exception:
        pass  # already exists
    try:
        conn.execute("ALTER TABLE outreach_send_attempts ADD COLUMN inline_attachments_json TEXT")
    except Exception:
        pass  # already exists
    try:
        conn.execute("ALTER TABLE outreach_log ADD COLUMN send_attempt_at TIMESTAMP")
    except Exception:
        pass  # already exists
    try:
        conn.execute("ALTER TABLE outreach_log ADD COLUMN uncertain_dismissed_at TIMESTAMP")
    except Exception:
        pass  # already exists
    try:
        conn.execute("ALTER TABLE contacts ADD COLUMN outreach_paused_at TIMESTAMP")
    except Exception:
        pass  # already exists
    conn.commit()


# ── JOBS ──────────────────────────────────────────────────────────────────────

def create_job(company, role, geography, source_type="company",
               recruiter_agency=None, jd_url=None, jd_text=None):
    conn = _get_conn()
    with _write_lock:
        cur = conn.execute(
            """INSERT INTO jobs (company, role, geography, source_type, recruiter_agency, jd_url, jd_text)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (company, role, geography, source_type, recruiter_agency, jd_url, jd_text),
        )
        conn.commit()
        return cur.lastrowid


def update_job(job_id, **kwargs):
    bad = set(kwargs) - _VALID_JOB_COLS
    if bad:
        raise ValueError(f"Unknown job column(s): {bad}")
    conn = _get_conn()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise ValueError(f"Job {job_id} not found")

    if "status" in kwargs:
        old = row["status"]
        new = kwargs["status"]
        allowed = VALID_TRANSITIONS.get(old, [])
        if new in ("withdrawn", "rejected"):
            if old not in ACTIVE_STATUSES:
                raise ValueError(f"Invalid transition: {old} -> {new}")
        elif new not in allowed:
            raise ValueError(f"Invalid transition: {old} -> {new}")

    if kwargs.get("status") == "applied" and "applied_at" not in kwargs:
        kwargs["applied_at"] = datetime.utcnow().isoformat()

    kwargs["updated_at"] = datetime.utcnow().isoformat()
    cols = ", ".join(f"{k} = ?" for k in kwargs)
    with _write_lock:
        conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*kwargs.values(), job_id))
        conn.commit()
    return get_job(job_id)


def get_job(job_id):
    conn = _get_conn()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def get_jobs(status=None, geo=None, sort="date", order="desc"):
    conn = _get_conn()
    where, params = [], []

    if status:
        vals = [status] if isinstance(status, str) else list(status)
        where.append(f"j.status IN ({','.join('?'*len(vals))})")
        params.extend(vals)
    if geo:
        vals = [geo] if isinstance(geo, str) else list(geo)
        where.append(f"j.geography IN ({','.join('?'*len(vals))})")
        params.extend(vals)

    sort_col = {"date": "j.created_at", "score": "j.ats_score", "company": "j.company"}.get(sort, "j.created_at")
    order_dir = "DESC" if order.lower() == "desc" else "ASC"
    where_clause = f"WHERE {' AND '.join(where)}" if where else ""

    rows = conn.execute(
        f"""SELECT j.*, COUNT(c.id) AS contact_count
            FROM jobs j
            LEFT JOIN contacts c ON c.job_id = j.id
            {where_clause}
            GROUP BY j.id
            ORDER BY {sort_col} {order_dir}""",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def delete_job(job_id):
    """Deletes a job. Nulls out job_id references in tables that don't
    cascade (email_dedup.first_contact_job_id, saved_jobs_queue.job_id,
    sourced_jobs.job_id) -- those rows are historical facts independent of
    the job's existence, so they're preserved rather than cascade-deleted.
    Raises sqlite3.IntegrityError if some other, unaccounted-for FK still
    blocks the delete."""
    conn = _get_conn()
    with _write_lock:
        conn.execute("UPDATE email_dedup SET first_contact_job_id = NULL WHERE first_contact_job_id = ?", (job_id,))
        conn.execute("UPDATE saved_jobs_queue SET job_id = NULL WHERE job_id = ?", (job_id,))
        conn.execute("UPDATE sourced_jobs SET job_id = NULL WHERE job_id = ?", (job_id,))
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()


def get_stats():
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    by_status = {}
    for row in conn.execute("SELECT status, COUNT(*) as n FROM jobs GROUP BY status").fetchall():
        by_status[row["status"]] = row["n"]

    by_geo = {}
    for row in conn.execute("SELECT geography, COUNT(*) as n FROM jobs GROUP BY geography").fetchall():
        by_geo[row["geography"]] = row["n"]

    avg_row = conn.execute("SELECT AVG(ats_score) FROM jobs WHERE ats_score IS NOT NULL").fetchone()
    avg_ats = round(avg_row[0], 1) if avg_row[0] is not None else None

    sent_count = conn.execute(
        "SELECT COUNT(DISTINCT job_id) FROM outreach_log WHERE channel = 'email' AND status IN ('gmail_draft', 'sent')"
    ).fetchone()[0]
    applied = by_status.get("applied", 0) + sent_count
    replied_jobs = conn.execute(
        """SELECT COUNT(DISTINCT c.job_id) FROM contacts c
           WHERE c.replied = 1
             AND c.job_id IN (
                 SELECT job_id FROM outreach_log WHERE channel = 'email' AND status IN ('gmail_draft', 'sent')
             )"""
    ).fetchone()[0]
    response_rate = round(replied_jobs / sent_count, 2) if sent_count else 0.0

    week_start = date.today().strftime("%Y-%m-%d")  # "this week" = today's applications for simplicity
    this_week_applied = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE status IN ('applied','sent','reply','interview','offer','rejected') AND updated_at >= date('now','-7 days')"
    ).fetchone()[0]
    interviews = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE status = 'interview' AND updated_at >= date('now','-7 days')"
    ).fetchone()[0]
    replies = conn.execute(
        "SELECT COUNT(*) FROM contacts WHERE replied = 1 AND created_at >= date('now','-7 days')"
    ).fetchone()[0]

    # Window is deliberately wide/fuzzy, not a strict 48h: applied_at uses a
    # 'T' separator while datetime('now') uses a space, so this string
    # compare can include a bit more than 2 days at the boundary. Never
    # excludes a recent job, which is all that matters — the frontend does
    # the real "is this today" bucketing in the user's own local timezone.
    applied_at_recent = [
        row["applied_at"] if row["applied_at"].endswith("Z") else row["applied_at"] + "Z"
        for row in conn.execute(
            "SELECT applied_at FROM jobs WHERE applied_at IS NOT NULL AND applied_at >= datetime('now', '-2 days')"
        ).fetchall()
    ]

    # Same deliberately wide/fuzzy 2-day window as applied_at_recent above.
    # channel='email' excludes LinkedIn connects/DMs, which share this table
    # but aren't what "emails sent" means to the user.
    sent_at_recent = [
        row["sent_at"] if row["sent_at"].endswith("Z") else row["sent_at"] + "Z"
        for row in conn.execute(
            "SELECT sent_at FROM outreach_log WHERE channel = 'email' AND status = 'sent' "
            "AND sent_at IS NOT NULL AND sent_at >= datetime('now', '-2 days')"
        ).fetchall()
    ]

    shortlist_new = conn.execute("SELECT COUNT(*) FROM sourced_jobs WHERE status = 'new'").fetchone()[0]

    return {
        "total_jobs": total,
        "by_status": by_status,
        "by_geo": by_geo,
        "avg_ats_score": avg_ats,
        "response_rate": response_rate,
        "this_week": {
            "applied": this_week_applied,
            "interviews": interviews,
            "replies": replies,
        },
        "applied_at_recent": applied_at_recent,
        "sent_at_recent": sent_at_recent,
        "shortlist_new": shortlist_new,
    }


# ── CONTACTS ─────────────────────────────────────────────────────────────────

def create_contact(job_id, name, contact_type, title=None, company=None,
                   email=None, linkedin_url=None, source="manual", apollo_id=None):
    conn = _get_conn()
    with _write_lock:
        cur = conn.execute(
            """INSERT INTO contacts (job_id, name, contact_type, title, company, email, linkedin_url, source, apollo_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_id, name, contact_type, title, company, email, linkedin_url, source, apollo_id),
        )
        conn.commit()
        return cur.lastrowid


def update_contact(contact_id, **kwargs):
    bad = set(kwargs) - _VALID_CONTACT_COLS
    if bad:
        raise ValueError(f"Unknown contact column(s): {bad}")
    conn = _get_conn()
    cols = ", ".join(f"{k} = ?" for k in kwargs)
    with _write_lock:
        conn.execute(f"UPDATE contacts SET {cols} WHERE id = ?", (*kwargs.values(), contact_id))
        conn.commit()
        row = conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
        return dict(row) if row else None


def delete_contact(contact_id):
    conn = _get_conn()
    with _write_lock:
        conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
        conn.commit()
        return True


def get_contacts(job_id):
    conn = _get_conn()
    contacts = [dict(r) for r in conn.execute(
        "SELECT * FROM contacts WHERE job_id = ? ORDER BY id", (job_id,)
    ).fetchall()]
    for c in contacts:
        c["outreach_entries"] = [dict(r) for r in conn.execute(
            "SELECT * FROM outreach_log WHERE contact_id = ? ORDER BY sequence_num", (c["id"],)
        ).fetchall()]
    return contacts


def get_all_contacts():
    conn = _get_conn()
    rows = conn.execute("""
        SELECT c.*,
               j.id        AS job_id,
               j.company   AS job_company,
               j.role      AS job_role,
               SUM(CASE WHEN ol.channel = 'email' THEN 1 ELSE 0 END) AS outreach_count,
               SUM(CASE WHEN ol.channel = 'email' AND ol.status IN ('sent','gmail_draft') THEN 1 ELSE 0 END) AS sent_count,
               SUM(CASE WHEN ol.channel IN ('linkedin_connect','linkedin_dm') AND ol.status IN ('sent','gmail_draft') THEN 1 ELSE 0 END) AS linkedin_done_count,
               (SELECT COUNT(*) FROM contacts c2
                WHERE c2.email = c.email AND c2.email IS NOT NULL AND c2.id != c.id) AS dedup_count
        FROM contacts c
        JOIN jobs j ON j.id = c.job_id
        LEFT JOIN outreach_log ol ON ol.contact_id = c.id
        GROUP BY c.id
        ORDER BY c.created_at DESC
    """).fetchall()
    return [dict(r) for r in rows]


def get_all_contact_linkedin_urls():
    conn = _get_conn()
    rows = conn.execute("SELECT linkedin_url FROM contacts WHERE linkedin_url IS NOT NULL").fetchall()
    return {row["linkedin_url"] for row in rows}


def get_all_contact_emails():
    conn = _get_conn()
    rows = conn.execute("SELECT email FROM contacts WHERE email IS NOT NULL").fetchall()
    return {row["email"] for row in rows}


# ── OUTREACH ─────────────────────────────────────────────────────────────────

def create_outreach_entry(contact_id, job_id, channel, sequence_num,
                          scheduled_date, subject, content, provider="agentmail"):
    conn = _get_conn()
    with _write_lock:
        cur = conn.execute(
            """INSERT INTO outreach_log (contact_id, job_id, channel, sequence_num, scheduled_date, subject, content, provider)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (contact_id, job_id, channel, sequence_num, scheduled_date, subject, content, provider),
        )
        conn.commit()
        return cur.lastrowid


def get_preceding_email(contact_id, sequence_num):
    """The same contact's most recent channel='email' touchpoint with a
    lower sequence_num, or None. Email sequence_nums are 1, 4, 5 -- LinkedIn
    touchpoints sit at 2 and 3, so 'sequence_num - 1' is NOT the predecessor
    for Email 2 (would return LinkedIn DM). This filters channel explicitly
    instead."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM outreach_log WHERE contact_id = ? AND channel = 'email' "
        "AND sequence_num < ? ORDER BY sequence_num DESC LIMIT 1",
        (contact_id, sequence_num),
    ).fetchone()
    return dict(row) if row else None


def update_outreach_entry(entry_id, **kwargs):
    bad = set(kwargs) - _VALID_OUTREACH_COLS
    if bad:
        raise ValueError(f"Unknown outreach column(s): {bad}")
    conn = _get_conn()
    cols = ", ".join(f"{k} = ?" for k in kwargs)
    with _write_lock:
        conn.execute(f"UPDATE outreach_log SET {cols} WHERE id = ?", (*kwargs.values(), entry_id))
        conn.commit()
        row = conn.execute("SELECT * FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
        return dict(row) if row else None


def cancel_pending_touchpoints(contact_id):
    """Mark this contact's not-yet-sent touchpoints skipped. Gmail-provider
    rows: draft or gmail_draft (unchanged historical behavior -- nothing has
    actually been transmitted at either status). AgentMail-provider rows:
    draft only -- sending/uncertain/sent/failed are never touched, since a
    row in any of those states might already represent a real sent email,
    and overwriting it would destroy the audit trail needed to resolve it
    later. Returns the cancelled rows (id, gmail_draft_id) so the caller can
    report a count and delete any live Gmail drafts.

    Also stamps contacts.outreach_paused_at -- the single, reusable signal
    (checked by /send's atomic claim and /check-status's replay guard)
    that this contact should no longer receive outreach, regardless of
    which of this function's four callers (explicit skip, bounce, reply,
    confirmed cascade) triggered it.

    Stamped UNCONDITIONALLY, every time this function is called -- not
    only when it actually cancels a row. A contact can be skipped while
    their only touchpoint is 'uncertain' (not 'draft'): nothing gets
    cancelled here (by design -- Task 2's own cancellation-preserves-
    evidence rule leaves that row alone), but the pause intent is just as
    real, and it's exactly that row a later /check-status replay (Task 8)
    must not be allowed to send through. Gating the stamp on "did this
    cancel anything" was the original (wrong) version of this function --
    it silently failed to protect precisely the case this column exists
    for."""
    conn = _get_conn()
    where = (
        "contact_id = ? AND ("
        "  (provider != 'agentmail' AND status IN ('draft', 'gmail_draft'))"
        "  OR (provider = 'agentmail' AND status = 'draft')"
        ")"
    )
    with _write_lock:
        rows = [dict(r) for r in conn.execute(
            f"SELECT id, gmail_draft_id FROM outreach_log WHERE {where}",
            (contact_id,),
        ).fetchall()]
        conn.execute(
            f"UPDATE outreach_log SET status = 'skipped', brief_sent_date = NULL, brief_position = NULL WHERE {where}",
            (contact_id,),
        )
        conn.execute(
            "UPDATE contacts SET outreach_paused_at = CURRENT_TIMESTAMP WHERE id = ?",
            (contact_id,),
        )
        conn.commit()
        return rows


def claim_and_record_attempt(entry_id, idempotency_key, expected_subject, expected_content, today,
                              endpoint, reply_to_message_id, recipient_email, subject,
                              text_body, html_body, inbox_id, cv_filename=None,
                              cv_base64=None, cv_file_hash=None, inline_attachments_json=None):
    """Atomically: (1) claims the row draft -> sending ONLY if EVERY
    eligibility condition still holds AT THIS EXACT MOMENT -- not just
    status and content, but the due date, the contact's reply/bounce/pause
    state, and (for Email 2/3) the preceding email's confirmed-sent status
    -- and (2) records the full attempt snapshot, in the SAME transaction,
    one commit. Any of these having changed since an earlier, separate
    check (in /send, Task 7) makes the claim itself fail, not just the
    earlier check -- that's the actual enforcement; the earlier checks are
    fast-path only, for a specific error message in the common case.

    expected_subject/expected_content must be the EXACT values the caller's
    fingerprint was built from (Task 6/7's `entry["subject"]`/
    `entry["content"]` snapshot from the top of the request) -- never a
    fresh SELECT issued after validation passed, which would silently
    accept whatever a concurrent edit left behind instead of rejecting it.

    today is the caller's UTC date string (`datetime.utcnow().date().isoformat()`)
    -- passed in rather than computed here so the comparison is explicit
    and testable, and so /send and this function are guaranteed to agree
    on what day it is.

    If anything doesn't hold, this returns False without ever inserting an
    attempt row. If the claim succeeds, an attempt row is guaranteed to
    exist for it before this function returns -- the crash-recovery sweep
    (Task 11) depends on that invariant always holding.

    Also re-verifies, atomically, that `recipient_email` still equals the
    contact's CURRENT email, and -- for Email 2/3 -- that
    `reply_to_message_id` still equals the preceding email's CURRENT
    `agentmail_message_id`, not merely "some predecessor is sent". Both
    are exactly the same class of bug as the content/subject check: an
    earlier, separate read (the fingerprint, or the predecessor lookup in
    `_prepare_agentmail_content`) could be stale by the time the claim
    actually runs if the contact's email changed or the predecessor's
    message id somehow differs -- the claim must not trust that earlier
    read, it must re-check the live row itself."""
    conn = _get_conn()
    with _write_lock:
        # Parameter order matches the ?s top-to-bottom, left-to-right:
        # (1) idempotency_key for SET, (2) id for WHERE id=, (3-4) subject/
        # content, (5) today, (6) recipient_email (against the contact's live
        # email), (7) reply_to_message_id (against the predecessor's live
        # agentmail_message_id -- irrelevant and never reached for Email 1,
        # short-circuited by "sequence_num = 1" before the OR's right side
        # would otherwise need evaluating).
        cur = conn.execute(
            """UPDATE outreach_log
               SET status = 'sending', send_idempotency_key = ?, send_attempt_at = CURRENT_TIMESTAMP
               WHERE id = ?
                 AND status = 'draft'
                 AND subject = ? AND content = ?
                 AND (sequence_num = 1 OR (scheduled_date IS NOT NULL AND scheduled_date <= ?))
                 AND ? = (SELECT c.email FROM contacts c WHERE c.id = outreach_log.contact_id)
                 AND NOT EXISTS (
                     SELECT 1 FROM contacts c
                     WHERE c.id = outreach_log.contact_id
                       AND (c.replied = 1 OR c.email_status = 'bounced' OR c.outreach_paused_at IS NOT NULL)
                 )
                 AND (
                     outreach_log.sequence_num = 1
                     OR ? = (
                         SELECT pred.agentmail_message_id FROM outreach_log pred
                         WHERE pred.contact_id = outreach_log.contact_id
                           AND pred.channel = 'email'
                           AND pred.status = 'sent'
                           AND pred.sequence_num = (
                               SELECT MAX(p2.sequence_num) FROM outreach_log p2
                               WHERE p2.contact_id = outreach_log.contact_id AND p2.channel = 'email'
                                 AND p2.sequence_num < outreach_log.sequence_num
                           )
                     )
                 )""",
            (idempotency_key, entry_id, expected_subject, expected_content, today,
             recipient_email, reply_to_message_id),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return False
        conn.execute(
            """INSERT INTO outreach_send_attempts
               (outreach_log_id, idempotency_key, endpoint, reply_to_message_id, recipient_email,
                subject, text_body, html_body, inbox_id, cv_filename, cv_base64, cv_file_hash,
                inline_attachments_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (entry_id, idempotency_key, endpoint, reply_to_message_id, recipient_email,
             subject, text_body, html_body, inbox_id, cv_filename, cv_base64, cv_file_hash,
             inline_attachments_json),
        )
        conn.commit()
        return True


def record_immediate_send_failure(idempotency_key):
    """For a send that failed DEFINITIVELY at the moment of the original
    /send call (AgentMail rejected it outright -- never ambiguous): the row
    goes straight back to 'draft' for an immediate retry, NOT to 'failed',
    which is reserved for a failure discovered later via reconciliation
    (Task 8). Deliberately does NOT call resolve_send_attempt, whose
    generic `SET status = resolved_status` would set outreach_log.status to
    'failed' too -- wrong here, and it would also make a follow-up
    'WHERE status = sending' reset match nothing. The attempt row itself
    still records resolved_status='failed' for audit -- monotonically,
    same rule as resolve_send_attempt (Task 3's "never downgrade a 'sent'
    attempt"): if this key's attempt is somehow already resolved 'sent',
    this must not overwrite it."""
    conn = _get_conn()
    with _write_lock:
        conn.execute(
            "UPDATE outreach_send_attempts SET resolved_status = 'failed', resolved_at = CURRENT_TIMESTAMP "
            "WHERE idempotency_key = ? AND (resolved_status IS NULL OR resolved_status != 'sent')",
            (idempotency_key,),
        )
        conn.execute(
            "UPDATE outreach_log SET status = 'draft' WHERE send_idempotency_key = ? AND status = 'sending'",
            (idempotency_key,),
        )
        conn.commit()


def get_send_attempt(idempotency_key):
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM outreach_send_attempts WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()
    return dict(row) if row else None


def resolve_send_attempt(idempotency_key, resolved_status, agentmail_message_id=None, agentmail_thread_id=None):
    """Always records the outcome on the attempt row (audit trail, even for
    a superseded attempt) -- but monotonically: once an attempt's own
    resolved_status is 'sent', nothing may downgrade it to 'failed' or
    'uncertain'. A late, out-of-order, or duplicate resolution call must
    never corrupt a confirmed-sent audit record. A non-'sent' resolution
    CAN be upgraded to 'sent' later (discovering a false failed-negative),
    so the guard is specifically "never overwrite 'sent'", not "only
    resolve once".

    Only applies the outcome to outreach_log if this key is still that
    row's CURRENT attempt and it's still sending/uncertain -- this is the
    guard that stops a late resolution for an old, retried-away attempt
    from clobbering a newer one. Returns True iff outreach_log was
    actually updated."""
    conn = _get_conn()
    with _write_lock:
        conn.execute(
            "UPDATE outreach_send_attempts SET resolved_status = ?, resolved_at = CURRENT_TIMESTAMP, "
            "agentmail_message_id = ?, agentmail_thread_id = ? "
            "WHERE idempotency_key = ? AND (resolved_status IS NULL OR resolved_status != 'sent')",
            (resolved_status, agentmail_message_id, agentmail_thread_id, idempotency_key),
        )
        cur = conn.execute(
            "UPDATE outreach_log SET status = ?, "
            "agentmail_message_id = COALESCE(?, agentmail_message_id), "
            "agentmail_thread_id = COALESCE(?, agentmail_thread_id), "
            "sent_at = CASE WHEN ? = 'sent' THEN CURRENT_TIMESTAMP ELSE sent_at END "
            "WHERE send_idempotency_key = ? AND status IN ('sending', 'uncertain')",
            (resolved_status, agentmail_message_id, agentmail_thread_id, resolved_status, idempotency_key),
        )
        conn.commit()
        return cur.rowcount > 0


def sweep_stale_sending(grace_seconds=120):
    """Rows stuck in 'sending' longer than grace_seconds get moved to
    'uncertain' -- never resent, never reverted to 'draft'. Race-safe: the
    UPDATE is scoped to the exact send_idempotency_key read at selection
    time, so if the row resolved in the gap between SELECT and UPDATE, this
    matches zero rows and correctly does nothing."""
    conn = _get_conn()
    with _write_lock:
        stale = conn.execute(
            "SELECT id, send_idempotency_key FROM outreach_log "
            "WHERE status = 'sending' AND send_attempt_at < datetime('now', ?)",
            (f"-{grace_seconds} seconds",),
        ).fetchall()
        swept = []
        for row in stale:
            cur = conn.execute(
                "UPDATE outreach_log SET status = 'uncertain' "
                "WHERE id = ? AND send_idempotency_key = ? AND status = 'sending'",
                (row["id"], row["send_idempotency_key"]),
            )
            if cur.rowcount > 0:
                swept.append(row["id"])
        conn.commit()
        return swept


def retry_failed_touchpoint(entry_id):
    """Only valid from 'failed' -- an unresolved 'uncertain' row must
    resolve first. Resets for a fresh /prepare + /send cycle: clears the
    current idempotency key (the old attempt's row in
    outreach_send_attempts is never deleted) and any Mission Brief
    dismissal, so the next attempt's outcome is visible even if the
    previous one was dismissed."""
    conn = _get_conn()
    with _write_lock:
        cur = conn.execute(
            "UPDATE outreach_log SET status = 'draft', send_idempotency_key = NULL, "
            "uncertain_dismissed_at = NULL WHERE id = ? AND status = 'failed'",
            (entry_id,),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
        row = conn.execute("SELECT * FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
        return dict(row)


def dismiss_uncertain_outreach(entry_id):
    """Mission Brief visibility only -- never touches status. An
    'uncertain'/'failed' row still shows its real status on the job's own
    OutreachTimeline regardless of dismissal."""
    conn = _get_conn()
    with _write_lock:
        cur = conn.execute(
            "UPDATE outreach_log SET uncertain_dismissed_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status IN ('uncertain', 'failed')",
            (entry_id,),
        )
        conn.commit()
        return cur.rowcount > 0


def get_uncertain_outreach():
    conn = _get_conn()
    rows = conn.execute(
        """SELECT ol.id, ol.sequence_num, ol.status, ol.send_attempt_at,
                  c.id AS contact_id, c.name AS contact_name,
                  j.id AS job_id, j.company, j.role
           FROM outreach_log ol
           JOIN contacts c ON c.id = ol.contact_id
           JOIN jobs j ON j.id = ol.job_id
           WHERE ol.provider = 'agentmail' AND ol.status IN ('uncertain', 'failed')
             AND ol.uncertain_dismissed_at IS NULL
           ORDER BY ol.send_attempt_at ASC"""
    ).fetchall()
    return [dict(r) for r in rows]


def get_followups_due(date=None):
    if date is None:
        date = datetime.utcnow().strftime("%Y-%m-%d")
    conn = _get_conn()
    rows = conn.execute(
        """SELECT ol.*, c.name AS contact_name, j.company, j.role, j.geography
           FROM outreach_log ol
           JOIN contacts c ON c.id = ol.contact_id
           JOIN jobs j ON j.id = ol.job_id
           WHERE ol.scheduled_date <= ? AND ol.status = 'draft' AND ol.channel = 'email'
             AND ol.provider != 'agentmail'
           ORDER BY ol.scheduled_date, ol.id""",
        (date,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_and_assign_followup_brief(date=None):
    if date is None:
        date = datetime.utcnow().strftime("%Y-%m-%d")
    conn = _get_conn()
    due = get_followups_due(date)
    eligible = [
        entry for entry in due
        if entry["sequence_num"] in (4, 5)
        and not other_contact_replied(entry["job_id"], entry["contact_id"])
    ]

    with _write_lock:
        conn.execute(
            "UPDATE outreach_log SET brief_sent_date = NULL, brief_position = NULL "
            "WHERE brief_sent_date = ?",
            (date,),
        )
        result = []
        for position, entry in enumerate(eligible, start=1):
            conn.execute(
                "UPDATE outreach_log SET brief_sent_date = ?, brief_position = ? WHERE id = ?",
                (date, position, entry["id"]),
            )
            entry["position"] = position
            result.append(entry)
        conn.commit()
        return result


def get_followup_brief_items(date, positions):
    if not positions:
        return []
    conn = _get_conn()
    placeholders = ",".join("?" for _ in positions)
    rows = conn.execute(
        f"""SELECT ol.*, c.name AS contact_name, j.company, j.role
            FROM outreach_log ol
            JOIN contacts c ON c.id = ol.contact_id
            JOIN jobs j ON j.id = ol.job_id
            WHERE ol.brief_sent_date = ? AND ol.brief_position IN ({placeholders})
              AND ol.status = 'draft'
            ORDER BY ol.brief_position""",
        (date, *positions),
    ).fetchall()
    return [dict(r) for r in rows]


def other_contact_replied(job_id, exclude_contact_id):
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM contacts WHERE job_id = ? AND id != ? AND replied = 1 LIMIT 1",
        (job_id, exclude_contact_id),
    ).fetchone()
    return row is not None


# ── EMAIL DEDUP ───────────────────────────────────────────────────────────────

def check_email_dedup(email, job_id):
    conn = _get_conn()
    row = conn.execute(
        """SELECT ed.*, j.company AS previous_job_company, j.role AS previous_job_role
           FROM email_dedup ed
           LEFT JOIN jobs j ON j.id = ed.first_contact_job_id
           WHERE ed.email = ? AND ed.first_contact_job_id != ?""",
        (email, job_id),
    ).fetchone()
    if row is None:
        return None
    return {
        "duplicate": True,
        "previous_job_company": row["previous_job_company"],
        "previous_job_role": row["previous_job_role"],
        "date": row["first_contact_date"],
        "contact_count": row["contact_count"],
    }


def record_email_sent(email, job_id):
    conn = _get_conn()
    with _write_lock:
        existing = conn.execute("SELECT * FROM email_dedup WHERE email = ?", (email,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE email_dedup SET contact_count = contact_count + 1 WHERE email = ?",
                (email,),
            )
        else:
            conn.execute(
                "INSERT INTO email_dedup (email, first_contact_job_id, first_contact_date) VALUES (?, ?, ?)",
                (email, job_id, datetime.utcnow().isoformat()),
            )
        conn.commit()


# ── COMPANY PROFILES ──────────────────────────────────────────────────────────

_VALID_COMPANY_PROFILE_COLS = {
    "sector", "company_size", "funding_stage", "tech_stack",
    "geography", "recent_news", "competitors", "hiring_for",
    "mission_values_culture", "employer_rating",
}


def queue_company_profile(company):
    if not company or company.strip().lower() in ("pending", "confidential", ""):
        return
    conn = _get_conn()
    with _write_lock:
        conn.execute(
            "INSERT OR IGNORE INTO company_profiles (company, profile_status) VALUES (?, 'pending')",
            (company.strip(),),
        )
        conn.commit()


def get_pending_company_profiles():
    conn = _get_conn()
    rows = conn.execute(
        "SELECT company FROM company_profiles WHERE profile_status = 'pending' ORDER BY created_at"
    ).fetchall()
    return [r["company"] for r in rows]


def save_company_profile(company, **fields):
    bad = set(fields) - _VALID_COMPANY_PROFILE_COLS
    if bad:
        raise ValueError(f"Unknown company profile column(s): {bad}")
    conn = _get_conn()
    company = company.strip()
    fields = dict(fields)
    fields["profile_status"] = "complete"
    fields["updated_at"] = datetime.utcnow().isoformat()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with _write_lock:
        conn.execute(
            "INSERT OR IGNORE INTO company_profiles (company, profile_status) VALUES (?, 'pending')",
            (company,),
        )
        conn.execute(f"UPDATE company_profiles SET {cols} WHERE company = ?", (*fields.values(), company))
        conn.commit()
    return get_company_profile(company)


def get_company_profile(company):
    conn = _get_conn()
    row = conn.execute("SELECT * FROM company_profiles WHERE company = ?", (company.strip(),)).fetchone()
    return dict(row) if row else None


# ── SAVED JOBS QUEUE ──────────────────────────────────────────────────────────

def queue_saved_job(url, linkedin_job_id, source_type):
    conn = _get_conn()
    with _write_lock:
        cur = conn.execute(
            "INSERT OR IGNORE INTO saved_jobs_queue (url, linkedin_job_id, source_type, status) VALUES (?, ?, ?, 'pending')",
            (url, linkedin_job_id, source_type),
        )
        conn.commit()
        return "queued" if cur.rowcount == 1 else "duplicate"


def get_pending_saved_jobs():
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM saved_jobs_queue WHERE status = 'pending' ORDER BY created_at"
    ).fetchall()
    return [dict(row) for row in rows]


def mark_saved_job_result(queue_id, status, job_id=None, error=None):
    conn = _get_conn()
    with _write_lock:
        conn.execute(
            "UPDATE saved_jobs_queue SET status = ?, job_id = ?, error = ?, processed_at = ? WHERE id = ?",
            (status, job_id, error, datetime.utcnow().isoformat(), queue_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM saved_jobs_queue WHERE id = ?", (queue_id,)).fetchone()
        return dict(row) if row else None


def job_exists_for_linkedin_id(linkedin_job_id):
    conn = _get_conn()
    row = conn.execute(
        "SELECT id FROM jobs WHERE jd_url LIKE ? LIMIT 1",
        (f"%/jobs/view/{linkedin_job_id}%",),
    ).fetchone()
    return row["id"] if row else None


def get_jobs_needing_contacts():
    conn = _get_conn()
    rows = conn.execute(
        """SELECT j.id, j.company, j.role, j.jd_url, cp.company_size
           FROM jobs j
           LEFT JOIN company_profiles cp ON cp.company = j.company
           WHERE j.contacts_discovery_status = 'pending'
           ORDER BY j.created_at"""
    ).fetchall()
    return [dict(r) for r in rows]


def is_gmail_message_processed(message_id):
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM processed_gmail_messages WHERE message_id = ?", (message_id,)
    ).fetchone()
    return row is not None


def record_processed_gmail_message(message_id, contact_id, job_id, classification,
                                    extracted_date=None, cascade_confirmed=None):
    conn = _get_conn()
    with _write_lock:
        conn.execute(
            "INSERT INTO processed_gmail_messages "
            "(message_id, contact_id, job_id, classification, extracted_date, cascade_confirmed) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (message_id, contact_id, job_id, classification, extracted_date, cascade_confirmed),
        )
        conn.commit()


def is_agentmail_message_processed(message_id):
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM processed_agentmail_messages WHERE message_id = ?", (message_id,)
    ).fetchone()
    return row is not None


def record_processed_agentmail_message(message_id, contact_id, job_id, classification,
                                       extracted_date=None, cascade_confirmed=None):
    conn = _get_conn()
    with _write_lock:
        conn.execute(
            "INSERT INTO processed_agentmail_messages "
            "(message_id, contact_id, job_id, classification, extracted_date, cascade_confirmed) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (message_id, contact_id, job_id, classification, extracted_date, cascade_confirmed),
        )
        conn.commit()


def get_inbox_digest():
    """Returns {replies: [...], bounced: {...}, rejected: {...}, ooo: {...}}.
    Only non-dismissed rows (digest_dismissed=0) -- persistent until acted on,
    not a rolling time window. 'replies' groups genuine_reply messages per
    contact, since the user acts on the relationship (confirm cascade, view
    thread, dismiss), not on one message within it. bounced/rejected/ooo stay
    flat lists -- the frontend collapses them, this layer just excludes
    'other' and dismissed rows."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT message_id, classification, extracted_date, cascade_confirmed, processed_at,
                  contact_id, contact_name, contact_type, job_id, company, role, provider
           FROM (
               SELECT pgm.message_id, pgm.classification, pgm.extracted_date, pgm.cascade_confirmed, pgm.processed_at,
                      c.id AS contact_id, c.name AS contact_name, c.contact_type,
                      j.id AS job_id, j.company, j.role, 'gmail' AS provider
               FROM processed_gmail_messages pgm
               JOIN contacts c ON c.id = pgm.contact_id
               JOIN jobs j ON j.id = pgm.job_id
               WHERE pgm.classification != 'other' AND pgm.digest_dismissed = 0
               UNION ALL
               SELECT pam.message_id, pam.classification, pam.extracted_date, pam.cascade_confirmed, pam.processed_at,
                      c.id AS contact_id, c.name AS contact_name, c.contact_type,
                      j.id AS job_id, j.company, j.role, 'agentmail' AS provider
               FROM processed_agentmail_messages pam
               JOIN contacts c ON c.id = pam.contact_id
               JOIN jobs j ON j.id = pam.job_id
               WHERE pam.classification != 'other' AND pam.digest_dismissed = 0
           )
           ORDER BY processed_at DESC"""
    ).fetchall()

    replies_by_contact = {}
    bounced, rejected, ooo = [], [], []

    for sqlite_row in rows:
        row = dict(sqlite_row)
        classification = row["classification"]
        if classification == "genuine_reply":
            entry = replies_by_contact.setdefault(row["contact_id"], {
                "contact_id": row["contact_id"],
                "contact_name": row["contact_name"],
                "contact_type": row["contact_type"],
                "job_id": row["job_id"],
                "company": row["company"],
                "role": row["role"],
                "message_ids": [],
                "message_count": 0,
                "latest_processed_at": row["processed_at"],
                "has_unconfirmed_cascade": False,
            })
            entry["message_ids"].append(row["message_id"])
            entry["message_count"] += 1
            if row["cascade_confirmed"] == 0:
                entry["has_unconfirmed_cascade"] = True
            # rows are ORDER BY processed_at DESC, so the first row seen per
            # contact is already the latest -- no comparison needed here
        elif classification == "bounce":
            bounced.append(row)
        elif classification == "rejection":
            rejected.append(row)
        elif classification == "ooo":
            ooo.append(row)

    return {
        "replies": list(replies_by_contact.values()),
        "bounced": {"count": len(bounced), "items": bounced},
        "rejected": {"count": len(rejected), "items": rejected},
        "ooo": {"count": len(ooo), "items": ooo},
    }


def dismiss_contact_digest(contact_id):
    """Dismiss every currently-visible digest message for one contact,
    across both providers -- a reply thread is the same relationship
    regardless of which provider sent the original outreach. Returns the
    number of rows updated."""
    conn = _get_conn()
    with _write_lock:
        cur1 = conn.execute(
            "UPDATE processed_gmail_messages SET digest_dismissed = 1 "
            "WHERE contact_id = ? AND digest_dismissed = 0",
            (contact_id,),
        )
        cur2 = conn.execute(
            "UPDATE processed_agentmail_messages SET digest_dismissed = 1 "
            "WHERE contact_id = ? AND digest_dismissed = 0",
            (contact_id,),
        )
        conn.commit()
        return cur1.rowcount + cur2.rowcount


def dismiss_digest_messages(message_ids):
    """Dismiss specific messages by ID (used for individual items inside the
    collapsed bounced/rejected/ooo sections). message_id is unique per
    provider table, so matching against both is safe -- a given id only
    ever exists in one of them. Returns rows updated."""
    if not message_ids:
        return 0
    conn = _get_conn()
    placeholders = ",".join("?" for _ in message_ids)
    with _write_lock:
        cur1 = conn.execute(
            f"UPDATE processed_gmail_messages SET digest_dismissed = 1 WHERE message_id IN ({placeholders})",
            message_ids,
        )
        cur2 = conn.execute(
            f"UPDATE processed_agentmail_messages SET digest_dismissed = 1 WHERE message_id IN ({placeholders})",
            message_ids,
        )
        conn.commit()
        return cur1.rowcount + cur2.rowcount


def confirm_cascade_for_contact(contact_id):
    """Flip cascade_confirmed=1 on every recorded message for this contact,
    across both providers -- a cascade decision is made once per
    relationship, not once per message or per provider. Returns the job_id
    to cascade against, or None if this contact has no recorded inbox
    messages at all."""
    conn = _get_conn()
    with _write_lock:
        row = conn.execute(
            "SELECT job_id FROM processed_gmail_messages WHERE contact_id = ? "
            "UNION SELECT job_id FROM processed_agentmail_messages WHERE contact_id = ? LIMIT 1",
            (contact_id, contact_id),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE processed_gmail_messages SET cascade_confirmed = 1 WHERE contact_id = ?",
            (contact_id,),
        )
        conn.execute(
            "UPDATE processed_agentmail_messages SET cascade_confirmed = 1 WHERE contact_id = ?",
            (contact_id,),
        )
        conn.commit()
        return row["job_id"]


def get_pending_draft_touchpoints(contact_id):
    """(entry_id, sequence_num) pairs for this contact's not-yet-materialized
    touchpoints. Only status='draft' — a 'gmail_draft' row already has its
    content authored and sits waiting for a human to send it; only 'draft'
    rows drive the Mission Brief 'due today' queue, so only those need to move
    when an OOO reply changes when the next send should happen."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, sequence_num FROM outreach_log WHERE contact_id = ? AND status = 'draft'",
        (contact_id,),
    ).fetchall()
    return [(row["id"], row["sequence_num"]) for row in rows]


def update_touchpoint_dates(date_updates):
    """Bulk-update scheduled_date for specific outreach_log rows.
    date_updates: list of (entry_id, new_date_iso) tuples."""
    conn = _get_conn()
    with _write_lock:
        for entry_id, new_date_iso in date_updates:
            conn.execute("UPDATE outreach_log SET scheduled_date = ? WHERE id = ?", (new_date_iso, entry_id))
        conn.commit()


# ── JOB SOURCING ──────────────────────────────────────────────────────────────

def start_sourcing_run(date_window):
    conn = _get_conn()
    with _write_lock:
        cur = conn.execute("INSERT INTO sourcing_runs (date_window) VALUES (?)", (date_window,))
        conn.commit()
        return cur.lastrowid


def finish_sourcing_run(run_id, outcome, locations, total_usd):
    conn = _get_conn()
    with _write_lock:
        conn.execute(
            "UPDATE sourcing_runs SET finished_at = CURRENT_TIMESTAMP, outcome = ?, locations_json = ?, total_usd = ? "
            "WHERE id = ?",
            (outcome, json.dumps(locations), total_usd, run_id),
        )
        conn.commit()


def get_latest_sourcing_run():
    row = _get_conn().execute("SELECT * FROM sourcing_runs ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    out = dict(row)
    out["locations"] = json.loads(out.pop("locations_json") or "[]")
    return out


def last_good_finished_by_location():
    """Per-location catch-up clock: a location that failed last night gets a
    past-week search even if the other locations succeeded."""
    rows = _get_conn().execute(
        "SELECT finished_at, locations_json FROM sourcing_runs "
        "WHERE finished_at IS NOT NULL ORDER BY id"
    ).fetchall()   # ponytail: full scan, fine at <=90 days of nightly runs (sweep keeps it bounded)
    out = {}
    for r in rows:
        for stat in json.loads(r["locations_json"] or "[]"):
            if stat.get("status") in ("ok", "charge_limited"):
                out[stat["location"]] = r["finished_at"]
    return out


def sourced_job_seen(linkedin_job_id):
    """Rule 24 dedup across every entry path: already shortlisted, already
    queued via Telegram, or already a job."""
    conn = _get_conn()
    if conn.execute("SELECT 1 FROM sourced_jobs WHERE linkedin_job_id = ?", (linkedin_job_id,)).fetchone():
        return True
    if conn.execute("SELECT 1 FROM saved_jobs_queue WHERE linkedin_job_id = ?", (linkedin_job_id,)).fetchone():
        return True
    return job_exists_for_linkedin_id(linkedin_job_id) is not None


_SOURCED_INSERT_COLS = (
    "linkedin_job_id", "run_id", "title", "company", "location", "url", "jd_text", "geo",
    "search_location", "posted_at", "is_agency", "filter_reason", "fit_score", "status",
)


def insert_sourced_job(fields):
    """Returns the new row id, or None if this LinkedIn ID is already stored."""
    values = [fields.get(c) for c in _SOURCED_INSERT_COLS]
    values += [json.dumps(fields.get("reasons") or []), json.dumps(fields.get("concerns") or [])]
    cols = ", ".join(_SOURCED_INSERT_COLS + ("reasons_json", "concerns_json"))
    marks = ", ".join("?" for _ in values)
    conn = _get_conn()
    with _write_lock:
        cur = conn.execute(
            f"INSERT INTO sourced_jobs ({cols}) VALUES ({marks}) ON CONFLICT(linkedin_job_id) DO NOTHING",
            values,
        )
        conn.commit()
        return cur.lastrowid if cur.rowcount == 1 else None


def _sourced_row(row):
    out = dict(row)
    out["reasons"] = json.loads(out.pop("reasons_json") or "[]")
    out["concerns"] = json.loads(out.pop("concerns_json") or "[]")
    return out


def get_sourced_jobs(statuses, geo=None):
    marks = ", ".join("?" for _ in statuses)
    sql = (f"SELECT s.*, j.status AS job_status FROM sourced_jobs s LEFT JOIN jobs j ON j.id = s.job_id "
           f"WHERE s.status IN ({marks})")
    params = list(statuses)
    if geo:
        sql += " AND s.geo = ?"
        params.append(geo)
    sql += " ORDER BY s.fit_score IS NULL, s.fit_score DESC, s.created_at DESC"
    rows = [_sourced_row(r) for r in _get_conn().execute(sql, params).fetchall()]
    for r in rows:   # only the card's Details (new rows) renders jd_text; it can be MBs elsewhere
        if r["status"] != "new":
            r["jd_text"] = None
    return rows


def sweep_sourced_jobs():
    """Retention (spec section 1): unreviewed rows expire after 7 days;
    filtered/expired/passed rows and run records are deleted after 30/90 days.
    Approved rows are kept -- they link to a job."""
    conn = _get_conn()
    with _write_lock:
        expired = conn.execute(
            "UPDATE sourced_jobs SET status = 'expired', updated_at = CURRENT_TIMESTAMP "
            "WHERE status = 'new' AND created_at < datetime('now', '-7 days')"
        ).rowcount
        deleted = conn.execute(
            "DELETE FROM sourced_jobs WHERE status IN ('filtered', 'expired', 'passed') "
            "AND updated_at < datetime('now', '-30 days')"
        ).rowcount
        runs_deleted = conn.execute(
            "DELETE FROM sourcing_runs WHERE started_at < datetime('now', '-90 days')"
        ).rowcount
        conn.commit()
    return {"expired": expired, "deleted": deleted, "runs_deleted": runs_deleted}


SOURCED_PASS_REASONS = {"wrong_seniority", "wrong_domain", "wrong_location", "company", "language", "other"}


def approve_sourced_job(sourced_id):
    """One transaction (spec section 4): create-or-link the job and mark the
    row approved together, so a crash leaves neither an orphaned approval nor
    a duplicate job on retry. Generation is dispatched by the caller AFTER
    this returns. Raises LookupError (no row) / ValueError (not approvable)."""
    conn = _get_conn()
    with _write_lock:
        try:
            row = conn.execute("SELECT * FROM sourced_jobs WHERE id = ?", (sourced_id,)).fetchone()
            if row is None:
                raise LookupError(f"Sourced job {sourced_id} not found")
            if row["status"] == "approved" and row["job_id"]:
                return {"job_id": row["job_id"], "created": False}
            if row["status"] != "new":
                raise ValueError(f"Cannot approve a {row['status']} posting")
            existing = job_exists_for_linkedin_id(row["linkedin_job_id"])
            if existing is not None:
                job_id, created = existing, False
            else:
                cur = conn.execute(
                    "INSERT INTO jobs (company, role, geography, source_type, jd_url) VALUES ('Pending', 'Pending', ?, ?, ?)",
                    (row["geo"], "recruiter" if row["is_agency"] else "company", row["url"]),
                )
                job_id, created = cur.lastrowid, True
            conn.execute(
                "UPDATE sourced_jobs SET status = 'approved', job_id = ?, owns_job = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (job_id, 1 if created else 0, sourced_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {"job_id": job_id, "created": created}


def pass_sourced_job(sourced_id, reason):
    conn = _get_conn()
    with _write_lock:
        cur = conn.execute(
            "UPDATE sourced_jobs SET status = 'passed', pass_reason = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status = 'new'",
            (reason, sourced_id),
        )
        conn.commit()
        return cur.rowcount == 1


def get_sourced_jobs_needing_recovery():
    """Jobs Approve created whose generation never finished (queued in memory
    or killed by a restart). Only owns_job=1 -- a linked job may belong to
    the separate saved-jobs drain process."""
    rows = _get_conn().execute(
        "SELECT j.id, j.jd_url, j.geography, j.source_type FROM sourced_jobs s JOIN jobs j ON j.id = s.job_id "
        "WHERE s.status = 'approved' AND s.owns_job = 1 AND j.status IN ('new', 'generating') ORDER BY j.id"
    ).fetchall()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    init_db()
    jid = create_job("Acme Corp", "Senior PM", "gcc")
    update_job(jid, status="generating")
    update_job(jid, status="cv_ready", ats_score=42.0, cv_path="output/Acme_Corp_Senior_PM/")
    cid = create_contact(jid, "Jane Doe", "hiring_manager", email="jane@acme.com")
    oid = create_outreach_entry(cid, jid, "email", 1, "2026-06-24", "Subject", "Body")
    assert get_job(jid)["status"] == "cv_ready"
    assert get_jobs()[0]["contact_count"] == 1
    assert get_followups_due("2026-12-31")[0]["contact_name"] == "Jane Doe"

    li_oid = create_outreach_entry(cid, jid, "linkedin_connect", 2, "2026-06-24", "", "LI note")
    due = get_followups_due("2026-12-31")
    assert all(e["channel"] == "email" for e in due), "LinkedIn touchpoints must not appear in due list"
    assert len(due) == 1, f"expected 1 due entry (email only), got {len(due)}"

    threaded = update_outreach_entry(oid, gmail_thread_id="thread-abc-123")
    assert threaded["gmail_thread_id"] == "thread-abc-123"

    try:
        update_job(jid, status="new")
        assert False, "should have raised"
    except ValueError:
        pass

    queue_company_profile("Acme Corp")
    assert get_pending_company_profiles() == ["Acme Corp"]
    assert get_company_profile("Acme Corp")["profile_status"] == "pending"
    saved = save_company_profile("Acme Corp", sector="SaaS", company_size="50-200",
                                 funding_stage="Series B", tech_stack="Python, React",
                                 geography="EU", recent_news="Raised Series B",
                                 competitors="Widgetco", hiring_for="Product")
    assert saved["profile_status"] == "complete"
    assert get_pending_company_profiles() == [], "profiled company must drop off the pending queue"
    queue_company_profile("Acme Corp")  # re-queueing an existing company must be a no-op
    assert get_company_profile("Acme Corp")["profile_status"] == "complete"

    updated = update_job(jid, salary_estimate="Base: 100-120K AED")
    assert updated["salary_estimate"] == "Base: 100-120K AED"

    q1 = queue_saved_job("https://www.linkedin.com/jobs/view/111222333/?trackingId=abc", "111222333", "company")
    assert q1 == "queued"
    q2 = queue_saved_job("https://www.linkedin.com/jobs/view/111222333/?trackingId=xyz", "111222333", "company")
    assert q2 == "duplicate", "same linkedin_job_id with a different query string must still dedup"

    pending = get_pending_saved_jobs()
    assert len(pending) == 1
    queue_row_id = pending[0]["id"]

    assert job_exists_for_linkedin_id("111222333") is None

    mark_saved_job_result(queue_row_id, "processed", job_id=jid)
    assert get_pending_saved_jobs() == [], "processed row must drop off the pending list"

    mark_saved_job_result(queue_row_id, "failed", error="LinkedIn fetch timed out")

    assert get_jobs_needing_contacts() == []
    update_job(jid, contacts_discovery_status="pending")
    needing = get_jobs_needing_contacts()
    assert len(needing) == 1 and needing[0]["id"] == jid
    update_job(jid, contacts_discovery_status="complete")
    assert get_jobs_needing_contacts() == [], "completed job must drop off the needs-contacts list"

    print("OK — all assertions passed")
