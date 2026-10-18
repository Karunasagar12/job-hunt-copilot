"""Tests for the placeholder auto-fix guard on Gmail draft creation."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest
import gmail_client

for _mod in ("api.app", "db", "api.db"):
    sys.modules.pop(_mod, None)

import api.app as app_module  # noqa: E402

db = app_module.db


@pytest.fixture
def client(gmail_credentials):
    with app_module.app.test_client() as c:
        yield c


def _make_job_contact_entry(content, subject="Following up", sequence_num=1):
    job_id = db.create_job("Acme Corp", "PM", "india")
    contact_id = db.create_contact(job_id, "Jane Doe", "hiring_manager", email="jane@acme.example")
    # provider="gmail" -- these tests exercise the Gmail-draft creation flow
    # specifically, which now rejects agentmail-provider rows outright (see
    # api/app.py create_gmail_draft/batch_draft guards). The db.py default
    # of "agentmail" is for the AgentMail cutover and doesn't apply here.
    entry_id = db.create_outreach_entry(contact_id, job_id, "email", sequence_num, "2026-07-13", subject, content,
                                        provider="gmail")
    return job_id, contact_id, entry_id


def _install_fake_gmail_create_draft(monkeypatch, captured):
    def _fake_create_draft(**kwargs):
        captured.append(kwargs)
        return "draft-123"

    monkeypatch.setattr(gmail_client, "create_draft", _fake_create_draft)
    monkeypatch.setattr(gmail_client, "get_draft_thread_info", lambda draft_id: None)


def test_placeholder_regex_matches_all_named_tokens():
    for token in ("[First Name]", "[Full Name]", "[Name]", "[Title]", "[Company]"):
        assert app_module._PLACEHOLDER_RE.search(f"Hi {token},")


def test_placeholder_regex_does_not_match_clean_content():
    assert not app_module._PLACEHOLDER_RE.search("Hi Jane, following up on my note from last week.")


def test_create_gmail_draft_autofixes_placeholder_before_creating(client, monkeypatch):
    job_id, contact_id, entry_id = _make_job_contact_entry("Hi [First Name],\n\nFollowing up.")
    captured_draft_calls = []
    _install_fake_gmail_create_draft(monkeypatch, captured_draft_calls)

    with patch("api.app.llm_client.call_llm") as mock_call_llm:
        mock_call_llm.return_value = "Subject: Following up\nHi Jane,\n\nFollowing up."
        resp = client.post(f"/api/outreach/{entry_id}/gmail-draft")

    assert resp.status_code == 200
    assert captured_draft_calls[0]["body"].startswith("Hi Jane,")
    entry = db._get_conn().execute("SELECT subject, content FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert "[First Name]" not in entry["content"]
    assert entry["content"].startswith("Hi Jane,")


def test_create_gmail_draft_blocks_if_still_placeholder_after_fix(client):
    job_id, contact_id, entry_id = _make_job_contact_entry("Hi [First Name],\n\nFollowing up.")

    with patch("api.app.llm_client.call_llm") as mock_call_llm:
        mock_call_llm.return_value = "Subject: Following up\nHi [First Name],\n\nStill broken."
        resp = client.post(f"/api/outreach/{entry_id}/gmail-draft")

    assert resp.status_code == 502
    entry = db._get_conn().execute("SELECT content FROM outreach_log WHERE id = ?", (entry_id,)).fetchone()
    assert entry["content"] == "Hi [First Name],\n\nFollowing up.", "must not overwrite stored content with a still-broken fix"


def test_create_gmail_draft_skips_llm_call_when_content_is_clean(client, monkeypatch):
    job_id, contact_id, entry_id = _make_job_contact_entry("Hi Jane,\n\nFollowing up on my note.")
    captured_draft_calls = []
    _install_fake_gmail_create_draft(monkeypatch, captured_draft_calls)

    with patch("api.app.llm_client.call_llm") as mock_call_llm:
        mock_call_llm.return_value = "should never be used"
        resp = client.post(f"/api/outreach/{entry_id}/gmail-draft")

    assert resp.status_code == 200
    mock_call_llm.assert_not_called()


def test_batch_draft_autofixes_one_entry_without_blocking_others(client, monkeypatch):
    _, _, clean_entry_id = _make_job_contact_entry("Hi Jane,\n\nFollowing up.", subject="Clean")
    _, _, dirty_entry_id = _make_job_contact_entry("Hi [Name],\n\nFollowing up.", subject="Dirty")
    captured_draft_calls = []
    _install_fake_gmail_create_draft(monkeypatch, captured_draft_calls)

    with patch("api.app.llm_client.call_llm") as mock_call_llm:
        mock_call_llm.return_value = "Subject: Dirty\nHi Jane,\n\nFollowing up."
        resp = client.post("/api/outreach/batch-draft", json={"ids": [clean_entry_id, dirty_entry_id]})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["created"] == 2
    assert body["errors"] == []
    dirty_entry = db._get_conn().execute("SELECT content FROM outreach_log WHERE id = ?", (dirty_entry_id,)).fetchone()
    assert "[Name]" not in dirty_entry["content"]


def test_redraft_outreach_still_works_after_refactor(client):
    _, _, entry_id = _make_job_contact_entry("Hi Jane,\n\nOld body.", subject="Old Subject")

    with patch("api.app.llm_client.call_llm") as mock_call_llm:
        mock_call_llm.return_value = "Subject: New Subject\nHi Jane,\n\nNew body."
        resp = client.post(f"/api/outreach/{entry_id}/redraft", json={"feedback": "make it warmer"})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["subject"] == "New Subject"
    assert body["content"] == "Hi Jane,\n\nNew body."


def test_redraft_outreach_500s_when_a_non_first_knowledge_file_is_missing(client, monkeypatch):
    """Regression test: the pre-check must cover all six files, not just career-master.md.

    Simulates identity.md (deliberately not the first knowledge file) being unreadable.
    Before the fix this slipped past the pre-check and blew up later inside _llm_redraft,
    returning a 502 "LLM redraft failed" instead of the correct 500.
    """
    _, _, entry_id = _make_job_contact_entry("Hi Jane,\n\nOld body.", subject="Old Subject")

    from pathlib import Path

    real_read_text = Path.read_text

    def _fake_read_text(self, *args, **kwargs):
        if self.name == "identity.md":
            raise OSError("simulated missing file: identity.md")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _fake_read_text)

    with patch("api.app.llm_client.call_llm") as mock_call_llm:
        # LLM must never be reached - if it is, the pre-check regressed.
        mock_call_llm.side_effect = RuntimeError("LLM should not be called")
        resp = client.post(f"/api/outreach/{entry_id}/redraft", json={"feedback": "make it warmer"})

    assert resp.status_code == 500
    body = resp.get_json()
    assert "Failed to load redraft context" in body["error"]
