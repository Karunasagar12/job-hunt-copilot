"""Lazy multi-provider LLM transport with safe, actionable errors."""
import os
import re
from pathlib import Path

import settings

PROVIDERS = ('anthropic', 'openrouter', 'openai_compatible', 'bedrock')
DEFAULT_MODELS = {
    'anthropic': 'claude-sonnet-5-5',
    'openrouter': 'anthropic/claude-sonnet-5.5',
    'openai_compatible': '',
    'bedrock': 'us.anthropic.claude-opus-4-6-v1',
}
# Verified against official provider pages on 2026-10-18; shared with Settings UI.
RECOMMENDED_MODELS = {
    'anthropic': ('claude-sonnet-5-5', 'claude-opus-5-5', 'claude-haiku-5-5'),
    'openrouter': ('anthropic/claude-sonnet-5.5', 'anthropic/claude-opus-5.5', 'anthropic/claude-haiku-5.5'),
    'bedrock': (DEFAULT_MODELS['bedrock'],),
}
_MESSAGES = {
    'auth': 'Authentication failed. Check your credentials in Settings.',
    'not_found': 'Model not found. Check the model and provider in Settings.',
    'rate_limit': 'Provider rate limit reached. Wait and try again.',
    'timeout': 'The model request timed out. Please retry.',
    'bad_request': 'The provider rejected the request. Check the model and configuration in Settings.',
    'unavailable': 'The provider is unavailable. Check network connectivity and retry.',
    'unknown': 'The model request failed. Check Settings and try again.',
    'config': 'LLM configuration is incomplete or unsupported. Check Settings.',
}


class LLMError(RuntimeError):
    def __init__(self, kind, message):
        self.kind = kind
        super().__init__(message)


def is_configured():
    provider = settings.get('llm.provider')
    if provider in ('fake', 'bedrock'):
        return True
    if provider in ('anthropic', 'openrouter'):
        return bool(settings.get('llm.api_key'))
    if provider == 'openai_compatible':
        return bool(settings.get('llm.base_url') and settings.get('llm.model'))
    return False


def _error_kind(exc):
    response = getattr(exc, 'response', None)
    code = response.get('Error', {}).get('Code', '') if isinstance(response, dict) else ''
    categories = {
        'auth': ('AuthenticationError', 'PermissionDeniedError', 'AccessDeniedException', 'UnrecognizedClientException', 'NoCredentialsError', 'PartialCredentialsError', 'ExpiredTokenException', 'InvalidSignatureException'),
        'not_found': ('NotFoundError', 'ResourceNotFoundException'),
        'rate_limit': ('RateLimitError', 'ThrottlingException', 'TooManyRequestsException'),
        'timeout': ('APITimeoutError', 'ModelTimeoutException', 'ReadTimeoutError', 'ConnectTimeoutError', 'TimeoutError'),
        'bad_request': ('BadRequestError', 'ValidationException'),
        'unavailable': ('APIConnectionError', 'InternalServerError', 'ServiceUnavailableError', 'ServiceUnavailableException', 'InternalServerException', 'EndpointConnectionError', 'ConnectionClosedError', 'ConnectionError', 'HTTPClientError'),
    }
    names = {cls.__name__ for cls in type(exc).__mro__} | {code}
    return next((kind for kind, values in categories.items() if names.intersection(values)), 'unknown')


def _fake(system_prompt, user_text):
    match = re.search(r'<!-- skill: ([a-z0-9-]+) -->', system_prompt) or re.search(r'<!-- skill: ([a-z0-9-]+) -->', user_text)
    if not match:
        return 'OK'
    skill = match.group(1)
    if skill == 'humanizer':
        return user_text
    if skill == 'profile-builder' and 'MODE:apply_gaps' in user_text.replace(' ', ''):
        skill = 'profile-builder-gaps'
    try:
        return (Path(__file__).resolve().parent / 'fake_llm' / (skill + '.txt')).read_text(encoding='utf-8')
    except OSError:
        raise LLMError('config', 'Fake output is missing for skill ' + skill + '.') from None


def call_llm(system_prompt: str, user_text: str, max_tokens: int = 4096, timeout: int = 300) -> str:
    if not is_configured():
        raise LLMError('config', _MESSAGES['config'])
    provider = settings.get('llm.provider')
    model = settings.get('llm.model') or DEFAULT_MODELS.get(provider, '')
    try:
        if provider == 'fake':
            return _fake(system_prompt, user_text)
        if provider == 'anthropic':
            from anthropic import Anthropic
            client = Anthropic(api_key=settings.get('llm.api_key'), timeout=timeout, max_retries=2)
            response = client.messages.create(model=model, system=system_prompt, messages=[{'role': 'user', 'content': user_text}], max_tokens=max_tokens)
            return ''.join(block.text for block in response.content if block.type == 'text')
        if provider in ('openrouter', 'openai_compatible'):
            from openai import OpenAI
            base_url = 'https://openrouter.ai/api/v1' if provider == 'openrouter' else settings.get('llm.base_url')
            client = OpenAI(api_key=settings.get('llm.api_key') or 'not-needed', base_url=base_url, timeout=timeout, max_retries=2)
            response = client.chat.completions.create(model=model, messages=[{'role': 'system', 'content': system_prompt}, {'role': 'user', 'content': user_text}], max_tokens=max_tokens)
            return response.choices[0].message.content or ''
        if provider == 'bedrock':
            import boto3
            from botocore.config import Config
            client = boto3.client('bedrock-runtime', region_name=settings.get('llm.aws_region') or 'us-east-1', config=Config(read_timeout=timeout, connect_timeout=10))
            kwargs = {'modelId': os.getenv('BEDROCK_MODEL_ID') or model, 'messages': [{'role': 'user', 'content': [{'text': user_text}]}], 'inferenceConfig': {'maxTokens': max_tokens}}
            if system_prompt:
                kwargs['system'] = [{'text': system_prompt}]
            response = client.converse(**kwargs)
            return ''.join(block['text'] for block in response['output']['message']['content'] if 'text' in block)
    except LLMError:
        raise
    except Exception as exc:
        kind = _error_kind(exc)
        raise LLMError(kind, _MESSAGES[kind]) from None
    raise LLMError('config', _MESSAGES['config'])
