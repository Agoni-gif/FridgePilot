from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.recipe import Ingredient


CLEARABLE_FIELDS = frozenset(
    {
        "ingredients",
        "meal",
        "servings",
        "max_time_minutes",
        "cuisine",
        "dietary_restrictions",
    }
)

SETTABLE_SCALAR_FIELDS = frozenset(
    {
        "meal",
        "servings",
        "max_time_minutes",
        "cuisine",
    }
)


class SessionState(BaseModel):
    schema_version: int = 1
    ingredients: list[Ingredient] = Field(default_factory=list, max_length=30)
    meal: str | None = Field(default=None, max_length=30)
    servings: int | None = Field(default=None, ge=1, le=20)
    max_time_minutes: int | None = Field(default=None, ge=1, le=300)
    cuisine: str | None = Field(default=None, max_length=50)
    dietary_restrictions: list[str] = Field(default_factory=list, max_length=10)
    excluded_recipe_titles: list[str] = Field(default_factory=list, max_length=10)
    last_recipe_id: int | None = None

    @field_validator("dietary_restrictions", "excluded_recipe_titles")
    @classmethod
    def trim_string_lists(cls, values: list[str]) -> list[str]:
        return [v.strip() for v in values if v and v.strip()]


class SessionOverrides(BaseModel):
    """Explicit set/clear markers relative to defaults (P0: no long-term defaults)."""

    set_fields: dict[str, Any] = Field(default_factory=dict)
    cleared_fields: list[str] = Field(default_factory=list)

    @field_validator("cleared_fields")
    @classmethod
    def validate_cleared(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for name in values:
            key = name.strip()
            if key in CLEARABLE_FIELDS and key not in cleaned:
                cleaned.append(key)
        return cleaned


class IngredientOps(BaseModel):
    add: list[Ingredient] = Field(default_factory=list, max_length=30)
    remove: list[str] = Field(default_factory=list, max_length=30)
    replace: list[Ingredient] | None = Field(default=None, max_length=30)


class DietaryOps(BaseModel):
    add: list[str] = Field(default_factory=list, max_length=10)
    remove: list[str] = Field(default_factory=list, max_length=10)
    replace: list[str] | None = Field(default=None, max_length=10)


class StateOps(BaseModel):
    set: dict[str, Any] = Field(default_factory=dict)
    clear: list[str] = Field(default_factory=list)
    ingredients: IngredientOps | None = None
    dietary_restrictions: DietaryOps | None = None
    exclude_recipe_title: str | None = Field(default=None, max_length=120)

    @field_validator("clear")
    @classmethod
    def validate_clear(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for name in values:
            key = name.strip()
            if key in CLEARABLE_FIELDS and key not in cleaned:
                cleaned.append(key)
        return cleaned


class PreferencePatch(BaseModel):
    set: dict[str, Any] = Field(default_factory=dict)
    clear: list[str] = Field(default_factory=list)

    @field_validator("clear")
    @classmethod
    def validate_clear(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for name in values:
            key = name.strip()
            if key in CLEARABLE_FIELDS and key not in cleaned:
                cleaned.append(key)
        return cleaned


IntentKind = Literal["generate", "revise", "explain", "clarify"]


class ParseResult(BaseModel):
    thinking: str | None = None
    intent: IntentKind = "generate"
    clarification_question: str | None = Field(default=None, max_length=500)
    referenced_recipe_id: int | None = None
    ops: StateOps = Field(default_factory=StateOps)
    search_queries: list[str] = Field(default_factory=list, max_length=4)
    explain_focus: str | None = Field(default=None, max_length=200)


class PublicContext(BaseModel):
    context_version: int = 0
    context_start_message_id: int | None = None
    state: SessionState | None = None
    long_term_preferences_applied: bool = False
    long_term_preferences_version: int | None = None


class RecentTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    response_status: str | None = None
    recipe_title: str | None = None
    message_id: int | None = None


class ConversationSummary(BaseModel):
    """Persisted background summary for turns outside the recent window."""

    text: str = Field(..., min_length=1, max_length=2000)
    covered_from_message_id: int | None = None
    covered_until_message_id: int


class AssembledContext(BaseModel):
    current_message: str
    recent_turns: list[RecentTurn] = Field(default_factory=list)
    session_state: SessionState | None = None
    session_overrides: SessionOverrides = Field(default_factory=SessionOverrides)
    last_recipe: dict[str, Any] | None = None
    conversation_summary: str | None = None
    summary_until_message_id: int | None = None
    user_defaults: dict[str, Any] = Field(default_factory=dict)
    allergies: list[str] = Field(default_factory=list)
    long_term_preferences_applied: bool = False
    long_term_preferences_version: int | None = None
    context_version: int = 0
    context_start_message_id: int | None = None
