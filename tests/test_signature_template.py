import json

from bs4 import BeautifulSoup
import pytest

import gmail_client
import paths
import profile as prof


@pytest.fixture
def configured_profile(monkeypatch, tmp_path):
    p = prof.load_profile()
    p.update(name='José <Müller>', email='jose@example.com', signoff_name='José',
             signoff_title='Research & Development', linkedin='https://linkedin.com/in/jose-example',
             github='github.com/jose-example', photo='')
    p['regions'][0].update(phone='+49 00 0000', location='Berlin & Remote')
    profile_path = tmp_path / 'profile.json'
    monkeypatch.setattr(paths, 'profile_path', lambda: profile_path)

    def save():
        profile_path.write_text(json.dumps(p, ensure_ascii=False), encoding='utf-8')

    save()
    return p, save


def test_example_signature_and_unknown_region_fallback():
    signature = gmail_client._get_signature('eu')
    assert 'Jane Doe' in signature
    assert '+33 1 00 00 00 00' in signature
    assert 'jane.doe@example.com' in signature
    assert '\n' not in signature and '\r' not in signature
    assert gmail_client._get_signature('unknown') == signature
    assert '<img' not in signature


def test_signature_uses_configured_unicode_identity_and_escaped_region(configured_profile):
    signature = gmail_client._get_signature('eu')
    assert 'José &lt;Müller&gt;' in signature
    assert 'Research &amp; Development' in signature
    assert 'Berlin &amp; Remote' in signature
    assert '+49 00 0000' in signature and 'jose@example.com' in signature
    soup = BeautifulSoup(signature, 'html.parser')
    assert 'José <Müller>' in soup.get_text()
    assert [a['href'] for a in soup.find_all('a')] == [
        'mailto:jose@example.com', 'https://linkedin.com/in/jose-example',
        'https://github.com/jose-example',
    ]


def test_optional_phone_and_links_have_no_broken_separators(configured_profile):
    p, save = configured_profile
    p.update(linkedin='', github='')
    p['regions'][0]['phone'] = ''
    save()
    signature = gmail_client._get_signature('eu')
    assert ' · ' not in signature and ' | ' not in signature
    assert len(BeautifulSoup(signature, 'html.parser').find_all('a')) == 1
    assert '{{' not in signature


def test_strip_example_signature():
    assert gmail_client.strip_signature(
        'Thanks for the reply.\n\nJane\nSenior Data Scientist\nlinkedin.com/in/janedoe-example\n'
    ) == 'Thanks for the reply.'


def test_strip_uses_configured_unicode_name_and_markers(configured_profile):
    assert gmail_client.strip_signature(
        'Thanks for the reply.\n\nJosé\nResearch & Development\nhttps://linkedin.com/in/jose-example\n'
    ) == 'Thanks for the reply.'
    ordinary = 'Please ask Jane\nSenior Data Scientist'
    assert gmail_client.strip_signature(ordinary) == ordinary
    assert gmail_client.strip_signature('A reply.\nJosé') == 'A reply.\n\nRegards,'


def test_missing_profile_keeps_body_and_omits_signature(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, 'profile_path', lambda: tmp_path / 'missing.json')
    assert gmail_client._get_signature('eu') == ''
    body = 'Thanks.\nJane\nSenior Data Scientist'
    assert gmail_client.strip_signature(body) == body


def test_missing_template_omits_signature(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, 'templates_dir', lambda: tmp_path)
    assert gmail_client._get_signature('eu') == ''
