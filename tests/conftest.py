"""Use an isolated session signing secret before application imports."""

import os
import secrets

os.environ["SECRET_KEY"] = secrets.token_urlsafe(32)
os.environ["APP_ENV"] = "test"

import pytest
from sqlalchemy.orm import sessionmaker

from app import database


@pytest.fixture
def isolated_database(tmp_path, monkeypatch):
    engine = database.create_sqlite_engine(f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=engine))
    database.init_db()
    try:
        yield engine
    finally:
        engine.dispose()
