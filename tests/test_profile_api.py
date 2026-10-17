import shutil
from io import BytesIO

import pytest
import paths
import profile as prof
import api.app as api


@pytest.fixture(autouse=True)
def private_profile(tmp_path, monkeypatch):
    shutil.copytree(paths.repo_dir() / 'examples/data', tmp_path, dirs_exist_ok=True)
    monkeypatch.setenv('DATA_DIR', str(tmp_path))


def test_get_profile(client):
    response = client.get('/api/profile')
    assert response.status_code == 200
    assert response.json['name'] == 'Jane Doe'


def test_put_profile_validates_and_saves(client):
    p = prof.load_profile()
    p['email'] = ''
    response = client.put('/api/profile', json=p)
    assert response.status_code == 400
    assert response.json['field'] == 'email'
    p['email'] = 'candidate@example.com'
    response = client.put('/api/profile', json=p)
    assert response.status_code == 200
    assert prof.load_profile()['email'] == p['email']


@pytest.mark.parametrize('body', ['{', 'null', '[]'])
def test_put_profile_bad_json(client, body):
    response = client.put('/api/profile', data=body, content_type='application/json')
    assert response.status_code == 400
    assert response.is_json and response.json['error']


def test_regions_and_presets(client):
    assert client.get('/api/profile/regions').json == [{'id': 'eu', 'label': 'Europe'}]
    response = client.get('/api/profile/region-presets')
    assert response.status_code == 200
    assert {p['id'] for p in response.json} == {'gcc', 'eu', 'uk', 'india', 'us'}


def test_profile_missing(client):
    paths.profile_path().unlink()
    assert client.get('/api/profile').json['error'] == 'profile_not_set'
    assert client.get('/api/profile').status_code == 404
    assert client.get('/api/profile/regions').json == []
    assert client.get('/api/profile/photo').status_code == 404
    assert client.delete('/api/profile/photo').status_code == 404
    response = client.post('/api/profile/photo', data={'photo': (BytesIO(b'x'), 'x.jpg')})
    assert response.status_code == 404
    response = client.post('/api/jobs', json={'jd_text': 'Example job'})
    assert response.status_code == 404 and response.is_json


@pytest.mark.parametrize('filename,blob', [('image.gif', b'GIF89a'), ('image.jpg', b'not an image'), ('image.png', b'\x89PNG\r\n\x1a\n' + b'x' * (5 * 1024 * 1024))], ids=['gif', 'invalid-jpg', 'oversized'])
def test_photo_invalid(client, filename, blob):
    response = client.post('/api/profile/photo', data={'photo': (BytesIO(blob), filename)})
    assert response.status_code == 400
    assert response.json['field'] == 'photo'


def test_photo_missing(client):
    assert client.post('/api/profile/photo').status_code == 400


@pytest.mark.parametrize('filename,target', [('portrait.JPEG', 'photo.jpg'), ('portrait.PNG', 'photo.png')])
def test_photo_round_trip(client, filename, target):
    if target.endswith('jpg'):
        blob = (paths.repo_dir() / 'examples/data/photo.jpg').read_bytes()
    else:
        from PIL import Image
        image = BytesIO()
        Image.new('RGB', (1, 1)).save(image, format='PNG')
        blob = image.getvalue()
    response = client.post('/api/profile/photo', data={'photo': (BytesIO(blob), filename)})
    assert response.status_code == 200
    assert response.json['photo'] == target
    assert paths.data(target).read_bytes() == blob
    assert client.get('/api/profile/photo').data == blob
    assert client.delete('/api/profile/photo').json['photo'] == ''
    assert client.get('/api/profile/photo').status_code == 404


def test_removed_regions_and_sourced_filters(client, monkeypatch):
    assert client.get('/api/stats/geo/gcc').status_code == 200
    response = client.get('/api/stats/geo/removed_region')
    assert response.json == {'total': 0, 'by_status': {}, 'avg_ats_score': None, 'response_rate': 0.0}
    calls = []
    monkeypatch.setattr(api.db, 'get_sourced_jobs', lambda status, geo: calls.append(geo) or [])
    for geo in ('eu', 'removed_region'):
        assert client.get('/api/sourced-jobs?geo=' + geo).status_code == 200
    assert calls == ['eu', 'removed_region']


def test_job_region_defaults_and_validation(client, monkeypatch):
    calls = []
    monkeypatch.setattr(api, 'run_pipeline_async', lambda job_id, **kw: calls.append(kw))
    response = client.post('/api/jobs', json={'jd_text': 'Example job'})
    assert response.status_code == 202
    assert api.db.get_job(response.json['job_id'])['geography'] == 'eu'
    assert calls[0]['geo'] == 'auto'
    assert client.post('/api/jobs', json={'jd_text': 'Example job', 'geography': 'removed_region'}).status_code == 400
    response = client.post('/api/jobs', json={'jd_text': 'Example job', 'geography': 'eu'})
    assert response.status_code == 202
    assert calls[-1]['geo'] == 'eu'


