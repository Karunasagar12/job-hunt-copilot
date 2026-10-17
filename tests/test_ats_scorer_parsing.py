import unittest.mock as mock

from generate import call_ats_scorer


def test_call_ats_scorer_parses_strict_format():
    report = "Some reasoning.\n\nSCORE: 40/50\nVERDICT: PASS"
    with mock.patch("generate.call_llm", return_value=report), \
         mock.patch("generate.load_knowledge", return_value="knowledge"):
        score, verdict, returned_report = call_ats_scorer("data module", "jd text")
    assert score == 40
    assert verdict == "PASS"
    assert returned_report == report


def test_call_ats_scorer_parses_ats_prefixed_mixed_case_variant():
    # Real observed LLM output that broke the old strict regex: "ATS Score: 42/50"
    # and "### Verdict: PASS" instead of the skill's instructed "SCORE:"/"VERDICT:".
    # This silently defaulted a genuine PASS to a false 0/FAIL before the fix.
    report = (
        "### Overall ATS Score Calculation\n\n"
        "| Dimension | Score |\n|---|---|\n| TOTAL | 41.5/50 |\n\n"
        "**ATS Score: 42/50** (Strong ATS match)\n\n"
        "### Verdict: PASS\n"
    )
    with mock.patch("generate.call_llm", return_value=report), \
         mock.patch("generate.load_knowledge", return_value="knowledge"):
        score, verdict, returned_report = call_ats_scorer("data module", "jd text")
    assert score == 42
    assert verdict == "PASS"
    assert returned_report == report


def test_call_ats_scorer_defaults_to_fail_when_truly_unparseable():
    report = "The model said something with no recognizable score or verdict at all."
    with mock.patch("generate.call_llm", return_value=report), \
         mock.patch("generate.load_knowledge", return_value="knowledge"):
        score, verdict, _ = call_ats_scorer("data module", "jd text")
    assert score == 0
    assert verdict == "FAIL"
