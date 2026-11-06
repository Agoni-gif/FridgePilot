from __future__ import annotations

from urllib.parse import urlparse, urlunparse

from app.schemas.recipe import MAX_SOURCE_URL_LENGTH, SearchResult

RECIPE_HINTS = (
    "菜谱",
    "做法",
    "食谱",
    "怎么做",
    "烹饪",
    "recipe",
    "cook",
    "homemade",
    "炒",
    "煮",
    "烤",
    "蒸",
)

MAX_CONTENT_CHARS = 1200
MAX_TOTAL_CHARS = 5000


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    # Drop fragment and normalize trailing slash lightly
    path = parsed.path.rstrip("/") or "/"
    return urlunparse(
        (parsed.scheme.lower(), parsed.netloc.lower(), path, "", parsed.query, "")
    )


def dedupe_results(results: list[SearchResult]) -> list[SearchResult]:
    seen: set[str] = set()
    unique: list[SearchResult] = []
    for item in results:
        if len(item.url) > MAX_SOURCE_URL_LENGTH:
            continue
        key = normalize_url(item.url)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def looks_relevant(item: SearchResult, ingredients: list[str]) -> bool:
    blob = f"{item.title} {item.content}".lower()
    if any(hint.lower() in blob for hint in RECIPE_HINTS):
        return True
    # At least one ingredient appears
    return any(name.lower() in blob for name in ingredients if name)


def truncate_content(text: str, limit: int = MAX_CONTENT_CHARS) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def filter_search_results(
    results: list[SearchResult],
    *,
    ingredients: list[str],
    max_results: int = 5,
) -> list[SearchResult]:
    cleaned = dedupe_results(results)
    relevant = [r for r in cleaned if looks_relevant(r, ingredients)]
    # If filtering removed everything, keep original unique set as fallback
    pool = relevant or cleaned

    selected: list[SearchResult] = []
    total_chars = 0
    for item in pool:
        content = truncate_content(item.content)
        if total_chars + len(content) > MAX_TOTAL_CHARS and selected:
            break
        selected.append(
            SearchResult(
                title=item.title[:200],
                url=item.url,
                content=content,
                score=item.score,
            )
        )
        total_chars += len(content)
        if len(selected) >= max_results:
            break
    return selected


def allowed_source_urls(results: list[SearchResult]) -> set[str]:
    return {normalize_url(r.url) for r in results}
