"""Parse generated outreach content and build scheduled touchpoint entries."""

from __future__ import annotations

import re
import profile as prof
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Final


@dataclass(frozen=True)
class _ScheduleItem:
    sequence_num: int
    channel: str
    day_offset: int
    label: str
    content_key: str


@dataclass(frozen=True)
class _ContactSection:
    contact_name: str
    blocks: dict[str, str]
    email1_subject: str


_SCHEDULE: Final[tuple[_ScheduleItem, ...]] = (
    _ScheduleItem(sequence_num=1, channel="email",            day_offset=0,  label="Email 1 (Day 0)",           content_key="email1"),
    _ScheduleItem(sequence_num=2, channel="linkedin_connect", day_offset=0,  label="LinkedIn Connect (Day 0)",  content_key="linkedin_connect"),
    _ScheduleItem(sequence_num=3, channel="linkedin_dm",      day_offset=1,  label="LinkedIn DM (Day 1)",       content_key="linkedin_dm"),
    _ScheduleItem(sequence_num=4, channel="email",            day_offset=5,  label="Email 2 (Day 5)",           content_key="email2"),
    _ScheduleItem(sequence_num=5, channel="email",            day_offset=12, label="Email 3 (Day 12)",          content_key="email3"),
)

_CONTACT_SECTION_RE: Final[re.Pattern[str]] = re.compile(
    r"(?ims)^\s*CONTACT:\s*(?P<header>[^\n\r]+)\s*(?P<body>.*?)(?=^\s*CONTACT:\s*|\Z)"
)

_TOUCHPOINT_HEADER_RE: Final[re.Pattern[str]] = re.compile(
    r"(?im)^\s*──\s*"
    r"(?P<header>EMAIL\s+1|LINKEDIN\s+CONNECTION\s+REQUEST|LINKEDIN\s+DM|EMAIL\s+2|EMAIL\s+3)"
    r"\b.*?──\s*$"
)

_SUBJECT_RE: Final[re.Pattern[str]] = re.compile(r"^\s*Subject:\s*(?P<subject>.*)\s*$", re.IGNORECASE)
_NON_NAME_CHARS_RE: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9\s]+")
_WHITESPACE_RE: Final[re.Pattern[str]] = re.compile(r"\s+")
# Drafter output sometimes ends a block with its own character count
# ("[67 chars]", "[max 300 chars]"). Never part of the message.
_CHAR_ANNOTATION_RE: Final[re.Pattern[str]] = re.compile(
    r"\s*\[(?:max\s*)?\d+\s*(?:chars?|characters)\]\s*$", re.IGNORECASE
)

_HEADER_KEY_MAP: Final[dict[str, str]] = {
    "email 1": "email1",
    "linkedin connection request": "linkedin_connect",
    "linkedin dm": "linkedin_dm",
    "email 2": "email2",
    "email 3": "email3",
}


def apply_weekend_skip(d: date) -> date:
    """Shift Saturday → Monday (+2), Sunday → Monday (+1). Weekdays unchanged."""
    if isinstance(d, datetime):
        d = d.date()
    if not isinstance(d, date):
        raise TypeError("d must be a datetime.date instance")
    if d.weekday() == 5:
        return d + timedelta(days=2)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def reschedule_from_new_base(pending_entries: list[tuple[int, int]], new_base_date: date) -> list[tuple[int, str]]:
    """Given a contact's not-yet-materialized touchpoints as (entry_id,
    sequence_num) pairs, recompute each one's scheduled_date anchored to
    new_base_date (e.g. an OOO return date) instead of the original send
    date, re-applying apply_weekend_skip. A sequence_num with no matching
    entry in _SCHEDULE is silently skipped rather than raising — this
    function only ever receives real outreach_log rows, so an unmatched
    sequence_num would indicate a caller bug, not something to crash on
    mid-scan."""
    offsets = {item.sequence_num: item.day_offset for item in _SCHEDULE}
    updates = []
    for entry_id, sequence_num in pending_entries:
        offset = offsets.get(sequence_num)
        if offset is None:
            continue
        new_date = apply_weekend_skip(new_base_date + timedelta(days=offset))
        updates.append((entry_id, new_date.isoformat()))
    return updates


def parse_and_schedule(
    outreach_raw: str,
    contacts: list[dict[str, Any]],
    start_date: date | None = None,
) -> list[dict[str, Any]]:
    """Parse outreach content and return scheduled touchpoint dicts.

    Returns one dict per contact per touchpoint (len(contacts) * 5 total).
    Each dict: contact_id, contact_name, channel, sequence_num,
                scheduled_date (ISO), subject, content.
    """
    if not isinstance(outreach_raw, str):
        raise TypeError("outreach_raw must be a string")
    if not isinstance(contacts, list):
        raise TypeError("contacts must be a list of dictionaries")

    if start_date is None:
        base_date = prof.today_local()
    elif isinstance(start_date, datetime):
        base_date = start_date.date()
    elif isinstance(start_date, date):
        base_date = start_date
    else:
        raise TypeError("start_date must be a datetime.date instance or None")

    sections = _parse_contact_sections(outreach_raw)
    results: list[dict[str, Any]] = []

    for contact in contacts:
        if not isinstance(contact, dict):
            raise TypeError("each contact must be a dictionary")

        contact_id = _get_required_int(contact, "id")
        contact_name = _get_required_str(contact, "name")
        section = _find_matching_section(contact_name, sections)
        placeholder = f"[Outreach content not yet generated for {contact_name}]"

        for item in _SCHEDULE:
            scheduled_date = apply_weekend_skip(base_date + timedelta(days=item.day_offset))
            subject = _subject_for_item(item, section)
            content = _content_for_item(item, section, placeholder)

            results.append({
                "contact_id": contact_id,
                "contact_name": contact_name,
                "channel": item.channel,
                "sequence_num": item.sequence_num,
                "scheduled_date": scheduled_date.isoformat(),
                "subject": subject,
                "content": content,
            })

    return results


