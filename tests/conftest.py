from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    monkeypatch.setattr("config.DATABASE_URL", f"sqlite:///{db_path.as_posix()}")

    import database

    database.configure_engine()
    database.init_db()
    session = database.get_session()
    yield session
    session.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "jobs.db"
    monkeypatch.setattr("config.DATABASE_URL", f"sqlite:///{db_path.as_posix()}")

    import database

    database.configure_engine()
    database.init_db()

    from fastapi.testclient import TestClient
    from app import app

    with TestClient(app) as test_client:
        yield test_client
