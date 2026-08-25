import logging
import webbrowser
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func

import config
from database import get_session, get_tracker_state, init_db
from filters import (
    DATE_OPTIONS,
    REMOTE_OPTIONS,
    SORT_OPTIONS,
    apply_filters,
    distinct_locations,
    paginate,
    saved_search_choices,
)
from models import Job, SavedSearch
from scheduler import next_check_at, run_all_searches, start_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent

app = FastAPI(title="LinkedIn Job Tracker")
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


def format_dt(value):
    if not value:
        return "—"
    if isinstance(value, str):
        return value
    return value.strftime("%d %b %Y %H:%M")


def format_time(value):
    if not value:
        return "—"
    return value.strftime("%H:%M")


templates.env.filters["dt"] = format_dt
templates.env.filters["hm"] = format_time


def tracker_status(session):
    state = get_tracker_state(session)
    jobs_stored = session.query(func.count(Job.id)).scalar() or 0
    start_of_day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    new_today = (
        session.query(func.count(Job.id))
        .filter(Job.discovered_at >= start_of_day)
        .scalar()
        or 0
    )
    error = state.last_error
    return {
        "running": error is None,
        "last_check_at": state.last_check_at,
        "next_check_at": next_check_at(state.last_check_at),
        "last_error": error,
        "jobs_stored": jobs_stored,
        "new_jobs_today": new_today,
        "last_jobs_found": state.last_jobs_found,
        "last_new_jobs": state.last_new_jobs,
        "interval_minutes": config.CHECK_INTERVAL_MINUTES,
    }


@app.get("/")
def index(
    request: Request,
    q: str = "",
    location: str = "all",
    date: str = "all",
    search_id: str = "all",
    remote: str = "all",
    sort: str = "newest",
    page: int = 1,
):
    session = get_session()
    try:
        query = apply_filters(
            session.query(Job),
            q=q,
            location=location,
            date=date,
            search_id=search_id,
            remote=remote,
            sort=sort,
        )
        listing = paginate(query, page=page)
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "status": tracker_status(session),
                "jobs": listing["items"],
                "page": listing["page"],
                "total_pages": listing["total_pages"],
                "total": listing["total"],
                "q": q,
                "location": location,
                "date": date,
                "search_id": search_id,
                "remote": remote,
                "sort": sort,
                "locations": distinct_locations(session),
                "searches": saved_search_choices(session),
                "date_options": DATE_OPTIONS,
                "remote_options": REMOTE_OPTIONS,
                "sort_options": SORT_OPTIONS,
            },
        )
    finally:
        session.close()


@app.get("/settings")
def settings(request: Request, edit: int | None = None):
    session = get_session()
    try:
        searches = session.query(SavedSearch).order_by(SavedSearch.id.asc()).all()
        editing = None
        if edit is not None:
            editing = session.get(SavedSearch, edit)
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "status": tracker_status(session),
                "searches": searches,
                "editing": editing,
            },
        )
    finally:
        session.close()


@app.post("/settings/searches")
def add_search(
    name: str = Form(...),
    keywords: str = Form(...),
    location: str = Form(""),
):
    session = get_session()
    try:
        session.add(
            SavedSearch(
                name=name.strip() or keywords.strip(),
                keywords=keywords.strip(),
                location=location.strip(),
                enabled=True,
                first_scan_done=False,
            )
        )
        session.commit()
    except Exception:
        logger.exception("Database error while adding a saved search")
        session.rollback()
    finally:
        session.close()
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/searches/{search_id}/edit")
def edit_search(
    search_id: int,
    name: str = Form(...),
    keywords: str = Form(...),
    location: str = Form(""),
):
    session = get_session()
    try:
        search = session.get(SavedSearch, search_id)
        if search:
            keywords_changed = search.keywords != keywords.strip()
            location_changed = search.location != location.strip()
            search.name = name.strip() or keywords.strip()
            search.keywords = keywords.strip()
            search.location = location.strip()
            if keywords_changed or location_changed:
                search.first_scan_done = False
            session.commit()
    except Exception:
        logger.exception("Database error while editing a saved search")
        session.rollback()
    finally:
        session.close()
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/searches/{search_id}/delete")
def delete_search(search_id: int):
    session = get_session()
    try:
        search = session.get(SavedSearch, search_id)
        if search:
            session.query(Job).filter(Job.search_id == search_id).update(
                {Job.search_id: None},
                synchronize_session=False,
            )
            session.delete(search)
            session.commit()
    except Exception:
        logger.exception("Database error while deleting a saved search")
        session.rollback()
    finally:
        session.close()
    return RedirectResponse("/settings", status_code=303)


@app.post("/settings/searches/{search_id}/toggle")
def toggle_search(search_id: int, enabled: str = Form("off")):
    session = get_session()
    try:
        search = session.get(SavedSearch, search_id)
        if search:
            search.enabled = enabled in ("on", "true", "1", "yes")
            session.commit()
    except Exception:
        logger.exception("Database error while toggling a saved search")
        session.rollback()
    finally:
        session.close()
    return RedirectResponse("/settings", status_code=303)


@app.post("/check-now")
def check_now():
    result = run_all_searches(notify=True)
    return JSONResponse(result)


@app.get("/api/status")
def api_status():
    session = get_session()
    try:
        data = tracker_status(session)
        data["last_check_at"] = format_dt(data["last_check_at"])
        data["next_check_at"] = format_time(data["next_check_at"]) if data["next_check_at"] else "—"
        return data
    finally:
        session.close()


def main():
    init_db()
    logger.info("Application started")
    start_scheduler()
    url = f"http://{config.HOST}:{config.PORT}"
    try:
        webbrowser.open(url)
    except Exception:
        logger.exception("Could not open the system browser")
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="info")


if __name__ == "__main__":
    main()
