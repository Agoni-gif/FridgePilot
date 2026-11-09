"""统一 API 响应辅助。

错误信封（兼容前端）::

    {"error": {"code": "...", "message": "...", "details"?: ...}}

成功响应仍通过 ``response_model`` 直接返回资源体。
请用 ``ApiCode`` + 本模块助手，避免在路由里硬编码 detail 字典。
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
    """可选的显式成功包装（多数接口直接返回资源体）。"""

    code: str = ApiCode.OK
    message: str = API_CODE_MESSAGES[ApiCode.OK]
    data: Any = None


def resolve_code(code: ApiCode | str) -> ApiCode | str:
    """规范化业务码。"""
    if isinstance(code, ApiCode):
        return code
    try:
        return ApiCode(code)
    except ValueError:
        return code


def default_message(code: ApiCode | str) -> str:
    """取业务码默认用户文案。"""
    resolved = resolve_code(code)
    if isinstance(resolved, ApiCode):
        return API_CODE_MESSAGES[resolved]
    return str(code)


def default_status(code: ApiCode | str, fallback: int = 400) -> int:
    """取业务码默认 HTTP 状态码。"""
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
    """构造 HTTPException / SSE 用的内部 detail 载荷。"""
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
    """构造完整 JSON 体 ``{"error": {...}}``。"""
    return {"error": error_detail(code, message, details=details)}


def api_error(
    code: ApiCode | str,
    message: str | None = None,
    *,
    status_code: int | None = None,
    details: dict[str, Any] | None = None,
) -> HTTPException:
    """创建带统一 error detail 形态的 HTTPException。"""
    return HTTPException(
        status_code=status_code if status_code is not None else default_status(code),
        detail=error_detail(code, message, details=details),
    )


class ApiException(Exception):
    """携带统一业务码的领域异常。

    Service 可抛出本类（或子类），路由用 ``raise api_error_from_exc(exc)`` 转换。
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
    """将 ApiException 转为 HTTPException。"""
    return api_error(
        exc.code,
        exc.message,
        status_code=exc.status_code,
        details=exc.details,
    )


def ok(data: Any = None, *, message: str | None = None) -> dict[str, Any]:
    """可选成功信封（仅在端点需要显式包装时使用）。"""
    return {
        "code": ApiCode.OK,
        "message": message if message is not None else API_CODE_MESSAGES[ApiCode.OK],
        "data": data,
    }
