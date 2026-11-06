from __future__ import annotations

import logging
import time

import httpx

from app.common.config import Settings
from app.schemas.recipe import SearchResult

logger = logging.getLogger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"


class TavilyError(Exception):
    """Raised when Tavily search fails."""


class TavilyProvider:
    def __init__(self, settings: Settings) -> None:
        self.api_key = settings.tavily_api_key
        self.timeout = settings.request_timeout_seconds
        self.max_results = settings.max_search_results

    async def search(self, query: str, *, max_results: int | None = None) -> list[SearchResult]:
        if not self.api_key:
            raise TavilyError("TAVILY_API_KEY is not configured")

        limit = max_results or self.max_results
        payload = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,
            "max_results": limit,
        }

        last_error: Exception | None = None
        for attempt in range(2):
            started = time.perf_counter()
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(TAVILY_SEARCH_URL, json=payload)
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                if resp.status_code >= 500 or resp.status_code == 429:
                    raise TavilyError(f"Tavily temporary error: HTTP {resp.status_code}")
                if resp.status_code >= 400:
                    logger.warning(
                        "Tavily HTTP %s elapsed_ms=%s query=%r",
                        resp.status_code,
                        elapsed_ms,
                        query,
                    )
                    raise TavilyError(f"Tavily request failed: HTTP {resp.status_code}")
                data = resp.json()
                results: list[SearchResult] = []
                for item in data.get("results", []):
                    url = (item.get("url") or "").strip()
                    title = (item.get("title") or "").strip() or url
                    content = (item.get("content") or "").strip()
                    if not url.startswith(("http://", "https://")):
                        continue
                    results.append(
                        SearchResult(
                            title=title[:200],
                            url=url,
                            content=content[:2000],
                            score=item.get("score"),
                        )
                    )
                logger.info(
                    "Tavily ok query=%r results=%s elapsed_ms=%s",
                    query,
                    len(results),
                    elapsed_ms,
                )
                return results
            except (httpx.TimeoutException, httpx.TransportError, TavilyError) as exc:
                last_error = exc
                logger.warning("Tavily attempt %s failed query=%r: %s", attempt + 1, query, exc)
                if attempt == 0:
                    if isinstance(exc, TavilyError) and "temporary" not in str(exc):
                        break
                    continue
                break

        raise TavilyError(f"Tavily search failed: {last_error}")
