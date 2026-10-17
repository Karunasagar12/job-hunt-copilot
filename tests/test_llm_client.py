from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

import llm_client


def _fake_response(text):
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": "end_turn",
    }


def test_call_llm_returns_response_text():
    mock_client = MagicMock()
    mock_client.converse.return_value = _fake_response("Hello there")
    with patch("llm_client.boto3.client", return_value=mock_client):
        result = llm_client.call_llm("You are helpful.", "Say hi")
    assert result == "Hello there"


def test_call_llm_sends_system_and_user_messages():
    mock_client = MagicMock()
    mock_client.converse.return_value = _fake_response("ok")
    with patch("llm_client.boto3.client", return_value=mock_client):
        llm_client.call_llm("SYSTEM PROMPT", "USER TEXT", max_tokens=500)
    kwargs = mock_client.converse.call_args.kwargs
    assert kwargs["system"] == [{"text": "SYSTEM PROMPT"}]
    assert kwargs["messages"] == [{"role": "user", "content": [{"text": "USER TEXT"}]}]
    assert kwargs["inferenceConfig"] == {"maxTokens": 500}


def test_call_llm_omits_system_param_when_empty():
    mock_client = MagicMock()
    mock_client.converse.return_value = _fake_response("ok")
    with patch("llm_client.boto3.client", return_value=mock_client):
        llm_client.call_llm("", "USER TEXT")
    kwargs = mock_client.converse.call_args.kwargs
    assert "system" not in kwargs


def test_call_llm_uses_model_id_env_var(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
    mock_client = MagicMock()
    mock_client.converse.return_value = _fake_response("ok")
    with patch("llm_client.boto3.client", return_value=mock_client):
        llm_client.call_llm("sys", "user")
    kwargs = mock_client.converse.call_args.kwargs
    assert kwargs["modelId"] == "us.anthropic.claude-sonnet-4-6"


def test_call_llm_defaults_to_opus_4_6_model_id(monkeypatch):
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    mock_client = MagicMock()
    mock_client.converse.return_value = _fake_response("ok")
    with patch("llm_client.boto3.client", return_value=mock_client):
        llm_client.call_llm("sys", "user")
    kwargs = mock_client.converse.call_args.kwargs
    assert kwargs["modelId"] == "us.anthropic.claude-opus-4-6-v1"


def test_call_llm_passes_timeout_to_client_config():
    captured = {}

    def _fake_client(service_name, region_name=None, config=None):
        captured["read_timeout"] = config.read_timeout
        mock = MagicMock()
        mock.converse.return_value = _fake_response("ok")
        return mock

    with patch("llm_client.boto3.client", side_effect=_fake_client):
        llm_client.call_llm("sys", "user", timeout=45)
    assert captured["read_timeout"] == 45


def test_call_llm_propagates_client_error():
    mock_client = MagicMock()
    mock_client.converse.side_effect = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
        "Converse",
    )
    with patch("llm_client.boto3.client", return_value=mock_client):
        with pytest.raises(ClientError):
            llm_client.call_llm("sys", "user")
