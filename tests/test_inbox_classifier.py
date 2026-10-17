from pathlib import Path
from unittest.mock import patch

import inbox_classifier


def test_classify_message_parses_valid_json():
    with patch("inbox_classifier.llm_client.call_llm") as mock_call_llm:
        mock_call_llm.return_value = '{"classification": "ooo", "extracted_date": "2026-07-15"}'
        result = inbox_classifier.classify_message("I am out of office until July 15th.")
    assert result == {"classification": "ooo", "extracted_date": "2026-07-15"}


def test_classify_message_strips_markdown_fences():
    with patch("inbox_classifier.llm_client.call_llm") as mock_call_llm:
        mock_call_llm.return_value = '```json\n{"classification": "rejection", "extracted_date": null}\n```'
        result = inbox_classifier.classify_message("We've decided to move forward with other candidates.")
    assert result == {"classification": "rejection", "extracted_date": None}


def test_classify_message_falls_back_to_other_on_invalid_classification():
    with patch("inbox_classifier.llm_client.call_llm") as mock_call_llm:
        mock_call_llm.return_value = '{"classification": "spam", "extracted_date": null}'
        result = inbox_classifier.classify_message("some content")
    assert result == {"classification": "other", "extracted_date": None}


def test_classify_message_falls_back_to_other_on_malformed_json():
    with patch("inbox_classifier.llm_client.call_llm") as mock_call_llm:
        mock_call_llm.return_value = "not json at all"
        result = inbox_classifier.classify_message("some content")
    assert result == {"classification": "other", "extracted_date": None}


def test_classify_message_falls_back_to_other_on_api_failure():
    with patch("inbox_classifier.llm_client.call_llm") as mock_call_llm:
        mock_call_llm.side_effect = RuntimeError("API down")
        result = inbox_classifier.classify_message("some content")
    assert result == {"classification": "other", "extracted_date": None}


def test_classify_message_nulls_non_string_extracted_date():
    # A misbehaving LLM returning a non-string extracted_date (e.g. an int or list)
    # must not pass through unchanged -- date.fromisoformat(extracted_date) downstream
    # only catches ValueError, not TypeError, so a non-string here would otherwise
    # crash the daily scan. classify_message fails closed to None instead.
    with patch("inbox_classifier.llm_client.call_llm") as mock_call_llm:
        mock_call_llm.return_value = '{"classification": "ooo", "extracted_date": 20260715}'
        result = inbox_classifier.classify_message("Out until sometime in July.")
    assert result == {"classification": "ooo", "extracted_date": None}


def test_classify_message_returns_bounce_for_delivery_failure_content():
    with patch("inbox_classifier.llm_client.call_llm") as mock_call_llm:
        mock_call_llm.return_value = '{"classification": "bounce", "extracted_date": null}'
        result = inbox_classifier.classify_message("Your message couldn't be delivered. jane@acme.com wasn't found.")
    assert result == {"classification": "bounce", "extracted_date": None}


def test_valid_classifications_includes_bounce():
    assert "bounce" in inbox_classifier._VALID_CLASSIFICATIONS
    assert len(inbox_classifier._VALID_CLASSIFICATIONS) == 5


def test_classify_message_bounce_with_markdown_fences():
    with patch("inbox_classifier.llm_client.call_llm") as mock_call_llm:
        mock_call_llm.return_value = '```json\n{"classification": "bounce", "extracted_date": null}\n```'
        result = inbox_classifier.classify_message("Delivery failure notice.")
    assert result == {"classification": "bounce", "extracted_date": None}


def test_classify_message_bounce_with_non_string_extracted_date():
    with patch("inbox_classifier.llm_client.call_llm") as mock_call_llm:
        mock_call_llm.return_value = '{"classification": "bounce", "extracted_date": 20260101}'
        result = inbox_classifier.classify_message("Undeliverable message.")
    assert result == {"classification": "bounce", "extracted_date": None}


def test_classify_message_bounce_preserves_string_extracted_date():
    with patch("inbox_classifier.llm_client.call_llm") as mock_call_llm:
        mock_call_llm.return_value = '{"classification": "bounce", "extracted_date": "2026-01-01"}'
        result = inbox_classifier.classify_message("Bounce with date.")
    assert result == {"classification": "bounce", "extracted_date": "2026-01-01"}


def test_skill_md_documents_bounce_category():
    skill_path = Path(inbox_classifier.__file__).resolve().parent / "skills" / "inbox-classifier" / "SKILL.md"
    assert skill_path.exists(), "SKILL.md must exist"
    content = skill_path.read_text(encoding="utf-8")
    assert '"bounce"' in content, "Output format schema must include bounce"
    assert "**bounce**" in content, "Classification rules must include bounce section"
    assert "Undeliverable" in content, "Bounce examples must mention Undeliverable"
    assert "mail-delivery-failure" in content, "Bounce description must mention mail-delivery-failure"
