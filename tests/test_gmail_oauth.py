"""Optional Gmail and localhost web OAuth, without real Google requests."""
import io
import json
import base64
import hashlib
import subprocess
import sys
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock

import pytest

import gmail_client as gmail
import integrations


@pytest.fixture(autouse=True)
def gmail_paths(monkeypatch):
    monkeypatch.delenv('GMAIL_CREDENTIALS_PATH', raising=False)
    monkeypatch.delenv('GMAIL_TOKEN_PATH', raising=False)
    monkeypatch.delenv('OAUTHLIB_INSECURE_TRANSPORT', raising=False)
    import api.settings_routes as routes
    monkeypatch.setattr(routes, '_gmail_oauth_states', set())
    monkeypatch.setattr(gmail, '_authorization_flows', {})


def test_api_import_without_google_packages():
    code = """
import sys
class BlockGoogle:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('google', 'google_auth_oauthlib')):
            raise ImportError('Google blocked by test')
sys.meta_path.insert(0, BlockGoogle())
import api.app
assert 'gmail_client' not in sys.modules
import gmail_client
assert gmail_client.compose_html_body('hello', '')
try:
    gmail_client._google()
except RuntimeError as exc:
    assert str(exc) == 'Gmail support needs the Google packages (included in the Docker image).'
else:
    raise AssertionError('Google dependency error missing')
"""
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('value', [{}, [], None, {'web': []}, {'web': {'client_id': [], 'client_secret': 'dummy'}}, {'installed': {'client_id': 'dummy'}}])
def test_upload_rejects_malformed_credentials(client, value):
    response = client.post('/api/gmail/credentials', data={'credentials': (io.BytesIO(json.dumps(value).encode()), 'credentials.json')})
    assert response.status_code == 400
    assert response.get_json()['error']


@pytest.mark.parametrize('kind', ['web', 'installed'])
def test_upload_saves_credentials_without_google(client, monkeypatch, kind):
    value = {kind: {'client_id': 'dummy-client', 'client_secret': 'dummy-secret'}}
    monkeypatch.setattr(gmail, '_flow', Mock(side_effect=AssertionError('must not authenticate')), raising=False)
    response = client.post('/api/gmail/credentials', data={'credentials': (io.BytesIO(json.dumps(value).encode()), 'credentials.json')})
    assert response.status_code == 200
    assert json.loads(gmail._credentials_path().read_text()) == value
    assert 'dummy-secret' not in response.get_data(as_text=True)


def test_upload_invalid_json_and_missing_file(client):
    assert client.post('/api/gmail/credentials').status_code == 400
    assert client.post('/api/gmail/credentials', data={'credentials': (io.BytesIO(b'{bad'), 'x.json')}).status_code == 400


def test_connect_callback_and_replay(client, monkeypatch):
    states = []
    def authorize(state):
        states.append(state)
        return 'https://accounts.google.com/o/oauth2/auth?state=' + state
    monkeypatch.setattr(gmail, 'authorization_url', authorize, raising=False)
    finish = Mock()
    monkeypatch.setattr(gmail, 'finish_authorization', finish, raising=False)
    first = client.get('/api/gmail/connect')
    assert first.status_code == 302 and first.location.startswith('https://accounts.google.com/')
    client.get('/api/gmail/connect')
    assert states[0] != states[1] and len(states[0]) >= 32
    assert client.get('/api/gmail/callback?code=dummy&state=wrong').status_code == 400
    assert client.get('/api/gmail/callback?code=dummy').status_code == 400
    response = client.get('/api/gmail/callback', query_string={'code': 'dummy-code', 'state': states[0]})
    assert response.status_code == 302
    assert response.location == 'http://127.0.0.1:8080/settings?gmail=connected'
    finish.assert_called_once_with('dummy-code', states[0])
    assert client.get('/api/gmail/callback', query_string={'code': 'dummy-code', 'state': states[0]}).status_code == 400


def test_callback_failure_is_safe_and_consumes_state(client, monkeypatch):
    seen = []
    monkeypatch.setattr(gmail, 'authorization_url', lambda state: seen.append(state) or 'https://accounts.google.com/', raising=False)
    finish = Mock(side_effect=RuntimeError('dummy-private-code'))
    monkeypatch.setattr(gmail, 'finish_authorization', finish, raising=False)
    client.get('/api/gmail/connect')
    response = client.get('/api/gmail/callback', query_string={'code': 'dummy', 'state': seen[0]})
    assert response.status_code == 400 and 'dummy-private-code' not in response.get_data(as_text=True)
    assert client.get('/api/gmail/callback', query_string={'code': 'dummy', 'state': seen[0]}).status_code == 400
    assert finish.call_count == 1


