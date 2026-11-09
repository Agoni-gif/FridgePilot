from datetime import datetime

from pydantic import BaseModel, Field

from .recipe import Recipe


class SessionSummary(BaseModel):
    id: str
    title: str
    created_at: datetime
    last_active_at: datetime


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary] = Field(default_factory=list)


class SessionMessage(BaseModel):
    id: int
    role: str
    content: str
    thinking: str | None = None
    created_at: datetime
    recipe: Recipe | None = None


class SessionMessagesResponse(BaseModel):
    session_id: str
    title: str
    messages: list[SessionMessage] = Field(default_factory=list)
