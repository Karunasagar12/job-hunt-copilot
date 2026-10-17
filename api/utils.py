import json
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

logger = logging.getLogger("jhc.pipeline")

# Worst case: CV-loop's 3 retry attempts (2 LLM calls each) + cover letter +
# outreach + humanizer = up to 9 sequential Bedrock calls. Observed ~60-75s/call
# (Opus 4.6 via Bedrock), so 9 calls alone can reach ~600-650s -- the old 300s
# cap was sized for a single faster (Azure gpt-5.4-pro) attempt and killed every
# job that needed a real retry (SPRINT_LOG.md, 2026-08-10).
PIPELINE_TIMEOUT = 900


def run_pipeline(job_id: int, *, jd_url: str = None, jd_text: str = None,
                 jd_file: str = None, geo: str = "auto", source_type: str = "company",
                 person_infos: list = None, company: str = None, db_update_fn=None):
    """Run generate.py as a subprocess. Calls db_update_fn(job_id, **kwargs) on completion."""
    cmd = [sys.executable, str(PROJECT_ROOT / "generate.py"), "--json-output",
           "--job-id", str(job_id), "--source-type", source_type, "--geo", geo]

    if jd_url:
        cmd += ["--jd-url", jd_url]
    elif jd_file:
        cmd += ["--jd-file", jd_file]
    elif jd_text:
        # Write to a temp file — CLI doesn't support piped jd_text
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(jd_text)
            tmp = f.name
        cmd += ["--jd-file", tmp]
    else:
        if db_update_fn:
            db_update_fn(job_id, status="failed", notes="No JD source provided")
        return

    if company:
        cmd += ["--company", company]
    for pi in (person_infos or []):
        cmd += ["--person-info", pi]

    start = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=PIPELINE_TIMEOUT)
    except subprocess.TimeoutExpired:
        logger.error(f"[PIPELINE job_id={job_id}] TIMEOUT after {PIPELINE_TIMEOUT}s")
        if db_update_fn:
            db_update_fn(job_id, status="failed", notes=f"Pipeline timeout after {PIPELINE_TIMEOUT}s")
        return

    elapsed = round(time.time() - start)

    if result.stdout:
        logger.info(f"[PIPELINE job_id={job_id}] stdout:\n{result.stdout}")
    if result.stderr:
        logger.warning(f"[PIPELINE job_id={job_id}] stderr:\n{result.stderr}")

    if result.returncode == 0:
        try:
            data = json.loads(result.stdout.strip().splitlines()[-1])
            log_company = data.get("company") or "?"
            log_role = data.get("role") or "?"
            log_score = data.get("ats_score") if data.get("ats_score") is not None else "?"
            logger.info(f"[PIPELINE job_id={job_id}] DONE in {elapsed}s | {log_company}/{log_role} ATS={log_score}")
            if db_update_fn and data.get("success"):
                db_update_fn(
                    job_id,
                    status="cv_ready",
                    ats_score=data.get("ats_score"),
                    cv_path=data.get("cv_path"),
                    cover_letter=data.get("cover_letter", ""),
                )
        except Exception:
            logger.warning(f"[PIPELINE job_id={job_id}] Could not parse JSON result after {elapsed}s")
    else:
        err_text = result.stderr or result.stdout or "unknown error"
        logger.error(f"[PIPELINE job_id={job_id}] FAILED in {elapsed}s | {err_text}")
        err = err_text[:2000]
        if db_update_fn:
            db_update_fn(job_id, status="failed", notes=f"Pipeline error: {err}")


# ponytail: per-process cap, like the in-flight outreach guard in app.py --
# fine while the API is one process; a multi-worker server would need a
# DB-backed claim instead.
GENERATION_SLOTS = threading.Semaphore(2)


def _run_with_slot(**kwargs):
    with GENERATION_SLOTS:
        run_pipeline(**kwargs)


def run_pipeline_async(job_id: int, **kwargs):
    """Fire-and-forget: run pipeline in background thread, at most two
    generate.py subprocesses at once (Shortlist bulk approvals)."""
    t = threading.Thread(target=_run_with_slot, kwargs={"job_id": job_id, **kwargs}, daemon=True)
    t.start()
