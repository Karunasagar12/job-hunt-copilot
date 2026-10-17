import importlib.util
import os
from pathlib import Path
import subprocess
import sys


def test_paths_module_exists():
    assert importlib.util.find_spec('paths') is not None


def test_data_dir_override_is_read_each_call(monkeypatch, tmp_path):
    import paths
    monkeypatch.setenv('DATA_DIR', str(tmp_path / 'first'))
    assert paths.data_dir() == tmp_path / 'first'
    assert paths.knowledge_dir() == tmp_path / 'first' / 'knowledge'
    assert paths.db_path() == tmp_path / 'first' / 'pipeline.db'
    monkeypatch.setenv('DATA_DIR', str(tmp_path / 'second'))
    assert paths.data('nested', 'file') == tmp_path / 'second' / 'nested' / 'file'


def test_defaults_and_code_paths(monkeypatch):
    import paths
    monkeypatch.delenv('DATA_DIR', raising=False)
    root = Path(__file__).resolve().parents[1]
    assert paths.repo_dir() == root
    assert paths.data_dir() == root / 'data'
    assert paths.skills_dir() == root / 'skills'
    assert paths.skill('cv-writer') == root / 'skills' / 'cv-writer' / 'SKILL.md'
    assert paths.skill('cv-writer').is_file()
    assert paths.templates_dir() == root / 'templates'
    for helper, filename in [(paths.settings_path, 'settings.json'), (paths.profile_path, 'profile.json'), (paths.scheduler_state_path, 'scheduler_state.json')]:
        assert helper() == root / 'data' / filename


def test_data_dir_expands_user_and_resolves(monkeypatch, tmp_path):
    import paths
    monkeypatch.setenv('DATA_DIR', str(tmp_path / 'nested' / '..' / 'data'))
    assert paths.data_dir() == tmp_path / 'data'
    monkeypatch.setenv('DATA_DIR', '~/copilot-data')
    assert paths.data_dir() == (Path.home() / 'copilot-data').resolve()


def test_ensure_dirs_creates_all_subdirectories(monkeypatch, tmp_path):
    import paths
    monkeypatch.setenv('DATA_DIR', str(tmp_path / 'nested' / 'data'))
    paths.ensure_dirs()
    paths.ensure_dirs()
    for helper, name in [(paths.knowledge_dir, 'knowledge'), (paths.output_dir, 'output'), (paths.uploads_dir, 'uploads'), (paths.gmail_dir, 'gmail'), (paths.logs_dir, 'logs')]:
        assert helper() == tmp_path / 'nested' / 'data' / name
        assert helper().is_dir()


def test_generate_preflight_from_unrelated_cwd(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(root))
    result = subprocess.run([sys.executable, '-c', 'import generate; generate._preflight()'], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_paths_import_does_not_create_data_dir(tmp_path):
    root = Path(__file__).resolve().parents[1]
    target = tmp_path / 'missing'
    env = dict(os.environ, DATA_DIR=str(target), PYTHONPATH=str(root))
    result = subprocess.run([sys.executable, '-c', 'import paths'], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not target.exists()


def test_db_default_uses_data_dir_in_fresh_process(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, DATA_DIR=str(tmp_path), PYTHONPATH=str(root))
    env.pop('DB_PATH', None)
    result = subprocess.run([sys.executable, '-c', 'import db, paths; assert db.DB_PATH == str(paths.db_path())'], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_gmail_paths_follow_data_dir_and_overrides(monkeypatch, tmp_path):
    import gmail_client
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.delenv('GMAIL_CREDENTIALS_PATH', raising=False)
    monkeypatch.delenv('GMAIL_TOKEN_PATH', raising=False)
    assert gmail_client._credentials_path() == tmp_path / 'gmail' / 'credentials.json'
    assert gmail_client._token_path() == tmp_path / 'gmail' / 'token.json'
    monkeypatch.setenv('GMAIL_TOKEN_PATH', 'alternate/token.json')
    assert gmail_client._token_path() == tmp_path / 'alternate' / 'token.json'
    absolute = tmp_path / 'absolute.json'
    monkeypatch.setenv('GMAIL_CREDENTIALS_PATH', str(absolute))
    assert gmail_client._credentials_path() == absolute
    monkeypatch.setenv('DATA_DIR', str(tmp_path / 'second'))
    assert gmail_client._token_path() == tmp_path / 'second' / 'alternate' / 'token.json'


def test_generate_loads_dotenv_data_and_db_paths_before_db_import(tmp_path):
    import shutil

    root = Path(__file__).resolve().parents[1]
    for filename in ('generate.py', 'paths.py', 'db.py'):
        shutil.copyfile(root / filename, tmp_path / filename)
    configured_data = tmp_path / 'configured-data'
    configured_data.mkdir()
    configured_db = configured_data / 'configured.db'
    (tmp_path / '.env').write_text(f'DATA_DIR={configured_data.as_posix()}\n', encoding='utf-8')
    (configured_data / '.env').write_text(f'DB_PATH={configured_db.as_posix()}\n', encoding='utf-8')
    env = dict(os.environ, PYTHONPATH=str(root))
    env.pop('DATA_DIR', None)
    env.pop('DB_PATH', None)
    script = (
        'import generate, paths, db; '
        f'assert paths.data_dir() == paths.Path({str(configured_data)!r}); '
        f'assert paths.Path(db.DB_PATH) == paths.Path({str(configured_db)!r}), db.DB_PATH; '
        f'assert paths.Path({str(configured_db)!r}).is_file()'
    )
    result = subprocess.run([sys.executable, '-c', script], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / 'data').exists()
