"""Pydantic 请求/响应与领域模型 schema。"""

from .chat import ChatPreferences, ChatRequest, ChatResponse, ChatMeta
from .context import PreferencePatch, PublicContext, SessionState
from .recipe import (
    Ingredient,
    Recipe,
    RecipeSource,
    SearchResult,
    UserConstraints,
)

__all__ = [
    "ChatPreferences",
    "ChatRequest",
    "ChatResponse",
    "ChatMeta",
    "PreferencePatch",
    "PublicContext",
    "SessionState",
    "Ingredient",
    "Recipe",
    "RecipeSource",
    "SearchResult",
    "UserConstraints",
]
