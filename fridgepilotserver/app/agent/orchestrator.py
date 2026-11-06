from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.agent.prompts import PARSE_SYSTEM, PROMPT_VERSION, REPAIR_SYSTEM, SUMMARIZE_SYSTEM
from app.agent.search_filter import allowed_source_urls, filter_search_results, normalize_url
from app.common.config import Settings
from app.common.logging_setup import preview_text
from app.providers.llm import LLMError, LLMProvider
from app.providers.tavily import TavilyError, TavilyProvider
from app.schemas.chat import ChatPreferences
from app.schemas.recipe import (
    MAX_SOURCE_URL_LENGTH,
    Recipe,
    RecipeSource,
    SearchResult,
    UserConstraints,
)

logger = logging.getLogger(__name__)


@dataclass
class AgentOutcome:
    status: str  # completed | insufficient_sources | error
    recipe: Recipe | None = None
    message: str | None = None
    search_used: bool = False
    elapsed_ms: int = 0
    prompt_version: str = PROMPT_VERSION
    constraints: UserConstraints | None = None
    search_results: list[SearchResult] | None = None


class AgentOrchestrator:
    """Fixed pipeline: parse → search → summarize (optional one repair)."""

    def __init__(
        self,
        settings: Settings,
        llm: LLMProvider | None = None,
        tavily: TavilyProvider | None = None,
    ) -> None:
        self.settings = settings
        self.llm = llm or LLMProvider(settings)
        self.tavily = tavily or TavilyProvider(settings)

    async def run(
        self,
        message: str,
        preferences: ChatPreferences | None = None,
        request_id: str = "-",
    ) -> AgentOutcome:
        started = time.perf_counter()
        logger.info(
            "request_id=%s agent start message=%r prompt_version=%s",
            request_id,
            preview_text(message),
            PROMPT_VERSION,
        )
        try:
            logger.info("request_id=%s stage=parse start", request_id)
            constraints = await self._parse_constraints(message, preferences)
            queries = self._build_queries(constraints)
            ingredient_names = [i.name for i in constraints.ingredients]
            logger.info(
                "request_id=%s stage=parse done ingredients=%s queries=%s meal=%s max_time=%s",
                request_id,
                ingredient_names,
                queries,
                constraints.meal,
                constraints.max_time_minutes,
            )
            if not queries:
                outcome = AgentOutcome(
                    status="insufficient_sources",
                    message="没能识别出可用食材，请补充食材名称后再试。",
                    elapsed_ms=self._elapsed(started),
                )
                self._log_outcome(request_id, outcome)
                return outcome

            logger.info("request_id=%s stage=search start queries=%s", request_id, queries[:3])
            raw_results = await self._search_all(queries)
            filtered = filter_search_results(
                raw_results,
                ingredients=ingredient_names,
                max_results=self.settings.max_search_results,
            )
            logger.info(
                "request_id=%s stage=search done raw=%s filtered=%s urls=%s",
                request_id,
                len(raw_results),
                len(filtered),
                [r.url for r in filtered],
            )
            if not filtered:
                outcome = AgentOutcome(
                    status="insufficient_sources",
                    message="当前没有检索到可用菜谱来源，请换一组食材或放宽条件后再试。",
                    search_used=True,
                    elapsed_ms=self._elapsed(started),
                    constraints=constraints,
                    search_results=[],
                )
                self._log_outcome(request_id, outcome)
                return outcome

            logger.info(
                "request_id=%s stage=summarize start candidates=%s",
                request_id,
                len(filtered),
            )
            recipe = await self._summarize(constraints, filtered, request_id=request_id)
            if recipe is None:
                outcome = AgentOutcome(
                    status="insufficient_sources",
                    message="搜索结果不足以整理成可靠菜谱，请补充食材或调整要求。",
                    search_used=True,
                    elapsed_ms=self._elapsed(started),
                    constraints=constraints,
                    search_results=filtered,
                )
                self._log_outcome(request_id, outcome)
                return outcome

            outcome = AgentOutcome(
                status="completed",
                recipe=recipe,
                search_used=True,
                elapsed_ms=self._elapsed(started),
                constraints=constraints,
                search_results=filtered,
            )
            self._log_outcome(request_id, outcome)
            return outcome
        except (LLMError, TavilyError) as exc:
            logger.exception("request_id=%s upstream failure: %s", request_id, exc)
            outcome = AgentOutcome(
                status="error",
                message=self._user_facing_upstream_error(exc),
                elapsed_ms=self._elapsed(started),
            )
            self._log_outcome(request_id, outcome)
            return outcome
        except Exception:
            logger.exception("request_id=%s unexpected agent failure", request_id)
            outcome = AgentOutcome(
                status="error",
                message="服务暂时不可用，请稍后重试。",
                elapsed_ms=self._elapsed(started),
            )
            self._log_outcome(request_id, outcome)
            return outcome

    def _log_outcome(self, request_id: str, outcome: AgentOutcome) -> None:
        logger.info(
            "request_id=%s agent done status=%s elapsed_ms=%s search_used=%s recipe=%r sources=%s",
            request_id,
            outcome.status,
            outcome.elapsed_ms,
            outcome.search_used,
            outcome.recipe.title if outcome.recipe else None,
            len(outcome.recipe.sources) if outcome.recipe else 0,
        )

    async def _parse_constraints(
        self,
        message: str,
        preferences: ChatPreferences | None,
    ) -> UserConstraints:
        pref_note = ""
        if preferences:
            pref_note = (
                f"\n用户偏好：max_time_minutes={preferences.max_time_minutes}, "
                f"servings={preferences.servings}, "
                f"dietary_restrictions={preferences.dietary_restrictions}"
            )
        data = await self.llm.chat_json(
            system=PARSE_SYSTEM,
            user=f"用户输入：{message}{pref_note}",
            purpose="parse",
        )
        data = await self._maybe_repair(data)
        constraints = UserConstraints.model_validate(data)

        if preferences:
            if preferences.max_time_minutes is not None:
                constraints.max_time_minutes = preferences.max_time_minutes
            if preferences.servings is not None:
                constraints.servings = preferences.servings
            if preferences.dietary_restrictions:
                merged = list(
                    dict.fromkeys(
                        [*constraints.dietary_restrictions, *preferences.dietary_restrictions]
                    )
                )
                constraints.dietary_restrictions = merged[:10]
        return constraints

    def _build_queries(self, constraints: UserConstraints) -> list[str]:
        queries = [q.strip() for q in constraints.search_queries if q and q.strip()]
        if queries:
            return queries[:4]

        names = [i.name for i in constraints.ingredients if i.name]
        if not names:
            return []

        # Prefer per-ingredient recipe queries for broader coverage
        if len(names) >= 3:
            built = [f"{name} 家常菜 做法" for name in names[:3]]
            if constraints.dietary_restrictions:
                built[0] = f"{built[0]} {constraints.dietary_restrictions[0]}"
            return built

        base = "、".join(names[:5]) + " 菜谱 做法"
        extras: list[str] = []
        if constraints.max_time_minutes:
            extras.append(f"{constraints.max_time_minutes}分钟")
        if constraints.dietary_restrictions:
            extras.append(" ".join(constraints.dietary_restrictions[:2]))
        if constraints.meal:
            extras.append(constraints.meal)
        if extras:
            queries.append(f"{base} {' '.join(extras)}")
        else:
            queries.append(base)
        return queries[:4]

    async def _search_all(self, queries: list[str]) -> list[SearchResult]:
        all_results: list[SearchResult] = []
        # Search up to 3 queries so multi-dish menus can get coverage
        for query in queries[:3]:
            results = await self.tavily.search(query)
            all_results.extend(results)
        return all_results

    async def _summarize(
        self,
        constraints: UserConstraints,
        results: list[SearchResult],
        request_id: str = "-",
    ) -> Recipe | None:
        allowed = allowed_source_urls(results)
        payload = {
            "constraints": constraints.model_dump(),
            "search_results": [r.model_dump() for r in results],
        }
        data = await self.llm.chat_json(
            system=SUMMARIZE_SYSTEM,
            user=json.dumps(payload, ensure_ascii=False),
            purpose="summarize",
        )
        data = await self._maybe_repair(data)

        if data.get("insufficient") is True:
            logger.info(
                "request_id=%s summarize marked insufficient reason=%s; retrying partial menu",
                request_id,
                preview_text(str(data.get("reason") or "")),
            )
            # Second pass: force a partial menu from whatever sources we have
            data = await self.llm.chat_json(
                system=SUMMARIZE_SYSTEM
                + "\n特别要求：禁止返回 insufficient。必须基于现有 search_results 输出至少一道有来源的菜。"
                "未覆盖的菜只能写在 tips，不能编造步骤。",
                user=json.dumps(
                    {
                        "constraints": constraints.model_dump(),
                        "search_results": [r.model_dump() for r in results],
                        "previous_refusal": data,
                    },
                    ensure_ascii=False,
                ),
                purpose="summarize_partial",
            )
            data = await self._maybe_repair(data)
            if data.get("insufficient") is True:
                return None

        recipe = self._validate_recipe(data, allowed, request_id=request_id)
        if recipe is not None:
            return recipe

        logger.warning("request_id=%s recipe schema invalid, attempting repair", request_id)
        repaired = await self.llm.chat_json(
            system=REPAIR_SYSTEM + "\n目标是符合菜谱 JSON Schema，且 sources.url 必须来自给定白名单。",
            user=json.dumps(
                {
                    "invalid_output": data,
                    "allowed_urls": sorted(allowed),
                    "search_results": [r.model_dump() for r in results],
                },
                ensure_ascii=False,
            ),
            purpose="repair",
        )
        return self._validate_recipe(repaired, allowed, request_id=request_id)

    def _validate_recipe(
        self,
        data: dict[str, Any],
        allowed: set[str],
        request_id: str = "-",
    ) -> Recipe | None:
        try:
            raw_sources = data.get("sources") or []
            trusted: list[dict[str, str]] = []
            for src in raw_sources:
                if not isinstance(src, dict):
                    continue
                url = str(src.get("url") or "").strip()
                title = str(src.get("title") or "").strip() or url
                if len(url) > MAX_SOURCE_URL_LENGTH:
                    logger.info(
                        "request_id=%s skipping oversized source URL chars=%s",
                        request_id,
                        len(url),
                    )
                    continue
                if normalize_url(url) in allowed:
                    trusted.append({"title": title[:200], "url": url})
            if not trusted:
                logger.warning(
                    "request_id=%s no trusted sources after whitelist filter",
                    request_id,
                )
                return None

            candidate = {
                **data,
                "title": self._clean_display_title(str(data.get("title") or "")),
                "summary": self._clean_display_text(str(data.get("summary") or "")),
                "sources": trusted,
                "insufficient": False,
            }
            candidate.pop("insufficient", None)
            recipe = Recipe.model_validate(candidate)
            recipe.sources = [RecipeSource.model_validate(s) for s in trusted]
            return recipe
        except ValidationError:
            logger.warning(
                "request_id=%s recipe validation failed",
                request_id,
                exc_info=True,
            )
            return None

    @staticmethod
    def _clean_display_title(title: str) -> str:
        cleaned = title.strip()
        patterns = [
            r"^可核验来源的?套餐方案[：:\s]*",
            r"[（(]\s*可核验来源版?\s*[）)]",
            r"[（(]\s*基于现有来源\s*[）)]",
            r"[（(]\s*有来源\s*[）)]",
            r"可核验来源版?",
            r"基于现有来源",
        ]
        for pattern in patterns:
            cleaned = re.sub(pattern, "", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ：:-—")
        return cleaned or title.strip()

    @staticmethod
    def _clean_display_text(text: str) -> str:
        cleaned = re.sub(r"[（(]\s*可核验来源版?\s*[）)]", "", text)
        cleaned = re.sub(r"可核验来源版?", "", cleaned)
        return re.sub(r"\s{2,}", " ", cleaned).strip()

    async def _maybe_repair(self, data: Any) -> dict[str, Any]:
        if isinstance(data, dict):
            return data
        repaired = await self.llm.chat_json(
            system=REPAIR_SYSTEM,
            user=str(data),
            purpose="repair_json",
        )
        if not isinstance(repaired, dict):
            raise LLMError("Failed to repair model JSON")
        return repaired

    @staticmethod
    def _elapsed(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)

    @staticmethod
    def _user_facing_upstream_error(exc: Exception) -> str:
        if isinstance(exc, TavilyError):
            return "菜谱搜索暂时不可用，请稍后重试。"
        if isinstance(exc, LLMError):
            return "模型服务暂时不可用，请稍后重试。"
        return "服务暂时不可用，请稍后重试。"
