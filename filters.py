import re
from datetime import datetime, timedelta

from sqlalchemy import or_

import config
from models import Job, SavedSearch

DATE_OPTIONS = [
    ("all", "All"),
    ("15m", "Last 15 minutes"),
    ("1h", "Last hour"),
    ("24h", "Last 24 hours"),
    ("3d", "Last 3 days"),
    ("7d", "Last 7 days"),
]

REMOTE_OPTIONS = [
    ("all", "All"),
    ("remote", "Remote"),
    ("hybrid", "Hybrid"),
    ("on-site", "On-site"),
]

SORT_OPTIONS = [
    ("newest", "Newest first"),
    ("oldest", "Oldest first"),
]

DATE_DELTAS = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "3d": timedelta(days=3),
    "7d": timedelta(days=7),
}

RELATIVE_POSTED_RE = re.compile(
    r"(?P<num>\d+)\s*(?P<unit>minutes?|mins?|hours?|hrs?|days?|weeks?|months?|years?)\s+ago",
    re.IGNORECASE,
)


def _parse_iso_datetime(value):
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
        return parsed.replace(tzinfo=None)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def parse_posted_at(posted_text, datetime_value=None, now=None):
    """Convert LinkedIn posted text like '2 days ago' into a datetime."""
    now = now or datetime.now()
    iso = _parse_iso_datetime(datetime_value) or _parse_iso_datetime(posted_text)
    if iso:
        return iso

    text = re.sub(r"^(reposted|posted)\s+", "", (posted_text or "").strip(), flags=re.IGNORECASE)
    if not text:
        return None

    lowered = text.lower()
    if lowered in {"just now", "now", "moments ago", "moment ago", "today"}:
        return now
    if lowered == "yesterday":
        return now - timedelta(days=1)

    match = RELATIVE_POSTED_RE.search(text)
    if not match:
        return None

    num = int(match.group("num"))
    unit = match.group("unit").lower()
    if unit.startswith("min"):
        return now - timedelta(minutes=num)
    if unit.startswith("hour") or unit.startswith("hr"):
        return now - timedelta(hours=num)
    if unit.startswith("day"):
        return now - timedelta(days=num)
    if unit.startswith("week"):
        return now - timedelta(weeks=num)
    if unit.startswith("month"):
        return now - timedelta(days=30 * num)
    if unit.startswith("year"):
        return now - timedelta(days=365 * num)
    return None


def apply_filters(query, q="", location="all", date="all", search_id="all", remote="all", sort="newest"):
    q = (q or "").strip()
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Job.title.ilike(like),
                Job.company.ilike(like),
                Job.location.ilike(like),
                Job.description.ilike(like),
            )
        )

    if location and location != "all":
        query = query.filter(Job.location == location)

    delta = DATE_DELTAS.get(date)
    if delta:
        cutoff = datetime.now() - delta
        query = query.filter(Job.posted_at.isnot(None), Job.posted_at >= cutoff)

    if search_id and search_id != "all":
        try:
            query = query.filter(Job.search_id == int(search_id))
        except (TypeError, ValueError):
            pass

    if remote and remote != "all":
        query = query.filter(Job.remote_type == remote)

    if sort == "oldest":
        query = query.order_by(Job.discovered_at.asc(), Job.id.asc())
    else:
        query = query.order_by(Job.discovered_at.desc(), Job.id.desc())

    return query


def paginate(query, page=1, per_page=None):
    per_page = per_page or config.JOBS_PER_PAGE
    try:
        page = max(int(page), 1)
    except (TypeError, ValueError):
        page = 1
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    total_pages = max((total + per_page - 1) // per_page, 1)
    return {
        "items": items,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": total_pages,
    }


def distinct_locations(session):
    rows = (
        session.query(Job.location)
        .filter(Job.location.isnot(None), Job.location != "")
        .distinct()
        .order_by(Job.location.asc())
        .all()
    )
    return [row[0] for row in rows]


def saved_search_choices(session):
    return session.query(SavedSearch).order_by(SavedSearch.name.asc()).all()
