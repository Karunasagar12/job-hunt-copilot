"""CV and optional LinkedIn document upload endpoints."""
from contextlib import ExitStack

from flask import Blueprint, jsonify, request

import onboarding
import profile as prof

onboarding_bp = Blueprint('onboarding', __name__)


def _err(msg, status=400, **extra):
    return jsonify({'error': msg, 'status': status, **extra}), status


@onboarding_bp.post('/api/onboarding/upload')
def upload_documents():
    cv = request.files.get('cv')
    if cv is None or not cv.filename:
        return _err('A CV file is required. Upload a .pdf or .docx file.')
    linkedin = request.files.get('linkedin')
    warnings = []
    chars = {'cv': 0, 'linkedin': 0}
    try:
        with ExitStack() as stack:
            prepared = {}
            for kind, document in (('cv', cv), ('linkedin', linkedin)):
                if document is None or not document.filename:
                    continue
                pending, text = stack.enter_context(onboarding.prepared_upload(document, kind))
                prepared[kind] = pending
                chars[kind] = len(text)
                if kind == 'linkedin' and not text:
                    warnings.append("Couldn't read any text from the LinkedIn file; continuing with the CV only.")
            for kind, pending in prepared.items():
                onboarding.store_prepared(pending, kind)
    except onboarding.OnboardingError as exc:
        return _err(str(exc))
    except OSError:
        return _err('Could not save the upload. Check the data directory.', 500)
    return jsonify({'chars': chars, 'warnings': warnings})


@onboarding_bp.post('/api/onboarding/draft')
def draft_profile():
    try:
        texts = onboarding.uploaded_text()
        if not texts['cv']:
            return _err('Upload a CV before drafting a profile.')
        existing = onboarding.load_source()
        task_id = onboarding.start_task(onboarding.draft, texts['cv'], texts['linkedin'], existing)
    except onboarding.OnboardingError as exc:
        return _err(str(exc))
    return jsonify({'task_id': task_id})


@onboarding_bp.get('/api/onboarding/draft/<task_id>')
def draft_status(task_id):
    status = onboarding.task_status(task_id)
    return jsonify(status) if status is not None else _err('Draft task not found. Please redraft.', 404)


@onboarding_bp.post('/api/onboarding/gaps')
def profile_gaps():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or 'source' not in payload or 'answers' not in payload:
        return _err('Provide a profile source and gap answers.')
    try:
        source = onboarding.validate_source(payload['source'])
        answers = onboarding.validate_answers(payload['answers'])
        texts = onboarding.uploaded_text()
        task_id = onboarding.start_task(onboarding.apply_gaps, source, answers,
                                        texts['cv'] + '\n' + texts['linkedin'])
    except onboarding.OnboardingError as exc:
        return _err(str(exc))
    return jsonify({'task_id': task_id})


@onboarding_bp.get('/api/onboarding/profile-source')
def get_profile_source():
    try:
        source = onboarding.load_source()
    except (OSError, ValueError):
        return _err('Could not read the saved profile source.', 500)
    return jsonify(source) if source is not None else _err('No profile yet', 404)


@onboarding_bp.put('/api/onboarding/profile-source')
def put_profile_source():
    try:
        source = request.get_json(force=True) or {}
        return jsonify(onboarding.save_source(source))
    except onboarding.OnboardingError as exc:
        return _err(str(exc), 400, unverified=getattr(exc, 'unverified', []))
    except prof.ProfileError as exc:
        return _err(str(exc), 400)
    except OSError:
        return _err('Could not save the profile source. Check the data directory.', 500)
