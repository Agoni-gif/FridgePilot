from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Force sqlite before app modules create the engine from Settings.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-jwt-secret"
os.environ["LLM_API_KEY"] = "test"
os.environ["TAVILY_API_KEY"] = "test"

from app.common.config import get_settings
from app.db.session import Base, create_db_engine, get_db
from app.main import create_app
from app.services.captcha_service import get_captcha_service


@pytest.fixture()
def client():
    get_settings.cache_clear()
    get_captcha_service().reset_for_tests()
    # 测试进程内若素材曾改名，重新扫盘避免沿用旧路径
    svc = get_captcha_service()
    svc._bg_paths = svc._discover_backgrounds()
    svc._scaled_cache.clear()

    engine = create_db_engine("sqlite://")
    # StaticPool keeps the same in-memory DB across connections
    engine.dispose()
    from sqlalchemy import create_engine

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    app = create_app()

    def _override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    get_captcha_service().reset_for_tests()
    get_settings.cache_clear()