def _parse_contact_sections(outreach_raw: str) -> list[_ContactSection]:
    sections: list[_ContactSection] = []
    for match in _CONTACT_SECTION_RE.finditer(outreach_raw):
        header = match.group("header").strip()
        raw_section = match.group(0)
        contact_name = _extract_contact_name(header)
        blocks = _extract_touchpoint_blocks(raw_section)

        email1_subject = ""
        if "email1" in blocks:
            email1_subject, email1_body = _extract_email_subject_and_body(blocks["email1"])
            blocks["email1"] = email1_body

        for email_key in ("email2", "email3"):
            if email_key in blocks:
                _, email_body = _extract_email_subject_and_body(blocks[email_key])
                blocks[email_key] = email_body

        if contact_name:
            sections.append(_ContactSection(
                contact_name=contact_name,
                blocks=blocks,
                email1_subject=email1_subject,
            ))

    return sections


def _extract_contact_name(header: str) -> str:
    return header.split("—", 1)[0].strip()


def _extract_touchpoint_blocks(raw_section: str) -> dict[str, str]:
    matches = list(_TOUCHPOINT_HEADER_RE.finditer(raw_section))
    blocks: dict[str, str] = {}
    for index, match in enumerate(matches):
        key = _normalize_touchpoint_header(match.group("header"))
        if key is None:
            continue  # ponytail: skip unknown headers — drafter output can vary slightly
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(raw_section)
        block = raw_section[match.end():next_start].strip()
        blocks[key] = block
    return blocks


def _normalize_touchpoint_header(header: str) -> str | None:
    normalized = _WHITESPACE_RE.sub(" ", header.strip().lower())
    return _HEADER_KEY_MAP.get(normalized)


def _extract_email_subject_and_body(block: str) -> tuple[str, str]:
    lines = block.splitlines()
    subject = ""
    body_lines: list[str] = []
    subject_removed = False
    for line in lines:
        subject_match = _SUBJECT_RE.match(line)
        if subject_match and not subject_removed:
            subject = subject_match.group("subject").strip()
            subject_removed = True
            continue
        body_lines.append(line)
    return subject, "\n".join(body_lines).strip()


def _find_matching_section(contact_name: str, sections: list[_ContactSection]) -> _ContactSection | None:
    best_section: _ContactSection | None = None
    best_score = 0
    for section in sections:
        score = _name_match_score(contact_name, section.contact_name)
        if score > best_score:
            best_score = score
            best_section = section
    return best_section if best_score > 0 else None


def _name_match_score(contact_name: str, section_name: str) -> int:
    contact_normalized = _normalize_name(contact_name)
    section_normalized = _normalize_name(section_name)
    if not contact_normalized or not section_normalized:
        return 0
    if contact_normalized == section_normalized:
        return 100
    contact_tokens = contact_normalized.split()
    section_tokens = section_normalized.split()
    if contact_tokens and section_tokens:
        if all(t in section_tokens for t in contact_tokens):
            return 90
        if all(t in contact_tokens for t in section_tokens):
            return 85
        if contact_tokens[0] == section_tokens[0]:
            return 75
    return 0


def _normalize_name(name: str) -> str:
    lowered = name.lower()
    without_punctuation = _NON_NAME_CHARS_RE.sub(" ", lowered)
    return _WHITESPACE_RE.sub(" ", without_punctuation).strip()


def _subject_for_item(item: _ScheduleItem, section: _ContactSection | None) -> str:
    if item.channel != "email" or section is None:
        return ""
    if item.content_key == "email1":
        return section.email1_subject
    if item.content_key in {"email2", "email3"}:
        return _reply_subject(section.email1_subject)
    return ""


def _reply_subject(subject: str) -> str:
    stripped = subject.strip()
    if not stripped:
        return ""
    if stripped.lower().startswith("re:"):
        return stripped
    return f"Re: {stripped}"


def _content_for_item(item: _ScheduleItem, section: _ContactSection | None, placeholder: str) -> str:
    if section is None:
        return placeholder
    content = _CHAR_ANNOTATION_RE.sub("", section.blocks.get(item.content_key, "")).strip()
    return content if content else placeholder


def _get_required_int(contact: dict[str, Any], key: str) -> int:
    value = contact.get(key)
    if not isinstance(value, int):
        raise ValueError(f"contact must include integer field '{key}'")
    return value


def _get_required_str(contact: dict[str, Any], key: str) -> str:
    value = contact.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"contact must include non-empty string field '{key}'")
    return value.strip()


def get_unmatched_contacts(outreach_raw: str, contacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return contacts that do not have a matching CONTACT section in outreach_raw."""
    if not contacts:
        return []
    if not outreach_raw:
        return list(contacts)
    sections = _parse_contact_sections(outreach_raw)
    if not sections:
        return list(contacts)
    return [
        c for c in contacts
        if not str(c.get("name") or "").strip()
        or _find_matching_section(str(c.get("name") or "").strip(), sections) is None
    ]