def test_flow_redirect_state_and_token_save(monkeypatch, gmail_credentials):
    import google_auth_oauthlib.flow
    flow = Mock()
    flow.authorization_url.return_value = ('https://accounts.google.com/dummy', 'dummy-state')
    flow.credentials.to_json.return_value = '{"dummy": true}'
    factory = Mock(return_value=flow)
    monkeypatch.setattr(google_auth_oauthlib.flow.Flow, 'from_client_secrets_file', factory)
    assert gmail.authorization_url('dummy-state') == 'https://accounts.google.com/dummy'
    factory.assert_called_with(str(gmail._credentials_path()), scopes=gmail.SCOPES, redirect_uri='http://localhost:8080/api/gmail/callback', state='dummy-state')
    flow.authorization_url.assert_called_once_with(access_type='offline', prompt='consent', state='dummy-state')
    gmail.finish_authorization('dummy-code', 'dummy-state')
    flow.fetch_token.assert_called_once_with(code='dummy-code')
    assert json.loads(gmail._token_path().read_text()) == {'dummy': True}


def test_callback_persists_token_at_override_path(client, monkeypatch, gmail_credentials):
    import google_auth_oauthlib.flow
    import paths
    monkeypatch.setenv('GMAIL_TOKEN_PATH', 'alternate/token.json')
    flow = Mock()
    flow.authorization_url.return_value = ('https://accounts.google.com/dummy', 'unused')
    flow.credentials.to_json.return_value = '{"dummy": true}'
    factory = Mock(return_value=flow)
    monkeypatch.setattr(google_auth_oauthlib.flow.Flow, 'from_client_secrets_file', factory)
    import api.settings_routes as routes
    assert client.get('/api/gmail/connect').status_code == 302
    state = next(iter(routes._gmail_oauth_states))
    response = client.get('/api/gmail/callback', query_string={'code': 'dummy-code', 'state': state})
    assert response.status_code == 302
    assert response.location == 'http://127.0.0.1:8080/settings?gmail=connected'
    assert json.loads(paths.data('alternate/token.json').read_text()) == {'dummy': True}
    flow.fetch_token.assert_called_once_with(code='dummy-code')
    factory.assert_called_with(str(gmail._credentials_path()), scopes=gmail.SCOPES, redirect_uri=gmail.REDIRECT_URI, state=state)
    assert integrations.connected('gmail')
    assert client.post('/api/gmail/disconnect').status_code == 200
    assert not paths.data('alternate/token.json').exists()
    assert gmail._credentials_path().exists()


def test_actual_sdk_preserves_pkce_for_each_single_use_callback(client, monkeypatch, gmail_credentials):
    from requests_oauthlib import OAuth2Session
    gmail._credentials_path().write_text(json.dumps({'web': {
        'client_id': 'dummy-client', 'client_secret': 'dummy-secret',
        'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
        'token_uri': 'https://oauth2.googleapis.com/token',
    }}), encoding='utf-8')
    exchanges = {}

    def fetch_token(session, token_url, **kwargs):
        exchanges[kwargs['code']] = kwargs
        session.token = {'access_token': 'dummy-access', 'refresh_token': 'dummy-refresh',
                         'token_type': 'Bearer', 'expires_at': 2000000000}
        return session.token

    monkeypatch.setattr(OAuth2Session, 'fetch_token', fetch_token)
    first = parse_qs(urlsplit(client.get('/api/gmail/connect').location).query)
    second = parse_qs(urlsplit(client.get('/api/gmail/connect').location).query)
    assert first['code_challenge_method'] == second['code_challenge_method'] == ['S256']
    assert first['state'] != second['state']
    for code, consent in (('dummy-second', second), ('dummy-first', first)):
        state = consent['state'][0]
        response = client.get('/api/gmail/callback', query_string={'code': code, 'state': state})
        verifier = exchanges[code]['code_verifier']
        assert isinstance(verifier, str) and verifier
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).decode('ascii').rstrip('=')
        assert challenge == consent['code_challenge'][0]
        assert response.status_code == 302
        assert response.location == 'http://127.0.0.1:8080/settings?gmail=connected'
        assert json.loads(gmail._token_path().read_text())['refresh_token'] == 'dummy-refresh'
        assert client.get('/api/gmail/callback', query_string={'code': code, 'state': state}).status_code == 400
        with pytest.raises(RuntimeError, match='expired|state|Connect|connect'):
            gmail.finish_authorization(code, state)
    assert len(exchanges) == 2


@pytest.mark.parametrize('token', ['[]', 'null', '"dummy"', '{"refresh_token":"dummy","client_id":"dummy","client_secret":"dummy","expiry":[]}', '{"refresh_token":"dummy","client_id":"dummy","client_secret":"dummy","expiry":123}'])
def test_actual_malformed_token_has_readable_error(gmail_credentials, token, monkeypatch):
    from google.auth.exceptions import RefreshError
    from google.oauth2.credentials import Credentials
    monkeypatch.setattr(Credentials, 'refresh', Mock(side_effect=RefreshError('dummy-invalid-token')))
    gmail._token_path().write_text(token, encoding='utf-8')
    with pytest.raises(RuntimeError, match='Gmail not connected'):
        gmail.get_service()


