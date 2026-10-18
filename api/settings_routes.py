"""Profile settings and photo endpoints."""
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

import paths
import profile as prof
import settings
import integrations

settings_bp = Blueprint('settings', __name__)
PHOTO_EXT = {'.jpg': '.jpg', '.jpeg': '.jpg', '.png': '.png'}


def _err(msg, status=400, **extra):
    return jsonify({'error': msg, 'status': status, **extra}), status


@settings_bp.get('/api/integrations')
def get_integrations():
    return jsonify(integrations.all_status())


@settings_bp.put('/api/integrations/<name>')
def put_integration(name):
    if name not in integrations.IDS:
        return _err('Unknown integration', 404)
    try:
        if not request.is_json:
            return _err('Integration settings must be a JSON object')
        partial = request.get_json()
        if not isinstance(partial, dict):
            return _err('Integration settings must be a JSON object')
    except BadRequest:
        return _err('Invalid JSON')
    partial = settings.strip_masked(partial)
    partial.pop('last_test', None)
    allowed = set(integrations.FIELDS[name])
    if name == 'apify':
        allowed.add('max_charge_usd')
    if name == 'gmail':
        allowed.add('enabled')
    if any(key not in allowed for key in partial):
        return _err('Unknown integration setting')
    for field in integrations.FIELDS[name]:
        if field in partial and not isinstance(partial[field], str):
            return _err('Credentials must be text')
    if 'enabled' in partial and not isinstance(partial['enabled'], bool):
        return _err('Enabled must be true or false')
    if 'max_charge_usd' in partial and (type(partial['max_charge_usd']) not in (int, float) or partial['max_charge_usd'] < 0):
        return _err('Maximum charge must be a nonnegative number')
    settings.update({'integrations': {name: {**partial, 'last_test': None}}})
    return jsonify(integrations.status(name))


@settings_bp.post('/api/integrations/<name>/test')
def test_integration(name):
    if name not in integrations.IDS:
        return _err('Unknown integration', 404)
    return jsonify(integrations.run_test(name))


@settings_bp.app_errorhandler(RequestEntityTooLarge)
def oversized_request(exc):
    return _err('Request is too large', 413)


@settings_bp.get('/api/settings')
def get_settings():
    value = settings.masked()
    return jsonify({'settings': value, 'load_error': settings.load_error()})


@settings_bp.put('/api/settings')
def put_settings():
    try:
        if not request.is_json:
            return _err('Settings must be a JSON object')
        partial = request.get_json()
        if not isinstance(partial, dict):
            return _err('Settings must be a JSON object')
        settings.update(settings.strip_masked(partial))
        return jsonify({'settings': settings.masked()})
    except BadRequest:
        return _err('Invalid JSON')


@settings_bp.get('/api/profile')
def get_profile():
    try:
        return jsonify(prof.load_profile())
    except prof.ProfileError:
        return _err('profile_not_set', 404)


@settings_bp.put('/api/profile')
def put_profile():
    try:
        if not request.is_json:
            return _err('Profile must be a JSON object', field=None)
        return jsonify(prof.save_profile(request.get_json()))
    except BadRequest:
        return _err('Invalid JSON', field=None)
    except prof.ProfileError as exc:
        return _err(str(exc), field=exc.field)


@settings_bp.get('/api/profile/regions')
def regions():
    try:
        return jsonify([{'id': r['id'], 'label': r['label']} for r in prof.load_profile()['regions']])
    except prof.ProfileError:
        return jsonify([])


@settings_bp.get('/api/profile/region-presets')
def region_presets():
    return jsonify(list(prof.REGION_PRESETS.values()))


@settings_bp.post('/api/profile/photo')
def upload_photo():
    try:
        p = prof.load_profile()
    except prof.ProfileError:
        return _err('profile_not_set', 404)
    photo = request.files.get('photo')
    if not photo or not photo.filename:
        return _err('Photo is required', field='photo')
    extension = PHOTO_EXT.get(Path(photo.filename).suffix.lower())
    if extension is None:
        return _err('Photo must be JPG, JPEG or PNG', field='photo')
    blob = photo.read(prof.MAX_PHOTO_BYTES + 1)
    try:
        prof.validate_photo(blob, extension)
    except prof.ProfileError as exc:
        return _err(str(exc), field=exc.field)
    filename = 'photo' + extension
    root = paths.data().resolve()
    target = paths.data(filename).resolve()
    if not target.is_relative_to(root):
        return _err('Invalid photo path', field='photo')
    root.mkdir(parents=True, exist_ok=True)
    target.write_bytes(blob)
    p['photo'] = filename
    return jsonify(prof.save_profile(p))


@settings_bp.delete('/api/profile/photo')
def delete_photo():
    try:
        p = prof.load_profile()
    except prof.ProfileError:
        return _err('profile_not_set', 404)
    p['photo'] = ''
    return jsonify(prof.save_profile(p))


@settings_bp.get('/api/profile/photo')
def get_photo():
    try:
        photo = prof.photo_path()
    except prof.ProfileError:
        return _err('profile_not_set', 404)
    if photo is None:
        return _err('Photo not found', 404)
    return send_file(photo)


@settings_bp.post('/api/settings/llm/test')
def test_llm():
    import llm_client
    try:
        llm_client.call_llm('Reply with OK', 'ping', max_tokens=10, timeout=30)
        return jsonify({'ok': True})
    except llm_client.LLMError as exc:
        return jsonify({'ok': False, 'kind': exc.kind, 'message': str(exc)})
    except Exception:
        return jsonify({'ok': False, 'kind': 'unknown', 'message': 'The model test failed. Check Settings and try again.'})
