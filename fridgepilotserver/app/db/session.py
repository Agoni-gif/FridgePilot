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
    _ensure_columns()


def _ensure_columns() -> None:
    """Add columns that create_all will not alter on existing tables."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    dialect = engine.dialect.name
    tables = set(inspector.get_table_names())

    def _add_column(table: str, column: str, ddl_sqlite: str, ddl_other: str) -> None:
        cols = {col["name"] for col in inspector.get_columns(table)}
        if column in cols:
            return
        with engine.begin() as conn:
            conn.execute(text(ddl_sqlite if dialect == "sqlite" else ddl_other))

    if "sessions" in tables:
        session_cols = {col["name"] for col in inspector.get_columns("sessions")}
        if "user_id" not in session_cols:
            with engine.begin() as conn:
                if dialect == "sqlite":
                    conn.execute(text("ALTER TABLE sessions ADD COLUMN user_id VARCHAR(64)"))
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_sessions_user_id ON sessions (user_id)"
                        )
                    )
                else:
                    conn.execute(
                        text("ALTER TABLE sessions ADD COLUMN user_id VARCHAR(64) NULL")
                    )
                    conn.execute(text("CREATE INDEX ix_sessions_user_id ON sessions (user_id)"))

        _add_column(
            "sessions",
            "context_version",
            "ALTER TABLE sessions ADD COLUMN context_version INTEGER DEFAULT 0",
            "ALTER TABLE sessions ADD COLUMN context_version INTEGER NOT NULL DEFAULT 0",
        )
        _add_column(
            "sessions",
            "context_start_message_id",
            "ALTER TABLE sessions ADD COLUMN context_start_message_id INTEGER",
            "ALTER TABLE sessions ADD COLUMN context_start_message_id INTEGER NULL",
        )
        _add_column(
            "sessions",
            "state_json",
            "ALTER TABLE sessions ADD COLUMN state_json TEXT",
            "ALTER TABLE sessions ADD COLUMN state_json TEXT NULL",
        )
        _add_column(
            "sessions",
            "session_overrides_json",
            "ALTER TABLE sessions ADD COLUMN session_overrides_json TEXT",
            "ALTER TABLE sessions ADD COLUMN session_overrides_json TEXT NULL",
        )
        _add_column(
            "sessions",
            "active_request_id",
            "ALTER TABLE sessions ADD COLUMN active_request_id VARCHAR(64)",
            "ALTER TABLE sessions ADD COLUMN active_request_id VARCHAR(64) NULL",
        )
        _add_column(
            "sessions",
            "active_request_expires_at",
            "ALTER TABLE sessions ADD COLUMN active_request_expires_at DATETIME",
            "ALTER TABLE sessions ADD COLUMN active_request_expires_at DATETIME NULL",
        )
        _add_column(
            "sessions",
            "summary_json",
            "ALTER TABLE sessions ADD COLUMN summary_json TEXT",
            "ALTER TABLE sessions ADD COLUMN summary_json TEXT NULL",
        )
        _add_column(
            "sessions",
            "summary_until_message_id",
            "ALTER TABLE sessions ADD COLUMN summary_until_message_id INTEGER",
            "ALTER TABLE sessions ADD COLUMN summary_until_message_id INTEGER NULL",
        )
        _add_column(
            "sessions",
            "summary_version",
            "ALTER TABLE sessions ADD COLUMN summary_version INTEGER DEFAULT 0",
            "ALTER TABLE sessions ADD COLUMN summary_version INTEGER NOT NULL DEFAULT 0",
        )

    if "messages" in tables:
        message_cols = {col["name"] for col in inspector.get_columns("messages")}
        if "thinking" not in message_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE messages ADD COLUMN thinking TEXT"))
        _add_column(
            "messages",
            "reply_to_message_id",
            "ALTER TABLE messages ADD COLUMN reply_to_message_id INTEGER",
            "ALTER TABLE messages ADD COLUMN reply_to_message_id INTEGER NULL",
        )
        _add_column(
            "messages",
            "response_status",
            "ALTER TABLE messages ADD COLUMN response_status VARCHAR(32)",
            "ALTER TABLE messages ADD COLUMN response_status VARCHAR(32) NULL",
        )

    if "recipes" in tables:
        _add_column(
            "recipes",
            "assistant_message_id",
            "ALTER TABLE recipes ADD COLUMN assistant_message_id INTEGER",
            "ALTER TABLE recipes ADD COLUMN assistant_message_id INTEGER NULL",
        )
        with engine.begin() as conn:
            try:
                if dialect == "sqlite":
                    conn.execute(
                        text(
                            "CREATE UNIQUE INDEX IF NOT EXISTS "
                            "uq_recipes_assistant_message_id "
                            "ON recipes (assistant_message_id)"
                        )
                    )
                else:
                    conn.execute(
                        text(
                            "CREATE UNIQUE INDEX uq_recipes_assistant_message_id "
                            "ON recipes (assistant_message_id)"
                        )
                    )
            except Exception:
                # Index may already exist on MySQL / re-runs.
                pass


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
