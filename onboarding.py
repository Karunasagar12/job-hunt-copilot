"""Extract onboarding documents and keep raw uploads in the private data directory."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile

from docx import Document
from pypdf import PdfReader

import paths

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
EXTENSIONS = ('.pdf', '.docx')
EMPTY_CV_ERROR = 'This PDF looks like an image. Export your CV as a text PDF or DOCX.'


class OnboardingError(ValueError):
    """A document cannot be accepted for onboarding."""


def extract_text(path: Path) -> str:
    extension = path.suffix.lower()
    if extension not in EXTENSIONS:
        raise OnboardingError('Upload a .pdf or .docx file.')
    try:
        if extension == '.pdf':
            reader = PdfReader(path)
            if reader.is_encrypted:
                raise OnboardingError('Could not read this protected PDF. Upload an unprotected PDF or DOCX.')
            return '\n'.join(page.extract_text() or '' for page in reader.pages).strip()
        document = Document(path)
        text = [paragraph.text for paragraph in document.paragraphs]
        text.extend(cell.text for table in document.tables for row in table.rows for cell in row.cells)
        return '\n'.join(text).strip()
    except OnboardingError:
        raise
    except Exception:
        # Parser exceptions may contain private filenames or document contents.
        raise OnboardingError('Could not read this file. Upload a valid text PDF or DOCX.') from None


@contextmanager
def prepared_upload(file_storage, kind):
    """Validate in a temporary file before replacing any previous raw upload."""
    if kind not in ('cv', 'linkedin'):
        raise OnboardingError('Invalid upload kind.')
    extension = Path(file_storage.filename or '').suffix.lower()
    if extension not in EXTENSIONS:
        raise OnboardingError('Upload a .pdf or .docx file.')
    content = file_storage.stream.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise OnboardingError('Each upload must be 10 MB or smaller.')
    if not content and kind == 'cv':
        raise OnboardingError('The CV file is empty. Upload a text PDF or DOCX.')
    directory = paths.uploads_dir()
    directory.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=directory, suffix=extension, delete=False) as temporary:
        pending = Path(temporary.name)
        temporary.write(content)
    try:
        text = extract_text(pending) if content else ''
        if kind == 'cv' and not text:
            raise OnboardingError(EMPTY_CV_ERROR)
        yield pending, text
    finally:
        pending.unlink(missing_ok=True)


def store_prepared(pending: Path, kind: str) -> Path:
    """Promote a validated document under a constant name, ignoring its filename."""
    if kind not in ('cv', 'linkedin') or pending.suffix.lower() not in EXTENSIONS:
        raise OnboardingError('Invalid upload kind or file type.')
    destination = paths.uploads_dir() / (kind + pending.suffix.lower())
    pending.replace(destination)
    for extension in EXTENSIONS:
        if extension != destination.suffix:
            destination.with_suffix(extension).unlink(missing_ok=True)
    return destination


def save_upload(file_storage, kind) -> Path:
    with prepared_upload(file_storage, kind) as (pending, _text):
        return store_prepared(pending, kind)


def uploaded_text() -> dict[str, str]:
    result = {'cv': '', 'linkedin': ''}
    for kind in result:
        for extension in EXTENSIONS:
            document = paths.uploads_dir() / (kind + extension)
            if document.is_file():
                result[kind] = extract_text(document) if document.stat().st_size else ''
                break
    return result
