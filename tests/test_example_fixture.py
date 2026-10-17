import json
from pathlib import Path

def test_fictional_profile_fixture():
    root = Path(__file__).resolve().parents[1]
    path = root / "examples/data/profile.json"
    assert path.is_file(), "fictional profile fixture must be shipped"
    profile = json.loads(path.read_text())
    assert profile["name"] == "Jane Doe"
    assert profile["default_region"] == "eu"
    assert (root / "examples/data/photo.jpg").is_file()
