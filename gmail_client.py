"""Gmail OAuth client for creating Gmail drafts only."""

from __future__ import annotations

import base64
import logging
import os
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

GOOGLE_PACKAGES_INSTALL_COMMAND = (
    "pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client"
)

try:
    from google.auth.exceptions import RefreshError, TransportError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError as exc:
    raise ImportError(
        "Google API packages are required. Install them with: "
        f"{GOOGLE_PACKAGES_INSTALL_COMMAND}"
    ) from exc


SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/gmail.readonly",
]

_PROJECT_ROOT = Path(__file__).resolve().parent
_LOGGER = logging.getLogger(__name__)


def _resolve_path_from_env(env_var: str, default_filename: str) -> Path:
    raw_path = os.getenv(env_var)
    if raw_path:
        path = Path(raw_path).expanduser()
        return path if path.is_absolute() else _PROJECT_ROOT / path
    return _PROJECT_ROOT / default_filename


def _credentials_path() -> Path:
    return _resolve_path_from_env("GMAIL_CREDENTIALS_PATH", "credentials.json")


def _token_path() -> Path:
    return _resolve_path_from_env("GMAIL_TOKEN_PATH", "token.json")


def _save_credentials(creds: Credentials, token_path: Path) -> None:
    try:
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
        os.chmod(token_path, 0o600)
    except OSError as exc:
        raise OSError(f"Failed to save Gmail token at {token_path}: {exc}") from exc


def get_service() -> Any:
    """Return an authenticated Gmail API resource object."""
    credentials_path = _credentials_path()
    token_path = _token_path()

    if not credentials_path.exists():
        raise FileNotFoundError(
            f"Gmail credentials not found at {credentials_path}. "
            "See BUILD_SPEC.md §9 for setup."
        )

    creds: Credentials | None = None

    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except (ValueError, OSError) as exc:
            _LOGGER.warning("Could not load Gmail token: %s", exc)
            creds = None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_credentials(creds, token_path)
        except (RefreshError, TransportError) as exc:
            _LOGGER.warning("Failed to refresh Gmail OAuth token: %s", exc)
            creds = None

    if not creds or not creds.valid:
        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path),
                SCOPES,
            )
            creds = flow.run_local_server(port=0)
            _save_credentials(creds, token_path)
        except FileNotFoundError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Failed to authenticate with Gmail OAuth: {exc}") from exc

    try:
        return build("gmail", "v1", credentials=creds)
    except Exception as exc:
        raise RuntimeError(f"Failed to build Gmail API service: {exc}") from exc


def _get_signature(geo: str = "eu") -> str:
    """Return the signature HTML for the given geo (eu/gcc/india), or empty string."""
    import re
    geo_map = {"gcc": "UAE", "eu": "EU", "india": "India"}
    fname = geo_map.get(geo.lower(), "EU")
    sig_path = _PROJECT_ROOT / "signatures" / "Final" / f"Signature_{fname}.html"
    try:
        html = sig_path.read_text(encoding="utf-8")
        m = re.search(r"<body[^>]*>(.*)</body>", html, re.DOTALL | re.IGNORECASE)
        signature = m.group(1).strip() if m else html
        # AgentMail converts formatting newlines between inline elements to
        # <br> tags. Keep template indentation out of the transmitted HTML;
        # explicit <br> tags still define any intended signature line breaks.
        return re.sub(r"\r?\n[ \t]*", "", signature)
    except Exception:
        return ""


_SIG_MARKERS = (
    "linkedin.com/in/janedoe-example",
    "senior data scientist",
)


