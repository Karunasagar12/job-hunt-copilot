"""Profile settings and photo endpoints."""
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

import paths
import profile as prof

settings_bp = Blueprint('settings', __name__)
PHOTO_EXT = {'.jpg': '.jpg', '.jpeg': '.jpg', '.png': '.png'}


def _err(msg, status=400, **extra):
    return jsonify({'error': msg, 'status': status, **extra}), status


@settings_bp.app_errorhandler(RequestEntityTooLarge)
def oversized_request(exc):
    return _err('Request is too large', 413)


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
    blob = photo.read(5 * 1024 * 1024 + 1)
    if len(blob) > 5 * 1024 * 1024:
        return _err('Photo must be at most 5 MB', field='photo')
    if extension == '.jpg':
        valid = blob.startswith(b'\xff\xd8\xff') and blob.endswith(b'\xff\xd9')
    else:
        valid = blob.startswith(b'\x89PNG\r\n\x1a\n')
    if not valid:
        return _err('Invalid photo file', field='photo')
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
