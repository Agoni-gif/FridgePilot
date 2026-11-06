from app.agent.orchestrator import AgentOrchestrator
from app.common.config import Settings


def test_validate_recipe_drops_forged_urls():
    settings = Settings(
        llm_api_key="x",
        tavily_api_key="y",
        database_url="sqlite:///:memory:",
    )
    agent = AgentOrchestrator(settings)
    allowed = {
        "https://trusted.com/recipe",
    }
    data = {
        "title": "番茄炒蛋",
        "summary": "家常",
        "ingredients": ["鸡蛋", "番茄"],
        "steps": ["炒"],
        "tips": [],
        "sources": [
            {"title": "真", "url": "https://trusted.com/recipe"},
            {"title": "假", "url": "https://evil.com/fake"},
        ],
        "confidence": "medium",
    }
    recipe = agent._validate_recipe(data, allowed)
    assert recipe is not None
    assert len(recipe.sources) == 1
    assert recipe.sources[0].url == "https://trusted.com/recipe"


def test_validate_recipe_rejects_when_no_trusted_source():
    settings = Settings(
        llm_api_key="x",
        tavily_api_key="y",
        database_url="sqlite:///:memory:",
    )
    agent = AgentOrchestrator(settings)
    data = {
        "title": "x",
        "summary": "y",
        "ingredients": ["a"],
        "steps": ["b"],
        "sources": [{"title": "假", "url": "https://evil.com/fake"}],
        "confidence": "low",
    }
    assert agent._validate_recipe(data, {"https://ok.com"}) is None


def test_validate_recipe_skips_oversized_url_keeps_others():
    settings = Settings(
        llm_api_key="x",
        tavily_api_key="y",
        database_url="sqlite:///:memory:",
    )
    agent = AgentOrchestrator(settings)
    long_url = "https://www.facebook.com/share/" + ("a" * 2500)
    short_url = "https://trusted.com/recipe"
    allowed = {short_url, long_url.rstrip("/")}  # normalize may strip slash
    from app.agent.search_filter import normalize_url

    allowed = {normalize_url(short_url), normalize_url(long_url)}
    data = {
        "title": "番茄炒蛋",
        "summary": "家常",
        "ingredients": ["鸡蛋", "番茄"],
        "steps": ["炒"],
        "tips": [],
        "sources": [
            {"title": "短", "url": short_url},
            {"title": "超长", "url": long_url},
        ],
        "confidence": "medium",
    }
    recipe = agent._validate_recipe(data, allowed)
    assert recipe is not None
    assert len(recipe.sources) == 1
    assert recipe.sources[0].url == short_url
