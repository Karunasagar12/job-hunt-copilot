"""Shared Bedrock Converse API helper. No import-time side effects (no
module-level client construction) -- safe to import from any module,
including lightweight standalone scripts (see inbox_classifier.py's own
docstring on why that matters in this codebase)."""
import os

import boto3
from botocore.config import Config

_DEFAULT_MODEL_ID = "us.anthropic.claude-opus-4-6-v1"


def call_llm(system_prompt: str, user_text: str, max_tokens: int = 4096, timeout: int = 300) -> str:
    """Calls the configured Bedrock model via the Converse API and returns the
    plain text response. Raises botocore.exceptions.ClientError/BotoCoreError
    on failure -- callers own their own fallback/error-translation behavior,
    this function is a thin, unopinionated transport."""
    client = boto3.client(
        "bedrock-runtime",
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        config=Config(read_timeout=timeout, connect_timeout=10),
    )
    kwargs = {
        "modelId": os.getenv("BEDROCK_MODEL_ID", _DEFAULT_MODEL_ID),
        "messages": [{"role": "user", "content": [{"text": user_text}]}],
        "inferenceConfig": {"maxTokens": max_tokens},
    }
    if system_prompt:
        kwargs["system"] = [{"text": system_prompt}]
    response = client.converse(**kwargs)
    return response["output"]["message"]["content"][0]["text"]
