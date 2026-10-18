"""CV and optional LinkedIn document upload endpoints."""
from contextlib import ExitStack

from flask import Blueprint, jsonify, request

import onboarding

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
