import logging
import threading
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.exc import IntegrityError

import config
from database import get_session, get_tracker_state
from linkedin import LinkedInAccessError, fetch_jobs
from filters import parse_posted_at
from models import Job, SavedSearch
from notifier import notify_new_job

logger = logging.getLogger(__name__)

_scheduler = None
_check_lock = threading.Lock()


def ingest_jobs(session, search, jobs, notify=True):
    """
    Save jobs that are not already in the database.

    The first completed scan for a search stores jobs without notifications
    so existing listings do not spam the desktop.
    """
    is_first_scan = not bool(getattr(search, "first_scan_done", False))
    new_jobs = []
    seen = set()

    for data in jobs:
        linkedin_id = data.get("linkedin_id")
        if not linkedin_id or linkedin_id in seen:
            continue
        seen.add(linkedin_id)
        exists = session.query(Job).filter_by(linkedin_id=linkedin_id).first()
        if exists:
            continue

        job = Job(
            linkedin_id=linkedin_id,
            title=data.get("title") or "Untitled job",
            company=data.get("company") or "",
            location=data.get("location") or "",
            url=data.get("url") or "",
            description=data.get("description"),
            posted_text=data.get("posted_text"),
            posted_at=data.get("posted_at") or parse_posted_at(data.get("posted_text")),
            employment_type=data.get("employment_type"),
            experience_level=data.get("experience_level"),
            remote_type=data.get("remote_type"),
            discovered_at=datetime.now(),
            search_name=data.get("search_name") or getattr(search, "name", None),
            search_id=getattr(search, "id", None),
        )
        session.add(job)
        new_jobs.append(job)

    if search is not None:
        search.first_scan_done = True

    try:
        session.commit()
    except IntegrityError:
        logger.info("Duplicate job ignored by unique linkedin_id")
        session.rollback()
        return []
    except Exception:
        logger.exception("Database error while saving jobs")
        session.rollback()
        raise

    should_notify = notify and not is_first_scan
    if should_notify:
        for job in new_jobs:
            notify_new_job(job)

    if new_jobs:
        logger.info("New jobs for '%s': %s", getattr(search, "name", "search"), len(new_jobs))
    return new_jobs


def run_all_searches(notify=True):
    """Run every enabled saved search. One failure does not stop the others."""
    if not _check_lock.acquire(blocking=False):
        logger.info("A check is already running")
        return {"busy": True, "jobs_found": 0, "new_jobs": 0, "error": None}

    session = get_session()
    jobs_found = 0
    new_jobs = 0
    errors = []

    try:
        searches = (
            session.query(SavedSearch)
            .filter_by(enabled=True)
            .order_by(SavedSearch.id.asc())
            .all()
        )
        if not searches:
            logger.info("No enabled saved searches")
        for search in searches:
            try:
                fetched = fetch_jobs(search)
                jobs_found += len(fetched)
                created = ingest_jobs(session, search, fetched, notify=notify)
                new_jobs += len(created)
            except LinkedInAccessError:
                logger.error("LinkedIn access error during search '%s'", search.name)
                errors.append(f"{search.name}: Unable to access LinkedIn")
            except Exception:
                logger.exception("Search failed: %s", search.name)
                errors.append(f"{search.name}: search failed")

        state = get_tracker_state(session)
        state.last_check_at = datetime.now()
        state.last_jobs_found = jobs_found
        state.last_new_jobs = new_jobs
        state.last_error = "; ".join(errors) if errors else None
        session.commit()
    except Exception:
        logger.exception("Database error during check")
        session.rollback()
        errors.append("Database error")
        try:
            state = get_tracker_state(session)
            state.last_check_at = datetime.now()
            state.last_error = "; ".join(errors)
            session.commit()
        except Exception:
            logger.exception("Database error while storing tracker state")
            session.rollback()
    finally:
        session.close()
        _check_lock.release()

    return {
        "busy": False,
        "jobs_found": jobs_found,
        "new_jobs": new_jobs,
        "error": "; ".join(errors) if errors else None,
    }


def start_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        run_all_searches,
        "interval",
        minutes=config.CHECK_INTERVAL_MINUTES,
        id="linkedin_job_check",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("Scheduler started")
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
    _scheduler = None


def get_scheduler():
    return _scheduler


def next_check_at(last_check_at):
    if last_check_at:
        return last_check_at + timedelta(minutes=config.CHECK_INTERVAL_MINUTES)
    scheduler = get_scheduler()
    if scheduler:
        job = scheduler.get_job("linkedin_job_check")
        if job and job.next_run_time:
            return job.next_run_time.replace(tzinfo=None)
    return None
