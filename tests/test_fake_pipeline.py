from pathlib import Path
import re
import pytest
import db
import generate
import llm_client
import paths
from pypdf import PdfReader


def test_fake_pipeline(monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER', 'fake')
    result = generate.run_single_job(jd='Acme Corp seeks a Senior DS in Paris. Python, SQL, forecasting.', geo='eu', company_override='Acme Corp')
    assert result['success'], result
    job = db.get_job(result['job_id'])
    assert job['company'] == 'Acme Corp'
    assert not job['ats_parse_warning']
    pdfs = list(Path(result['cv_path']).glob('JaneDoe_*.pdf'))
    assert len(pdfs) == 1
    assert 1 <= len(PdfReader(pdfs[0]).pages) <= 2


def test_fake_covers_markers(monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER', 'fake')
    root = paths.repo_dir()
    files = list((root / 'skills').rglob('*.md')) + list(root.glob('*.py')) + list((root / 'api').glob('*.py'))
    markers = set()
    for file in files:
        markers.update(re.findall(r'<!-- skill: ([a-z0-9-]+) -->', file.read_text(encoding='utf-8')))
    for name in markers - {'humanizer'}:
        assert (root / 'fake_llm' / (name + '.txt')).is_file(), name
        assert llm_client.call_llm('<!-- skill: ' + name + ' -->', '')


def test_fake_outreach_and_ats_parse(monkeypatch):
    import outreach_manager
    monkeypatch.setenv('LLM_PROVIDER', 'fake')
    score, verdict, report = generate.call_ats_scorer('example', 'example')
    assert (score, verdict) == (42, 'PASS')
    raw = llm_client.call_llm('<!-- skill: ' + 'outreach-drafter -->', '')
    entries = outreach_manager.parse_and_schedule(raw, [{'id': 1, 'name': 'Alex Smith'}])
    assert len(entries) == 5
    assert all('not yet generated' not in entry['content'] for entry in entries)
    assert all(entry['subject'] for entry in entries if entry['channel'] == 'email')
    assert all('GENERAL TEMPLATE' not in entry['content'] for entry in entries)
    assert '-- FOR HIRING MANAGER --' in raw
    assert '-- FOR RECRUITER --' in raw
