import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

import config
from models import Base, Job, SavedSearch, TrackerState

logger = logging.getLogger(__name__)

engine = None
SessionLocal = None


def configure_engine(url=None):
    """Create (or recreate) the SQLAlchemy engine and session factory."""
    global engine, SessionLocal
    url = url or config.DATABASE_URL
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_engine(url, connect_args=connect_args, future=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine


def get_session():
    if SessionLocal is None:
        configure_engine()
    return SessionLocal()


def seed_defaults(session):
    if session.query(SavedSearch).count() == 0:
        for item in config.DEFAULT_SEARCHES:
            session.add(
                SavedSearch(
                    name=item["name"],
                    keywords=item["keywords"],
                    location=item["location"],
                    enabled=True,
                    first_scan_done=False,
                )
            )
        logger.info("Created default saved searches")

    if session.query(TrackerState).count() == 0:
        session.add(TrackerState(id=1))

    session.commit()


def ensure_schema():
    """Add columns created after the first run, then backfill posted_at."""
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("jobs")}
    if "posted_at" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN posted_at DATETIME"))
        logger.info("Added posted_at column")

    from filters import parse_posted_at

    session = get_session()
    try:
        missing = session.query(Job).filter(Job.posted_at.is_(None), Job.posted_text.isnot(None)).all()
        for job in missing:
            job.posted_at = parse_posted_at(job.posted_text)
        if missing:
            session.commit()
            logger.info("Backfilled posted_at for %s jobs", len(missing))
    except Exception:
        logger.exception("Database error while backfilling posted_at")
        session.rollback()
    finally:
        session.close()


def init_db(url=None):
    if engine is None or url:
        configure_engine(url)
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    session = get_session()
    try:
        seed_defaults(session)
    except Exception:
        logger.exception("Database error while seeding defaults")
        session.rollback()
        raise
    finally:
        session.close()


def get_tracker_state(session):
    state = session.get(TrackerState, 1)
    if state is None:
        state = TrackerState(id=1)
        session.add(state)
        session.commit()
        session.refresh(state)
    return state
