"""会话列表与消息历史 schema。"""

from datetime import datetime

from pydantic import BaseModel, Field

from .recipe import Recipe


class SessionSummary(BaseModel):
    """会话列表中的摘要项。"""

    id: str
    title: str
    created_at: datetime
    last_active_at: datetime


class SessionListResponse(BaseModel):
    """会话列表响应。"""

    sessions: list[SessionSummary] = Field(default_factory=list)


class SessionMessage(BaseModel):
    """单条会话消息（可附带菜谱）。"""

    id: int
    role: str
    content: str
    thinking: str | None = None
    created_at: datetime
    recipe: Recipe | None = None


class SessionMessagesResponse(BaseModel):
    """会话消息历史响应。"""

    session_id: str
    title: str
    messages: list[SessionMessage] = Field(default_factory=list)
