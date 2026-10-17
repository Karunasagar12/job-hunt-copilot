"""Signature indentation must not become line breaks in delivered mail."""
from bs4 import BeautifulSoup
import pytest

import gmail_client
from api.app import _signature_to_cid


@pytest.mark.parametrize('geo,phone,location', [
    ('eu', '+33 1 00 00 00 00', 'Paris, France'),
    ('india', '+33 1 00 00 00 00', 'Example City, India'),
    ('gcc', '+33 1 00 00 00 00', 'Dubai, UAE'),
])
def test_signature_has_no_formatting_newlines_and_keeps_inline_content(geo, phone, location):
    signature = gmail_client._get_signature(geo)
    rewritten = signature.replace('\n', '<br>')
    soup = BeautifulSoup(rewritten, 'html.parser')
    assert '\n' not in signature and '\r' not in signature
    assert len(soup.find_all('br')) == 4
    text = soup.get_text(' ', strip=True)
    assert phone in text and location in text
    assert 'jane.doe@example.com' in text
    assert 'https://linkedin.com/in/janedoe-example' in [a.get('href') for a in soup.find_all('a')]
    converted, images = _signature_to_cid(signature)
    assert converted == signature and images == []


def test_signature_fixture_preserves_embedded_image_cids(monkeypatch, tmp_path):
    import base64
    from io import BytesIO
    from PIL import Image
    image = BytesIO()
    Image.new('RGB', (1, 1), 'white').save(image, format='PNG')
    encoded = base64.b64encode(image.getvalue()).decode('ascii')
    directory = tmp_path / 'signatures' / 'Final'
    directory.mkdir(parents=True)
    html = '<body>\n<div>Jane<br>' + ''.join(f'<img src="data:image/png;base64,{encoded}">' for _ in range(4)) + '</div>\n</body>'
    (directory / 'Signature_EU.html').write_text(html, encoding='utf-8')
    monkeypatch.setattr(gmail_client, '_PROJECT_ROOT', tmp_path)
    signature = gmail_client._get_signature('eu')
    assert '\n' not in signature and '<br>' in signature
    converted, images = _signature_to_cid(signature)
    assert len(images) == 4 and converted.count('cid:') == 4


def test_signature_preserves_explicit_line_breaks(monkeypatch, tmp_path):
    directory = tmp_path / 'signatures' / 'Final'
    directory.mkdir(parents=True)
    (directory / 'Signature_EU.html').write_text('<body>\nName<br>\n Role\n</body>', encoding='utf-8')
    monkeypatch.setattr(gmail_client, '_PROJECT_ROOT', tmp_path)
    assert gmail_client._get_signature('eu') == 'Name<br>Role'
