import re
from pathlib import Path

import integrations


ROOT = Path(__file__).resolve().parent.parent


def test_relative_links_resolve():
    for md in [ROOT / "README.md", *ROOT.glob("docs/**/*.md")]:
        for target in re.findall(
            r"\]\((?!https?://|#|mailto:)([^)#]+)",
            md.read_text(encoding="utf-8"),
        ):
            assert (md.parent / target).exists(), f"{md.relative_to(ROOT)} -> {target}"


def test_every_integration_has_docs():
    for integration in integrations.IDS:
        assert (ROOT / "docs" / "integrations" / f"{integration}.md").is_file()
    for integration in integrations.all_status():
        assert (ROOT / integration["docs_url"]).is_file(), integration["docs_url"]


def test_readme_has_required_sections():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for heading in (
        "## What it does",
        "## What you need",
        "## Install",
        "## First run",
        "## What it costs",
        "## Updating",
        "## Your data",
        "## Troubleshooting",
    ):
        assert heading in text, heading
