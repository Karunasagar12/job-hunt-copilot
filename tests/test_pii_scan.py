from pathlib import Path
import importlib.util
import os
import subprocess
import sys
import shutil

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'pii_scan.py'


def scanner():
    assert SCRIPT.exists(), 'privacy scanner has not been implemented'
    spec = importlib.util.spec_from_file_location('pii_scan', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scan_reports_case_insensitive_term_and_line():
    assert scanner().scan_text('clean\nSECRETNAME\n', ['secretname']) == [(2, 'secretname')]


def test_load_terms_strips_comments_and_collects_allowlist():
    assert scanner().load_terms('#comment\n\n foo \n!Bar12') == (['foo'], ['bar12'])


def test_allowed_strings_are_removed_before_matching():
    assert scanner().scan_text('Handle12', ['handle'], ['handle12']) == []


def test_missing_denylist_exits_two(tmp_path):
    assert SCRIPT.exists(), 'privacy scanner has not been implemented'
    env = {**os.environ, 'PII_DENYLIST': str(tmp_path / 'missing.txt')}
    result = subprocess.run([sys.executable, str(SCRIPT)], env=env, capture_output=True)
    assert result.returncode == 2



def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True)


def test_cli_scans_tracked_staged_untracked_and_binary_but_not_ignored(tmp_path):
    assert SCRIPT.exists(), 'privacy scanner has not been implemented'
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / 'scripts').mkdir()
    fixture_script = repo / 'scripts' / 'pii_scan.py'
    shutil.copyfile(SCRIPT, fixture_script)
    git(repo, 'init', '-b', 'main')
    git(repo, 'config', 'user.name', 'Template Contributors')
    git(repo, 'config', 'user.email', 'contributors@example.org')
    (repo / '.gitignore').write_text('ignored.txt\n', encoding='utf-8')
    (repo / 'tracked.txt').write_text('safe', encoding='utf-8')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'test fixture')
    (repo / 'tracked.txt').write_text('secretname', encoding='utf-8')
    (repo / 'staged.txt').write_text('safe\nsecretname', encoding='utf-8')
    git(repo, 'add', 'staged.txt')
    (repo / 'loose.bin').write_bytes(b'\x00secretname\xff')
    (repo / 'ignored.txt').write_text('secretname', encoding='utf-8')
    denylist = tmp_path / 'terms.txt'
    denylist.write_text('secretname', encoding='utf-8')
    env = {**os.environ, 'PII_DENYLIST': str(denylist)}
    result = subprocess.run([sys.executable, str(fixture_script)], cwd=tmp_path, env=env,
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert set(result.stdout.splitlines()) == {
        'tracked.txt:1:secretname', 'staged.txt:2:secretname', 'loose.bin:1:secretname'
    }
    assert result.stderr == ''


def test_history_scans_author_and_message_without_echoing_message(tmp_path):
    assert SCRIPT.exists(), 'privacy scanner has not been implemented'
    (tmp_path / 'scripts').mkdir()
    fixture_script = tmp_path / 'scripts' / 'pii_scan.py'
    shutil.copyfile(SCRIPT, fixture_script)
    git(tmp_path, 'init', '-b', 'main')
    git(tmp_path, 'config', 'user.name', 'SecretName')
    git(tmp_path, 'config', 'user.email', 'contributors@example.org')
    git(tmp_path, 'commit', '--allow-empty', '-m', 'privatecontext secretname')
    denylist = tmp_path / '.git' / 'terms.txt'
    denylist.write_text('secretname', encoding='utf-8')
    env = {**os.environ, 'PII_DENYLIST': str(denylist)}
    result = subprocess.run([sys.executable, str(fixture_script), '--history'], cwd=ROOT,
                            env=env, capture_output=True, text=True)
    assert result.returncode == 1
    assert len(result.stdout.splitlines()) >= 2
    assert all(line.startswith('history/') and line.endswith(':secretname')
               for line in result.stdout.splitlines())
    assert 'privatecontext' not in result.stdout
