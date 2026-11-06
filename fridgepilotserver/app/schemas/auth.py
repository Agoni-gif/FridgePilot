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
    """Login with username or email in the `account` field."""

    account: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("account")
    @classmethod
    def strip_account(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("账号不能为空")
        return cleaned


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
