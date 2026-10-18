"""Fictional profile drafts exercise server ownership and evidence checks."""
from copy import deepcopy
import json
import time
from threading import Event

import pytest

import onboarding as ob
import profile as prof
import skill_loader
from tests.test_onboarding_extract import pdf, upload


def source():
    return {'roles': [{'company': 'Acme Analytics', 'achievements': [
        {'text': 'Led migration', 'needs_metric': True},
        {'text': 'Ran workshops', 'needs_metric': True}]}]}


def ready():
    return ob.assign_source_ids(ob.validate_source(source()))


@pytest.mark.parametrize('text', ['{"roles": []}', '```json\n{"roles": []}\n```',
                                  'Here is the result: {"roles": []} Thank you.',
                                  'before {"career": {"narrative": "brace } inside"}} after'])
def test_json_object_extraction(text):
    assert isinstance(ob.parse_llm_json(text), dict)


@pytest.mark.parametrize('text', ['', '[]', '{broken}', '{"roles":',
    '{"roles":[{"company":"Acme Analytics","achievements":[{"text":"Delivered work"}]}], BROKEN}'])
def test_json_invalid_is_readable(text):
    with pytest.raises(ob.OnboardingError, match='JSON'):
        ob.parse_llm_json(text)


def test_placeholder_free_skill_load_does_not_require_profile(monkeypatch):
    monkeypatch.setattr(prof, 'load_profile', lambda: (_ for _ in ()).throw(AssertionError('profile read')))
    assert '<!-- skill: profile-builder -->' in skill_loader.load_skill('profile-builder')


def test_validation_defaults_and_copy():
    original = source()
    result = ob.validate_source(original)
    assert result['career']['headline_variants'] == []
    assert result['education'] == result['projects'] == result['certifications'] == []
    assert result['skills'] == {}
    assert result['roles'][0]['hidden'] is False
    assert result['roles'][0]['achievements'][0]['unverified'] is False
    assert original == source()


@pytest.mark.parametrize('value', [[], {'roles': {}}, {'roles': [None]},
    {'roles': [{'achievements': ['bad']}]}, {'roles': [{'hidden': 'false'}]},
    {'roles': [{'technologies': [3]}]}, {'career': {'headline_variants': [3]}},
    {'career': {'target_roles': {}}}, {'skills': {'tools': 'Python'}},
    {'education': [{'degree': {}}]}, {'projects': [None]}, {'certifications': [False]}])
def test_nested_bad_types_are_onboarding_errors(value):
    with pytest.raises(ob.OnboardingError):
        ob.validate_source(value)


def test_ids_stable_insert_reorder_and_collisions():
    original = source()
    original['roles'] += [{'company': 'Acme Apps', 'achievements': [{'text': 'Built'}]},
                          {'company': 'Google', 'achievements': [{'text': 'Built'}]}]
    result = ob.assign_source_ids(ob.validate_source(original))
    assert [[a['id'] for a in r['achievements']] for r in result['roles']] == [
        ['AA-01', 'AA-02'], ['AA2-01'], ['GO-01']]
    result['roles'][0]['achievements'].insert(0, ob.validate_source(source())['roles'][0]['achievements'][0])
    result['roles'].reverse()
    again = ob.assign_source_ids(result)
    assert [a['id'] for a in again['roles'][-1]['achievements']] == ['AA-03', 'AA-01', 'AA-02']
    assert result['roles'][-1]['achievements'][0]['id'] == ''
    assert ob.assign_source_ids(again) == again


def test_id_many_prefix_collisions_and_duplicate_ids():
    value = ob.validate_source({'roles': [{'company': 'Acme Analytics', 'achievements': [{}]} for _ in range(12)]})
    result = ob.assign_source_ids(value)
    assert result['roles'][-1]['achievements'][0]['id'] == 'AA12-01'
    result['roles'][0]['achievements'].append(deepcopy(result['roles'][0]['achievements'][0]))
    ids = [a['id'] for r in ob.assign_source_ids(result)['roles'] for a in r['achievements']]
    assert len(ids) == len(set(ids))


def test_new_collision_role_inserted_before_existing_keeps_ids():
    value = ready()
    value['roles'].insert(0, ob.validate_source({'roles': [
        {'company': 'Acme Apps', 'achievements': [{'text': 'Built tools'}]}]})['roles'][0])
    result = ob.assign_source_ids(value)
    assert result['roles'][0]['achievements'][0]['id'] == 'AA2-01'
    assert [a['id'] for a in result['roles'][1]['achievements']] == ['AA-01', 'AA-02']


