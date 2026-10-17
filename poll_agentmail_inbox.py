#!/usr/bin/env python3
"""Daily scan of AgentMail threads for replies, rejections, and OOO
auto-replies tied to this system's own AgentMail outreach. Reuses the same
classification (inbox_classifier) and cancellation primitives
(poll_gmail_inbox._act_on_classification) the Gmail scan already uses, so
behavior stays consistent regardless of which provider sent the original
outreach. Does NOT scan for bounce-specific delivery-failure notifications
the way poll_gmail_inbox.scan_bounces() does -- AgentMail's bounce-signaling
mechanism isn't confirmed; classify_message()'s own content-based "bounce"
classification still applies to any inbound message in a tracked thread.

Not yet wired to a systemd timer -- per this project's Testing & Deploy
Protocol, a new scheduled script must be hand-run once against real-shaped
data before its first timer fire, and AgentMail real outreach isn't enabled
yet. Run manually for now: `python poll_agentmail_inbox.py`.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# The client captures its API key at import time, including for standalone runs.
load_dotenv(Path(__file__).resolve().parent / ".env")

import agentmail_client
import db
import inbox_classifier
from poll_gmail_inbox import _act_on_classification


def scan_reply_threads(inbox_id):
    """Walk AgentMail threads with a sent outreach message, classify any new
    inbound message not authored by this inbox itself."""
    conn = db._get_conn()
    threads = conn.execute(
        "SELECT DISTINCT agentmail_thread_id, contact_id, job_id FROM outreach_log "
        "WHERE status = 'sent' AND provider = 'agentmail' AND agentmail_thread_id IS NOT NULL"
    ).fetchall()
    processed = 0
    for row in threads:
        try:
            messages = agentmail_client.get_thread_messages(inbox_id, row["agentmail_thread_id"])
        except Exception:
            continue
        for msg in messages:
            if inbox_id.lower() in (msg.get("from") or "").lower():
                continue
            message_id = msg.get("message_id")
            if not message_id or db.is_agentmail_message_processed(message_id):
                continue
            body = msg.get("text") or msg.get("extracted_text") or ""
            result = inbox_classifier.classify_message(body)
            cascade_confirmed = _act_on_classification(
                row["contact_id"], row["job_id"], result["classification"], result["extracted_date"]
            )
            db.record_processed_agentmail_message(
                message_id, row["contact_id"], row["job_id"],
                result["classification"], result["extracted_date"], cascade_confirmed,
            )
            processed += 1
    return processed


def run_agentmail_inbox_scan():
    db.init_db()
    inbox_id = os.getenv("AGENTMAIL_INBOX_ID", "")
    if not inbox_id or not agentmail_client.AGENTMAIL_API_KEY:
        return 0
    return scan_reply_threads(inbox_id)


if __name__ == "__main__":
    n = run_agentmail_inbox_scan()
    print(f"poll_agentmail_inbox: processed {n} message(s)")
