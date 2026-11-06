import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "-")
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail and "message" in detail:
        body = {"error": detail}
        code = detail.get("code")
    else:
        body = {
            "error": {
                "code": "HTTP_ERROR",
                "message": str(detail),
            }
        }
        code = "HTTP_ERROR"
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
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "请求参数无效，请检查输入长度和字段格式。",
                "details": {"issues": exc.errors()},
            }
        },
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
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "服务暂时不可用，请稍后重试。",
            }
        },
    )
