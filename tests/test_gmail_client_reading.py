import base64
from unittest.mock import MagicMock

import gmail_client


def _b64(text):
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8").rstrip("=")


def test_get_account_email(monkeypatch):
    service = MagicMock()
    service.users.return_value.getProfile.return_value.execute.return_value = {"emailAddress": "me@example.com"}
    monkeypatch.setattr(gmail_client, "get_service", lambda: service)
    assert gmail_client.get_account_email() == "me@example.com"


def test_get_thread_messages_extracts_plain_text_body(monkeypatch):
    service = MagicMock()
    service.users.return_value.threads.return_value.get.return_value.execute.return_value = {
        "messages": [{
            "id": "msg1",
            "payload": {
                "headers": [{"name": "From", "value": "jane@acme.com"}, {"name": "Date", "value": "Mon, 1 Jan 2026"}],
                "parts": [{"mimeType": "text/plain", "body": {"data": _b64("Thanks, I'll pass this along.")}}],
            },
        }],
    }
    monkeypatch.setattr(gmail_client, "get_service", lambda: service)
    messages = gmail_client.get_thread_messages("thread1")
    assert messages == [{
        "message_id": "msg1", "from": "jane@acme.com", "date": "Mon, 1 Jan 2026",
        "body": "Thanks, I'll pass this along.",
    }]


def test_get_thread_messages_falls_back_to_html_when_no_plain_text(monkeypatch):
    service = MagicMock()
    service.users.return_value.threads.return_value.get.return_value.execute.return_value = {
        "messages": [{
            "id": "msg1",
            "payload": {
                "headers": [],
                "parts": [{"mimeType": "text/html", "body": {"data": _b64("<p>Hello</p>")}}],
            },
        }],
    }
    monkeypatch.setattr(gmail_client, "get_service", lambda: service)
    messages = gmail_client.get_thread_messages("thread1")
    assert messages[0]["body"] == "<p>Hello</p>"


def test_get_thread_messages_handles_non_multipart_body(monkeypatch):
    service = MagicMock()
    service.users.return_value.threads.return_value.get.return_value.execute.return_value = {
        "messages": [{
            "id": "msg1",
            "payload": {"headers": [], "body": {"data": _b64("Plain body, no parts.")}},
        }],
    }
    monkeypatch.setattr(gmail_client, "get_service", lambda: service)
    messages = gmail_client.get_thread_messages("thread1")
    assert messages[0]["body"] == "Plain body, no parts."


def test_search_messages_fetches_full_content_for_each_hit(monkeypatch):
    service = MagicMock()
    service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        "messages": [{"id": "bounce1"}],
    }
    service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
        "id": "bounce1",
        "payload": {
            "headers": [{"name": "From", "value": "mailer-daemon@acme.com"}],
            "body": {"data": _b64("Delivery failed for jane@acme.com")},
        },
    }
    monkeypatch.setattr(gmail_client, "get_service", lambda: service)
    results = gmail_client.search_messages("from:mailer-daemon")
    assert results[0]["message_id"] == "bounce1"
    assert "jane@acme.com" in results[0]["body"]


def test_get_thread_messages_extracts_body_from_nested_multipart_alternative(monkeypatch):
    service = MagicMock()
    service.users.return_value.threads.return_value.get.return_value.execute.return_value = {
        "messages": [{
            "id": "msg1",
            "payload": {
                "headers": [{"name": "From", "value": "jane@acme.com"}, {"name": "Date", "value": "Mon, 1 Jan 2026"}],
                "parts": [
                    {
                        "mimeType": "multipart/alternative",
                        "parts": [
                            {"mimeType": "text/plain", "body": {"data": _b64("Nested plain text reply.")}},
                            {"mimeType": "text/html", "body": {"data": _b64("<p>Nested plain text reply.</p>")}},
                        ],
                    }
                ],
            },
        }],
    }
    monkeypatch.setattr(gmail_client, "get_service", lambda: service)
    messages = gmail_client.get_thread_messages("thread1")
    assert messages[0]["body"] == "Nested plain text reply."


