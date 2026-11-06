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
from app.api.routes import router
from app.common.config import get_settings
from app.common.logging_setup import setup_logging
from app.db.session import init_db
from app.middleware import RequestLoggingMiddleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    setup_logging(settings)
    logger.info("Starting FridgePilot server env=%s", settings.app_env)
    init_db()
    logger.info("Database ready dialect=%s", settings.database_url.split(":")[0])
    yield
    logger.info("Shutting down FridgePilot server")


def create_app() -> FastAPI:
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
    return app


app = create_app()
