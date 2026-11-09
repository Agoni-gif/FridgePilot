"""Unified API response helpers.

Error envelope (kept for frontend compatibility)::

    {"error": {"code": "...", "message": "...", "details"?: ...}}

Success responses continue to return the resource/body directly via
``response_model``. Use ``ApiCode`` + these helpers instead of hardcoding
``detail={"code": ..., "message": ...}`` in every route.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel

from app.common.api_codes import API_CODE_HTTP_STATUS, API_CODE_MESSAGES, ApiCode


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class SuccessResponse(BaseModel):
    """Optional envelope when an endpoint wants an explicit ok wrapper."""

    code: str = ApiCode.OK
    message: str = API_CODE_MESSAGES[ApiCode.OK]
    data: Any = None


def resolve_code(code: ApiCode | str) -> ApiCode | str:
    if isinstance(code, ApiCode):
        return code
    try:
        return ApiCode(code)
    except ValueError:
        return code


def default_message(code: ApiCode | str) -> str:
    resolved = resolve_code(code)
    if isinstance(resolved, ApiCode):
        return API_CODE_MESSAGES[resolved]
    return str(code)


def default_status(code: ApiCode | str, fallback: int = 400) -> int:
    resolved = resolve_code(code)
    if isinstance(resolved, ApiCode):
        return API_CODE_HTTP_STATUS[resolved]
    return fallback


def error_detail(
    code: ApiCode | str,
    message: str | None = None,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the inner ``detail`` payload for ``HTTPException`` / SSE errors."""
    payload: dict[str, Any] = {
        "code": str(code),
        "message": message if message is not None else default_message(code),
    }
    if details is not None:
        payload["details"] = details
    return payload


def error_body(
    code: ApiCode | str,
    message: str | None = None,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the full JSON body ``{"error": {...}}``."""
    return {"error": error_detail(code, message, details=details)}


def api_error(
    code: ApiCode | str,
    message: str | None = None,
    *,
    status_code: int | None = None,
    details: dict[str, Any] | None = None,
) -> HTTPException:
    """Create an ``HTTPException`` with the unified error detail shape."""
    return HTTPException(
        status_code=status_code if status_code is not None else default_status(code),
        detail=error_detail(code, message, details=details),
    )


class ApiException(Exception):
    """Domain exception carrying a unified API code.

    Services can raise this (or subclasses) and routes convert with
    ``raise api_error_from_exc(exc)``.
    """

    def __init__(
        self,
        code: ApiCode | str,
        message: str | None = None,
        *,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = str(code)
        self.message = message if message is not None else default_message(code)
        self.status_code = (
            status_code if status_code is not None else default_status(code)
        )
        self.details = details
        super().__init__(self.message)


def api_error_from_exc(exc: ApiException) -> HTTPException:
    return api_error(
        exc.code,
        exc.message,
        status_code=exc.status_code,
        details=exc.details,
    )


def ok(data: Any = None, *, message: str | None = None) -> dict[str, Any]:
    """Optional success envelope helper (use when an endpoint needs it)."""
    return {
        "code": ApiCode.OK,
        "message": message if message is not None else API_CODE_MESSAGES[ApiCode.OK],
        "data": data,
    }
