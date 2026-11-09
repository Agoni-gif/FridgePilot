"""聊天接口请求/响应 schema。"""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .context import PreferencePatch, PublicContext
from .recipe import Recipe


class ChatPreferences(BaseModel):
    """单轮可选偏好（与长期偏好不同，仅作用于本次请求）。"""

    max_time_minutes: int | None = Field(default=None, ge=1, le=300)
    servings: int | None = Field(default=None, ge=1, le=20)
    dietary_restrictions: list[str] = Field(default_factory=list, max_length=10)


class ChatRequest(BaseModel):
    """同步/流式聊天请求体。"""

    message: str = Field(..., min_length=1, max_length=1000)
    session_id: str | None = Field(default=None, max_length=64)
    preferences: ChatPreferences | None = None
    preference_patch: PreferencePatch | None = None

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("message must not be empty")
        return cleaned


class ChatMeta(BaseModel):
    """聊天响应元信息：是否检索、耗时、提示词版本等。"""
    search_used: bool = False
    elapsed_ms: int = 0
    prompt_version: str | None = None
    detail: str | None = None


class ChatResponse(BaseModel):
    """同步聊天完整响应。"""
    session_id: str
    status: Literal["completed", "insufficient_sources", "error", "clarification"]
    recipe: Recipe | None = None
    message: str | None = None
    thinking: str | None = None
    meta: ChatMeta
    context: PublicContext | None = None


class ErrorBody(BaseModel):
    """错误 detail 结构（兼容部分客户端模型）。"""
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    """错误响应信封。"""
    error: ErrorBody
