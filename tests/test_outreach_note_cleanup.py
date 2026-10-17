import pytest

import outreach_manager

RAW = """CONTACT: Jane Doe — Hiring Manager

── EMAIL 1 (Day 0 — send first) ──
Subject: PM role
Body one.

── LINKEDIN CONNECTION REQUEST (Day 0 — send same day) ──
Hi Jane, I emailed you about the PM role. Would welcome connecting.{annotation}

── LINKEDIN DM (after acceptance) ──
Thanks for connecting.
"""


@pytest.mark.parametrize("annotation", [" [67 chars]", " [max 300 chars]", "\n[180 characters]", ""])
def test_connection_note_annotation_stripped(annotation):
    touchpoints = outreach_manager.parse_and_schedule(
        RAW.format(annotation=annotation), [{"id": 1, "name": "Jane Doe"}]
    )
    note = next(t for t in touchpoints if t["channel"] == "linkedin_connect")["content"]
    assert note == "Hi Jane, I emailed you about the PM role. Would welcome connecting."