def test_refresh_saves_token_and_returns_service(gmail_credentials, monkeypatch):
    from google.oauth2.credentials import Credentials
    import googleapiclient.discovery
    gmail._token_path().write_text('{}', encoding='utf-8')
    creds = Mock(valid=True, expired=True, refresh_token='dummy')
    creds.to_json.return_value = '{"refreshed": true}'
    monkeypatch.setattr(Credentials, 'from_authorized_user_file', Mock(return_value=creds))
    build = Mock(return_value='dummy-service')
    monkeypatch.setattr(googleapiclient.discovery, 'build', build)
    assert gmail.get_service() == 'dummy-service'
    creds.refresh.assert_called_once()
    assert json.loads(gmail._token_path().read_text()) == {'refreshed': True}
    build.assert_called_once_with('gmail', 'v1', credentials=creds)


def test_draft_detection_without_google_remains_unknown(monkeypatch):
    monkeypatch.setattr(gmail, '_google', Mock(side_effect=RuntimeError('Google packages missing')))
    assert gmail.check_draft_sent('dummy-draft') is None


def test_missing_token_is_noninteractive(gmail_credentials):
    with pytest.raises(RuntimeError, match='Gmail not connected'):
        gmail.get_service()


def test_missing_credentials_is_readable():
    with pytest.raises(RuntimeError, match='Gmail credentials not uploaded'):
        gmail.get_service()


@pytest.mark.parametrize('mode', ['malformed', 'invalid', 'refresh_failure'])
def test_unusable_token_never_opens_browser(gmail_credentials, monkeypatch, mode):
    from google.oauth2.credentials import Credentials
    from google.auth.exceptions import RefreshError
    from google_auth_oauthlib.flow import InstalledAppFlow
    gmail._token_path().write_text('{}', encoding='utf-8')
    forbidden = Mock(side_effect=AssertionError('interactive OAuth forbidden'))
    monkeypatch.setattr(InstalledAppFlow, 'run_local_server', forbidden)
    creds = Mock(valid=False, expired=mode == 'refresh_failure', refresh_token='dummy')
    creds.refresh.side_effect = RefreshError('dummy-private-refresh')
    loader = Mock(side_effect=ValueError('bad token')) if mode == 'malformed' else Mock(return_value=creds)
    monkeypatch.setattr(Credentials, 'from_authorized_user_file', loader)
    with pytest.raises(RuntimeError, match='Gmail not connected'):
        gmail.get_service()
    result = integrations.run_test('gmail')
    assert result['ok'] is False and 'dummy-private-refresh' not in result['message']
    forbidden.assert_not_called()


def test_disconnect_retains_credentials(client, gmail_credentials):
    gmail._token_path().write_text('{}', encoding='utf-8')
    assert client.post('/api/gmail/disconnect').status_code == 200
    assert not gmail._token_path().exists() and gmail._credentials_path().exists()
    assert client.post('/api/gmail/disconnect').status_code == 200


@pytest.mark.parametrize('agentmail,gmail_connected,provider', [(False, False, 'agentmail'), (True, False, 'agentmail'), (False, True, 'gmail'), (True, True, 'agentmail')])
def test_outreach_selects_connected_provider(client, monkeypatch, agentmail, gmail_connected, provider):
    import api.app as api
    monkeypatch.setattr(integrations, 'connected', lambda name: agentmail if name == 'agentmail' else gmail_connected)
    monkeypatch.setattr(api.db, 'get_job', lambda job_id: {'id': job_id, 'outreach_raw': 'dummy'})
    monkeypatch.setattr(api.db, '_get_conn', lambda: SimpleNamespace(execute=lambda *a: SimpleNamespace(fetchone=lambda: None)))
    monkeypatch.setattr(api.db, 'get_contacts', lambda job_id: [{'id': 1, 'name': 'Example'}])
    monkeypatch.setattr(api.outreach_manager, 'get_unmatched_contacts', lambda *a: [])
    monkeypatch.setattr(api.outreach_manager, 'parse_and_schedule', lambda *a: [dict(contact_id=1, channel='email', sequence_num=1, scheduled_date='2026-10-18', subject='Example', content='Example')])
    create = Mock()
    monkeypatch.setattr(api.db, 'create_outreach_entry', create)
    assert client.post('/api/jobs/1/outreach/start').status_code == 200
    assert create.call_args.kwargs['provider'] == provider


@pytest.mark.parametrize('script', ['poll_gmail_inbox.py', 'poll_gmail_sent.py'])
def test_disconnected_poll_entrypoint_skips(script):
    result = subprocess.run([sys.executable, script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'gmail not connected; skipping' in result.stdout
