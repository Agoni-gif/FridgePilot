from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .context import PreferencePatch, PublicContext
from .recipe import Recipe


class ChatPreferences(BaseModel):
    max_time_minutes: int | None = Field(default=None, ge=1, le=300)
    servings: int | None = Field(default=None, ge=1, le=20)
    dietary_restrictions: list[str] = Field(default_factory=list, max_length=10)


class ChatRequest(BaseModel):
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
    search_used: bool = False
    elapsed_ms: int = 0
    prompt_version: str | None = None
    detail: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    status: Literal["completed", "insufficient_sources", "error", "clarification"]
    recipe: Recipe | None = None
    message: str | None = None
    thinking: str | None = None
    meta: ChatMeta
    context: PublicContext | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
