import base64
from unittest.mock import patch, MagicMock

import pytest

import agentmail_client as am


def _mock_response(status_code, json_data=None, text="", json_exc=None):
    resp = MagicMock()
    resp.status_code = status_code
    if json_exc is not None:
        resp.json.side_effect = json_exc
    else:
        resp.json.return_value = json_data or {}
    resp.text = text
    return resp


@patch("agentmail_client.requests.post")
def test_send_email_success_calls_send_endpoint(mock_post, monkeypatch):
    monkeypatch.setattr(am, "AGENTMAIL_API_KEY", "test-key")
    mock_post.return_value = _mock_response(200, {"message_id": "m1", "thread_id": "t1"})

    result = am.send_email("idem-1", "inbox-1", "a@acme.com", "Subject", "Body text")

    assert result == {"message_id": "m1", "thread_id": "t1"}
    args, kwargs = mock_post.call_args
    assert args[0] == "https://api.agentmail.to/v0/inboxes/inbox-1/messages/send"
    assert kwargs["headers"]["Idempotency-Key"] == "idem-1"
    assert kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert kwargs["json"]["to"] == ["a@acme.com"]
    assert kwargs["json"]["text"] == "Body text"


@patch("agentmail_client.requests.post")
def test_send_email_with_reply_to_calls_reply_endpoint(mock_post, monkeypatch):
    monkeypatch.setattr(am, "AGENTMAIL_API_KEY", "test-key")
    mock_post.return_value = _mock_response(200, {"message_id": "m2", "thread_id": "t1"})

    am.send_email("idem-2", "inbox-1", "a@acme.com", "Re: Subject", "Body", reply_to_message_id="m1")

    args, _ = mock_post.call_args
    assert args[0] == "https://api.agentmail.to/v0/inboxes/inbox-1/messages/m1/reply"


@patch("agentmail_client.requests.post")
def test_send_email_includes_both_text_and_html_body(mock_post, monkeypatch):
    """Regression: a later replay (Task 8) must resend BOTH fields exactly
    as originally sent -- AgentMail's idempotency contract treats a request
    with different content (including a missing/changed html field) as a
    different request and returns 409."""
    monkeypatch.setattr(am, "AGENTMAIL_API_KEY", "test-key")
    mock_post.return_value = _mock_response(200, {"message_id": "m1", "thread_id": "t1"})

    am.send_email("idem-1", "inbox-1", "a@acme.com", "Subject", "plain body", html_body="<p>styled</p>")

    _, kwargs = mock_post.call_args
    assert kwargs["json"]["text"] == "plain body"
    assert kwargs["json"]["html"] == "<p>styled</p>"


@patch("agentmail_client.requests.post")
def test_send_email_encodes_attachment_bytes_as_base64(mock_post, monkeypatch):
    """Attachments are passed as bytes already in memory -- this module
    never reads a file path, so a replay built from a stored snapshot is
    byte-identical to the original call."""
    monkeypatch.setattr(am, "AGENTMAIL_API_KEY", "test-key")
    mock_post.return_value = _mock_response(200, {"message_id": "m1", "thread_id": "t1"})

    am.send_email("idem-1", "inbox-1", "a@acme.com", "Subject", "Body",
                   attachment_bytes=b"%PDF-1.4 fake content", attachment_filename="cv.pdf")

    _, kwargs = mock_post.call_args
    attachment = kwargs["json"]["attachments"][0]
    assert attachment["filename"] == "cv.pdf"
    assert attachment["content_type"] == "application/pdf"
    assert base64.b64decode(attachment["content"]) == b"%PDF-1.4 fake content"


@patch("agentmail_client.requests.post")
def test_send_email_raises_definitive_error_on_4xx(mock_post, monkeypatch):
    monkeypatch.setattr(am, "AGENTMAIL_API_KEY", "test-key")
    mock_post.return_value = _mock_response(422, text="invalid recipient")

    with pytest.raises(am.AgentMailError):
        am.send_email("idem-1", "inbox-1", "bad", "Subject", "Body")


