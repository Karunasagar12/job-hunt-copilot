import db
import pytest


@pytest.fixture(autouse=True)
def init_test_db():
    db.init_db()
    # Clear all data between tests to ensure isolation
    conn = db._get_conn()
    conn.execute("DELETE FROM outreach_log")
    conn.execute("DELETE FROM contacts")
    conn.execute("DELETE FROM jobs")
    conn.commit()


def _touchpoint(scheduled_date, sequence_num=4, job_id=None, contact_id=None):
    if job_id is None:
        job_id = db.create_job("Acme", "PM", "eu", source_type="company")
    if contact_id is None:
        contact_id = db.create_contact(job_id, "Jane", "hiring_manager")
    entry_id = db.create_outreach_entry(
        contact_id, job_id, "email", sequence_num, scheduled_date, "Re: subject", "body",
        provider="gmail",
    )
    return entry_id, job_id, contact_id


def test_assign_brief_only_includes_sequence_4_and_5():
    date = "2030-06-01"
    id1, _, _ = _touchpoint(date, sequence_num=1)
    id4, _, _ = _touchpoint(date, sequence_num=4)
    id5, _, _ = _touchpoint(date, sequence_num=5)
    result = db.get_and_assign_followup_brief(date)
    ids = {item["id"] for item in result}
    assert id4 in ids
    assert id5 in ids
    assert id1 not in ids


def test_assign_brief_excludes_cross_contact_reply():
    date = "2030-06-02"
    job_id = db.create_job("Acme", "PM", "eu", source_type="company")
    c1 = db.create_contact(job_id, "Jane", "hiring_manager")
    c2 = db.create_contact(job_id, "John", "recruiter")
    db.update_contact(c2, replied=1)
    entry_id, _, _ = _touchpoint(date, job_id=job_id, contact_id=c1)
    result = db.get_and_assign_followup_brief(date)
    assert entry_id not in {item["id"] for item in result}


def test_assign_brief_writes_position_and_date():
    date = "2030-06-03"
    entry_id, _, _ = _touchpoint(date)
    result = db.get_and_assign_followup_brief(date)
    item = next(i for i in result if i["id"] == entry_id)
    assert item["position"] == 1
    row = db._get_conn().execute(
        "SELECT brief_sent_date, brief_position FROM outreach_log WHERE id = ?", (entry_id,)
    ).fetchone()
    assert row["brief_sent_date"] == date
    assert row["brief_position"] == 1


def test_assign_brief_unconditionally_overwrites_on_rerun():
    date = "2030-06-04"
    id_a, _, _ = _touchpoint(date)
    id_b, _, _ = _touchpoint(date)
    db.get_and_assign_followup_brief(date)
    db.update_outreach_entry(id_a, status="sent")  # id_a now ineligible
    result = db.get_and_assign_followup_brief(date)
    positions = {item["id"]: item["position"] for item in result}
    assert id_a not in positions
    assert positions[id_b] == 1  # renumbered, not left at its stale earlier position
    row_a = db._get_conn().execute(
        "SELECT brief_sent_date, brief_position FROM outreach_log WHERE id = ?", (id_a,)
    ).fetchone()
    assert row_a["brief_sent_date"] is None
    assert row_a["brief_position"] is None


def test_resolve_returns_only_requested_positions():
    date = "2030-06-05"
    id_a, _, _ = _touchpoint(date)
    id_b, _, _ = _touchpoint(date)
    db.get_and_assign_followup_brief(date)
    result = db.get_followup_brief_items(date, [1])
    assert len(result) == 1
    assert result[0]["id"] == id_a


def test_resolve_excludes_position_whose_status_left_draft():
    date = "2030-06-06"
    entry_id, _, _ = _touchpoint(date)
    db.get_and_assign_followup_brief(date)
    db.update_outreach_entry(entry_id, status="sent")
    result = db.get_followup_brief_items(date, [1])
    assert result == []


def test_resolve_scoped_to_requested_date_only():
    date = "2030-06-07"
    _touchpoint(date)
    db.get_and_assign_followup_brief(date)
    result = db.get_followup_brief_items("2030-06-08", [1])
    assert result == []


def test_resolve_empty_positions_returns_empty():
    assert db.get_followup_brief_items("2030-06-01", []) == []


def test_cancel_pending_touchpoints_clears_brief_columns():
    date = "2030-06-09"
    entry_id, _, contact_id = _touchpoint(date)
    db.get_and_assign_followup_brief(date)
    db.cancel_pending_touchpoints(contact_id)
    row = db._get_conn().execute(
        "SELECT brief_sent_date, brief_position, status FROM outreach_log WHERE id = ?", (entry_id,)
    ).fetchone()
    assert row["status"] == "skipped"
    assert row["brief_sent_date"] is None
    assert row["brief_position"] is None


def test_assign_brief_includes_overdue_touchpoint():
    scheduled = "2030-06-10"
    query_date = "2030-06-11"  # one day after the scheduled date -- still overdue and pending
    entry_id, _, _ = _touchpoint(scheduled)
    result = db.get_and_assign_followup_brief(query_date)
    assert entry_id in {item["id"] for item in result}
