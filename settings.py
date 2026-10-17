"""Local settings with lazy environment overrides."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
import tempfile
from uuid import uuid4

import paths

DEFAULTS = {
    'llm': {'provider': 'anthropic', 'model': '', 'api_key': '', 'base_url': '', 'aws_region': 'us-east-1'},
    'integrations': {
        'agentmail': {'api_key': '', 'inbox_id': ''}, 'gmail': {'enabled': False},
        'fullenrich': {'api_key': ''}, 'apify': {'api_token': '', 'max_charge_usd': 5},
        'firecrawl': {'api_key': ''},
    },
    'webhooks': {'secret': '', 'saved_jobs_secret': ''},
    'schedule': {'inbox_scan': '07:00', 'job_sourcing': '04:30', 'gmail_sent_poll_minutes': 15},
}
ENV_MAP = {
    'LLM_PROVIDER': 'llm.provider', 'LLM_MODEL': 'llm.model', 'LLM_API_KEY': 'llm.api_key',
    'LLM_BASE_URL': 'llm.base_url', 'AWS_DEFAULT_REGION': 'llm.aws_region',
    'AGENTMAIL_API_KEY': 'integrations.agentmail.api_key',
    'AGENTMAIL_INBOX_ID': 'integrations.agentmail.inbox_id',
    'FULLENRICH_API_KEY': 'integrations.fullenrich.api_key',
    'APIFY_API_TOKEN': 'integrations.apify.api_token',
    'FIRECRAWL_API_KEY': 'integrations.firecrawl.api_key',
    'WEBHOOK_SECRET': 'webhooks.secret', 'SAVED_JOBS_WEBHOOK_SECRET': 'webhooks.saved_jobs_secret',
}
_load_error = None


def _merge(base, partial):
    result = deepcopy(base)
    for key, value in partial.items():
        result[key] = _merge(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else deepcopy(value)
    return result


def _read_file():
    global _load_error
    try:
        value = json.loads(paths.settings_path().read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise ValueError('Settings must be a JSON object')
    except FileNotFoundError:
        value = {}
    except (ValueError, UnicodeError):
        # Do not include parser input: it may contain credentials.
        _load_error = 'Settings file is invalid; expected a UTF-8 JSON object.'
        return {}
    _load_error = None
    return value


def load():
    return _merge(DEFAULTS, _read_file())


def load_error():
    return _load_error


def get(path, default=None):
    for name, mapped in ENV_MAP.items():
        if mapped == path and os.getenv(name):
            return os.environ[name]
    value = load()
    for part in path.split('.'):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def update(partial):
    global _load_error
    if not isinstance(partial, dict):
        raise ValueError('Settings must be a JSON object')
    value = _merge(load(), partial)
    target = paths.settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if _load_error:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = target.with_name(f'{target.name}.corrupt-{stamp}-{uuid4().hex}')
        with backup.open('xb') as stream:
            stream.write(target.read_bytes())
        os.chmod(backup, 0o600)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent, prefix='.settings-', suffix='.tmp', delete=False) as stream:
            temporary = stream.name
            # ponytail: Windows ignores POSIX modes; data/ is local-only anyway
            os.chmod(temporary, 0o600)
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
        os.replace(temporary, target)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    _load_error = None
    return value


def mask(value):
    value = str(value) if value is not None else ''
    return value[:4] + '…' + value[-4:] if len(value) > 8 else ('…' if value else '')


def _masked(value, secret=False):
    if isinstance(value, dict):
        return {key: _masked(item, secret or key.lower() in ('api_key', 'api_token') or 'secret' in key.lower()) for key, item in value.items()}
    if isinstance(value, list):
        return [_masked(item, secret) for item in value]
    return mask(value) if secret else value


def masked():
    return _masked(load())


def strip_masked(partial):
    if isinstance(partial, dict):
        return {key: strip_masked(value) for key, value in partial.items() if not (isinstance(value, str) and '…' in value)}
    if isinstance(partial, list):
        return [strip_masked(value) for value in partial if not (isinstance(value, str) and '…' in value)]
    return deepcopy(partial)
