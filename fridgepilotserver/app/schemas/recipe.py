"""菜谱、来源与用户约束 schema。"""

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


class Ingredient(BaseModel):
    """食材名称与可选用量。"""

    name: str = Field(..., min_length=1, max_length=50)
    quantity: str | None = Field(default=None, max_length=50)


class UserConstraints(BaseModel):
    """传给总结模型的用户约束与检索 query。"""

    ingredients: list[Ingredient] = Field(default_factory=list, max_length=30)
    meal: str | None = Field(default=None, max_length=30)
    max_time_minutes: int | None = Field(default=None, ge=1, le=300)
    servings: int | None = Field(default=None, ge=1, le=20)
    cuisine: str | None = Field(default=None, max_length=50)
    dietary_restrictions: list[str] = Field(default_factory=list, max_length=10)
    allergies: list[str] = Field(default_factory=list, max_length=10)
    search_queries: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("dietary_restrictions", "allergies")
    @classmethod
    def trim_restrictions(cls, values: list[str]) -> list[str]:
        return [v.strip() for v in values if v and v.strip()][:10]


MAX_SOURCE_URL_LENGTH = 2048


class RecipeSource(BaseModel):
    """菜谱可核验来源链接。"""

    title: str = Field(..., min_length=1, max_length=200)
    url: str = Field(..., min_length=1, max_length=MAX_SOURCE_URL_LENGTH)

    @field_validator("url")
    @classmethod
    def must_be_http(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("URL must be http or https")
        return value


class Recipe(BaseModel):
    """结构化菜谱（含来源与置信度）。"""

    title: str = Field(..., min_length=1, max_length=120)
    summary: str = Field(..., min_length=1, max_length=500)
    prep_time_minutes: int | None = Field(default=None, ge=0, le=300)
    cook_time_minutes: int | None = Field(default=None, ge=0, le=300)
    servings: int | None = Field(default=None, ge=1, le=20)
    ingredients: list[str] = Field(..., min_length=1, max_length=40)
    steps: list[str] = Field(..., min_length=1, max_length=30)
    tips: list[str] = Field(default_factory=list, max_length=10)
    sources: list[RecipeSource] = Field(..., min_length=1, max_length=5)
    confidence: Literal["low", "medium", "high"] = "medium"

    @field_validator("ingredients", "steps", "tips")
    @classmethod
    def non_empty_strings(cls, values: list[str]) -> list[str]:
        cleaned = [v.strip() for v in values if v and v.strip()]
        if not cleaned and values is not None:
            # tips 允许空；ingredients/steps 由 min_length 约束
            return cleaned
        return cleaned


class SearchResult(BaseModel):
    """网页检索原始结果条目。"""

    title: str
    url: str
    content: str = ""
    score: float | None = None
