from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class SavedSearch(Base):
    __tablename__ = "saved_searches"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    keywords = Column(String(255), nullable=False)
    location = Column(String(255), nullable=False, default="")
    enabled = Column(Boolean, nullable=False, default=True)
    first_scan_done = Column(Boolean, nullable=False, default=False)

    jobs = relationship("Job", back_populates="search")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)
    linkedin_id = Column(String(64), unique=True, nullable=False, index=True)
    title = Column(String(500), nullable=False, default="")
    company = Column(String(255), nullable=False, default="")
    location = Column(String(255), nullable=False, default="")
    url = Column(Text, nullable=False, default="")
    description = Column(Text, nullable=True)
    posted_text = Column(String(100), nullable=True)
    posted_at = Column(DateTime, nullable=True, index=True)
    employment_type = Column(String(100), nullable=True)
    experience_level = Column(String(100), nullable=True)
    remote_type = Column(String(50), nullable=True)
    discovered_at = Column(DateTime, nullable=False, default=datetime.now, index=True)
    search_name = Column(String(255), nullable=True)
    search_id = Column(Integer, ForeignKey("saved_searches.id"), nullable=True)

    search = relationship("SavedSearch", back_populates="jobs")


class TrackerState(Base):
    __tablename__ = "tracker_state"

    id = Column(Integer, primary_key=True)
    last_check_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    last_jobs_found = Column(Integer, nullable=False, default=0)
    last_new_jobs = Column(Integer, nullable=False, default=0)
