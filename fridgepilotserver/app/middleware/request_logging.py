from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("app.request")

SKIP_PATHS = {"/api/v1/health", "/docs", "/openapi.json", "/redoc"}


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.exception(
                "request_id=%s method=%s path=%s failed after %sms",
                request_id,
                request.method,
                request.url.path,
                elapsed_ms,
            )
            raise

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        response.headers["X-Request-Id"] = request_id

        if request.url.path not in SKIP_PATHS:
            logger.info(
                "request_id=%s method=%s path=%s status=%s elapsed_ms=%s",
                request_id,
                request.method,
                request.url.path,
                response.status_code,
                elapsed_ms,
            )
        return response
