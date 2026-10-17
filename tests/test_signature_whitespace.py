"""Signature indentation must not become line breaks in delivered mail."""
from bs4 import BeautifulSoup
import pytest

import gmail_client
from api.app import _signature_to_cid


@pytest.mark.parametrize('geo,phone,location', [
    ('eu', '+33 1 00 00 00 00', 'Paris, France'),
    ('india', '+33 1 00 00 00 00', 'Paris, France'),
    ('gcc', '+33 1 00 00 00 00', 'Paris, France'),
])
def test_signature_has_no_formatting_newlines_and_keeps_inline_content(geo, phone, location):
    signature = gmail_client._get_signature(geo)
    rewritten = signature.replace('\n', '<br>')
    soup = BeautifulSoup(rewritten, 'html.parser')
    assert '\n' not in signature and '\r' not in signature
    assert len(soup.find_all('br')) == 0
    assert len(soup.find_all('tr')) == 5
    text = soup.get_text(' ', strip=True)
    assert phone in text and location in text
    assert 'jane.doe@example.com' in text
    assert 'https://linkedin.com/in/janedoe-example' in [a.get('href') for a in soup.find_all('a')]
    converted, images = _signature_to_cid(signature)
    assert converted == signature and images == []


def test_signature_preserves_explicit_line_breaks(monkeypatch, tmp_path):
    (tmp_path / 'signature.html').write_text('<body>\nName<br>\n Role\n</body>', encoding='utf-8')
    monkeypatch.setattr(gmail_client.paths, 'templates_dir', lambda: tmp_path)
    assert gmail_client._get_signature('eu') == 'Name<br>Role'