@pytest.mark.parametrize('text,metric,evidence,flag', [
    ('Saved 40 hours', '', '40 hours', False), ('Moved 1,200 rows', '', '1200 rows', False),
    ('Shipped v2', '', 'Shipped software', True), ('Improved', '25%', '20%', True),
    ('Saved 1.20 hours', '', '120 hours', True), ('Saved 40 and 99 hours', '', '40 hours', True),
    ('Saved .5 hours', '', '5 hours', True)])
def test_number_evidence_strict(text, metric, evidence, flag):
    value = ready()
    value['roles'][0]['achievements'][0].update(text=text, metric=metric)
    checked = ob.flag_unverified(value, evidence)
    assert checked['roles'][0]['achievements'][0]['unverified'] is flag
    assert checked is not value


def test_draft_owns_ids_flags_and_prompt(monkeypatch):
    model = ready()
    model['roles'][0]['achievements'][0].update(id='FORGED-99', text='Shipped v2', unverified=False)
    calls = []
    def call(system, prompt, **kwargs):
        calls.append((system, prompt, kwargs))
        return json.dumps(model)
    monkeypatch.setattr(ob.llm_client, 'call_llm', call)
    result = ob.draft('Fictional CV', 'LinkedIn evidence')
    assert result['roles'][0]['achievements'][0]['id'] == 'AA-01'
    assert result['roles'][0]['achievements'][0]['unverified'] is True
    assert '# CV' in calls[0][1] and 'LinkedIn evidence' in calls[0][1]
    assert calls[0][2] == {'max_tokens': 8000, 'timeout': 300}
    assert '<!-- skill: profile-builder -->' in calls[0][0]


def test_existing_ids_preserved_but_fabricated_ids_rejected(monkeypatch):
    existing = ready()
    model = deepcopy(existing)
    model['roles'][0]['achievements'].reverse()
    model['roles'][0]['achievements'].append({'id': 'FORGED-99', 'text': 'New'})
    monkeypatch.setattr(ob.llm_client, 'call_llm', lambda *a, **k: json.dumps(model))
    result = ob.draft('Evidence', existing=existing)
    assert [a['id'] for a in result['roles'][0]['achievements']] == ['AA-02', 'AA-01', 'AA-03']


@pytest.mark.parametrize('bad', ['broken JSON', '{"roles": {}}',
    '{"roles":[{"company":"Acme Analytics","achievements":[{"text":"Delivered work"}]}], BROKEN}'])
def test_retry_once_for_invalid_json_or_schema(monkeypatch, bad):
    calls = []
    def call(system, prompt, **kwargs):
        calls.append(prompt)
        return bad if len(calls) == 1 else json.dumps(source())
    monkeypatch.setattr(ob.llm_client, 'call_llm', call)
    assert ob.draft('CV')['roles']
    assert len(calls) == 2
    assert 'validation' in calls[1].lower() and 'ONLY JSON' in calls[1]


def test_retry_gives_up_and_transport_not_retried(monkeypatch):
    calls = []
    def bad(*a, **k):
        calls.append(1)
        return 'private broken payload'
    monkeypatch.setattr(ob.llm_client, 'call_llm', bad)
    with pytest.raises(ob.OnboardingError, match='JSON'):
        ob.draft('CV')
    assert len(calls) == 2
    def unavailable(*a, **k):
        calls.append(1)
        raise ob.llm_client.LLMError('timeout', 'safe timeout')
    monkeypatch.setattr(ob.llm_client, 'call_llm', unavailable)
    with pytest.raises(ob.llm_client.LLMError):
        ob.draft('CV')
    assert len(calls) == 3


def test_gaps_merge_only_answered_fields_and_recheck_numbers(monkeypatch):
    original = ready()
    original['career']['narrative'] = 'Keep user narrative'
    model = deepcopy(original)
    model['career']['narrative'] = 'Unwanted rewrite'
    model['roles'][0]['company'] = 'Wrong company'
    model['roles'][0]['achievements'][0].update(text='Moved 3 TB, saved 25%', metric='25%', context='Wrong context')
    model['roles'][0]['achievements'][1].update(text='Deleted workshops', metric='99%')
    calls = []
    def call(system, prompt, **kwargs):
        calls.append(prompt)
        return json.dumps(model)
    monkeypatch.setattr(ob.llm_client, 'call_llm', call)
    result = ob.apply_gaps(original, {'AA-01': 'moved 3 TB, cut cost 25%'}, 'CV')
    expected = deepcopy(original)
    expected['roles'][0]['achievements'][0].update(text='Moved 3 TB, saved 25%', metric='25%', needs_metric=False)
    assert result == expected
    assert original['roles'][0]['achievements'][0]['text'] == 'Led migration'
    assert calls[0].startswith('MODE: apply_gaps')
    model['roles'][0]['achievements'] = []
    assert ob.apply_gaps(original, {'AA-01': '3 TB'}, '') == original


