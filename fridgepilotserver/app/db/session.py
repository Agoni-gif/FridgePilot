from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.common.config import get_settings


class Base(DeclarativeBase):
    pass


def _ensure_sqlite_dir(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return
    raw = database_url.removeprefix("sqlite:///")
    if raw == ":memory:" or raw.startswith(":memory:"):
        return
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)


def _is_sqlite(database_url: str) -> bool:
    return database_url.startswith("sqlite:")


def _is_mysql(database_url: str) -> bool:
    return database_url.startswith("mysql:") or database_url.startswith("mysql+")


def create_db_engine(database_url: str) -> Engine:
    _ensure_sqlite_dir(database_url)

    if _is_sqlite(database_url):
        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine

    # MySQL / other dialects
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_recycle=28000,
    )


settings = get_settings()
engine = create_db_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    # Import models so metadata is populated
    from app.db import models  # noqa: F401

    if _is_mysql(settings.database_url):
        _ensure_mysql_database(settings.database_url)

    Base.metadata.create_all(bind=engine)


def _ensure_mysql_database(database_url: str) -> None:
    """Create the target schema if it does not exist (local MySQL convenience)."""
    parsed = urlparse(database_url)
    db_name = (parsed.path or "").lstrip("/")
    if not db_name:
        return

    # Connect to server without selecting the database
    server_url = database_url.rsplit("/", 1)[0] + "/"
    server_engine = create_engine(server_url, pool_pre_ping=True)
    try:
        with server_engine.begin() as conn:
            conn.exec_driver_sql(
                f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    finally:
        server_engine.dispose()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
