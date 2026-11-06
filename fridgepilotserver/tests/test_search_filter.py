from app.agent.search_filter import (
    allowed_source_urls,
    dedupe_results,
    filter_search_results,
    normalize_url,
)
from app.schemas.recipe import SearchResult


def test_normalize_and_dedupe():
    a = SearchResult(title="A", url="https://Example.com/recipe/", content="番茄炒蛋做法")
    b = SearchResult(title="B", url="https://example.com/recipe", content="重复")
    c = SearchResult(title="C", url="https://other.com/x", content="鸡蛋菜谱")
    unique = dedupe_results([a, b, c])
    assert len(unique) == 2
    assert normalize_url(a.url) == normalize_url(b.url)


def test_filter_keeps_relevant_and_limits():
    results = [
        SearchResult(title="番茄炒蛋做法", url="https://a.com/1", content="家常菜谱 " * 200),
        SearchResult(title="无关新闻", url="https://b.com/2", content="股市大涨"),
        SearchResult(title="鸡蛋汤菜谱", url="https://c.com/3", content="简单做法"),
    ]
    filtered = filter_search_results(results, ingredients=["番茄", "鸡蛋"], max_results=5)
    urls = {r.url for r in filtered}
    assert "https://a.com/1" in urls
    assert "https://c.com/3" in urls
    assert "https://b.com/2" not in urls
    assert all(len(r.content) <= 1200 for r in filtered)


def test_allowed_source_urls():
    results = [SearchResult(title="t", url="https://x.com/path/", content="")]
    assert "https://x.com/path" in allowed_source_urls(results)
