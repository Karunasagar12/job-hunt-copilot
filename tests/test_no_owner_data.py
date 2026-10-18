import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_NAMES = {".env", "token.json", "credentials.json", "pipeline.db"}
IMAGE_OK_PREFIXES = ("examples/", "dashboard/public/", "docs/images/")


def _tracked():
    return subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()


def test_no_secret_or_db_files_tracked():
    for f in _tracked():
        name = Path(f).name
        assert name not in FORBIDDEN_NAMES and not name.endswith((".db", ".db-wal", ".db-shm")), f
        assert not f.startswith("data/"), f


def test_images_only_in_allowed_places():
    for f in _tracked():
        if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".pdf")):
            assert f.startswith(IMAGE_OK_PREFIXES), f