def test_empty_gaps_no_call_and_unknown_ids_ignored(monkeypatch):
    def forbidden(*a, **k):
        pytest.fail('No model call expected')
    monkeypatch.setattr(ob.llm_client, 'call_llm', forbidden)
    assert ob.apply_gaps(ready(), {}, '') == ready()
    assert ob.apply_gaps(ready(), {'UNKNOWN-01': 'hello'}, '') == ready()


def test_gaps_flags_unsupported_answered_numbers(monkeypatch):
    model = ready()
    model['roles'][0]['achievements'][0].update(text='Saved 99%', metric='99%')
    monkeypatch.setattr(ob.llm_client, 'call_llm', lambda *a, **k: json.dumps(model))
    result = ob.apply_gaps(ready(), {'AA-01': 'Saved 25%'}, '')
    assert result['roles'][0]['achievements'][0]['unverified'] is True


def test_gaps_preserves_untouched_verification_and_user_confirmation(monkeypatch):
    original = ready()
    original['roles'][0]['achievements'][1].update(text='Confirmed 99 workshops', unverified=False)
    model = deepcopy(original)
    model['roles'][0]['achievements'][0].update(text='Moved 3 TB', metric='3 TB')
    model['roles'][0]['achievements'][1].update(text='Made 999 workshops', unverified=False)
    monkeypatch.setattr(ob.llm_client, 'call_llm', lambda *a, **k: json.dumps(model))
    result = ob.apply_gaps(original, {'AA-01': 'Moved 3 TB'}, '')
    assert result['roles'][0]['achievements'][1] == original['roles'][0]['achievements'][1]


def test_draft_clears_model_unverified_flag_for_supported_claim(monkeypatch):
    model = ready()
    model['roles'][0]['achievements'][0].update(text='Saved 40 hours', unverified=True)
    monkeypatch.setattr(ob.llm_client, 'call_llm', lambda *a, **k: json.dumps(model))
    assert ob.draft('Saved 40 hours')['roles'][0]['achievements'][0]['unverified'] is False


def test_task_status_result_copy_and_uuid():
    from uuid import UUID
    task_id = ob.start_task(lambda: {'nested': ['original']})
    assert str(UUID(task_id)) == task_id
    result = wait_task(task_id)
    result['result']['nested'].append('mutation')
    assert ob.task_status(task_id)['result'] == {'nested': ['original']}


def wait_task(task_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        status = ob.task_status(task_id)
        if status['status'] != 'running':
            return status
        time.sleep(.01)
    pytest.fail('Task did not finish')


def test_task_lifecycle_and_sanitized_error():
    release = Event()
    task_id = ob.start_task(lambda: (release.wait(3), {'ok': True})[1])
    try:
        assert ob.task_status(task_id) == {'status': 'running'}
    finally:
        release.set()
    assert wait_task(task_id) == {'status': 'done', 'result': {'ok': True}}
    assert ob.task_status('unknown') is None
    def bad():
        raise RuntimeError('secret-token private-filename traceback')
    status = wait_task(ob.start_task(bad))
    assert status['status'] == 'error'
    assert 'secret-token' not in status['error'] and 'traceback' not in status['error']


def test_upload_fake_draft_gaps_routes(client):
    assert client.post('/api/onboarding/draft').status_code == 400
    assert client.get('/api/onboarding/draft/unknown').status_code == 404
    assert upload(client, (pdf('Jane Doe moved 3 TB and cut cost 25%'), 'cv.pdf')).status_code == 200
    response = client.post('/api/onboarding/draft')
    assert response.status_code == 200
    task_id = response.json['task_id']
    result = wait_task(task_id)
    assert client.get('/api/onboarding/draft/' + task_id).json == result
    assert result['status'] == 'done'
    value = result['result']
    assert len(value['roles']) == 3 and value['roles'][2]['hidden']
    assert [role['company'] for role in value['roles']] == ['Acme Analytics', 'Northwind Health', 'Contoso Labs']
    response = client.post('/api/onboarding/gaps', json={'source': value, 'answers': {'AA-01': 'moved 3 TB, cut cost 25%'}})
    assert response.status_code == 200
    final = wait_task(response.json['task_id'])
    assert final['status'] == 'done'
    achievement = final['result']['roles'][0]['achievements'][0]
    assert '3 TB' in achievement['text'] and '25%' in achievement['text']
    assert final['result']['roles'][0]['achievements'][1] == value['roles'][0]['achievements'][1]


@pytest.mark.parametrize('payload', [None, [], {}, {'source': [], 'answers': {}},
    {'source': {}, 'answers': []}, {'source': {}, 'answers': {'AA-01': 3}}])
def test_malformed_gaps_400(client, payload):
    assert client.post('/api/onboarding/gaps', json=payload).status_code == 400
