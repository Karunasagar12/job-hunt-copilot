from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import MagicMock
import sys
import pytest
import llm_client


def configure(monkeypatch, provider, **values):
    monkeypatch.setenv('LLM_PROVIDER', provider)
    for name in ('LLM_MODEL', 'LLM_API_KEY', 'LLM_BASE_URL', 'BEDROCK_MODEL_ID', 'AWS_DEFAULT_REGION'):
        monkeypatch.delenv(name, raising=False)
    environment = {'model': 'LLM_MODEL', 'api_key': 'LLM_API_KEY', 'base_url': 'LLM_BASE_URL', 'aws_region': 'AWS_DEFAULT_REGION'}
    for key, value in values.items():
        monkeypatch.setenv(environment[key], value)


@pytest.mark.parametrize('provider,values,expected', [
    ('fake', {}, True), ('bedrock', {}, True), ('anthropic', {}, False),
    ('anthropic', {'api_key': 'test-key'}, True), ('openrouter', {'api_key': 'test-key'}, True),
    ('openrouter', {}, False), ('openai_compatible', {'base_url': 'http://localhost:11434/v1', 'model': 'local'}, True),
    ('openai_compatible', {'model': 'local'}, False), ('openai_compatible', {'base_url': 'http://localhost'}, False),
    ('unknown', {}, False),
])
def test_configuration(monkeypatch, provider, values, expected):
    configure(monkeypatch, provider, **values)
    assert llm_client.is_configured() is expected
    if not expected:
        with pytest.raises(llm_client.LLMError) as error:
            llm_client.call_llm('system', 'user')
        assert error.value.kind == 'config'


def test_provider_choices_and_models():
    assert llm_client.PROVIDERS == ('anthropic', 'openrouter', 'openai_compatible', 'bedrock')
    assert llm_client.DEFAULT_MODELS['anthropic'] == 'claude-sonnet-5-5'
    assert llm_client.DEFAULT_MODELS['openrouter'] == 'anthropic/claude-sonnet-5.5'


@pytest.mark.parametrize('provider', ['anthropic', 'openrouter', 'openai_compatible'])
def test_sdk_dispatch(monkeypatch, provider):
    configure(monkeypatch, provider, api_key='test-key', model='chosen-model', base_url='http://localhost/v1')
    constructor = MagicMock()
    client = constructor.return_value
    client.messages.create.return_value = NS(content=[NS(type='text', text='one'), NS(type='tool_use'), NS(type='text', text='two')])
    client.chat.completions.create.return_value = NS(choices=[NS(message=NS(content='reply'))])
    monkeypatch.setitem(sys.modules, 'anthropic', NS(Anthropic=constructor))
    monkeypatch.setitem(sys.modules, 'openai', NS(OpenAI=constructor))
    assert llm_client.call_llm('system', 'user', max_tokens=99, timeout=17) == ('onetwo' if provider == 'anthropic' else 'reply')
    assert constructor.call_args.kwargs['max_retries'] == 2
    assert constructor.call_args.kwargs['timeout'] == 17
    if provider != 'anthropic':
        assert constructor.call_args.kwargs['base_url'] == ('https://openrouter.ai/api/v1' if provider == 'openrouter' else 'http://localhost/v1')
        assert client.chat.completions.create.call_args.kwargs['messages'] == [{'role': 'system', 'content': 'system'}, {'role': 'user', 'content': 'user'}]
    call = client.messages.create if provider == 'anthropic' else client.chat.completions.create
    assert call.call_args.kwargs['model'] == 'chosen-model'
    assert call.call_args.kwargs['max_tokens'] == 99


@pytest.mark.parametrize('name,kind', [('AuthenticationError', 'auth'), ('PermissionDeniedError', 'auth'), ('NotFoundError','not_found'), ('RateLimitError','rate_limit'), ('APITimeoutError','timeout'), ('BadRequestError','bad_request'), ('APIConnectionError','unavailable'), ('InternalServerError','unavailable'), ('ServiceUnavailableError','unavailable'), ('OtherError','unknown')])
def test_safe_sdk_errors(monkeypatch, name, kind):
    configure(monkeypatch, 'anthropic', api_key='secret-credential')
    constructor = MagicMock(side_effect=type(name, (Exception,), {})('secret-credential'))
    monkeypatch.setitem(sys.modules, 'anthropic', NS(Anthropic=constructor))
    with pytest.raises(llm_client.LLMError) as error:
        llm_client.call_llm('s', 'u')
    assert error.value.kind == kind
    assert 'secret-credential' not in str(error.value)
    assert str(error.value)


