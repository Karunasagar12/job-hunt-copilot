import copy
from datetime import date, datetime, timezone
import json
from pathlib import Path

import pytest
import profile as prof
import paths


def sample_base():
    return json.loads((paths.repo_dir() / 'examples/data/profile.json').read_text(encoding='utf-8'))


@pytest.fixture
def base():
    return sample_base()


def test_local_profile_module_and_fixture(base):
    assert Path(prof.__file__).resolve() == paths.repo_dir() / 'profile.py'
    p = prof.load_profile()
    assert p['file_prefix'] == 'JaneDoe'
    assert prof.region_ids(p) == ['eu']
    assert prof.profile_exists()


@pytest.mark.parametrize(('field', 'value'), [
    ('name', ''), ('email', ' '), ('file_prefix', '../bad'),
    ('regions', []), ('default_region', 'missing'),
    ('timezone', 'Invalid/Nowhere'), ('photo', 'missing.png'),
    ('regions', ['eu']), ('name', 12), ('target_titles', 'engineer'),
    ('linkedin', []), ('photo', 1),
])
def test_validation_fields(base, field, value):
    base[field] = value
    with pytest.raises(prof.ProfileError) as exc:
        prof.validate(base)
    assert exc.value.field == field


def test_normalization_and_no_input_mutation(base):
    for key in ('file_prefix', 'timezone', 'signoff_name', 'signoff_title', 'linkedin', 'github'):
        base.pop(key, None)
    base['regions'][0]['keywords'] = [' PARIS ', '']
    base['extra_agencies'] = [' Example Staffing ', '']
    original = copy.deepcopy(base)
    p = prof.validate(base)
    assert base == original
    assert p['file_prefix'] == 'JaneDoe'
    assert p['timezone'] == 'UTC'
    assert p['signoff_name'] == 'Jane'
    assert p['signoff_title'] == p['headline']
    assert p['linkedin'] == p['github'] == ''
    assert p['regions'][0]['keywords'] == ['paris']
    assert p['extra_agencies'] == ['Example Staffing']


def test_duplicate_and_invalid_region_ids(base):
    base['regions'] *= 2
    with pytest.raises(prof.ProfileError) as exc:
        prof.validate(base)
    assert exc.value.field == 'regions'
    base['regions'] = [{'id': 'Bad ID'}]
    with pytest.raises(prof.ProfileError):
        prof.validate(base)


@pytest.mark.parametrize(('name', 'expected'), [("José Müller-O'Brien", 'JoseMullerOBrien'), ('李雷', 'Candidate'), ('X' * 60, 'X' * 40)])
def test_file_prefix(name, expected):
    assert prof.derive_file_prefix(name) == expected


def test_identity_preserves_unicode_and_region_order(base):
    base['name'] = 'José Müller'
    base['regions'].append(copy.deepcopy(prof.REGION_PRESETS['gcc']))
    p = prof.validate(base)
    expected = ('# Identity\n\n## Common\nName: José Müller\nEmail: jane.doe@example.com\n'
                'LinkedIn: linkedin.com/in/janedoe-example\nGitHub: \nTitle: Senior Data Scientist\n'
                'Photo: photo.jpg\n\n## Europe\nPhone: +33 1 00 00 00 00\nLocation: Paris, France\n'
                '\n## Gulf\nPhone: \nLocation: \n')
    assert prof.render_identity_md(p) == expected


@pytest.mark.parametrize(('text', 'expected'), [('Dubai', 'gcc'), ('Chennai', 'india'),
    ('Europe and Dubai', 'gcc'), ('Remote Anywhere', 'eu'), ('ukulele', 'eu'),
    ('London', 'uk'), ('Bengaluru', 'india'), ('New York', 'us')])
def test_ordered_whole_word_detection(base, text, expected):
    base['regions'] = [copy.deepcopy(prof.REGION_PRESETS[r]) for r in ('gcc', 'india', 'uk', 'us', 'eu')]
    assert prof.detect_region(text, prof.validate(base)) == expected


def test_region_fallbacks(base):
    p = prof.validate(base)
    assert prof.detect_region('Dubai', p) == 'eu'
    assert prof.get_region('missing', p)['id'] == 'eu'
    assert prof.get_region(p=p)['id'] == 'eu'
    base.pop('default_region')
    assert prof.validate(base)['default_region'] == 'eu'


