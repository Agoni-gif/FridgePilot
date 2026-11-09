"""FridgePilot FastAPI 应用入口：生命周期、中间件、路由与异常处理挂载。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.errors import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.api.auth_routes import router as auth_router
from app.api.preference_routes import router as preference_router
from app.api.routes import router
from app.common.config import get_settings
from app.common.logging_setup import setup_logging
from app.db.session import init_db
from app.middleware import RequestLoggingMiddleware

logger = logging.getLogger(__name__)


def _assert_database_policy(settings) -> None:
    """本地开发必须用 MySQL；SQLite 仅留给生产/Docker。"""
    url = (settings.database_url or "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is empty. For local development set a MySQL URL in the "
            "repo-root .env (see .env.example)."
        )
    is_sqlite = url.startswith("sqlite:")
    if settings.app_env == "development" and is_sqlite:
        raise RuntimeError(
            "Local development must use MySQL (DATABASE_URL=mysql+pymysql://...). "
            "SQLite is only for production/Docker Compose."
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    """启动时初始化日志与数据库，关闭时打日志。"""
    settings = get_settings()
    setup_logging(settings)
    logger.info("Starting FridgePilot server env=%s", settings.app_env)
    _assert_database_policy(settings)
    init_db()
    logger.info("Database ready dialect=%s", settings.database_url.split(":")[0])
    yield
    logger.info("Shutting down FridgePilot server")


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。"""
    settings = get_settings()
    app = FastAPI(title="FridgePilot API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestLoggingMiddleware)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(router)
    app.include_router(auth_router)
    app.include_router(preference_router)
    return app


app = create_app()
