import importlib
import re

import pytest
import paths
import profile as prof

NAMES = ('cv-writer', 'cover-letter-writer', 'outreach-drafter', 'humanizer', 'ats-scorer', 'inbox-classifier')

@pytest.mark.parametrize('name', NAMES)

def test_skill_template_contract(name):
    raw = paths.skill(name).read_text(encoding='utf-8')
    assert raw.splitlines()[0] == f'<!-- skill: {name} -->'
    assert set(re.findall(r'{{([^{}]+)}}', raw)) <= set(prof.PLACEHOLDERS)
    assert not re.search(r'Jane|jane\.doe@example\.com|janedoe-example', raw, re.I)

@pytest.mark.parametrize('name', NAMES)

def test_load_skill_fills_profile_placeholders(name):
    loader = importlib.import_module('skill_loader')
    loaded = loader.load_skill(name)
    assert '{{' not in loaded
    if name == 'outreach-drafter':
        assert prof.load_profile()['signoff_name'] in loaded

def test_missing_skill_has_actionable_error(monkeypatch, tmp_path):
    loader = importlib.import_module('skill_loader')
    monkeypatch.setattr(paths, 'skill', lambda name: tmp_path / name)
    with pytest.raises(RuntimeError, match='Skill file not found:'):
        loader.load_skill('missing')

@pytest.mark.parametrize('name', ['cv-writer', 'ats-scorer'])

def test_hidden_role_is_explicit(name):
    assert 'HIDDEN — skills only' in paths.skill(name).read_text(encoding='utf-8')

def test_prompt_quality_rules_are_retained():
    cv = paths.skill('cv-writer').read_text(encoding='utf-8')
    outreach = paths.skill('outreach-drafter').read_text(encoding='utf-8')
    assert 'Most recent 2 roles: up to 6 bullets each. Older roles: up to 3. Internships: up to 2.' in cv
    assert 'arrow' in cv.lower() and '→' in cv
    assert 'summary. If the JD text begins with' in cv
    assert 'round every count/dollar/quantity metric, no threshold' in cv
    assert 'Max 200 characters' in outreach
    assert 'Mention visa status, work authorisation, immigration details, or right to work' in outreach
    assert 'A literal square bracket appearing anywhere' in outreach
    assert 'no EMAIL 4' in outreach

def test_ranker_prompt_has_marker():
    import source_jobs
    assert source_jobs.build_system_prompt().startswith('<!-- skill: job-ranker -->\n')

def test_cv_input_uses_region_label(monkeypatch):
    import generate
    calls = []
    monkeypatch.setattr(generate, 'call_llm', lambda *args: calls.append(args) or "JOB_COMPANY='Acme'\nJOB_TITLE='DS'")
    generate.call_cv_writer('Example JD', 'eu', 'Knowledge')
    assert calls[0][0] == 'cv-writer'
    assert f"Detected geography: {prof.get_region('eu')['label']}" in calls[0][1]

def test_generate_shared_loader_and_provider_neutral_error(monkeypatch):
    import generate
    loader = importlib.import_module('skill_loader')
    monkeypatch.setattr(loader, 'load_skill', lambda name: '<!-- skill: humanizer -->\nLoaded')
    monkeypatch.setattr(generate.llm_client, 'call_llm', lambda *args, **kwargs: (_ for _ in ()).throw(ValueError('unavailable')))
    with pytest.raises(RuntimeError, match='LLM call failed .*humanizer'):
        generate.call_llm('humanizer', 'Input')

def test_loader_rejects_unknown_profile_placeholder(monkeypatch, tmp_path):
    loader = importlib.import_module('skill_loader')
    path = tmp_path / 'SKILL.md'
    path.write_text('{{unknown_identity}}', encoding='utf-8')
    monkeypatch.setattr(paths, 'skill', lambda name: path)
    with pytest.raises(prof.ProfileError, match='Unknown placeholder'):
        loader.load_skill('custom')

