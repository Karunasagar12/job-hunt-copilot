import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet

from generate import verify_ats_parseability

FILLER = (
    "This is a longer paragraph of filler text used to ensure the extracted "
    "PDF content clears the minimum-length threshold for the parseability check."
)


def _make_pdf(path, lines):
    doc = SimpleDocTemplate(path, pagesize=A4)
    styles = getSampleStyleSheet()
    story = [Paragraph(line, styles["Normal"]) for line in lines]
    doc.build(story)


def test_verify_ats_parseability_passes_clean_pdf():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "clean.pdf")
        _make_pdf(path, [
            "Jane Doe",
            "jane.doe@example.com",
            "Professional Summary",
            FILLER,
            "Professional Experience",
            FILLER,
            "Education",
            FILLER,
            "Skills",
            "Python, SQL. " + FILLER,
        ])
        issues = verify_ats_parseability(path, "Jane Doe", "jane.doe@example.com")
        assert issues == []


def test_verify_ats_parseability_flags_missing_email():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "no_email.pdf")
        _make_pdf(path, [
            "Jane Doe",
            "Professional Summary", FILLER,
            "Professional Experience", FILLER,
            "Education", FILLER,
            "Skills", FILLER,
        ])
        issues = verify_ats_parseability(path, "Jane Doe", "jane.doe@example.com")
        assert any("email" in issue.lower() for issue in issues)


def test_verify_ats_parseability_accepts_uppercase_section_headers():
    # resume_design_base.py's real renderer uppercases section headers for visual
    # styling (_section_header: text.upper()) -- this reproduces that, since the
    # other tests in this file use mixed-case fixtures that never exercised the
    # real bug (case-sensitive matching against always-uppercase real output).
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "uppercase.pdf")
        _make_pdf(path, [
            "Jane Doe", "jane.doe@example.com",
            "PROFESSIONAL SUMMARY", FILLER,
            "PROFESSIONAL EXPERIENCE", FILLER,
            "EDUCATION", FILLER,
            "SKILLS", FILLER,
        ])
        issues = verify_ats_parseability(path, "Jane Doe", "jane.doe@example.com")
        assert issues == []


def test_verify_ats_parseability_flags_missing_section():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "no_education.pdf")
        _make_pdf(path, [
            "Jane Doe", "jane.doe@example.com",
            "Professional Summary", FILLER,
            "Professional Experience", FILLER,
            "Skills", FILLER,
        ])
        issues = verify_ats_parseability(path, "Jane Doe", "jane.doe@example.com")
        assert any("education" in issue.lower() for issue in issues)


def test_verify_ats_parseability_flags_out_of_order_sections():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "out_of_order.pdf")
        _make_pdf(path, [
            "Jane Doe", "jane.doe@example.com",
            "Skills", FILLER,
            "Professional Summary", FILLER,
            "Professional Experience", FILLER,
            "Education", FILLER,
        ])
        issues = verify_ats_parseability(path, "Jane Doe", "jane.doe@example.com")
        assert any("order" in issue.lower() for issue in issues)


def test_verify_ats_parseability_flags_near_empty_pdf():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "empty.pdf")
        _make_pdf(path, ["x"])
        issues = verify_ats_parseability(path, "Jane Doe", "jane.doe@example.com")
        assert any("little text" in issue.lower() or "empty" in issue.lower() for issue in issues)


def test_verify_ats_parseability_flags_page_overflow():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "overflow.pdf")
        _make_pdf(path, [
            "Jane Doe", "jane.doe@example.com",
            "Professional Summary", FILLER,
            "Professional Experience",
        ] + [FILLER] * 80 + [
            "Education", FILLER,
            "Skills", FILLER,
        ])
        issues = verify_ats_parseability(path, "Jane Doe", "jane.doe@example.com")
        assert any("page" in issue.lower() for issue in issues)


def test_verify_ats_parseability_flags_arrow_glyph():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "arrow.pdf")
        _make_pdf(path, [
            "Jane Doe", "jane.doe@example.com",
            "Professional Summary", FILLER,
            "Professional Experience", "Grew revenue 10% → 20%. " + FILLER,
            "Education", FILLER,
            "Skills", FILLER,
        ])
        issues = verify_ats_parseability(path, "Jane Doe", "jane.doe@example.com")
        assert any("arrow" in issue.lower() or "→" in issue for issue in issues)


def test_verify_ats_parseability_flags_agency_leak_when_agency_given():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "agency_leak.pdf")
        _make_pdf(path, [
            "Jane Doe", "jane.doe@example.com",
            "Professional Summary", "Recruited via Robert Walters. " + FILLER,
            "Professional Experience", FILLER,
            "Education", FILLER,
            "Skills", FILLER,
        ])
        issues = verify_ats_parseability(
            path, "Jane Doe", "jane.doe@example.com", agency_name="Robert Walters"
        )
        assert any("agency" in issue.lower() for issue in issues)


def test_verify_ats_parseability_skips_agency_check_when_no_agency_given():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "no_agency_check.pdf")
        _make_pdf(path, [
            "Jane Doe", "jane.doe@example.com",
            "Professional Summary", "Mentions Robert Walters here. " + FILLER,
            "Professional Experience", FILLER,
            "Education", FILLER,
            "Skills", FILLER,
        ])
        issues = verify_ats_parseability(path, "Jane Doe", "jane.doe@example.com")
        assert not any("agency" in issue.lower() for issue in issues)
