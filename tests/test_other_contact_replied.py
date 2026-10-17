import db
import pytest


@pytest.fixture(autouse=True)
def init_test_db():
    db.init_db()


def _job():
    return db.create_job("Acme", "PM", "eu", source_type="company")


def test_other_contact_replied_false_when_nobody_replied():
    job_id = _job()
    c1 = db.create_contact(job_id, "Jane", "hiring_manager")
    db.create_contact(job_id, "John", "recruiter")
    assert db.other_contact_replied(job_id, c1) is False


def test_other_contact_replied_true_when_another_contact_replied():
    job_id = _job()
    c1 = db.create_contact(job_id, "Jane", "hiring_manager")
    c2 = db.create_contact(job_id, "John", "recruiter")
    db.update_contact(c2, replied=1)
    assert db.other_contact_replied(job_id, c1) is True


def test_other_contact_replied_ignores_own_reply():
    job_id = _job()
    c1 = db.create_contact(job_id, "Jane", "hiring_manager")
    db.update_contact(c1, replied=1)
    assert db.other_contact_replied(job_id, c1) is False


def test_other_contact_replied_scoped_to_same_job_only():
    job1 = _job()
    job2 = _job()
    c1 = db.create_contact(job1, "Jane", "hiring_manager")
    c2 = db.create_contact(job2, "John", "recruiter")
    db.update_contact(c2, replied=1)
    assert db.other_contact_replied(job1, c1) is False