def strip_signature(body: str) -> str:
    """Remove the hardcoded Jane signature block from the end of an email body."""
    lines = body.splitlines()
    if not lines:
        return body
    i = len(lines) - 1
    while i >= 0 and not lines[i].strip():
        i -= 1
    if i < 0:
        return body
    found = False
    while i >= 0:
        lower = lines[i].strip().lower()
        if lower == "jane" or any(m in lower for m in _SIG_MARKERS):
            found = True
            i -= 1
            continue
        break
    if not found:
        return body
    cleaned = lines[: i + 1]
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()
    result = "\n".join(cleaned)
    _closings = ("regards", "best", "thanks", "cheers", "sincerely", "warm")
    last = cleaned[-1].strip().lower() if cleaned else ""
    if not any(last.startswith(w) for w in _closings):
        result += "\n\nRegards,"
    return result


def get_draft_thread_info(draft_id: str) -> dict | None:
    """Return {thread_id, message_id} for an existing draft, or None on any failure."""
    try:
        service = get_service()
        resp = service.users().drafts().get(userId="me", id=draft_id, format="full").execute()
        msg = resp["message"]
        thread_id = msg["threadId"]
        headers = msg.get("payload", {}).get("headers", [])
        message_id = next(
            (
                h["value"]
                for h in headers
                if isinstance(h, dict) and h.get("name", "").lower() == "message-id"
            ),
            None,
        )
        return {"thread_id": str(thread_id), "message_id": message_id}
    except Exception:
        return None


def check_draft_sent(draft_id: str) -> bool | None:
    """Return True if this specific draft no longer exists (sent or discarded), False if
    it's still a live draft, None if the check itself failed (network/auth/rate-limit
    error) — callers must treat None as 'unknown, skip' and never as sent. Only an HTTP
    404 on THIS draft ID means it's gone; any other HttpError status (403 expired token,
    429 rate limited, 5xx transient) is a check failure, not a sent signal. Checking the
    draft's own ID (not the thread) matters because Email 2/3 share a Gmail thread with
    Email 1 — a thread-level 'was anything sent' check would falsely flag Email 2/3 as
    sent the moment Email 1 is sent."""
    try:
        service = get_service()
        service.users().drafts().get(userId="me", id=draft_id).execute()
        return False
    except HttpError as e:
        if e.resp.status == 404:
            return True
        return None
    except Exception:
        return None


def compose_html_body(plain_body: str, signature_html: str) -> str:
    """Escape plain_body for HTML and append signature_html below it.
    Shared by Gmail's MIME alternative-part builder and the AgentMail
    /prepare endpoint, so both providers compose an identical-looking
    signed body from the same escaping logic."""
    escaped_body = (
        plain_body.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br>\n")
    )
    return (
        '<div style="font-family:sans-serif;font-size:14px;line-height:1.5">'
        f"{escaped_body}"
        "</div>"
        "<br><br>"
        f"{signature_html}"
    )


def _build_raw_message(
    to_email: str,
    subject: str,
    body: str,
    cc: str | None = None,
    reply_to_message_id: str | None = None,
    html_signature: str = "",
    attachment_path: str | None = None,
) -> str:
    if html_signature:
        body_part = MIMEMultipart("alternative")
        html_body = compose_html_body(body, html_signature)
        body_part.attach(MIMEText(body, "plain"))
        body_part.attach(MIMEText(html_body, "html"))
    else:
        body_part = MIMEText(body, "plain")

    if attachment_path:
        message = MIMEMultipart("mixed")
        message.attach(body_part)
        try:
            with open(attachment_path, "rb") as f:
                attachment = MIMEApplication(f.read(), _subtype="pdf")
        except OSError as exc:
            raise RuntimeError(f"Could not read CV attachment at {attachment_path}: {exc}") from exc
        attachment.add_header(
            "Content-Disposition", "attachment", filename=Path(attachment_path).name
        )
        message.attach(attachment)
    else:
        message = body_part

    message["To"] = to_email
    message["Subject"] = subject
    if cc:
        message["Cc"] = cc
    if reply_to_message_id is not None:
        message["In-Reply-To"] = reply_to_message_id
        message["References"] = reply_to_message_id

    return base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8").rstrip("=")


