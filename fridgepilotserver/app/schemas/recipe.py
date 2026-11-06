from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


class Ingredient(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    quantity: str | None = Field(default=None, max_length=50)


class UserConstraints(BaseModel):
    ingredients: list[Ingredient] = Field(default_factory=list, max_length=30)
    meal: str | None = Field(default=None, max_length=30)
    max_time_minutes: int | None = Field(default=None, ge=1, le=300)
    servings: int | None = Field(default=None, ge=1, le=20)
    cuisine: str | None = Field(default=None, max_length=50)
    dietary_restrictions: list[str] = Field(default_factory=list, max_length=10)
    search_queries: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("dietary_restrictions")
    @classmethod
    def trim_restrictions(cls, values: list[str]) -> list[str]:
        return [v.strip() for v in values if v and v.strip()][:10]


MAX_SOURCE_URL_LENGTH = 2048


class RecipeSource(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    url: str = Field(..., min_length=1, max_length=MAX_SOURCE_URL_LENGTH)

    @field_validator("url")
    @classmethod
    def must_be_http(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("URL must be http or https")
        return value


class Recipe(BaseModel):
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
            # tips may be empty; ingredients/steps enforced by min_length
            return cleaned
        return cleaned


class SearchResult(BaseModel):
    title: str
    url: str
    content: str = ""
    score: float | None = None
