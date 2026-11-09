"""Unified API business / error codes.

Use these constants everywhere instead of hardcoding string literals.
HTTP status defaults live in ``app.common.response``.
"""

from __future__ import annotations

from enum import StrEnum


class ApiCode(StrEnum):
    # Generic
    OK = "OK"
    HTTP_ERROR = "HTTP_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"

    # Auth / identity
    UNAUTHORIZED = "UNAUTHORIZED"
    INVALID_TOKEN = "INVALID_TOKEN"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    USERNAME_TAKEN = "USERNAME_TAKEN"
    EMAIL_TAKEN = "EMAIL_TAKEN"
    UNKNOWN_PROVIDER = "UNKNOWN_PROVIDER"

    # Captcha
    CAPTCHA_FAILED = "CAPTCHA_FAILED"
    CAPTCHA_LOCKED = "CAPTCHA_LOCKED"
    CAPTCHA_RATE_LIMITED = "CAPTCHA_RATE_LIMITED"
    CAPTCHA_ASSET_MISSING = "CAPTCHA_ASSET_MISSING"

    # Session / chat
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    SESSION_FORBIDDEN = "SESSION_FORBIDDEN"
    SESSION_BUSY = "SESSION_BUSY"
    SESSION_CONFLICT = "SESSION_CONFLICT"
    INPUT_TOO_LONG = "INPUT_TOO_LONG"

    # Preferences
    PREFERENCE_VERSION_CONFLICT = "PREFERENCE_VERSION_CONFLICT"
    PREFERENCE_INVALID = "PREFERENCE_INVALID"


# Default user-facing messages. Dynamic messages (e.g. length limits) override these.
API_CODE_MESSAGES: dict[ApiCode, str] = {
    ApiCode.OK: "ok",
    ApiCode.HTTP_ERROR: "请求失败，请稍后重试。",
    ApiCode.VALIDATION_ERROR: "请求参数无效，请检查输入长度和字段格式。",
    ApiCode.INTERNAL_ERROR: "服务暂时不可用，请稍后重试。",
    ApiCode.NOT_IMPLEMENTED: "该登录方式即将开放，请使用用户名/邮箱登录。",
    ApiCode.UNAUTHORIZED: "请先登录。",
    ApiCode.INVALID_TOKEN: "登录已失效，请重新登录。",
    ApiCode.INVALID_CREDENTIALS: "账号或密码错误",
    ApiCode.USERNAME_TAKEN: "用户名已被占用",
    ApiCode.EMAIL_TAKEN: "邮箱已被注册",
    ApiCode.UNKNOWN_PROVIDER: "不支持的登录方式。",
    ApiCode.CAPTCHA_FAILED: "验证失败，请刷新后重试",
    ApiCode.CAPTCHA_LOCKED: "尝试次数较多，请稍后再试",
    ApiCode.CAPTCHA_RATE_LIMITED: "请求有点快，请稍等几秒再试",
    ApiCode.CAPTCHA_ASSET_MISSING: "验证码背景图未配置",
    ApiCode.SESSION_NOT_FOUND: "会话不存在。",
    ApiCode.SESSION_FORBIDDEN: "无权访问该会话。",
    ApiCode.SESSION_BUSY: "会话正在处理中，请稍后再试。",
    ApiCode.SESSION_CONFLICT: "会话状态冲突，请刷新后重试。",
    ApiCode.INPUT_TOO_LONG: "输入过长。",
    ApiCode.PREFERENCE_VERSION_CONFLICT: "偏好版本冲突，请刷新后重试。",
    ApiCode.PREFERENCE_INVALID: "偏好参数无效。",
}


# Default HTTP status for each business code.
API_CODE_HTTP_STATUS: dict[ApiCode, int] = {
    ApiCode.OK: 200,
    ApiCode.HTTP_ERROR: 400,
    ApiCode.VALIDATION_ERROR: 422,
    ApiCode.INTERNAL_ERROR: 500,
    ApiCode.NOT_IMPLEMENTED: 501,
    ApiCode.UNAUTHORIZED: 401,
    ApiCode.INVALID_TOKEN: 401,
    ApiCode.INVALID_CREDENTIALS: 401,
    ApiCode.USERNAME_TAKEN: 409,
    ApiCode.EMAIL_TAKEN: 409,
    ApiCode.UNKNOWN_PROVIDER: 404,
    ApiCode.CAPTCHA_FAILED: 400,
    ApiCode.CAPTCHA_LOCKED: 429,
    ApiCode.CAPTCHA_RATE_LIMITED: 429,
    ApiCode.CAPTCHA_ASSET_MISSING: 500,
    ApiCode.SESSION_NOT_FOUND: 404,
    ApiCode.SESSION_FORBIDDEN: 403,
    ApiCode.SESSION_BUSY: 409,
    ApiCode.SESSION_CONFLICT: 409,
    ApiCode.INPUT_TOO_LONG: 422,
    ApiCode.PREFERENCE_VERSION_CONFLICT: 409,
    ApiCode.PREFERENCE_INVALID: 422,
}
