#!/usr/bin/env python3
"""Poll Gmail for drafts that were sent manually and update outreach_log accordingly.

Run on a schedule via systemd timer — see deploy/gmail-poll.service + deploy/gmail-poll.timer.
Checks each outreach_log row's OWN gmail_draft_id (not thread-level), so that Email 2/3
sharing a Gmail thread with an already-sent Email 1 are never falsely marked sent.
"""
from datetime import datetime

import db
import gmail_client


def poll_sent_drafts() -> int:
    db.init_db()
    conn = db._get_conn()
    rows = conn.execute(
        "SELECT id, gmail_draft_id FROM outreach_log "
        "WHERE status = 'gmail_draft' AND gmail_draft_id IS NOT NULL"
    ).fetchall()
    updated = 0
    for row in rows:
        sent = gmail_client.check_draft_sent(row["gmail_draft_id"])
        if sent:
            db.update_outreach_entry(
                row["id"], status="sent", sent_at=datetime.utcnow().isoformat()
            )
            updated += 1
    return updated


if __name__ == "__main__":
    n = poll_sent_drafts()
    print(f"poll_gmail_sent: {n} entries marked sent")
