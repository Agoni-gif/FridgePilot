import pytest
from pydantic import ValidationError

from app.schemas.chat import ChatRequest
from app.schemas.recipe import Recipe


def test_chat_request_strips_and_rejects_blank():
    req = ChatRequest(message="  番茄鸡蛋  ")
    assert req.message == "番茄鸡蛋"
    with pytest.raises(ValidationError):
        ChatRequest(message="   ")


def test_recipe_requires_http_sources():
    recipe = Recipe(
        title="番茄炒蛋",
        summary="快手菜",
        ingredients=["鸡蛋 3 个", "番茄 2 个"],
        steps=["打蛋", "炒制"],
        sources=[{"title": "来源", "url": "https://example.com/r"}],
        confidence="medium",
    )
    assert recipe.title == "番茄炒蛋"
    with pytest.raises(ValidationError):
        Recipe(
            title="x",
            summary="y",
            ingredients=["a"],
            steps=["b"],
            sources=[{"title": "bad", "url": "ftp://x"}],
        )
