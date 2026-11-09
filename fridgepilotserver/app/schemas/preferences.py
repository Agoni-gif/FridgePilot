"""用户长期做饭偏好 schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class PreferenceValues(BaseModel):
    """长期做饭默认值白名单字段（不含 enable/version）。"""

    servings: int | None = Field(default=None, ge=1, le=20)
    max_time_minutes: int | None = Field(default=None, ge=1, le=300)
    cuisine: str | None = Field(default=None, max_length=50)
    dietary_restrictions: list[str] = Field(default_factory=list, max_length=10)
    allergies: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("cuisine")
    @classmethod
    def trim_cuisine(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("dietary_restrictions", "allergies")
    @classmethod
    def trim_lists(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in values:
            text = raw.strip()
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned[:10]


class UserPreferencesResponse(BaseModel):
    """偏好读写 API 响应。"""

    enabled: bool = False
    preferences: PreferenceValues = Field(default_factory=PreferenceValues)
    version: int = 0
    updated_at: datetime | None = None
    exists: bool = False


class UserPreferencesPatch(BaseModel):
    """带乐观锁 version 的偏好部分更新。"""

    version: int = Field(..., ge=0)
    enabled: bool | None = None
    set: dict[str, Any] = Field(default_factory=dict)
    clear: list[str] = Field(default_factory=list)

    @field_validator("clear")
    @classmethod
    def validate_clear(cls, values: list[str]) -> list[str]:
        allowed = {
            "servings",
            "max_time_minutes",
            "cuisine",
            "dietary_restrictions",
            "allergies",
        }
        cleaned: list[str] = []
        for name in values:
            key = name.strip()
            if key in allowed and key not in cleaned:
                cleaned.append(key)
        return cleaned
