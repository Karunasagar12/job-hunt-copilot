import json
from pathlib import Path

import pytest
import generate
import paths
import profile as prof


@pytest.fixture
def candidate(monkeypatch):
    p = json.loads((paths.repo_dir() / 'examples/data/profile.json').read_text(encoding='utf-8'))
    p['photo'] = ''
    p['extra_agencies'] = ['Talent Bridge']
    p = prof.validate(p)
    monkeypatch.setattr(prof, 'load_profile', lambda: p)
    return p


@pytest.mark.parametrize('text', ['Office in Berlin', 'Remote Anywhere'])
def test_detect_geo_uses_profile_regions(candidate, text):
    assert generate.detect_geo(text, 'auto') == 'eu'


def test_detect_geo_validates_explicit_region(candidate):
    assert generate.detect_geo('Remote', 'eu') == 'eu'
    with pytest.raises(ValueError, match='Unknown region.*Known'):
        generate.detect_geo('Remote', 'mars')


def test_output_base_uses_configurable_prefix_and_safe_unicode_slug(candidate):
    assert generate.output_base('Acme Corp', 'Data Scientist') == 'JaneDoe_Acme_Corp_Data_Scientist'
    candidate['file_prefix'] = 'Custom_Name'
    assert generate.output_base('Müller / Corp', 'Data: Scientist?') == 'Custom_Name_Müller_Corp_Data_Scientist'


def test_agencies_combine_profile_and_builtins(candidate):
    assert generate.is_agency('Talent Bridge')
    assert generate.is_agency('Michael Page')
    assert not generate.is_agency('Acme Corp')


def test_real_render_without_photo_uses_full_width_header(candidate, tmp_path):
    from pypdf import PdfReader
    from design.resume_design_base import MX
    code = """NAME='Jane Doe'
EMAIL='jane.doe@example.com'
PHONE=''
LOCATION=''
LINKEDIN=''
GITHUB=''
SUMMARY='Data scientist.'
EXPERIENCE=[]
EDUCATION=[]
SKILLS={}
PROJECTS=[]
CERTS=[]
JOB_COMPANY='Acme'
JOB_TITLE='DS'
"""
    output = tmp_path / 'cv.pdf'
    generate.render_pdf(code, str(output))
    assert output.stat().st_size > 1000
    page = PdfReader(output).pages[0]
    positions = []
    page.extract_text(visitor_text=lambda text, cm, tm, font, size: positions.append((text, cm, tm)))
    name = next((cm, tm) for text, cm, tm in positions if 'Jane Doe' in text)
    assert name[0][4] + name[1][4] == pytest.approx(MX, abs=1)
    assert not list(page.images)


def test_parser_regions_and_default(candidate):
    parser = generate.build_arg_parser()
    assert next(a for a in parser._actions if a.dest == 'geo').choices == ['eu', 'auto']
    assert parser.parse_args([]).geo == 'auto'


def test_empty_data_reports_setup_and_help_still_works(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    assert generate.setup_missing() == ['profile', 'knowledge']
    parser = generate.build_arg_parser()
    assert next(a for a in parser._actions if a.dest == 'geo').choices is None
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(['--help'])
    assert exc.value.code == 0
    assert '--geo' in capsys.readouterr().out
    with pytest.raises(SystemExit, match=r'Finish setup in the dashboard \(Profile\)'):
        generate._preflight()


def test_setup_requires_regular_knowledge_files(candidate, tmp_path, monkeypatch):
    monkeypatch.setattr(paths, 'knowledge_dir', lambda: tmp_path)
    for name in ('career-master.md', 'employment-master.md', 'education-master.md', 'skills-master.md', 'identity.md'):
        (tmp_path / name).write_text('Example', encoding='utf-8')
    assert generate.setup_missing() == []
    (tmp_path / 'identity.md').unlink()
    (tmp_path / 'identity.md').mkdir()
    assert generate.setup_missing() == ['knowledge']
