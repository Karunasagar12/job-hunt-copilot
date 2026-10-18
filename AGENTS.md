# Contributor guide

Job Hunt Copilot is a local-first job application assistant. It creates tailored application materials and tracks job applications. Keep the product usable by non-technical job seekers and keep personal information out of the repository.

## Project map

- `api/`: Flask API and request helpers.
- `dashboard/`: React interface.
- `data/`: runtime settings, profile, knowledge, database, uploads, and output. This directory is user data and must never be committed.
- `examples/data/`: fictional starter data used for onboarding and tests.
- `skills/`: prompt instructions used for generation.
- `design/`: PDF rendering code.
- `tests/`: Python test suite; `tests/conftest.py` provides isolated test data and the fake LLM.
- `scripts/`: maintenance and smoke-test helpers.
- `docs/`: user guides, integration guides, and [Design Rules](docs/DESIGN_RULES.md).

## Run and test

For local development, install `requirements-dev.txt`, then run `python api/app.py`. In another terminal, run `cd dashboard` and `npm run dev`. Run the Python suite with `pytest` and validate the dashboard with `cd dashboard`, `npm run check`, and `npm run build`. Run `python scripts/pii_scan.py` before proposing changes.

Docker users should use the included start scripts. Never expose the local web server beyond `127.0.0.1` because the application has no login.

## Data contract

Application code reads and writes user-specific data through `paths.py`, under `DATA_DIR` (by default the repository's `data/` directory). Keep generated files and credentials there. `examples/data/` is fictional and safe for tests. Never commit `data/`, credentials, tokens, databases, logs, generated applications, or real CVs.

## Conventions

- Follow [Design Rules](docs/DESIGN_RULES.md), especially source-backed claims and human review of external actions.
- Keep comments short and focused on non-obvious behavior; avoid decorative commentary.
- Add shared test isolation to `tests/conftest.py`; do not let tests read or mutate a real user's data.
- Each `skills/*/SKILL.md` file must include the repository's skill marker and a fake-provider output so the offline fake LLM can exercise it.
- Never add personal information to source, tests, screenshots, examples, or commit messages. Keep the private PII denylist outside the repository.
- Make a local commit before any deployment or release handoff. Release and publishing actions are separate from ordinary code changes.
