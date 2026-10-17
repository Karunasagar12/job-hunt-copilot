import db


def test_rejected_reachable_from_applied_before_any_interview():
    db.init_db()
    jid = db.create_job("Acme Corp", "PM", "india")
    db.update_job(jid, status="generating")
    db.update_job(jid, status="cv_ready")
    db.update_job(jid, status="applied")
    job = db.update_job(jid, status="rejected")
    assert job["status"] == "rejected"


def test_rejected_reachable_from_offer():
    db.init_db()
    jid = db.create_job("Acme Corp 2", "PM", "india")
    db.update_job(jid, status="generating")
    db.update_job(jid, status="cv_ready")
    db.update_job(jid, status="applied")
    db.update_job(jid, status="sent")
    db.update_job(jid, status="reply")
    db.update_job(jid, status="interview")
    db.update_job(jid, status="offer")
    job = db.update_job(jid, status="rejected")
    assert job["status"] == "rejected"