def test_cover_letter_uses_configured_prefix(client):
    p = prof.load_profile()
    p['file_prefix'] = 'Custom_Candidate'
    prof.save_profile(p)
    job_id = api.db.create_job('Example / Co', 'Senior Manager', 'eu')
    api.db.update_job(job_id, cover_letter='Dear team,\n\nExample application.')
    response = client.get(f'/api/jobs/{job_id}/cover-letter/pdf')
    assert response.status_code == 200
    assert 'Custom_Candidate_Example_Co_Senior_Manager_CoverLetter.pdf' in response.headers['Content-Disposition']


def test_salary_custom_region_and_removed_fallback(client, monkeypatch):
    p = prof.load_profile()
    p['regions'][0].update(location='Custom City', salary_sites=['pay.example.com', 'salary.example.org'])
    prof.save_profile(p)
    monkeypatch.setenv('FIRECRAWL_API_KEY', 'test-key')
    calls = []
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'data': [{'title': 'Pay', 'description': 'Compensation research'}]}
    monkeypatch.setattr(api.requests, 'post', lambda *a, **kw: calls.append(kw) or Response())
    assert api._search_firecrawl_salary('Example', 'Manager', 'removed_region') == 'Pay: Compensation research'
    assert calls[0]['json']['query'] == 'Example Manager salary Custom City (site:pay.example.com OR site:salary.example.org)'
    for name in ('career-master.md', 'employment-master.md'):
        (paths.knowledge_dir() / name).write_text('Example career', encoding='utf-8')
    prompts = []
    monkeypatch.setattr(api.llm_client, 'call_llm', lambda system, prompt, **kw: prompts.append(prompt) or 'Estimate')
    job_id = api.db.create_job('Example', 'Manager', 'removed_region')
    assert client.get(f'/api/jobs/{job_id}/salary-estimate').status_code == 200
    assert 'LOCATION: Custom City' in prompts[0]


@pytest.mark.parametrize('payload', [None, {'data': None}, {'data': [None]}])
def test_salary_malformed_search_response_returns_empty(monkeypatch, payload):
    monkeypatch.setenv('FIRECRAWL_API_KEY', 'test-key')
    class Response:
        def raise_for_status(self): pass
        def json(self): return payload
    monkeypatch.setattr(api.requests, 'post', lambda *a, **kw: Response())
    assert api._search_firecrawl_salary('Example', 'Manager', 'eu') == ''


def test_photo_request_limit_returns_json(client):
    assert api.app.config['MAX_CONTENT_LENGTH'] == 12 * 1024 * 1024
    response = client.post('/api/profile/photo', data=b'x' * (12 * 1024 * 1024 + 1), content_type='multipart/form-data; boundary=example')
    assert response.status_code == 413
    assert response.is_json and response.json['error']


@pytest.mark.parametrize('content_type,body', [
    ('application/json', '{'),
    ('text/plain', '{}'),
])
def test_profile_invalid_request_includes_field(client, content_type, body):
    response = client.put('/api/profile', data=body, content_type=content_type)
    assert response.status_code == 400
    assert response.json['error']
    assert 'field' in response.json
    assert response.json['field'] is None


def test_job_request_limit_returns_json(client):
    response = client.post('/api/jobs', json={'jd_text': 'x' * (12 * 1024 * 1024)})
    assert response.status_code == 413
    assert response.is_json and response.json['error']


@pytest.mark.parametrize('filename', ['.env', 'settings.json'])
def test_profile_rejects_non_image_photo_file(client, filename):
    p = prof.load_profile()
    paths.data(filename).write_text('harmless-private-sentinel', encoding='utf-8')
    p['photo'] = filename
    response = client.put('/api/profile', json=p)
    assert response.status_code == 400
    assert response.json['field'] == 'photo'


@pytest.mark.parametrize('filename', ['.env', 'settings.json'])
def test_photo_get_never_serves_non_image_profile_path(client, filename):
    import json
    p = prof.load_profile()
    paths.data(filename).write_text('harmless-private-sentinel', encoding='utf-8')
    p['photo'] = filename
    paths.profile_path().write_text(json.dumps(p), encoding='utf-8')
    response = client.get('/api/profile/photo')
    assert response.status_code == 404
    assert b'harmless-private-sentinel' not in response.data


def test_photo_rejects_signature_only_png_without_replacing_photo(client):
    before = paths.data('photo.jpg').read_bytes()
    response = client.post('/api/profile/photo', data={'photo': (BytesIO(b'\x89PNG\r\n\x1a\n'), 'broken.png')})
    assert response.status_code == 400
    assert response.json['field'] == 'photo'
    assert paths.data('photo.jpg').read_bytes() == before
    assert not paths.data('photo.png').exists()


def test_photo_get_never_serves_non_image_bytes_with_image_suffix(client):
    paths.data('photo.jpg').write_bytes(b'harmless-private-sentinel')
    response = client.get('/api/profile/photo')
    assert response.status_code == 404
    assert b'harmless-private-sentinel' not in response.data