@patch("agentmail_client.requests.post")
def test_send_email_raises_replay_mismatch_on_409(mock_post, monkeypatch):
    """Regression: a 409 must raise a DISTINCT exception from AgentMailError
    -- it must never be treated as a definitive failure (the original
    attempt may have actually succeeded), and must never allow a caller to
    conclude 'failed' and permit a fresh retry."""
    monkeypatch.setattr(am, "AGENTMAIL_API_KEY", "test-key")
    mock_post.return_value = _mock_response(409, text="idempotency key conflict")

    with pytest.raises(am.AgentMailReplayMismatch):
        am.send_email("idem-1", "inbox-1", "a@acme.com", "Subject", "Body")


@patch("agentmail_client.requests.post")
def test_send_email_raises_ambiguous_on_5xx(mock_post, monkeypatch):
    monkeypatch.setattr(am, "AGENTMAIL_API_KEY", "test-key")
    mock_post.return_value = _mock_response(503, text="upstream error")

    with pytest.raises(am.AgentMailAmbiguous):
        am.send_email("idem-1", "inbox-1", "a@acme.com", "Subject", "Body")


@patch("agentmail_client.requests.post")
def test_send_email_raises_ambiguous_on_timeout(mock_post, monkeypatch):
    import requests
    monkeypatch.setattr(am, "AGENTMAIL_API_KEY", "test-key")
    mock_post.side_effect = requests.exceptions.Timeout("timed out")

    with pytest.raises(am.AgentMailAmbiguous):
        am.send_email("idem-1", "inbox-1", "a@acme.com", "Subject", "Body")


@patch("agentmail_client.requests.post")
def test_send_email_raises_ambiguous_on_200_with_invalid_json(mock_post, monkeypatch):
    """A 200 whose body isn't valid JSON must never leak a raw JSONDecodeError
    -- callers only catch AgentMailError/AgentMailReplayMismatch/AgentMailAmbiguous,
    so anything else would surface as an unhandled 500 and strand the row in
    'sending' instead of 'uncertain'."""
    monkeypatch.setattr(am, "AGENTMAIL_API_KEY", "test-key")
    mock_post.return_value = _mock_response(200, text="not json", json_exc=ValueError("invalid json"))

    with pytest.raises(am.AgentMailAmbiguous):
        am.send_email("idem-1", "inbox-1", "a@acme.com", "Subject", "Body")


@patch("agentmail_client.requests.post")
def test_send_email_raises_ambiguous_on_200_missing_message_id(mock_post, monkeypatch):
    monkeypatch.setattr(am, "AGENTMAIL_API_KEY", "test-key")
    mock_post.return_value = _mock_response(200, {"thread_id": "t1"})

    with pytest.raises(am.AgentMailAmbiguous):
        am.send_email("idem-1", "inbox-1", "a@acme.com", "Subject", "Body")


@patch("agentmail_client.requests.post")
def test_send_email_raises_ambiguous_on_200_missing_thread_id(mock_post, monkeypatch):
    monkeypatch.setattr(am, "AGENTMAIL_API_KEY", "test-key")
    mock_post.return_value = _mock_response(200, {"message_id": "m1"})

    with pytest.raises(am.AgentMailAmbiguous):
        am.send_email("idem-1", "inbox-1", "a@acme.com", "Subject", "Body")


@patch("agentmail_client.requests.post")
def test_send_email_raises_ambiguous_on_200_non_dict_json(mock_post, monkeypatch):
    monkeypatch.setattr(am, "AGENTMAIL_API_KEY", "test-key")
    mock_post.return_value = _mock_response(200, ["message_id", "thread_id"])

    with pytest.raises(am.AgentMailAmbiguous):
        am.send_email("idem-1", "inbox-1", "a@acme.com", "Subject", "Body")


@patch("agentmail_client.requests.post")
def test_send_email_well_formed_200_still_returns_ids(mock_post, monkeypatch):
    """Regression guard: the new validation must not reject a normal response."""
    monkeypatch.setattr(am, "AGENTMAIL_API_KEY", "test-key")
    mock_post.return_value = _mock_response(200, {"message_id": "m1", "thread_id": "t1"})

    result = am.send_email("idem-1", "inbox-1", "a@acme.com", "Subject", "Body")

    assert result == {"message_id": "m1", "thread_id": "t1"}