def test_extract_message_body_deeply_nested_three_levels_prefers_plain_text():
    """Verify text/plain is found at 3+ levels of nesting and preferred over text/html."""
    message = {
        "payload": {
            "parts": [
                {
                    "mimeType": "multipart/mixed",
                    "parts": [
                        {
                            "mimeType": "multipart/related",
                            "parts": [
                                {
                                    "mimeType": "multipart/alternative",
                                    "parts": [
                                        {"mimeType": "text/plain", "body": {"data": _b64("Deep plain")}},
                                        {"mimeType": "text/html", "body": {"data": _b64("<p>Deep html</p>")}},
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    }
    assert gmail_client._extract_message_body(message) == "Deep plain"


def test_extract_message_body_prefers_deep_plain_text_over_shallow_html():
    """Verify that any text/plain beats any text/html regardless of nesting depth."""
    message = {
        "payload": {
            "parts": [
                {"mimeType": "text/html", "body": {"data": _b64("<p>Shallow html</p>")}},
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {"mimeType": "text/plain", "body": {"data": _b64("Deep plain")}},
                    ],
                },
            ]
        }
    }
    assert gmail_client._extract_message_body(message) == "Deep plain"


def test_extract_message_body_returns_empty_when_no_text_parts_in_nested_tree():
    """Verify empty string when no text/plain or text/html leaves exist anywhere in the tree."""
    message = {
        "payload": {
            "parts": [
                {
                    "mimeType": "multipart/mixed",
                    "parts": [
                        {"mimeType": "application/pdf", "body": {"data": _b64("pdf-content")}},
                        {"mimeType": "image/png", "body": {"data": _b64("png-content")}},
                    ],
                }
            ]
        }
    }
    assert gmail_client._extract_message_body(message) == ""


def test_extract_message_body_skips_parts_with_missing_or_empty_body_data():
    """Verify parts without body.data are skipped and fallback to next candidate works."""
    message = {
        "payload": {
            "parts": [
                {"mimeType": "text/plain", "body": {}},
                {"mimeType": "text/html", "body": {"data": _b64("<p>Fallback html</p>")}},
            ]
        }
    }
    assert gmail_client._extract_message_body(message) == "<p>Fallback html</p>"


def test_extract_message_body_empty_nested_parts_list_treated_as_leaf():
    """Verify an empty nested parts list does not crash; sibling leaf parts are still found."""
    message = {
        "payload": {
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "parts": [],
                },
                {"mimeType": "text/plain", "body": {"data": _b64("Sibling plain")}},
            ]
        }
    }
    assert gmail_client._extract_message_body(message) == "Sibling plain"


def test_extract_message_body_handles_non_dict_items_in_parts_gracefully():
    """Verify non-dict items in the parts list are ignored without crashing."""
    message = {
        "payload": {
            "parts": [
                None,
                "not-a-dict",
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {"mimeType": "text/plain", "body": {"data": _b64("Valid plain")}},
                    ],
                },
            ]
        }
    }
    assert gmail_client._extract_message_body(message) == "Valid plain"


def test_extract_message_body_no_parts_and_no_body_data_returns_empty():
    """Verify empty string when there are no parts and payload.body.data is missing."""
    message = {
        "payload": {
            "body": {},
        }
    }
    assert gmail_client._extract_message_body(message) == ""


def test_extract_message_body_no_parts_and_no_body_key_returns_empty():
    """Verify empty string when payload has no parts and no body key at all."""
    message = {
        "payload": {}
    }
    assert gmail_client._extract_message_body(message) == ""


def test_extract_message_body_flat_list_only_html_no_plain():
    """Verify fallback to text/html in a flat single-level parts list with no text/plain."""
    message = {
        "payload": {
            "parts": [
                {"mimeType": "text/html", "body": {"data": _b64("<h1>Only HTML</h1>")}},
            ]
        }
    }
    assert gmail_client._extract_message_body(message) == "<h1>Only HTML</h1>"


def test_extract_message_body_flat_list_plain_and_html_prefers_plain():
    """Verify text/plain is preferred over text/html in a flat single-level list."""
    message = {
        "payload": {
            "parts": [
                {"mimeType": "text/html", "body": {"data": _b64("<p>HTML</p>")}},
                {"mimeType": "text/plain", "body": {"data": _b64("Plain")}},
            ]
        }
    }
    assert gmail_client._extract_message_body(message) == "Plain"


def test_extract_message_body_unicode_replacement_character():
    """Verify UTF-8 decoding with replacement characters for invalid byte sequences."""
    invalid_bytes = b"\xff\xfe"
    b64_data = base64.urlsafe_b64encode(invalid_bytes).decode("ascii").rstrip("=")
    message = {
        "payload": {
            "parts": [
                {"mimeType": "text/plain", "body": {"data": b64_data}},
            ]
        }
    }
    result = gmail_client._extract_message_body(message)
    assert "�" in result


def test_extract_message_body_single_part_direct_body():
    """Verify non-multipart message with body directly on payload still works."""
    message = {
        "payload": {
            "body": {"data": _b64("Direct body content")},
        }
    }
    assert gmail_client._extract_message_body(message) == "Direct body content"
