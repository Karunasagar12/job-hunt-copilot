import base64
import os

import requests

AGENTMAIL_API_KEY = os.getenv("AGENTMAIL_API_KEY")
BASE_URL = "https://api.agentmail.to/v0"


class AgentMailError(Exception):
    """AgentMail definitively rejected the request (4xx, excluding 409 --
    see AgentMailReplayMismatch). Safe to treat as a clean failure --
    nothing was sent."""


class AgentMailAmbiguous(Exception):
    """Timeout, connection error, or 5xx -- whether AgentMail processed the
    request is genuinely unknown. Callers must mark the touchpoint
    'uncertain', never retry automatically."""


class AgentMailReplayMismatch(Exception):
    """AgentMail returned 409: per their documented idempotency contract,
    this means the request's content doesn't match what's on record for
    this idempotency key. If the caller replayed an exact snapshot of the
    original request (Task 8), this should never happen -- if it does, we
    cannot conclude the original attempt failed (it may have succeeded).
    Callers must NEVER treat this as AgentMailError -- the row must stay
    'uncertain', never become 'failed', and must never be retried with a
    fresh key while this is unresolved."""


def _headers(idempotency_key):
    return {
        "Authorization": f"Bearer {AGENTMAIL_API_KEY}",
        "Content-Type": "application/json",
        "Idempotency-Key": idempotency_key,
    }


def send_email(idempotency_key, inbox_id, to_email, subject, text_body, html_body=None,
               reply_to_message_id=None, attachment_bytes=None, attachment_filename=None,
               extra_attachments=None, timeout=20):
    """POST .../messages/send (reply_to_message_id is None) or
    .../messages/{id}/reply (reply_to_message_id given). Returns
    {"message_id": ..., "thread_id": ...} on confirmed success. Raises
    AgentMailError on a definitive rejection, AgentMailReplayMismatch on a
    409, AgentMailAmbiguous on timeout/connection error/5xx -- callers must
    not treat any of these three the same way. attachment_bytes is raw
    bytes already in memory -- this function never reads from disk, so a
    caller replaying a stored attempt snapshot sends byte-identical
    content to the original call. extra_attachments is a list of
    already-base64-encoded, AgentMail-shaped attachment dicts (e.g. inline
    signature images) appended verbatim after the CV -- never re-encoded
    here, so a replay from a stored snapshot stays byte-identical."""
    payload = {"to": [to_email], "subject": subject, "text": text_body}
    if html_body:
        payload["html"] = html_body
    attachments = []
    if attachment_bytes:
        attachments.append({
            "filename": attachment_filename or "attachment.pdf",
            "content_type": "application/pdf",
            "content": base64.b64encode(attachment_bytes).decode("ascii"),
        })
    if extra_attachments:
        attachments.extend(extra_attachments)
    if attachments:
        payload["attachments"] = attachments

    if reply_to_message_id:
        url = f"{BASE_URL}/inboxes/{inbox_id}/messages/{reply_to_message_id}/reply"
    else:
        url = f"{BASE_URL}/inboxes/{inbox_id}/messages/send"

    try:
        resp = requests.post(url, json=payload, headers=_headers(idempotency_key), timeout=timeout)
    except requests.exceptions.RequestException as exc:
        raise AgentMailAmbiguous(str(exc)) from exc

    if resp.status_code >= 500:
        raise AgentMailAmbiguous(f"AgentMail server error: {resp.status_code}")
    if resp.status_code == 409:
        raise AgentMailReplayMismatch(f"AgentMail reports a content mismatch for this idempotency key: {resp.text}")
    if resp.status_code >= 400:
        raise AgentMailError(f"AgentMail rejected the request ({resp.status_code}): {resp.text}")

    try:
        data = resp.json()
    except ValueError as exc:
        raise AgentMailAmbiguous(f"AgentMail returned HTTP 200 with an unparseable or incomplete body: {resp.text[:200]}") from exc
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("message_id"), str)
        or not data.get("message_id")
        or not isinstance(data.get("thread_id"), str)
        or not data.get("thread_id")
    ):
        raise AgentMailAmbiguous(f"AgentMail returned HTTP 200 with an unparseable or incomplete body: {resp.text[:200]}")
    return {"message_id": data["message_id"], "thread_id": data["thread_id"]}


def get_thread_messages(inbox_id, thread_id, timeout=20):
    """Read-only: GET .../inboxes/{inbox_id}/threads/{thread_id}, paginating
    via next_page_token until exhausted. Returns the raw list of message
    dicts (each with at least message_id/thread_id/from/timestamp/labels,
    and usually 'text' for the plain-text body). Raises
    requests.exceptions.RequestException on a network failure or
    requests.exceptions.HTTPError on a non-2xx response (via
    response.raise_for_status()) -- deliberately NOT the send-path's
    AgentMailError/AgentMailAmbiguous/AgentMailReplayMismatch taxonomy, since
    those encode idempotent-SEND outcome semantics that don't apply to a
    read. Callers should catch broadly and skip this thread for this scan
    pass, exactly like poll_gmail_inbox.py already does for
    gmail_client.get_thread_messages failures."""
    from urllib.parse import quote
    messages = []
    page_token = None
    while True:
        params = {"limit": 100}
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(
            f"{BASE_URL}/inboxes/{quote(inbox_id, safe='')}/threads/{quote(thread_id, safe='')}",
            headers={"Authorization": f"Bearer {AGENTMAIL_API_KEY}"},
            params=params, timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        messages.extend(data.get("messages", []))
        page_token = data.get("next_page_token")
        if not page_token:
            break
    return messages
