import db


def test_get_all_contact_linkedin_urls_is_db_wide():
    db.init_db()
    job1 = db.create_job("Acme Corp", "PM", "india")
    job2 = db.create_job("Beta Inc", "PM", "india")
    db.create_contact(job1, "Jane Doe", "hiring_manager", linkedin_url="https://linkedin.com/in/jane")
    db.create_contact(job2, "No URL Person", "peer")
    urls = db.get_all_contact_linkedin_urls()
    assert "https://linkedin.com/in/jane" in urls
    assert None not in urls


def test_get_all_contact_emails_is_db_wide():
    db.init_db()
    job1 = db.create_job("Acme Corp", "PM", "india")
    job2 = db.create_job("Beta Inc", "PM", "india")
    db.create_contact(job1, "Jane Doe", "hiring_manager", email="jane@acme.com")
    db.create_contact(job2, "No Email Person", "peer")
    emails = db.get_all_contact_emails()
    assert "jane@acme.com" in emails
    assert None not in emails
