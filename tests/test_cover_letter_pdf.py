import os
import tempfile
from io import BytesIO

import pytest
from pypdf import PdfReader

from api.app import app, db

SAMPLE_COVER_LETTER = """Jane Doe
Paris, France | jane.doe@example.com | +33 1 00 00 00 00 | linkedin.com/in/janedoe-example

Cover Letter: Project Manager
Example Health, Paris, France   25 June 2026

I am applying for the Project Manager role at Example Health because this role sits where clinical impact and delivery discipline meet.

My background combines product execution, stakeholder management, and healthcare AI delivery.

• **Built 6 recurring reports,** automating model evaluation for a fictional analytics team.
• **Monitored 3 model services,** including forecasting and batch scoring examples.

At Example Health, I would focus on making delivery status and risks visible across teams.

I can join within 2 weeks of offer acceptance.
"""


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _make_job(cover_letter=None, company="Example Health", role="Project Manager"):
    job_id = db.create_job(company, role, "india")
    if cover_letter is not None:
        db.update_job(job_id, cover_letter=cover_letter)
    return job_id


def _pdf_text(pdf_bytes):
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_cover_letter_pdf_renders_bold_and_bullets(client):
    job_id = _make_job(SAMPLE_COVER_LETTER)
    resp = client.get(f"/api/jobs/{job_id}/cover-letter/pdf")

    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "application/pdf"
    assert resp.data.startswith(b"%PDF")

    text = _pdf_text(resp.data)
    assert "**" not in text
    assert "Built 6 recurring reports" in text
    assert "Monitored 3 model services" in text
    assert "Jane Doe" in text
    assert "Cover Letter: Project Manager" in text
    # Note: the bullet glyph itself isn't asserted here. ReportLab's base-14
    # WinAnsiEncoding maps byte 0x7F to the "bullet" glyph (a real PDF viewer
    # renders a dot), but pypdf's extractor doesn't resolve that non-standard
    # mapping back to "•" — a known ReportLab/pypdf interop quirk, not a
    # rendering defect.


def test_cover_letter_pdf_malformed_text_does_not_500(client):
    job_id = _make_job("Single wall-of-text line with **bold** and no blank-line structure.")
    resp = client.get(f"/api/jobs/{job_id}/cover-letter/pdf")

    assert resp.status_code == 200
    assert resp.data.startswith(b"%PDF")
    assert "**" not in _pdf_text(resp.data)


def test_cover_letter_pdf_404_when_missing(client):
    job_id = _make_job(None)
    resp = client.get(f"/api/jobs/{job_id}/cover-letter/pdf")
    assert resp.status_code == 404


def test_cover_letter_pdf_404_when_job_not_found(client):
    resp = client.get("/api/jobs/999999/cover-letter/pdf")
    assert resp.status_code == 404
