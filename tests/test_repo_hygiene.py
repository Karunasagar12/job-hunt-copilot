import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _bytes(name):
    return (ROOT / name).read_bytes()


def test_bat_files_are_crlf():
    for filename in ("start.bat", "update.bat"):
        contents = _bytes(filename)
        assert b"\r\n" in contents and contents.count(b"\n") == contents.count(b"\r\n"), filename


def test_unix_scripts_are_lf_and_executable_in_git():
    for filename in ("start.command", "start.sh", "update.command", "update.sh", "scripts/smoke.sh"):
        assert b"\r\n" not in _bytes(filename), filename
        mode = subprocess.run(
            ["git", "ls-files", "-s", filename],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()[0]
        assert mode == "100755", filename


def test_compose_binds_localhost_only():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert '"127.0.0.1:8080:8080"' in compose
    assert "0.0.0.0:8080" not in compose
