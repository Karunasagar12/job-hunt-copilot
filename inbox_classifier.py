"""LLM-based classification of inbound outreach replies. Standalone module —
does not import generate.py, which has import-time side effects (load_dotenv,
db.init_db()) that don't belong in a lightweight cron script's import chain.
llm_client has no import-time side effects of its own, so it's safe to import
directly here. Matches the existing convention of standalone scripts staying
minimal (see poll_gmail_sent.py, process_saved_jobs_queue.py)."""
import json
from pathlib import Path

import llm_client

_SKILL_PATH = Path(__file__).resolve().parent / "skills" / "inbox-classifier" / "SKILL.md"
_VALID_CLASSIFICATIONS = {"ooo", "rejection", "genuine_reply", "bounce", "other"}


def classify_message(body: str) -> dict:
    """Classify an inbound email body. Returns {"classification": str,
    "extracted_date": str | None}. Never raises — any failure (API error,
    malformed JSON, an unrecognized classification value) falls back to
    {"classification": "other", "extracted_date": None} so a single bad
    message can never crash the daily scan."""
    try:
        skill = _SKILL_PATH.read_text(encoding="utf-8")
        raw = llm_client.call_llm(skill, body, max_tokens=200, timeout=60).strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        parsed = json.loads(raw)
        classification = parsed.get("classification")
        if classification not in _VALID_CLASSIFICATIONS:
            return {"classification": "other", "extracted_date": None}
        extracted_date = parsed.get("extracted_date")
        if not isinstance(extracted_date, (str, type(None))):
            extracted_date = None  # a misbehaving LLM returning a non-string here would
            # otherwise crash date.fromisoformat() downstream (Task 6) with a TypeError,
            # which only catches ValueError -- fail closed instead of propagating it.
        return {"classification": classification, "extracted_date": extracted_date}
    except Exception:
        return {"classification": "other", "extracted_date": None}
