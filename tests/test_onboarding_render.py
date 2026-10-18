from pathlib import Path
from threading import Event, Thread

import pytest
import onboarding
import paths
import profile as prof

SRC = onboarding.validate_source({
    "career": {"narrative": "Data scientist.", "target_roles": ["Senior Data Scientist"],
               "headline_variants": [{"label": "DS", "text": "Builds ML."}]},
    "roles": [{"company": "Acme Analytics", "title": "Senior Data Scientist", "location": "Paris, France",
               "start": "2022-01", "end": "present", "description": "B2B analytics.", "owned": "ML roadmap.",
               "achievements": [{"text": "Cut churn | 18%", "metric": "18%", "context": "line1\nline2"}],
               "technologies": ["Python"], "keywords": ["churn"]},
              {"company": "Contoso Labs", "title": "Advisor", "hidden": True,
               "technologies": ["Rust"], "keywords": ["systems"]}],
    "education": [{"degree": "MSc Data Science", "school": "Example University", "dates": "2019–2021"}],
    "projects": [{"name": "Churn Lab", "context": "Kaggle", "text": "Top 5%"}],
    "skills": {"Technical": ["Python", "SQL"]}, "certifications": ["AWS ML"]})
GOLDEN = Path(__file__).parent / "fixtures" / "onboarding" / "golden_employment.md"


def test_render_employment_matches_golden():
    src = onboarding.assign_source_ids(SRC)
    md = onboarding.render_knowledge(src, prof.load_profile())["employment-master.md"]
    assert md == GOLDEN.read_text(encoding="utf-8")


def test_cells_escape_pipes_and_newlines():
    md = onboarding.render_knowledge(onboarding.assign_source_ids(SRC), prof.load_profile())["employment-master.md"]
    assert "Cut churn \\| 18%" in md and "line1 line2" in md


def test_role_headings_and_dates_flatten_untrusted_newlines():
    source = onboarding.assign_source_ids(SRC)
    source["roles"][0].update(company="Acme\n| Analytics", title="Senior\nData Scientist",
                               start="2022-01\nextra", end="present\n")
    source["roles"][1].update(company="Contoso\nLabs", title="Advisor\nII")
    md = onboarding.render_knowledge(source, prof.load_profile())["employment-master.md"]
    assert "## Acme \\| Analytics — Senior Data Scientist" in md
    assert "**Dates:** 2022-01 extra – Present" in md
    assert "## Contoso Labs — Advisor II (HIDDEN — skills only)" in md


def test_hidden_role_rendered_as_skills_only():
    md = onboarding.render_knowledge(onboarding.assign_source_ids(SRC), prof.load_profile())["employment-master.md"]
    assert "## Contoso Labs — Advisor (HIDDEN — skills only)" in md
    hidden_block = md.split("(HIDDEN — skills only)")[1]
    assert "Verified Achievements" not in hidden_block and "Rust" in hidden_block


def test_all_four_files_and_headings():
    files = onboarding.render_knowledge(SRC, prof.load_profile())
    assert set(files) == {"career-master.md", "employment-master.md", "education-master.md", "skills-master.md"}
    assert "## Projects & Competitions" in files["education-master.md"]
    assert "## Career Narrative" in files["career-master.md"]


def test_save_rejects_unverified_and_round_trips(client):
    bad = onboarding.assign_source_ids(onboarding.validate_source(SRC))
    bad["roles"][0]["achievements"][0]["unverified"] = True
    response = client.put("/api/onboarding/profile-source", json=bad)
    assert response.status_code == 400 and response.get_json()["unverified"] == ["AA-01"]
    bad["roles"][0]["achievements"][0]["unverified"] = False
    assert client.put("/api/onboarding/profile-source", json=bad).status_code == 200
    got = client.get("/api/onboarding/profile-source").get_json()
    assert got["roles"][0]["achievements"][0]["id"] == "AA-01"
    assert (paths.knowledge_dir() / "employment-master.md").read_text(encoding="utf-8").startswith("# Employment Master")


def test_unsupported_context_number_is_flagged_and_rejected(client):
    source = onboarding.assign_source_ids(SRC)
    source["roles"][0]["achievements"][0]["context"] = "Compared 42 synthetic cases."
    flagged = onboarding.flag_unverified(source, "18%")
    assert flagged["roles"][0]["achievements"][0]["unverified"] is True
    response = client.put("/api/onboarding/profile-source", json=flagged)
    assert response.status_code == 400
    assert response.get_json()["unverified"] == ["AA-01"]


