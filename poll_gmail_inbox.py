#!/usr/bin/env python3
"""Daily scan of Gmail for replies, rejections, OOO auto-replies, and
bounces tied to this system's own outreach. Classifies each new message
via inbox_classifier and acts through the same primitives the manual
dashboard buttons use (api.app's _cancel_contact_touchpoints /
_cascade_cancel_for_job), never a parallel mechanism.

Run on a schedule via systemd timer — see deploy/poll-gmail-inbox.service +
deploy/poll-gmail-inbox.timer (07:00 IST / 01:30 UTC daily). One message's
classification failure never stops the rest of the scan.
"""
from datetime import date

import api.app as app_module
import db
import paths
import gmail_client
import inbox_classifier
from outreach_manager import reschedule_from_new_base


def _act_on_classification(contact_id, job_id, classification, extracted_date):
    """Run the contact-scoped action for one classified message. Returns
    the cascade_confirmed value to store (None = n/a, 0 = suggested but
    not yet confirmed — see api.app._cascade_cancel_for_job, which the
    digest's confirm button calls)."""
    if classification == "genuine_reply":
        db.update_contact(contact_id, replied=1)
        app_module._cancel_contact_touchpoints(contact_id)
        contact = db._get_conn().execute(
            "SELECT contact_type FROM contacts WHERE id = ?", (contact_id,)
        ).fetchone()
        if contact and contact["contact_type"] in app_module._CASCADE_CONTACT_TYPES:
            return 0
        return None

    if classification == "bounce":
        db.update_contact(contact_id, email_status="bounced")
        app_module._cancel_contact_touchpoints(contact_id)
        return None

    if classification == "rejection":
        app_module._cancel_contact_touchpoints(contact_id)
        return None

    if classification == "ooo":
        if extracted_date:
            try:
                new_base = date.fromisoformat(extracted_date)
            except (ValueError, TypeError):
                return None
            pending = db.get_pending_draft_touchpoints(contact_id)
            updates = reschedule_from_new_base(pending, new_base)
            db.update_touchpoint_dates(updates)
        return None

    return None  # 'other' — no action


def scan_reply_threads(account_email):
    """Pass 1: walk threads with a sent outreach message, classify any new
    inbound message not authored by this account."""
    conn = db._get_conn()
    threads = conn.execute(
        "SELECT DISTINCT gmail_thread_id, contact_id, job_id FROM outreach_log "
        "WHERE status = 'sent' AND gmail_thread_id IS NOT NULL"
    ).fetchall()
    processed = 0
    for row in threads:
        try:
            messages = gmail_client.get_thread_messages(row["gmail_thread_id"])
        except Exception:
            continue
        for msg in messages:
            if account_email.lower() in msg["from"].lower():
                continue
            if db.is_gmail_message_processed(msg["message_id"]):
                continue
            result = inbox_classifier.classify_message(msg["body"])
            cascade_confirmed = _act_on_classification(
                row["contact_id"], row["job_id"], result["classification"], result["extracted_date"]
            )
            db.record_processed_gmail_message(
                msg["message_id"], row["contact_id"], row["job_id"],
                result["classification"], result["extracted_date"], cascade_confirmed,
            )
            processed += 1
    return processed


def scan_bounces():
    """Pass 2: search for delivery-failure notifications, match the failed
    recipient's email back to a contact."""
    try:
        messages = gmail_client.search_messages(
            'from:mailer-daemon OR subject:"Delivery Status Notification" OR '
            'subject:"Undeliverable:" OR from:postmaster'
        )
    except Exception:
        return 0
    processed = 0
    conn = db._get_conn()
    known_contacts = conn.execute(
        "SELECT id, job_id, email FROM contacts WHERE email IS NOT NULL"
    ).fetchall()
    for msg in messages:
        if db.is_gmail_message_processed(msg["message_id"]):
            continue
        contact = next(
            (c for c in known_contacts if c["email"] and c["email"].lower() in msg["body"].lower()),
            None,
        )
        if not contact:
            continue
        db.update_contact(contact["id"], email_status="bounced")
        app_module._cancel_contact_touchpoints(contact["id"])
        db.record_processed_gmail_message(msg["message_id"], contact["id"], contact["job_id"], "bounce")
        processed += 1
    return processed


def run_inbox_scan():
    paths.ensure_dirs()
    db.init_db()
    account_email = gmail_client.get_account_email()
    reply_count = scan_reply_threads(account_email)
    bounce_count = scan_bounces()
    return reply_count + bounce_count


if __name__ == "__main__":
    n = run_inbox_scan()
    print(f"poll_gmail_inbox: processed {n} message(s)")
