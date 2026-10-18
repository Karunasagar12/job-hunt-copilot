"""Credential presence, safe connection diagnostics, and API route gates."""
from datetime import datetime, timezone
import os
from pathlib import Path
from urllib.parse import quote

import requests

import paths
import settings

IDS = ('agentmail', 'gmail', 'fullenrich', 'apify', 'firecrawl')
LABELS = {'agentmail': 'AgentMail', 'gmail': 'Gmail', 'fullenrich': 'FullEnrich',
          'apify': 'Apify', 'firecrawl': 'Firecrawl'}
FIELDS = {'agentmail': ('api_key', 'inbox_id'), 'gmail': (), 'fullenrich': ('api_key',),
          'apify': ('api_token',), 'firecrawl': ('api_key',)}


def _val(name, field):
    return settings.get(f'integrations.{name}.{field}')


def _cfg(name):
    value = settings.get(f'integrations.{name}', {})
    return value if isinstance(value, dict) else {}


def _gmail_path(variable, filename):
    raw = os.getenv(variable)
    if not raw:
        return paths.gmail_dir() / filename
    value = Path(raw).expanduser()
    return value if value.is_absolute() else paths.data_dir() / value


def configured(name):
    if name not in IDS:
        return False
    if name == 'gmail':
        return _gmail_path('GMAIL_CREDENTIALS_PATH', 'credentials.json').is_file()
    return all(isinstance(_val(name, field), str) and _val(name, field).strip()
               for field in FIELDS[name])


def status(name):
    state, message = 'not_connected', 'Not configured yet'
    if configured(name):
        last = _cfg(name).get('last_test')
        state, message = 'connected', 'Configured'
        if isinstance(last, dict) and last.get('ok') is False:
            state, message = 'error', 'Connection test failed. Check your credentials and try again.'
        if name == 'gmail' and not _gmail_path('GMAIL_TOKEN_PATH', 'token.json').is_file():
            state, message = 'error', 'Click Connect Gmail to finish sign-in'
    return {'id': name, 'label': LABELS[name], 'state': state, 'message': message,
            'docs_url': f'docs/integrations/{name}.md'}


def all_status():
    return [status(name) for name in IDS]


def connected(name):
    return name in IDS and status(name)['state'] == 'connected'


def connected_ids():
    return {name for name in IDS if connected(name)}


def _test(name):
    if name == 'gmail':
        if not _gmail_path('GMAIL_TOKEN_PATH', 'token.json').is_file():
            return False, 'Click Connect Gmail to finish sign-in'
        from gmail_client import get_service
        get_service().users().getProfile(userId='me').execute()
        return True, 'Connected successfully'
    if name == 'fullenrich':
        from fullenrich_client import check_credentials
        return check_credentials()
    if name == 'agentmail':
        import agentmail_client
        response = requests.get(
            f"{agentmail_client.BASE_URL}/inboxes/{quote(_val(name, 'inbox_id'), safe='')}",
            headers={'Authorization': f'Bearer {agentmail_client._api_key()}'}, timeout=15)
    elif name == 'apify':
        response = requests.get('https://api.apify.com/v2/users/me',
                                headers={'Authorization': f"Bearer {_val(name, 'api_token')}"}, timeout=15)
    else:
        response = requests.post('https://api.firecrawl.dev/v1/search',
                                 headers={'Authorization': f"Bearer {_val(name, 'api_key')}"},
                                 json={'query': 'software engineer salary', 'limit': 1}, timeout=30)
    return (True, 'Connected successfully') if response.status_code == 200 else (False, 'Connection test failed. Check your credentials and try again.')


def run_test(name):
    if not configured(name):
        ok, message = False, 'Not configured yet'
    else:
        try:
            ok, message = _test(name)
        except Exception:
            ok, message = False, 'Connection test failed. Check your credentials and try again.'
    result = {'ok': bool(ok), 'message': message}
    settings.update({'integrations': {name: {'last_test': {
        **result, 'at': datetime.now(timezone.utc).isoformat()}}}})
    return result


def require(name):
    if configured(name):
        return None
    from flask import jsonify
    return jsonify({'error': 'integration_not_connected', 'integration': name, 'status': 409}), 409