def test_gap_merge_rechecks_original_context_numbers(monkeypatch):
    source = onboarding.assign_source_ids(SRC)
    source["roles"][0]["achievements"][0].update(context="Compared 42 synthetic cases.", unverified=False)
    proposal = onboarding.validate_source(source)
    proposal["roles"][0]["achievements"][0]["context"] = ""
    monkeypatch.setattr(onboarding, "_call_profile_builder", lambda _prompt: proposal)

    merged = onboarding.apply_gaps(source, {"AA-01": "The 18% result is from the benchmark."}, "18%")
    achievement = merged["roles"][0]["achievements"][0]
    assert achievement["context"] == "Compared 42 synthetic cases."
    assert achievement["unverified"] is True


def test_gap_answer_numbers_are_scoped_to_their_achievement(monkeypatch):
    source = onboarding.validate_source(SRC)
    source["roles"][0]["achievements"][0]["context"] = "Compared 42 synthetic cases."
    source["roles"][0]["achievements"].append({
        "id": "", "text": "Reviewed 42 cases", "metric": "42 cases", "context": "",
        "needs_metric": False, "unverified": False,
    })
    source = onboarding.assign_source_ids(source)
    proposal = onboarding.validate_source(source)
    proposal["roles"][0]["achievements"][0]["context"] = ""
    monkeypatch.setattr(onboarding, "_call_profile_builder", lambda _prompt: proposal)

    result = onboarding.apply_gaps(
        source,
        {"AA-01": "Confirmed the result", "AA-02": "Verified 42 cases"},
        "18%",
    )
    first, second = result["roles"][0]["achievements"]
    assert first["id"] == "AA-01" and first["unverified"] is True
    assert first["context"] == "Compared 42 synthetic cases."
    assert second["id"] == "AA-02" and second["unverified"] is False


def test_partial_save_failure_keeps_setup_gate_closed(monkeypatch):
    import generate

    source = onboarding.assign_source_ids(SRC)
    atomic_write = prof._atomic_write

    def fail_on_employment(path, text):
        if path.name == "employment-master.md":
            raise OSError("simulated disk failure")
        return atomic_write(path, text)

    monkeypatch.setattr(prof, "_atomic_write", fail_on_employment)
    with pytest.raises(OSError, match="simulated disk failure"):
        onboarding.save_source(source)

    marker = paths.knowledge_dir() / ".profile-source-save-incomplete"
    assert marker.is_file()
    assert "knowledge" in generate.setup_missing()

    monkeypatch.setattr(prof, "_atomic_write", atomic_write)
    onboarding.save_source(source)
    assert not marker.exists()
    assert "knowledge" not in generate.setup_missing()


def test_concurrent_saves_keep_readiness_marker_until_both_finish(monkeypatch):
    original_write = prof._atomic_write
    first_render_started = Event()
    release_first = Event()
    second_started = Event()
    second_done = Event()
    first_blocked = False
    errors = []

    def controlled_write(path, text):
        nonlocal first_blocked
        if path.name == "career-master.md" and not first_blocked:
            first_blocked = True
            first_render_started.set()
            if not release_first.wait(5):
                raise TimeoutError("test did not release first save")
        return original_write(path, text)

    monkeypatch.setattr(prof, "_atomic_write", controlled_write)
    first = Thread(target=lambda: _save_capturing_errors(SRC, errors))

    def save_second():
        second_started.set()
        try:
            onboarding.save_source({**SRC, "career": {**SRC["career"], "narrative": "Second writer."}})
        except Exception as exc:  # surfaced in the main test thread below
            errors.append(exc)
        finally:
            second_done.set()

    first.start()
    assert first_render_started.wait(5)
    second = Thread(target=save_second)
    second.start()
    assert second_started.wait(5)
    try:
        assert not second_done.wait(0.1)
        assert (paths.knowledge_dir() / ".profile-source-save-incomplete").is_file()
    finally:
        release_first.set()
        first.join(5)
        second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert not errors
    assert not (paths.knowledge_dir() / ".profile-source-save-incomplete").exists()


def _save_capturing_errors(source, errors):
    try:
        onboarding.save_source(source)
    except Exception as exc:
        errors.append(exc)
