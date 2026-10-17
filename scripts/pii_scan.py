"""Scan Git-visible files and optional commit metadata without printing source lines."""
import argparse
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def load_terms(path):
    """Return lowercase denied terms and !-prefixed allowed strings."""
    terms, allowed = [], []
    for raw in Path(path).read_text(encoding='utf-8-sig').splitlines():
        term = raw.strip().lower()
        if not term or term.startswith('#'):
            continue
        if term.startswith('!'):
            if term[1:]:
                allowed.append(term[1:])
        else:
            terms.append(term)
    return terms, allowed


def scan_text(text, terms, allowed=()):
    """Return (one-based line, denied term), masking allowed strings first."""
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.lower()
        for value in sorted(allowed, key=len, reverse=True):
            if value:
                line = line.replace(value.lower(), '')
        for term in terms:
            if term and term.lower() in line:
                hits.append((number, term))
    return hits


def git(*args):
    return subprocess.run(['git', *args], check=True, capture_output=True).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', action='store_true', help='also scan commit authors and messages')
    args = parser.parse_args()
    denylist = Path(os.environ.get('PII_DENYLIST', ROOT.parent / 'pii_denylist.txt'))
    if not denylist.is_file():
        return 2
    terms, allowed = load_terms(denylist)
    repo = Path(os.fsdecode(git('rev-parse', '--show-toplevel')).strip())
    os.chdir(repo)
    paths = git('ls-files', '-z', '--cached', '--others', '--exclude-standard').split(b'\0')
    hits = set()
    for raw_path in paths:
        if not raw_path:
            continue
        path = Path(os.fsdecode(raw_path))
        # Never follow a tracked symlink outside the repository.
        if path.is_symlink() or not path.is_file():
            continue
        data = path.read_bytes()
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            text = data.decode('latin1')
        for line, term in scan_text(text, terms, allowed):
            hits.add((path.as_posix(), line, term))
    if args.history:
        commits = git('rev-list', '--all').splitlines()
        for commit in commits:
            sha = commit.decode('ascii')
            metadata = git('show', '-s', '--format=%an%n%ae%n%B', sha).decode('utf-8', errors='replace')
            for line, term in scan_text(metadata, terms, allowed):
                hits.add((f'history/{sha}', line, term))
    for path, line, term in sorted(hits):
        print(f'{path}:{line}:{term}')
    return 1 if hits else 0


if __name__ == '__main__':
    raise SystemExit(main())
