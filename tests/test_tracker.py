from datetime import datetime, timedelta

from sqlalchemy.exc import IntegrityError

import config
from filters import apply_filters
from linkedin import build_search_url, derive_linkedin_id, normalize_job
from models import Job, SavedSearch
from scheduler import ingest_jobs, start_scheduler, stop_scheduler


def _job_data(linkedin_id, **overrides):
    data = {
        "linkedin_id": linkedin_id,
        "title": "Backend Engineer",
        "company": "ABC Company",
        "location": "Cairo, Egypt",
        "url": f"https://www.linkedin.com/jobs/view/{linkedin_id}",
        "description": "Python FastAPI role",
        "posted_text": "2 days ago",
        "employment_type": None,
        "experience_level": None,
        "remote_type": None,
        "search_name": "Python Backend",
    }
    data.update(overrides)
    return data


def test_job_linkedin_id_is_unique(db):
    db.add(Job(linkedin_id="11111111", title="One", url="https://example.com/1"))
    db.commit()
    db.add(Job(linkedin_id="11111111", title="Two", url="https://example.com/2"))
    try:
        db.commit()
        assert False, "Expected unique constraint on linkedin_id"
    except IntegrityError:
        db.rollback()


def test_new_job_detection_inserts_once(db):
    search = db.query(SavedSearch).first()
    search.first_scan_done = True
    db.commit()

    created = ingest_jobs(db, search, [_job_data("22222222")], notify=False)
    assert len(created) == 1
    created_again = ingest_jobs(db, search, [_job_data("22222222")], notify=False)
    assert created_again == []
    assert db.query(Job).filter_by(linkedin_id="22222222").count() == 1


def test_duplicate_jobs_in_same_batch_are_ignored(db):
    search = db.query(SavedSearch).first()
    search.first_scan_done = True
    db.commit()

    batch = [_job_data("33333333"), _job_data("33333333", title="Copy")]
    created = ingest_jobs(db, search, batch, notify=False)
    assert len(created) == 1
    assert db.query(Job).filter_by(linkedin_id="33333333").count() == 1


def test_first_scan_does_not_need_notifications(db):
    search = db.query(SavedSearch).first()
    search.first_scan_done = False
    db.commit()

    created = ingest_jobs(db, search, [_job_data("44444444")], notify=True)
    db.refresh(search)
    assert len(created) == 1
    assert search.first_scan_done is True


def test_date_filtering(db):
    now = datetime.now()
    db.add(
        Job(
            linkedin_id="d1",
            title="New",
            posted_text="2 hours ago",
            posted_at=now - timedelta(hours=2),
            discovered_at=now,
            url="https://example.com/d1",
        )
    )
    db.add(
        Job(
            linkedin_id="d2",
            title="Old",
            posted_text="4 days ago",
            posted_at=now - timedelta(days=4),
            discovered_at=now,
            url="https://example.com/d2",
        )
    )
    db.commit()

    recent = apply_filters(db.query(Job), date="24h").all()
    week = apply_filters(db.query(Job), date="7d").all()
    assert [job.linkedin_id for job in recent] == ["d1"]
    assert {job.linkedin_id for job in week} == {"d1", "d2"}


def test_parse_posted_at():
    from filters import parse_posted_at

    now = datetime(2026, 8, 25, 19, 0, 0)
    assert parse_posted_at("2 hours ago", now=now) == now - timedelta(hours=2)
    assert parse_posted_at("1 day ago", now=now) == now - timedelta(days=1)
    assert parse_posted_at("2 weeks ago", now=now) == now - timedelta(weeks=2)
    assert parse_posted_at("just now", now=now) == now
    assert parse_posted_at("2026-08-24", now=now).date().isoformat() == "2026-08-24"


def test_text_search(db):
    db.add(Job(linkedin_id="t1", title="Django Developer", company="Acme", location="Cairo", url="u1"))
    db.add(Job(linkedin_id="t2", title="Frontend", company="Other", location="Alexandria", description="React", url="u2"))
    db.commit()

    hits = apply_filters(db.query(Job), q="django").all()
    assert [job.linkedin_id for job in hits] == ["t1"]
    location_hits = apply_filters(db.query(Job), q="alexandria").all()
    assert [job.linkedin_id for job in location_hits] == ["t2"]


def test_saved_search_crud(client):
    listed = client.get("/settings")
    assert listed.status_code == 200
    assert "Python Backend" in listed.text

    added = client.post(
        "/settings/searches",
        data={"name": "Rust Egypt", "keywords": "Rust", "location": "Egypt"},
        follow_redirects=True,
    )
    assert added.status_code == 200
    assert "Rust Egypt" in added.text

    from database import get_session

    session = get_session()
    search = session.query(SavedSearch).filter_by(name="Rust Egypt").one()
    search_id = search.id
    session.close()

    edited = client.post(
        f"/settings/searches/{search_id}/edit",
        data={"name": "Rust Remote", "keywords": "Rust Engineer", "location": "Remote"},
        follow_redirects=True,
    )
    assert "Rust Remote" in edited.text

    client.post(f"/settings/searches/{search_id}/toggle", data={})
    session = get_session()
    search = session.get(SavedSearch, search_id)
    assert search.enabled is False
    session.close()

    deleted = client.post(f"/settings/searches/{search_id}/delete", follow_redirects=True)
    assert deleted.status_code == 200
    assert "Rust Remote" not in deleted.text


def test_scheduler_interval_configuration():
    assert config.CHECK_INTERVAL_MINUTES == 5
    scheduler = start_scheduler()
    try:
        job = scheduler.get_job("linkedin_job_check")
        assert job is not None
        assert job.trigger.interval.total_seconds() == config.CHECK_INTERVAL_MINUTES * 60
    finally:
        stop_scheduler()


def test_search_url_is_encoded():
    url = build_search_url("Python Backend", "Egypt")
    assert url.startswith("https://www.linkedin.com/jobs/search/?")
    assert "Python+Backend" in url or "Python%20Backend" in url
    assert "Egypt" in url


def test_linkedin_id_derivation():
    assert derive_linkedin_id("urn:li:jobPosting:4123456789", "") == "4123456789"
    assert derive_linkedin_id("", "https://www.linkedin.com/jobs/view/4123456789") == "4123456789"
    hashed = derive_linkedin_id("", "https://www.linkedin.com/jobs/view/unknown-role")
    assert hashed
    assert hashed == derive_linkedin_id("", "https://www.linkedin.com/jobs/view/unknown-role")


def test_normalize_job_handles_missing_fields():
    class Search:
        id = 9
        name = "FastAPI Developer"

    job = normalize_job({"title": "", "company": None, "url": "/jobs/view/55555555"}, Search())
    assert job["linkedin_id"] == "55555555"
    assert job["title"] == "Untitled job"
    assert job["url"] == "https://www.linkedin.com/jobs/view/55555555"
    assert job["search_name"] == "FastAPI Developer"


def test_home_page_loads(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Jobs" in response.text
    assert "Tracker:" in response.text


def test_notification_does_not_crash():
    from notifier import notify_new_job

    class FakeJob:
        title = "Backend Engineer"
        company = "ABC Company"
        location = "Egypt"

    notify_new_job(FakeJob())
