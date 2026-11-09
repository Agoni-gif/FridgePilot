"""统一业务/错误码。

请使用这些常量，避免在各处硬编码字符串。
默认 HTTP 状态码见 ``app.common.response``。
"""

from __future__ import annotations

from enum import StrEnum


class ApiCode(StrEnum):
    # 通用
    OK = "OK"
    HTTP_ERROR = "HTTP_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"

    # 认证 / 身份
    UNAUTHORIZED = "UNAUTHORIZED"
    INVALID_TOKEN = "INVALID_TOKEN"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    USERNAME_TAKEN = "USERNAME_TAKEN"
    EMAIL_TAKEN = "EMAIL_TAKEN"
    UNKNOWN_PROVIDER = "UNKNOWN_PROVIDER"

    # 验证码
    CAPTCHA_FAILED = "CAPTCHA_FAILED"
    CAPTCHA_LOCKED = "CAPTCHA_LOCKED"
    CAPTCHA_RATE_LIMITED = "CAPTCHA_RATE_LIMITED"
    CAPTCHA_ASSET_MISSING = "CAPTCHA_ASSET_MISSING"

    # 会话 / 聊天
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    SESSION_FORBIDDEN = "SESSION_FORBIDDEN"
    SESSION_BUSY = "SESSION_BUSY"
    SESSION_CONFLICT = "SESSION_CONFLICT"
    INPUT_TOO_LONG = "INPUT_TOO_LONG"

    # 偏好
    PREFERENCE_VERSION_CONFLICT = "PREFERENCE_VERSION_CONFLICT"
    PREFERENCE_INVALID = "PREFERENCE_INVALID"


# 默认面向用户的文案；动态消息（如长度限制）可覆盖
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


# 各业务码默认 HTTP 状态
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
