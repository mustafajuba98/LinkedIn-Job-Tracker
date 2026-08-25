from pathlib import Path

APP_DIR = Path(__file__).resolve().parent

CHECK_INTERVAL_MINUTES = 5
HEADLESS = True
DATABASE_URL = f"sqlite:///{(APP_DIR / 'jobs.db').as_posix()}"
MAX_JOBS_PER_SEARCH = 50
JOBS_PER_PAGE = 50
HOST = "127.0.0.1"
PORT = 8000

DEFAULT_SEARCHES = [
    {"name": "Python Backend", "keywords": "Python Backend", "location": "Egypt"},
    {"name": "Django Developer", "keywords": "Django Developer", "location": "Egypt"},
    {"name": "Backend Engineer Python", "keywords": "Backend Engineer Python", "location": "Egypt"},
    {"name": "FastAPI Developer", "keywords": "FastAPI Developer", "location": "Egypt"},
]
