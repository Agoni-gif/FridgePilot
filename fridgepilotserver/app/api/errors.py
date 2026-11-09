import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.common.api_codes import ApiCode
from app.common.response import error_body

logger = logging.getLogger(__name__)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "-")
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail and "message" in detail:
        body = {"error": detail}
        code = detail.get("code")
    else:
        body = error_body(ApiCode.HTTP_ERROR, str(detail))
        code = ApiCode.HTTP_ERROR
    logger.warning(
        "request_id=%s http_error status=%s code=%s path=%s",
        request_id,
        exc.status_code,
        code,
        request.url.path,
    )
    return JSONResponse(status_code=exc.status_code, content=body)


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "-")
    logger.warning(
        "request_id=%s validation_error path=%s issues=%s",
        request_id,
        request.url.path,
        exc.errors(),
    )
    return JSONResponse(
        status_code=422,
        content=error_body(
            ApiCode.VALIDATION_ERROR,
            details={"issues": exc.errors()},
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "-")
    logger.exception(
        "request_id=%s unhandled_error path=%s: %s",
        request_id,
        request.url.path,
        exc,
    )
    return JSONResponse(
        status_code=500,
        content=error_body(ApiCode.INTERNAL_ERROR),
    )
