"""Integration credentials, safe diagnostics, and early route gates."""
import importlib
from unittest.mock import Mock

import pytest

import paths
import settings


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch):
    for name in settings.ENV_MAP:
        if name.startswith(('AGENTMAIL_', 'FULLENRICH_', 'APIFY_', 'FIRECRAWL_')):
            monkeypatch.delenv(name, raising=False)
    for name in ('GMAIL_CREDENTIALS_PATH', 'GMAIL_TOKEN_PATH'):
        monkeypatch.delenv(name, raising=False)


def module():
    return importlib.import_module('integrations')


def test_all_unconfigured(client):
    response = client.get('/api/integrations')
    assert response.status_code == 200
    items = response.get_json()
    assert [item['id'] for item in items] == ['agentmail', 'gmail', 'fullenrich', 'apify', 'firecrawl']
    assert all(item['state'] == 'not_connected' for item in items)
    assert all(item['docs_url'] == f"docs/integrations/{item['id']}.md" for item in items)
    assert module().connected_ids() == set()


@pytest.mark.parametrize('url,integration', [
    ('/api/outreach/999/prepare', 'agentmail'),
    ('/api/outreach/999/send', 'agentmail'),
    ('/api/outreach/999/check-status', 'agentmail'),
    ('/api/outreach/999/retry', 'agentmail'),
    ('/api/outreach/999/gmail-draft', 'gmail'),
    ('/api/outreach/batch-draft', 'gmail'),
    ('/api/contacts/999/get-email', 'fullenrich'),
    ('/api/contacts/match-linkedin', 'fullenrich'),
])
def test_gate_precedes_validation(client, url, integration):
    response = client.post(url, data='{bad', content_type='application/json')
    assert response.status_code == 409
    assert response.get_json() == {'error': 'integration_not_connected', 'integration': integration, 'status': 409}


def test_configuration_test_failure_persistence_and_reset(client, monkeypatch):
    api = module()
    secret = 'credential-private-value'
    response = client.put('/api/integrations/firecrawl', json={'api_key': secret, 'last_test': {'ok': False}})
    assert response.get_json()['state'] == 'connected'
    assert secret not in response.get_data(as_text=True)
    monkeypatch.setattr(api, '_test', lambda name: (False, 'Invalid key'))
    assert client.post('/api/integrations/firecrawl/test').get_json() == {'ok': False, 'message': 'Invalid key'}
    assert api.status('firecrawl')['state'] == 'error'
    stored = settings.get('integrations.firecrawl.last_test')
    assert stored['ok'] is False and stored['message'] == 'Invalid key' and stored['at']
    assert api.require('firecrawl') is None
    response = client.put('/api/integrations/firecrawl', json={'api_key': settings.mask(secret)})
    assert response.get_json()['state'] == 'connected'
    assert settings.get('integrations.firecrawl.api_key') == secret
    assert settings.get('integrations.firecrawl.last_test') is None
    monkeypatch.setattr(api, '_test', lambda name: (True, 'Connected'))
    assert api.run_test('firecrawl')['ok'] is True
    assert 'firecrawl' in api.connected_ids()


def test_environment_leaf_and_gmail_files(monkeypatch):
    api = module()
    monkeypatch.setenv('FULLENRICH_API_KEY', 'environment-key')
    assert api.configured('fullenrich')
    paths.gmail_dir().mkdir(parents=True, exist_ok=True)
    paths.gmail_dir().joinpath('credentials.json').write_text('{}', encoding='utf-8')
    assert api.configured('gmail')
    assert api.status('gmail')['state'] == 'error'
    assert api.status('gmail')['message'] == 'Click Connect Gmail to finish sign-in'
    paths.gmail_dir().joinpath('token.json').write_text('{}', encoding='utf-8')
    assert api.connected('gmail')


@pytest.mark.parametrize('body', [[], None, {'api_key': []}, {'api_key': {}}, {'api_key': 12}])
def test_malformed_config_is_readable_400(client, body):
    response = client.put('/api/integrations/firecrawl', json=body)
    assert response.status_code == 400
    assert response.get_json()['error']


def test_invalid_json_and_unknown_id(client):
    assert client.put('/api/integrations/unknown', json={}).status_code == 404
    assert client.post('/api/integrations/unknown/test').status_code == 404
    assert client.put('/api/integrations/firecrawl', data='{bad', content_type='application/json').status_code == 400


def test_unconfigured_and_exception_safe(monkeypatch):
    api = module()
    assert api.run_test('apify') == {'ok': False, 'message': 'Not configured yet'}
    settings.update({'integrations': {'apify': {'api_token': 'private-key'}}})
    def explode(name):
        raise RuntimeError('private-key reflected response')
    monkeypatch.setattr(api, '_test', explode)
    result = api.run_test('apify')
    assert result['ok'] is False
    assert 'private-key' not in str(result) + str(settings.get('integrations.apify.last_test'))


@pytest.mark.parametrize('name,url,method,timeout', [
    ('agentmail', 'https://api.agentmail.to/v0/inboxes/inbox', 'get', 15),
    ('fullenrich', 'https://app.fullenrich.com/api/v2/account/credits', 'get', 15),
    ('apify', 'https://api.apify.com/v2/users/me', 'get', 15),
    ('firecrawl', 'https://api.firecrawl.dev/v1/search', 'post', 30),
])
def test_cheap_authenticated_requests(monkeypatch, name, url, method, timeout):
    api = module()
    settings.update({'integrations': {name: {'api_key': 'private-key', 'api_token': 'private-key', 'inbox_id': 'inbox'}}})
    request = Mock(return_value=Mock(status_code=200))
    monkeypatch.setattr('requests.' + method, request)
    assert api.run_test(name)['ok'] is True
    args, kwargs = request.call_args
    assert args == (url,)
    assert kwargs['headers']['Authorization'] == 'Bearer private-key'
    assert kwargs['timeout'] == timeout
    if name == 'firecrawl':
        assert kwargs['json'] == {'query': 'software engineer salary', 'limit': 1}
    request.return_value.status_code = 401
    request.return_value.text = 'private-key'
    assert api.run_test(name)['ok'] is False
    assert 'private-key' not in api.status(name)['message']


def test_gmail_profile_check(monkeypatch):
    import gmail_client
    api = module()
    paths.gmail_dir().mkdir(parents=True, exist_ok=True)
    for filename in ('credentials.json', 'token.json'):
        paths.gmail_dir().joinpath(filename).write_text('{}', encoding='utf-8')
    service = Mock()
    monkeypatch.setattr(gmail_client, 'get_service', lambda: service)
    assert api.run_test('gmail')['ok'] is True
    service.users.return_value.getProfile.assert_called_once_with(userId='me')
    service.users.return_value.getProfile.return_value.execute.assert_called_once_with()