def create_draft(
    to_email: str,
    subject: str,
    body: str,
    cc: str | None = None,
    thread_id: str | None = None,
    reply_to_message_id: str | None = None,
    geo: str = "eu",
    attachment_path: str | None = None,
) -> str:
    """Create a Gmail draft and return its draft ID. Never sends email."""
    if not to_email:
        raise ValueError("to_email must be a non-empty string.")
    if subject is None:
        raise ValueError("subject must not be None.")
    if body is None:
        raise ValueError("body must not be None.")

    service = get_service()
    sig = _get_signature(geo)

    raw_message = _build_raw_message(
        to_email=to_email,
        subject=subject,
        body=body,
        cc=cc,
        reply_to_message_id=reply_to_message_id if thread_id else None,
        html_signature=sig,
        attachment_path=attachment_path,
    )
    draft_body: dict = {"message": {"raw": raw_message}}
    if thread_id:
        draft_body["message"]["threadId"] = thread_id

    try:
        draft = (
            service.users()
            .drafts()
            .create(userId="me", body=draft_body)
            .execute()
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to create Gmail draft: {exc}") from exc

    draft_id = draft.get("id") if isinstance(draft, dict) else None
    if not draft_id:
        raise RuntimeError("Gmail draft was created without returning a draft ID.")

    return str(draft_id)


def delete_draft(draft_id: str) -> None:
    """Delete a Gmail draft. Never raises — any failure (already sent,
    already deleted, transient API error) is logged and swallowed, since
    this always accompanies a DB-side cancellation that must complete
    regardless of whether the Gmail-side cleanup succeeds."""
    try:
        service = get_service()
        service.users().drafts().delete(userId="me", id=draft_id).execute()
    except Exception as exc:
        _LOGGER.warning("Failed to delete Gmail draft %s: %s", draft_id, exc)


def get_account_email() -> str:
    """Return the authenticated account's own email address, for filtering
    out self-sent messages when scanning threads for replies."""
    service = get_service()
    profile = service.users().getProfile(userId="me").execute()
    return profile["emailAddress"]


def _header_value(message: dict, name: str) -> str | None:
    headers = message.get("payload", {}).get("headers", [])
    return next(
        (h["value"] for h in headers if isinstance(h, dict) and h.get("name", "").lower() == name.lower()),
        None,
    )


def _extract_message_body(message: dict) -> str:
    """Extract plain-text body from a Gmail API message resource, walking
    multipart payloads recursively and preferring text/plain over text/html.
    """
    payload = message.get("payload", {})
    parts = payload.get("parts")
    if not parts:
        data = payload.get("body", {}).get("data")
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace") if data else ""

    def _flatten_leaf_parts(mime_parts: list) -> list:
        """Return all leaf MIME parts from a possibly nested parts tree."""
        leaf_parts = []
        for part in mime_parts:
            if not isinstance(part, dict):
                continue

            nested_parts = part.get("parts")
            if nested_parts:
                leaf_parts.extend(_flatten_leaf_parts(nested_parts))
            else:
                leaf_parts.append(part)

        return leaf_parts

    leaf_parts = _flatten_leaf_parts(parts)

    for part in leaf_parts:
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data")
            if data:
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

    for part in leaf_parts:
        if part.get("mimeType") == "text/html":
            data = part.get("body", {}).get("data")
            if data:
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

    return ""


def get_thread_messages(thread_id: str) -> list[dict]:
    """Return every message in a thread as {message_id, from, date, body}."""
    service = get_service()
    thread = service.users().threads().get(userId="me", id=thread_id, format="full").execute()
    result = []
    for msg in thread.get("messages", []):
        result.append({
            "message_id": msg["id"],
            "from": _header_value(msg, "From") or "",
            "date": _header_value(msg, "Date") or "",
            "body": _extract_message_body(msg),
        })
    return result


def search_messages(query: str) -> list[dict]:
    """Search the inbox and return matching messages as {message_id, from, date, body}."""
    service = get_service()
    resp = service.users().messages().list(userId="me", q=query).execute()
    result = []
    for item in resp.get("messages", []):
        msg = service.users().messages().get(userId="me", id=item["id"], format="full").execute()
        result.append({
            "message_id": msg["id"],
            "from": _header_value(msg, "From") or "",
            "date": _header_value(msg, "Date") or "",
            "body": _extract_message_body(msg),
        })
    return result


def find_sent_thread(to_email: str, subject: str) -> dict | None:
    """Search Sent mail for a message to `to_email` with this exact subject.
    Returns {"thread_id": str, "message_id": str} on exactly one match --
    message_id is the RFC Message-Id header value (the same kind of value
    get_draft_thread_info already extracts for new drafts), NOT the Gmail
    API's internal message id that search_messages/get_thread_messages
    return under the same field name. Returns None on zero or multiple
    matches -- never guesses which one is the real original."""
    service = get_service()
    query = f'in:sent to:{to_email} subject:"{subject}"'
    resp = service.users().messages().list(userId="me", q=query).execute()
    matches = resp.get("messages", [])
    if len(matches) != 1:
        return None
    msg = service.users().messages().get(userId="me", id=matches[0]["id"], format="full").execute()
    return {
        "thread_id": str(msg["threadId"]),
        "message_id": _header_value(msg, "Message-Id"),
    }


if __name__ == "__main__":
    from types import SimpleNamespace

    class _FakeDraftsResource:
        def __init__(self, outcome):
            self._outcome = outcome

        def get(self, userId, id):
            return self

        def delete(self, userId, id):
            return self

        def execute(self):
            if self._outcome == "ok":
                return {"id": "d1"}
            if self._outcome == 404:
                raise HttpError(SimpleNamespace(status=404, reason="Not Found"), b"not found")
            if self._outcome == 403:
                raise HttpError(SimpleNamespace(status=403, reason="Forbidden"), b"forbidden")
            raise RuntimeError("simulated network error")

    class _FakeUsers:
        def __init__(self, outcome):
            self._outcome = outcome

        def drafts(self):
            return _FakeDraftsResource(self._outcome)

    class _FakeService:
        def __init__(self, outcome):
            self._outcome = outcome

        def users(self):
            return _FakeUsers(self._outcome)

    _orig_get_service = get_service

    get_service = lambda: _FakeService("ok")
    assert check_draft_sent("d1") is False, "a draft that still exists must not be treated as sent"

    get_service = lambda: _FakeService(404)
    assert check_draft_sent("d1") is True, "HTTP 404 means the draft is gone — sent"

    get_service = lambda: _FakeService(403)
    assert check_draft_sent("d1") is None, "a 403 (expired token) must NOT be treated as sent"

    get_service = lambda: _FakeService("network-error")
    assert check_draft_sent("d1") is None, "a generic/transient failure must NOT be treated as sent"

    get_service = lambda: _FakeService("ok")
    delete_draft("d1")  # must not raise on success

    get_service = lambda: _FakeService(404)
    delete_draft("d1")  # must not raise even when the draft is already gone

    get_service = lambda: _FakeService("network-error")
    delete_draft("d1")  # must not raise on a transient failure

    get_service = _orig_get_service

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-1.4 fake pdf content for test")
        tmp_pdf = f.name

    raw_with_attachment = _build_raw_message(
        to_email="test@example.com", subject="Test", body="Hello", attachment_path=tmp_pdf,
    )
    decoded = base64.urlsafe_b64decode(raw_with_attachment + "==")
    assert b"Content-Disposition: attachment" in decoded, "PDF must be attached when attachment_path is given"
    assert Path(tmp_pdf).name.encode() in decoded, "attachment filename must appear in the MIME headers"
    assert b"multipart/mixed" in decoded

    raw_without_attachment = _build_raw_message(
        to_email="test@example.com", subject="Test", body="Hello",
    )
    decoded_plain = base64.urlsafe_b64decode(raw_without_attachment + "==")
    assert b"Content-Disposition: attachment" not in decoded_plain, "no attachment_path means no attachment part"

    os.unlink(tmp_pdf)

    print("OK — all assertions passed")