def test_fake_ping_echo_and_missing(monkeypatch):
    configure(monkeypatch, 'fake')
    assert llm_client.call_llm('Reply with OK', 'ping') == 'OK'
    marker = '<!-- skill: ' + 'humanizer -->'
    assert llm_client.call_llm(marker, 'unchanged') == 'unchanged'
    with pytest.raises(llm_client.LLMError) as error:
        llm_client.call_llm('<!-- skill: ' + 'missing-skill -->', '')
    assert error.value.kind == 'config'


def test_llm_test_endpoint(client, monkeypatch):
    configure(monkeypatch, 'fake')
    assert client.post('/api/settings/llm/test').json == {'ok': True}
    monkeypatch.setattr(llm_client, 'call_llm', MagicMock(side_effect=llm_client.LLMError('auth', 'Check Settings.')))
    response = client.post('/api/settings/llm/test')
    assert response.status_code == 200
    assert response.json == {'ok': False, 'kind': 'auth', 'message': 'Check Settings.'}


def test_setup_requires_llm_first(monkeypatch, tmp_path):
    import generate
    configure(monkeypatch, 'anthropic')
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    assert generate.setup_missing() == ['llm', 'profile', 'knowledge']

@pytest.mark.parametrize('code,kind', [('AccessDeniedException','auth'), ('UnrecognizedClientException','auth'), ('ResourceNotFoundException','not_found'), ('ThrottlingException','rate_limit'), ('ValidationException','bad_request'), ('ModelTimeoutException','timeout'), ('ServiceUnavailableException','unavailable')])
def test_bedrock_safe_error_codes(monkeypatch, code, kind):
    from botocore.exceptions import ClientError
    import boto3
    configure(monkeypatch, 'bedrock')
    client = MagicMock()
    client.converse.side_effect = ClientError({'Error': {'Code': code, 'Message': 'secret-credential'}}, 'Converse')
    monkeypatch.setattr(boto3, 'client', MagicMock(return_value=client))
    with pytest.raises(llm_client.LLMError) as error:
        llm_client.call_llm('system', 'user')
    assert error.value.kind == kind
    assert 'secret-credential' not in str(error.value)


def test_custom_provider_without_key(monkeypatch):
    configure(monkeypatch, 'openai_compatible', model='local', base_url='http://localhost/v1')
    constructor = MagicMock()
    constructor.return_value.chat.completions.create.return_value = NS(choices=[NS(message=NS(content='local reply'))])
    monkeypatch.setitem(sys.modules, 'openai', NS(OpenAI=constructor))
    assert llm_client.call_llm('', 'hello') == 'local reply'
    assert constructor.call_args.kwargs['api_key'] == 'not-needed'


def test_bedrock_settings_model_region_and_timeouts(monkeypatch):
    import boto3
    configure(monkeypatch, 'bedrock', model='chosen', aws_region='eu-west-1')
    constructor = MagicMock()
    constructor.return_value.converse.return_value = {'output': {'message': {'content': [{'text': 'one'}, {'text': 'two'}]}}}
    monkeypatch.setattr(boto3, 'client', constructor)
    assert llm_client.call_llm('system', 'user', timeout=42) == 'onetwo'
    kwargs = constructor.call_args.kwargs
    assert kwargs['region_name'] == 'eu-west-1'
    assert kwargs['config'].read_timeout == 42
    assert kwargs['config'].connect_timeout == 10
    assert constructor.return_value.converse.call_args.kwargs['modelId'] == 'chosen'


def test_import_is_lazy(tmp_path):
    import subprocess
    code = "import sys; import llm_client; assert not {'boto3', 'anthropic', 'openai'} & sys.modules.keys()"
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1])
    assert result.returncode == 0, result.stderr


def test_endpoint_uses_small_probe(client, monkeypatch):
    call = MagicMock(return_value='OK')
    monkeypatch.setattr(llm_client, 'call_llm', call)
    assert client.post('/api/settings/llm/test').json == {'ok': True}
    call.assert_called_once_with('Reply with OK', 'ping', max_tokens=10, timeout=30)


def test_endpoint_unexpected_failure_is_safe_and_http_200(client, monkeypatch):
    monkeypatch.setattr(llm_client, 'call_llm', MagicMock(side_effect=RuntimeError('secret-credential')))
    response = client.post('/api/settings/llm/test')
    assert response.status_code == 200
    assert response.json['ok'] is False
    assert response.json['kind'] == 'unknown'
    assert 'secret-credential' not in response.json['message']


def test_sdk_error_with_http_response_is_safe(monkeypatch):
    configure(monkeypatch, 'anthropic', api_key='secret-credential')
    error = type('AuthenticationError', (Exception,), {})('secret-credential')
    error.response = NS(status_code=401)
    monkeypatch.setitem(sys.modules, 'anthropic', NS(Anthropic=MagicMock(side_effect=error)))
    with pytest.raises(llm_client.LLMError) as caught:
        llm_client.call_llm('system', 'user')
    assert caught.value.kind == 'auth'
    assert 'secret-credential' not in str(caught.value)