def test_get_region_accepts_region_id_keyword(base):
    p = prof.validate(base)
    assert prof.get_region(region_id='eu', p=p)['id'] == 'eu'


def test_save_returns_normalized_profile(base, tmp_path, monkeypatch):
    base['photo'] = ''
    base['name'] = ' Jane Doe '
    base.pop('signoff_name')
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    saved = prof.save_profile(base)
    assert saved == prof.validate(base)
    assert saved['name'] == 'Jane Doe'
    assert saved['signoff_name'] == 'Jane'
    assert base['name'] == ' Jane Doe '


def test_placeholders_and_agencies(base):
    base['extra_agencies'] = ['Example Staffing']
    p = prof.validate(base)
    assert prof.fill_placeholders('{{ name }} / {{signoff_name}} / {{github}}', p) == 'Jane Doe / Jane / '
    for key in prof.PLACEHOLDERS:
        assert prof.fill_placeholders('{{' + key + '}}', p) == p[key]
    with pytest.raises(prof.ProfileError):
        prof.fill_placeholders('{{unknown}}', p)
    assert prof.is_extra_agency('EXAMPLE STAFFING', p)
    assert not prof.is_extra_agency('Another Company', p)


def test_timezone(base):
    base['timezone'] = 'Asia/Dubai'
    assert prof.today_local(prof.validate(base), datetime(2026, 10, 17, 22, 30, tzinfo=timezone.utc)) == date(2026, 10, 18)


@pytest.mark.parametrize('token', ['Name', 'unknown1', 'name_typo2'])
def test_unknown_placeholder_tokens_are_rejected(base, token):
    with pytest.raises(prof.ProfileError):
        prof.fill_placeholders('{{ ' + token + ' }}', prof.validate(base))


def test_photo_path_and_containment(base, tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    base['photo'] = ''
    assert prof.photo_path(base) is None
    (tmp_path / 'photo.jpg').write_bytes(b'photo')
    base['photo'] = 'photo.jpg'
    assert prof.photo_path(prof.validate(base)) == tmp_path / 'photo.jpg'
    outside = tmp_path.parent / 'outside-photo.jpg'
    outside.write_bytes(b'photo')
    for value in ('../outside-photo.jpg', str(outside), '.'):
        base['photo'] = value
        with pytest.raises(prof.ProfileError) as exc:
            prof.validate(base)
        assert exc.value.field == 'photo'


def test_save_load_cache_and_path_switch(base, tmp_path, monkeypatch):
    # Load the fixture before redirecting DATA_DIR to an empty directory.
    base['photo'] = ''
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    assert not prof.profile_exists()
    prof.save_profile(base)
    assert paths.profile_path().is_file()
    assert (paths.knowledge_dir() / 'identity.md').read_text(encoding='utf-8').startswith('# Identity')
    first = prof.load_profile()
    first['regions'][0]['keywords'].append('mutated')
    assert 'mutated' not in prof.load_profile()['regions'][0]['keywords']
    base['name'] = 'José Doe'
    paths.profile_path().write_text(json.dumps(base, ensure_ascii=False), encoding='utf-8')
    assert prof.load_profile()['name'] == 'José Doe'
    other = tmp_path / 'other'
    monkeypatch.setenv('DATA_DIR', str(other))
    with pytest.raises(prof.ProfileError):
        prof.load_profile()
    prof.save_profile(base)
    assert prof.load_profile()['name'] == 'José Doe'
    assert 'José' in paths.profile_path().read_text(encoding='utf-8')


@pytest.mark.parametrize('content', ['{broken', 'null', '[]', '"text"'])
def test_invalid_json_profile(content, tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    paths.profile_path().write_text(content, encoding='utf-8')
    with pytest.raises(prof.ProfileError):
        prof.load_profile()


def test_atomic_failure_keeps_profile_and_cleans_temp(base, tmp_path, monkeypatch):
    base['photo'] = ''
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    prof.save_profile(base)
    before = paths.profile_path().read_bytes()
    def fail_replace(*args):
        raise OSError('replace failed')
    monkeypatch.setattr(prof.os, 'replace', fail_replace)
    base['name'] = 'Changed Name'
    with pytest.raises(OSError, match='replace failed'):
        prof.save_profile(base)
    assert paths.profile_path().read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ['knowledge', 'profile.json']