@patch("agentmail_client.requests.post")
def test_send_email_pdf_then_extra_attachments_verbatim(mock_post, monkeypatch):
    """extra_attachments (inline CID signature images) are appended AFTER the
    CV, byte-for-byte as given -- never re-encoded, so a replay from a stored
    snapshot stays identical to the original call."""
    monkeypatch.setattr(am, "AGENTMAIL_API_KEY", "test-key")
    mock_post.return_value = _mock_response(200, {"message_id": "m1", "thread_id": "t1"})
    inline = {"filename": "signature-0.png", "content_type": "image/png", "content": "aW1hZ2U=",
              "content_disposition": "inline", "content_id": "signature-image-0@jobhunt.local"}

    am.send_email("idem-1", "inbox-1", "a@acme.com", "Subject", "Body",
                   attachment_bytes=b"%PDF-1.4", attachment_filename="cv.pdf",
                   extra_attachments=[inline])

    _, kwargs = mock_post.call_args
    attachments = kwargs["json"]["attachments"]
    assert len(attachments) == 2
    assert attachments[0]["filename"] == "cv.pdf"
    assert "content_disposition" not in attachments[0]
    assert attachments[1] is inline


@patch("agentmail_client.requests.post")
def test_send_email_extra_attachments_without_pdf(mock_post, monkeypatch):
    monkeypatch.setattr(am, "AGENTMAIL_API_KEY", "test-key")
    mock_post.return_value = _mock_response(200, {"message_id": "m1", "thread_id": "t1"})
    inline = [{"filename": "sig.png", "content_type": "image/png", "content": "abc=",
               "content_disposition": "inline", "content_id": "sig@local"}]

    am.send_email("idem-1", "inbox-1", "a@acme.com", "Subject", "Body", extra_attachments=inline)

    assert mock_post.call_args.kwargs["json"]["attachments"] == inline


@patch("agentmail_client.requests.post")
def test_send_email_no_attachments_omits_key(mock_post, monkeypatch):
    monkeypatch.setattr(am, "AGENTMAIL_API_KEY", "test-key")
    mock_post.return_value = _mock_response(200, {"message_id": "m1", "thread_id": "t1"})

    am.send_email("idem-1", "inbox-1", "a@acme.com", "Subject", "Body")

    assert "attachments" not in mock_post.call_args.kwargs["json"]


@patch("agentmail_client.requests.get")
def test_get_thread_messages_single_page(mock_get, monkeypatch):
    monkeypatch.setattr(am, "AGENTMAIL_API_KEY", "test-key")
    resp = MagicMock()
    resp.json.return_value = {"messages": [{"message_id": "m1"}], "next_page_token": None}
    mock_get.return_value = resp

    messages = am.get_thread_messages("inbox-1", "thread-1")

    assert messages == [{"message_id": "m1"}]
    resp.raise_for_status.assert_called_once()


@patch("agentmail_client.requests.get")
def test_get_thread_messages_paginates_until_exhausted(mock_get, monkeypatch):
    monkeypatch.setattr(am, "AGENTMAIL_API_KEY", "test-key")
    page1 = MagicMock()
    page1.json.return_value = {"messages": [{"message_id": "m1"}], "next_page_token": "tok2"}
    page2 = MagicMock()
    page2.json.return_value = {"messages": [{"message_id": "m2"}], "next_page_token": None}
    mock_get.side_effect = [page1, page2]

    messages = am.get_thread_messages("inbox-1", "thread-1")

    assert [m["message_id"] for m in messages] == ["m1", "m2"]
    assert mock_get.call_count == 2
    assert "page_token" not in mock_get.call_args_list[0].kwargs["params"]
    assert mock_get.call_args_list[1].kwargs["params"]["page_token"] == "tok2"


@patch("agentmail_client.requests.get")
def test_get_thread_messages_raises_on_http_error(mock_get, monkeypatch):
    import requests
    monkeypatch.setattr(am, "AGENTMAIL_API_KEY", "test-key")
    resp = MagicMock()
    resp.raise_for_status.side_effect = requests.exceptions.HTTPError("403")
    mock_get.return_value = resp

    with pytest.raises(requests.exceptions.HTTPError):
        am.get_thread_messages("inbox-1", "thread-1")
