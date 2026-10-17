"""Repository assets and configurable private data paths, without side effects."""
import os
from pathlib import Path


def repo_dir() -> Path:
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    configured = os.getenv('DATA_DIR')
    return Path(configured).expanduser().resolve() if configured else repo_dir() / 'data'


def data(*parts) -> Path:
    return data_dir().joinpath(*parts)


def knowledge_dir() -> Path:
    return data('knowledge')


def output_dir() -> Path:
    return data('output')


def uploads_dir() -> Path:
    return data('uploads')


def gmail_dir() -> Path:
    return data('gmail')


def logs_dir() -> Path:
    return data('logs')


def db_path() -> Path:
    return data('pipeline.db')


def settings_path() -> Path:
    return data('settings.json')


def profile_path() -> Path:
    return data('profile.json')


def scheduler_state_path() -> Path:
    return data('scheduler_state.json')


def skills_dir() -> Path:
    return repo_dir() / 'skills'


def skill(name) -> Path:
    return skills_dir() / name / 'SKILL.md'


def templates_dir() -> Path:
    return repo_dir() / 'templates'


def ensure_dirs() -> None:
    for directory in (knowledge_dir(), output_dir(), uploads_dir(), gmail_dir(), logs_dir()):
        directory.mkdir(parents=True, exist_ok=True)
