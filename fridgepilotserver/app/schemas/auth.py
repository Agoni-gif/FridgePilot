from __future__ import annotations

import re

from pydantic import BaseModel, EmailStr, Field, field_validator

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,32}$")


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    email: EmailStr | None = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        cleaned = value.strip()
        if not USERNAME_RE.fullmatch(cleaned):
            raise ValueError("用户名仅支持 3–32 位字母、数字或下划线")
        return cleaned


class LoginRequest(BaseModel):
    """使用用户名或邮箱（account）登录，并附带滑块验证码结果。"""

    account: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)
    captcha_id: str = Field(min_length=8, max_length=64)
    captcha_x: float = Field(ge=0, le=1000)

    @field_validator("account")
    @classmethod
    def strip_account(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("账号不能为空")
        return cleaned


class CaptchaChallengeResponse(BaseModel):
    captcha_id: str
    bg_image: str
    piece_image: str
    piece_y: int
    piece_pad: int = 0
    bg_width: int
    bg_height: int
    piece_size: int


class CaptchaVerifyRequest(BaseModel):
    captcha_id: str = Field(min_length=8, max_length=64)
    captcha_x: float = Field(ge=0, le=1000)


class CaptchaVerifyResponse(BaseModel):
    ok: bool = True


class UserPublic(BaseModel):
    id: str
    username: str
    email: str | None = None


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


class PhoneSendCodeRequest(BaseModel):
    phone: str = Field(min_length=5, max_length=32)


class PhoneLoginRequest(BaseModel):
    phone: str = Field(min_length=5, max_length=32)
    code: str = Field(min_length=4, max_length=12)
