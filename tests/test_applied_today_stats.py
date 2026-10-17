from datetime import datetime, timedelta

import db


def test_applied_at_recent_includes_recent_excludes_old_and_is_utc_tagged():
    db.init_db()

    jid_recent = db.create_job("Recent Co", "PM", "india")
    db.update_job(jid_recent, status="generating")
    db.update_job(jid_recent, status="cv_ready")
    recent_job = db.update_job(jid_recent, status="applied")
    recent_applied_at = recent_job["applied_at"]

    jid_old = db.create_job("Old Co", "PM", "india")
    db.update_job(jid_old, status="generating")
    db.update_job(jid_old, status="cv_ready")
    db.update_job(jid_old, status="applied")
    old_applied_at = (datetime.utcnow() - timedelta(days=5)).isoformat()
    conn = db._get_conn()
    conn.execute("UPDATE jobs SET applied_at = ? WHERE id = ?", (old_applied_at, jid_old))
    conn.commit()

    stats = db.get_stats()
    recent = stats["applied_at_recent"]

    assert all(ts.endswith("Z") for ts in recent), "every timestamp must be unambiguously UTC-tagged"
    assert any(ts.startswith(recent_applied_at) for ts in recent), "job applied moments ago must be included"
    assert not any(ts.startswith(old_applied_at) for ts in recent), "job applied 5 days ago must be excluded"
