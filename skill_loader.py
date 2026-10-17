"""Load repository skill prompts with the configured candidate identity."""
import paths
import profile as prof


def load_skill(name: str) -> str:
    path = paths.skill(name)
    if not path.is_file():
        raise RuntimeError(f"Skill file not found: {path}")
    return prof.fill_placeholders(path.read_text(encoding="utf-8"))
