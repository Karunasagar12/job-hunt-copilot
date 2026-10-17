import unittest.mock as mock

from generate import run_single_job
import db


def test_run_single_job_passes_gate_on_first_attempt_no_retry(monkeypatch, tmp_path):
    import generate
    monkeypatch.setattr(generate.paths, "output_dir", lambda: tmp_path)
    fake_data_module = (
        "JOB_COMPANY = 'Acme Corp'\n"
        "JOB_TITLE = 'Product Manager'\n"
        "NAME = 'Jane Doe'\n"
        "EMAIL = 'jane@example.com'\n"
    )

    with mock.patch("generate.fetch_jd", return_value="Sample JD text"), \
         mock.patch("generate.resolve_company", return_value=None), \
         mock.patch("generate.detect_geo", return_value="eu"), \
         mock.patch("generate.load_knowledge", return_value="knowledge"), \
         mock.patch("generate.call_cv_writer", return_value=fake_data_module) as mock_cv_writer, \
         mock.patch("generate.call_ats_scorer", return_value=(40, "PASS", "SCORE: 40/50\nVERDICT: PASS")), \
         mock.patch("generate.render_pdf", return_value=[]), \
         mock.patch("generate.call_cover_letter", return_value="Dear Hiring Manager,"), \
         mock.patch("generate.call_outreach_template", return_value="Outreach text"), \
         mock.patch("generate.call_humanizer", return_value="Humanized outreach"), \
         mock.patch("generate.shutil.move") as mock_move:
        result = run_single_job(jd="Sample JD text", label="happy-path-test")

    assert result["success"] is True
    assert mock_cv_writer.call_count == 1
    mock_move.assert_called_once()

    job = db.get_job(result["job_id"])
    assert not job["ats_parse_warning"]
