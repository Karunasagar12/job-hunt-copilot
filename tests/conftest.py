import os
import sys
import shutil
from pathlib import Path
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_ROOT = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".pytest-tmp")
os.makedirs(TEST_ROOT, exist_ok=True)
os.environ["TMP"] = TEST_ROOT
os.environ["TEMP"] = TEST_ROOT
tempfile.tempdir = TEST_ROOT
DATA_DIR = tempfile.mkdtemp(prefix="data-", dir=TEST_ROOT)
shutil.copytree(Path(__file__).resolve().parents[1] / "examples" / "data", DATA_DIR, dirs_exist_ok=True)
os.environ["DATA_DIR"] = DATA_DIR
DB_PATH = os.path.join(DATA_DIR, "pipeline.db")
os.environ["DB_PATH"] = DB_PATH
os.environ.setdefault("LLM_PROVIDER", "fake")

# ponytail: centralized here (same reasoning as DB_PATH above) so every test
# file gets a "configured" AgentMail env by default without its own guard --
# real network calls are mocked throughout, this just satisfies
# _prepare_agentmail_content's config-validation check (Important 7).
os.environ.setdefault("AGENTMAIL_API_KEY", "test-agentmail-key")
os.environ.setdefault("AGENTMAIL_INBOX_ID", "test-inbox-id")

try:
    os.remove(os.environ["DB_PATH"])
except FileNotFoundError:
    pass


@pytest.fixture(autouse=True)
def isolated_data(tmp_path_factory, monkeypatch):
    """Each test receives clean example assets, including settings and profile."""
    destination = tmp_path_factory.mktemp('example-data')
    shutil.copytree(Path(__file__).resolve().parents[1] / 'examples' / 'data', destination, dirs_exist_ok=True)
    monkeypatch.setenv('DATA_DIR', str(destination))


@pytest.fixture
def gmail_credentials():
    """Credential presence for tests of mocked Gmail route business rules."""
    import paths
    paths.gmail_dir().mkdir(parents=True, exist_ok=True)
    paths.gmail_dir().joinpath('credentials.json').write_text('{}', encoding='utf-8')


@pytest.fixture
def client():
    from api.app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
