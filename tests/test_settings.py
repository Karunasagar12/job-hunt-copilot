import importlib
import json

import pytest

import paths


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    module = importlib.import_module('settings')
    for name in getattr(module, 'ENV_MAP', {}):
        monkeypatch.delenv(name, raising=False)
    return module


def test_defaults_and_lazy_environment(cfg, monkeypatch):
    assert cfg.load()['llm']['provider'] == 'anthropic'
    assert cfg.get('schedule.gmail_sent_poll_minutes') == 15
    cfg.update({'llm': {'provider': 'file'}})
    monkeypatch.setenv('LLM_PROVIDER', 'environment')
    assert cfg.get('llm.provider') == 'environment'
    assert cfg.load()['llm']['provider'] == 'file'
    monkeypatch.setenv('LLM_PROVIDER', '')
    assert cfg.get('llm.provider') == 'file'
    assert cfg.get('missing.path', 'fallback') == 'fallback'


def test_deep_merge_and_atomic_save(cfg):
    cfg.update({'integrations': {'agentmail': {'api_key': 'first'}}})
    saved = cfg.update({'integrations': {'agentmail': {'inbox_id': 'inbox'}}})
    assert saved['integrations']['agentmail'] == {'api_key': 'first', 'inbox_id': 'inbox'}
    assert saved['integrations']['apify']['max_charge_usd'] == 5
    saved['integrations']['gmail']['enabled'] = True
    assert cfg.DEFAULTS['integrations']['gmail']['enabled'] is False
    assert list(paths.data_dir().iterdir()) == [paths.settings_path()]


def test_recursive_masking_and_stripping(cfg):
    cfg.update({'llm': {'api_key': 'sk-ant-SECRETSECRET1234'},
                'webhooks': {'secret': 'private-webhook-value'},
                'extra': [{'nested_secret': 'hidden', 'api_token': 'token-value'}]})
    masked = cfg.masked()
    assert masked['llm']['api_key'] == 'sk-a…1234'
    assert 'private-webhook-value' not in json.dumps(masked)
    assert masked['extra'][0]['nested_secret'] == '…'
    assert cfg.mask('') == ''
    assert cfg.strip_masked({'llm': {'api_key': 'sk-a…1234', 'model': 'new'}}) == {'llm': {'model': 'new'}}
    assert cfg.strip_masked({'items': [{'api_key': '…', 'name': 'kept'}]}) == {'items': [{'name': 'kept'}]}


@pytest.mark.parametrize('raw', [b'{bad', b'\xff', b'[]', b'null', b'42', b'"text"'])
def test_corrupt_file_recovery_preserves_original(cfg, raw):
    paths.settings_path().write_bytes(raw)
    assert cfg.load()['llm']['provider'] == 'anthropic'
    assert cfg.load_error()
    cfg.update({'llm': {'model': 'recovered'}})
    assert cfg.load_error() is None
    assert cfg.get('llm.model') == 'recovered'
    backups = list(paths.data_dir().glob('settings.json.corrupt-*'))
    assert len(backups) == 1
    assert backups[0].read_bytes() == raw


def test_missing_clears_error(cfg):
    paths.settings_path().write_text('bad', encoding='utf-8')
    cfg.load()
    paths.settings_path().unlink()
    cfg.load()
    assert cfg.load_error() is None


def test_failed_replace_keeps_original_and_cleans_temp(cfg, monkeypatch):
    cfg.update({'llm': {'model': 'original'}})
    original = paths.settings_path().read_bytes()
    def fail(*args):
        raise PermissionError('replace denied')
    monkeypatch.setattr(cfg.os, 'replace', fail)
    with pytest.raises(PermissionError):
        cfg.update({'llm': {'model': 'new'}})
    assert paths.settings_path().read_bytes() == original
    assert list(paths.data_dir().iterdir()) == [paths.settings_path()]


@pytest.mark.parametrize('corrupt', [False, True])
def test_unsupported_chmod_does_not_abort_save_or_backup(cfg, monkeypatch, corrupt):
    original = b'{invalid settings'
    if corrupt:
        paths.settings_path().write_bytes(original)

    def unsupported(*args):
        raise OSError('unsupported chmod')

    monkeypatch.setattr(cfg.os, 'chmod', unsupported)
    cfg.update({'llm': {'model': 'saved-without-chmod'}})
    assert cfg.get('llm.model') == 'saved-without-chmod'
    assert cfg.load_error() is None
    backups = list(paths.data_dir().glob('settings.json.corrupt-*'))
    assert len(backups) == int(corrupt)
    if corrupt:
        assert backups[0].read_bytes() == original
    assert not list(paths.data_dir().glob('*.tmp'))


def test_settings_api_masked_echo_and_invalid_bodies(cfg, client):
    cfg.update({'llm': {'api_key': 'sk-ant-SECRETSECRET1234'}})
    response = client.get('/api/settings')
    assert response.status_code == 200
    body = response.get_json()
    assert body['load_error'] is None
    assert body['settings']['llm']['api_key'] == 'sk-a…1234'
    body['settings']['llm']['model'] = 'new-model'
    response = client.put('/api/settings', json=body['settings'])
    assert response.status_code == 200
    assert cfg.get('llm.api_key') == 'sk-ant-SECRETSECRET1234'
    assert cfg.get('llm.model') == 'new-model'
    assert 'SECRETSECRET' not in response.get_data(as_text=True)
    for value in ([], None, 42, 'text'):
        assert client.put('/api/settings', data=json.dumps(value), content_type='application/json').status_code == 400
    assert client.put('/api/settings', data='{', content_type='application/json').status_code == 400
    assert client.put('/api/settings', data='text').status_code == 400


def test_agentmail_reads_key_after_import(cfg, monkeypatch):
    import agentmail_client
    monkeypatch.setenv('AGENTMAIL_API_KEY', 'late-key')
    assert agentmail_client._headers('id')['Authorization'] == 'Bearer late-key'
    monkeypatch.setenv('AGENTMAIL_API_KEY', 'changed-key')
    assert agentmail_client._headers('id')['Authorization'] == 'Bearer changed-key'