def test_generate_prompt_includes_filled_skill_and_knowledge(monkeypatch):
    import generate
    prompts = []
    monkeypatch.setattr(generate.llm_client, 'call_llm', lambda system, user, **kwargs: prompts.append((system, user)) or 'Clean')
    assert generate.call_llm('outreach-drafter', 'Draft request', 'Verified facts') == 'Clean'
    system, user = prompts[0]
    assert system.startswith('<!-- skill: outreach-drafter -->\n')
    assert prof.load_profile()['signoff_name'] in system
    assert '{{' not in system
    assert '# KNOWLEDGE BASE\nVerified facts' in system
    assert user == 'Draft request'

def test_inbox_reader_uses_shared_loader(monkeypatch):
    import inbox_classifier
    loader = importlib.import_module('skill_loader')
    names = []
    monkeypatch.setattr(loader, 'load_skill', lambda name: names.append(name) or '<!-- skill: inbox-classifier -->\nLoaded')
    prompts = []
    monkeypatch.setattr(inbox_classifier.llm_client, 'call_llm', lambda system, user, **kw: prompts.append(system) or '{"classification":"genuine_reply","extracted_date":null}')
    assert inbox_classifier.classify_message('Thanks')['classification'] == 'genuine_reply'
    assert names == ['inbox-classifier']
    assert prompts == ['<!-- skill: inbox-classifier -->\nLoaded']

def test_redraft_uses_shared_outreach_prompt(monkeypatch):
    import api.app as api
    loader = importlib.import_module('skill_loader')
    names, prompts = [], []
    monkeypatch.setattr(loader, 'load_skill', lambda name: names.append(name) or '<!-- skill: outreach-drafter -->\nLoaded')
    monkeypatch.setattr(api.llm_client, 'call_llm', lambda system, user, **kw: prompts.append(system) or 'Subject: Hello\nHi Alex')
    result = api._llm_redraft(
        {'sequence_num': 1, 'subject': 'Old', 'content': 'Body'},
        {'name': 'Alex', 'title': 'Manager', 'company': 'Acme'},
        {'company': 'Acme', 'role': 'DS', 'jd_text': 'JD'}, 'Improve')
    assert names == ['outreach-drafter']
    assert prompts[0].startswith('<!-- skill: outreach-drafter -->\nLoaded\n\n')
    assert result == ('Hello', 'Hi Alex')

def test_salary_prompt_has_marker(monkeypatch, client):
    import api.app as api
    monkeypatch.setattr(api.db, 'get_job', lambda job_id: {'role': 'Data Scientist', 'company': 'Acme', 'geography': 'eu'})
    monkeypatch.setattr(api.db, 'get_company_profile', lambda company: None)
    monkeypatch.setattr(api.db, 'update_job', lambda *args, **kw: None)
    monkeypatch.setattr(api, '_search_firecrawl_salary', lambda *args: '')
    prompts = []
    monkeypatch.setattr(api.llm_client, 'call_llm', lambda system, user, **kw: prompts.append(user) or 'Estimate')
    assert client.get('/api/jobs/1/salary-estimate').status_code == 200
    assert prompts[0].startswith('<!-- skill: salary-estimator -->\n')

def test_redraft_reports_missing_skill_context(monkeypatch, client):
    import api.app as api
    import db
    loader = importlib.import_module('skill_loader')
    job_id = db.create_job('Acme', 'DS', 'eu', jd_text='JD')
    contact_id = db.create_contact(job_id, 'Alex', 'hiring_manager')
    entry_id = db.create_outreach_entry(contact_id, job_id, 'email', 1, '2026-10-18', 'Hello', 'Hi Alex')
    def missing(name):
        raise RuntimeError('Skill file not found: missing/SKILL.md')
    monkeypatch.setattr(loader, 'load_skill', missing)
    response = client.post(f'/api/outreach/{entry_id}/redraft', json={})
    assert response.status_code == 500
    assert 'Failed to load redraft context: Skill file not found:' in response.json['error']
