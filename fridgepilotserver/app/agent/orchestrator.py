"""Agent 编排器：解析 → 检索 → 总结/解释，产出 AgentOutcome。"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

# 流式进度回调：推送 thinking 文本
ProgressCallback = Callable[[str], Awaitable[None]]

from app.agent.prompts import (
    EXPLAIN_SYSTEM,
    PARSE_SYSTEM,
    PROMPT_VERSION,
    REPAIR_SYSTEM,
    SUMMARIZE_SYSTEM,
)
from app.agent.search_filter import allowed_source_urls, filter_search_results, normalize_url
from app.common.config import Settings
from app.common.logging_setup import preview_text
from app.providers.llm import LLMError, LLMProvider
from app.providers.tavily import TavilyError, TavilyProvider
from app.schemas.chat import ChatPreferences
from app.schemas.context import (
    AssembledContext,
    ParseResult,
    PreferencePatch,
    SessionOverrides,
    SessionState,
    StateOps,
)
from app.schemas.recipe import (
    MAX_SOURCE_URL_LENGTH,
    Recipe,
    RecipeSource,
    SearchResult,
    UserConstraints,
)
from app.services.conversation_context import build_parse_user_payload
from app.services.state_merge import (
    apply_state_ops,
    detect_allergy_conflict,
    empty_overrides,
    empty_state,
    merge_ops,
    preference_patch_to_ops,
    preferences_to_ops,
    recipe_conflicts_with_allergies,
)

logger = logging.getLogger(__name__)


@dataclass
class AgentOutcome:
    """一轮 Agent 执行结果，供 ChatService 落库与响应组装。"""

    status: str  # completed | insufficient_sources | error | clarification
    recipe: Recipe | None = None
    message: str | None = None
    thinking: str | None = None
    search_used: bool = False
    elapsed_ms: int = 0
    prompt_version: str = PROMPT_VERSION
    constraints: UserConstraints | None = None
    search_results: list[SearchResult] | None = None
    merged_state: SessionState | None = None
    merged_overrides: SessionOverrides | None = None
    commit_state: bool = False
    update_last_recipe: bool = False
    exclude_previous_recipe: bool = False
    intent: str | None = None


class AgentOrchestrator:
    """固定流水线：解析(+上下文) → 合并 → 澄清|解释|检索 → 总结。"""

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
        on_progress: ProgressCallback | None = None,
        *,
        context: AssembledContext | None = None,
        preference_patch: PreferencePatch | None = None,
        memory_enabled: bool | None = None,
    ) -> AgentOutcome:
        """入口：按是否启用会话记忆走上下文流水线或旧版单轮流水线。"""
        started = time.perf_counter()
        thinking_parts: list[str] = []
        use_memory = (
            self.settings.session_memory_enabled
            if memory_enabled is None
            else memory_enabled
        )
        logger.info(
            "request_id=%s agent start message=%r prompt_version=%s memory=%s",
            request_id,
            preview_text(message),
            PROMPT_VERSION,
            use_memory,
        )
        try:
            if use_memory and context is not None:
                return await self._run_with_memory(
                    message=message,
                    preferences=preferences,
                    preference_patch=preference_patch,
                    context=context,
                    request_id=request_id,
                    on_progress=on_progress,
                    started=started,
                    thinking_parts=thinking_parts,
                )
            return await self._run_legacy(
                message=message,
                preferences=preferences,
                request_id=request_id,
                on_progress=on_progress,
                started=started,
                thinking_parts=thinking_parts,
            )
        except (LLMError, TavilyError) as exc:
            logger.exception("request_id=%s upstream failure: %s", request_id, exc)
            outcome = AgentOutcome(
                status="error",
                message=self._user_facing_upstream_error(exc),
                thinking=self._join_thinking(thinking_parts),
                elapsed_ms=self._elapsed(started),
            )
            self._log_outcome(request_id, outcome)
            return outcome
        except Exception:
            logger.exception("request_id=%s unexpected agent failure", request_id)
            outcome = AgentOutcome(
                status="error",
                message="服务暂时不可用，请稍后重试。",
                thinking=self._join_thinking(thinking_parts),
                elapsed_ms=self._elapsed(started),
            )
            self._log_outcome(request_id, outcome)
            return outcome

    async def _run_with_memory(
        self,
        *,
        message: str,
        preferences: ChatPreferences | None,
        preference_patch: PreferencePatch | None,
        context: AssembledContext,
        request_id: str,
        on_progress: ProgressCallback | None,
        started: float,
        thinking_parts: list[str],
    ) -> AgentOutcome:
        """带会话记忆：上下文解析 → 合并 → 澄清/解释/检索总结。"""
        await self._emit(on_progress, "开始分析本轮意图与做饭条件…")
        logger.info("request_id=%s stage=parse start (memory)", request_id)
        parsed = await self._parse_contextual(context, thinking_parts=thinking_parts)
        await self._emit(on_progress, self._join_thinking(thinking_parts))

        if parsed is None:
            outcome = AgentOutcome(
                status="error",
                message="没能理解本轮要求，请换种说法再试一次。",
                thinking=self._join_thinking(thinking_parts),
                elapsed_ms=self._elapsed(started),
                intent="clarify",
                commit_state=False,
            )
            self._log_outcome(request_id, outcome)
            return outcome

        client_ops = merge_ops(
            preferences_to_ops(preferences),
            preference_patch_to_ops(preference_patch),
        )
        combined_ops = merge_ops(parsed.ops, client_ops)
        exclude_previous = bool(
            combined_ops.exclude_recipe_title and combined_ops.exclude_recipe_title.strip()
        )

        if parsed.intent == "clarify" or parsed.clarification_question:
            question = (
                parsed.clarification_question
                or "还需要补充一点信息才能继续，请再说具体一些。"
            )
            outcome = AgentOutcome(
                status="clarification",
                message=question,
                thinking=self._join_thinking(thinking_parts),
                elapsed_ms=self._elapsed(started),
                intent="clarify",
                commit_state=False,
            )
            self._log_outcome(request_id, outcome)
            return outcome

        allergies = list(context.user_defaults.get("allergies") or [])
        allergy_question = detect_allergy_conflict(allergies, combined_ops)
        if allergy_question:
            outcome = AgentOutcome(
                status="clarification",
                message=allergy_question,
                thinking=self._join_thinking(thinking_parts),
                elapsed_ms=self._elapsed(started),
                intent="clarify",
                commit_state=False,
            )
            self._log_outcome(request_id, outcome)
            return outcome

        merge = apply_state_ops(
            context.session_state,
            context.session_overrides,
            combined_ops,
            require_ingredients_for_generate=parsed.intent
            in {"generate", "revise"},
        )
        if not merge.ok:
            outcome = AgentOutcome(
                status="clarification",
                message=merge.clarification
                or "条件有点不清楚，请再补充一下。",
                thinking=self._join_thinking(thinking_parts),
                elapsed_ms=self._elapsed(started),
                intent="clarify",
                commit_state=False,
            )
            self._log_outcome(request_id, outcome)
            return outcome

        if parsed.intent == "explain":
            return await self._explain(
                context=context,
                parsed=parsed,
                merged_state=merge.state,
                merged_overrides=merge.overrides,
                request_id=request_id,
                on_progress=on_progress,
                started=started,
                thinking_parts=thinking_parts,
            )

        # generate / revise：过敏作为检索/总结的保护性约束
        constraints = self._state_to_constraints(
            merge.state, parsed.search_queries, allergies=allergies
        )
        queries = self._build_queries(constraints, merge.state)
        ingredient_names = [i.name for i in constraints.ingredients]
        logger.info(
            "request_id=%s stage=parse done intent=%s ingredients=%s queries=%s",
            request_id,
            parsed.intent,
            ingredient_names,
            queries,
        )
        if not queries:
            outcome = AgentOutcome(
                status="clarification",
                message="没能识别出可用食材，请补充食材名称后再试。",
                thinking=self._join_thinking(thinking_parts),
                elapsed_ms=self._elapsed(started),
                merged_state=merge.state,
                merged_overrides=merge.overrides,
                intent=parsed.intent,
                commit_state=False,
            )
            self._log_outcome(request_id, outcome)
            return outcome

        # 上一道菜仅作 revise 参考；排除标题只来自显式 exclude / 已存排除列表，
        # 不要因为 intent=revise（如「改成四人份」）就自动把当前菜加进排除。
        return await self._search_and_summarize(
            constraints=constraints,
            queries=queries,
            ingredient_names=ingredient_names,
            merged_state=merge.state,
            merged_overrides=merge.overrides,
            intent=parsed.intent or "generate",
            commit_state=True,
            request_id=request_id,
            on_progress=on_progress,
            started=started,
            thinking_parts=thinking_parts,
            target_recipe=context.last_recipe if parsed.intent == "revise" else None,
            excluded_titles=list(merge.state.excluded_recipe_titles),
            exclude_previous_recipe=exclude_previous,
        )

    async def _run_legacy(
        self,
        *,
        message: str,
        preferences: ChatPreferences | None,
        request_id: str,
        on_progress: ProgressCallback | None,
        started: float,
        thinking_parts: list[str],
    ) -> AgentOutcome:
        """无会话记忆：单轮解析约束后直接检索总结。"""
        await self._emit(on_progress, "开始分析用户输入中的食材与约束…")
        logger.info("request_id=%s stage=parse start", request_id)
        constraints = await self._parse_constraints_legacy(
            message, preferences, thinking_parts=thinking_parts
        )
        await self._emit(on_progress, self._join_thinking(thinking_parts))
        queries = self._build_queries(constraints, None)
        ingredient_names = [i.name for i in constraints.ingredients]
        if not queries:
            outcome = AgentOutcome(
                status="insufficient_sources",
                message="没能识别出可用食材，请补充食材名称后再试。",
                thinking=self._join_thinking(thinking_parts),
                elapsed_ms=self._elapsed(started),
            )
            self._log_outcome(request_id, outcome)
            return outcome
        return await self._search_and_summarize(
            constraints=constraints,
            queries=queries,
            ingredient_names=ingredient_names,
            merged_state=None,
            merged_overrides=None,
            intent="generate",
            commit_state=False,
            request_id=request_id,
            on_progress=on_progress,
            started=started,
            thinking_parts=thinking_parts,
            target_recipe=None,
            excluded_titles=[],
            exclude_previous_recipe=False,
        )

    async def _explain(
        self,
        *,
        context: AssembledContext,
        parsed: ParseResult,
        merged_state: SessionState,
        merged_overrides: SessionOverrides,
        request_id: str,
        on_progress: ProgressCallback | None,
        started: float,
        thinking_parts: list[str],
    ) -> AgentOutcome:
        """解释意图：基于已有菜谱回答，不重新搜索。"""
        if not context.last_recipe:
            outcome = AgentOutcome(
                status="clarification",
                message="还没有可解释的菜谱。请先生成一道菜，或说明你想了解哪一道。",
                thinking=self._join_thinking(thinking_parts),
                elapsed_ms=self._elapsed(started),
                intent="clarify",
                commit_state=False,
            )
            self._log_outcome(request_id, outcome)
            return outcome

        self._append_thinking(thinking_parts, "基于已保存的菜谱回答问题，不重新搜索。")
        await self._emit(on_progress, self._join_thinking(thinking_parts))
        payload = {
            "question": context.current_message,
            "focus": parsed.explain_focus,
            "recipe": context.last_recipe,
        }
        result = await self.llm.chat_json(
            system=EXPLAIN_SYSTEM,
            user=json.dumps(payload, ensure_ascii=False),
            purpose="explain",
        )
        self._append_thinking(thinking_parts, result.reasoning)
        data = await self._maybe_repair(result.data, thinking_parts=thinking_parts)
        message = str(data.get("message") or "").strip() or "这道菜目前没有更多可说明的细节。"
        outcome = AgentOutcome(
            status="completed",
            message=message,
            thinking=self._join_thinking(thinking_parts),
            elapsed_ms=self._elapsed(started),
            merged_state=merged_state,
            merged_overrides=merged_overrides,
            intent="explain",
            commit_state=False,
        )
        self._log_outcome(request_id, outcome)
        return outcome

    async def _search_and_summarize(
        self,
        *,
        constraints: UserConstraints,
        queries: list[str],
        ingredient_names: list[str],
        merged_state: SessionState | None,
        merged_overrides: SessionOverrides | None,
        intent: str,
        commit_state: bool,
        request_id: str,
        on_progress: ProgressCallback | None,
        started: float,
        thinking_parts: list[str],
        target_recipe: dict[str, Any] | None,
        excluded_titles: list[str],
        exclude_previous_recipe: bool = False,
    ) -> AgentOutcome:
        """检索 → 过滤 → 总结成可核验菜谱（含来源白名单校验）。"""
        query_preview = "；".join(queries[:3])
        self._append_thinking(
            thinking_parts,
            f"接下来用这些词去联网检索真实菜谱：{query_preview}。",
        )
        await self._emit(on_progress, self._join_thinking(thinking_parts))

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
        if filtered:
            titles = "；".join(item.title for item in filtered[:5] if item.title)
            self._append_thinking(
                thinking_parts,
                f"联网搜索完成，从 {len(raw_results)} 条原始结果中筛出 {len(filtered)} 条候选"
                + (f"：{titles}。" if titles else "。"),
            )
        else:
            self._append_thinking(
                thinking_parts,
                f"联网搜索完成，但 {len(raw_results)} 条结果都不够相关，无法继续整理菜谱。",
            )
        await self._emit(on_progress, self._join_thinking(thinking_parts))

        if not filtered:
            outcome = AgentOutcome(
                status="insufficient_sources",
                message="当前没有检索到可用菜谱来源，请换一组食材或放宽条件后再试。",
                thinking=self._join_thinking(thinking_parts),
                search_used=True,
                elapsed_ms=self._elapsed(started),
                constraints=constraints,
                search_results=[],
                merged_state=merged_state,
                merged_overrides=merged_overrides,
                intent=intent,
                commit_state=commit_state,
                update_last_recipe=False,
                exclude_previous_recipe=exclude_previous_recipe,
            )
            self._log_outcome(request_id, outcome)
            return outcome

        self._append_thinking(thinking_parts, "开始基于候选来源整理可操作的烹饪步骤…")
        await self._emit(on_progress, self._join_thinking(thinking_parts))

        recipe = await self._summarize(
            constraints,
            filtered,
            request_id=request_id,
            thinking_parts=thinking_parts,
            target_recipe=target_recipe,
            excluded_titles=excluded_titles,
        )
        await self._emit(on_progress, self._join_thinking(thinking_parts))
        if recipe is None:
            outcome = AgentOutcome(
                status="insufficient_sources",
                message="搜索结果不足以整理成可靠菜谱，请补充食材或调整要求。",
                thinking=self._join_thinking(thinking_parts),
                search_used=True,
                elapsed_ms=self._elapsed(started),
                constraints=constraints,
                search_results=filtered,
                merged_state=merged_state,
                merged_overrides=merged_overrides,
                intent=intent,
                commit_state=commit_state,
                update_last_recipe=False,
                exclude_previous_recipe=exclude_previous_recipe,
            )
            self._log_outcome(request_id, outcome)
            return outcome

        allergen = recipe_conflicts_with_allergies(recipe, constraints.allergies)
        if allergen:
            self._append_thinking(
                thinking_parts,
                f"整理结果含有过敏原「{allergen}」，已拦截，不返回该菜谱。",
            )
            await self._emit(on_progress, self._join_thinking(thinking_parts))
            outcome = AgentOutcome(
                status="insufficient_sources",
                message=(
                    f"整理出的菜谱含有你声明过敏的「{allergen}」，已拦截。"
                    "请换一组食材或调整要求后再试。"
                ),
                thinking=self._join_thinking(thinking_parts),
                search_used=True,
                elapsed_ms=self._elapsed(started),
                constraints=constraints,
                search_results=filtered,
                merged_state=merged_state,
                merged_overrides=merged_overrides,
                intent=intent,
                commit_state=commit_state,
                update_last_recipe=False,
                exclude_previous_recipe=exclude_previous_recipe,
            )
            self._log_outcome(request_id, outcome)
            return outcome

        outcome = AgentOutcome(
            status="completed",
            recipe=recipe,
            thinking=self._join_thinking(thinking_parts),
            search_used=True,
            elapsed_ms=self._elapsed(started),
            constraints=constraints,
            search_results=filtered,
            merged_state=merged_state,
            merged_overrides=merged_overrides,
            intent=intent,
            commit_state=commit_state,
            update_last_recipe=True,
            exclude_previous_recipe=exclude_previous_recipe,
        )
        self._log_outcome(request_id, outcome)
        return outcome

    def _log_outcome(self, request_id: str, outcome: AgentOutcome) -> None:
        """记录本轮 Agent 结束摘要日志。"""
        logger.info(
            "request_id=%s agent done status=%s intent=%s elapsed_ms=%s search_used=%s recipe=%r sources=%s",
            request_id,
            outcome.status,
            outcome.intent,
            outcome.elapsed_ms,
            outcome.search_used,
            outcome.recipe.title if outcome.recipe else None,
            len(outcome.recipe.sources) if outcome.recipe else 0,
        )

    async def _parse_contextual(
        self,
        context: AssembledContext,
        *,
        thinking_parts: list[str],
    ) -> ParseResult | None:
        """带上下文的意图/ops 解析；失败时尝试一次 schema 修复。"""
        result = await self.llm.chat_json(
            system=PARSE_SYSTEM,
            user=build_parse_user_payload(context),
            purpose="parse_context",
        )
        self._append_thinking(thinking_parts, result.reasoning)
        data = await self._maybe_repair(result.data, thinking_parts=thinking_parts)
        parsed = self._validate_parse_result(data)
        if parsed is not None:
            return parsed

        # 有限的一次 schema 修复；不要为 generate/revise 捏造空 ops
        logger.warning("parse result schema invalid; attempting repair")
        repaired = await self.llm.chat_json(
            system=REPAIR_SYSTEM
            + "\n目标是符合解析 JSON Schema（含 intent、ops、search_queries 等字段）。"
            "不要丢弃用户本轮明确提出的条件修改。",
            user=json.dumps({"invalid_output": data}, ensure_ascii=False),
            purpose="repair_parse",
        )
        self._append_thinking(thinking_parts, repaired.reasoning)
        repaired_data = await self._maybe_repair(
            repaired.data, thinking_parts=thinking_parts
        )
        parsed = self._validate_parse_result(repaired_data)
        if parsed is not None:
            return parsed

        logger.warning("parse result still invalid after repair; refusing to continue")
        return None

    @staticmethod
    def _validate_parse_result(data: dict[str, Any]) -> ParseResult | None:
        """校验解析 JSON 是否符合 ParseResult。"""
        try:
            return ParseResult.model_validate(data)
        except ValidationError:
            logger.warning("parse result validation failed", exc_info=True)
            return None

    async def _parse_constraints_legacy(
        self,
        message: str,
        preferences: ChatPreferences | None,
        *,
        thinking_parts: list[str],
    ) -> UserConstraints:
        """旧版单轮：从用户消息抽出 UserConstraints。"""
        pref_note = ""
        if preferences:
            pref_note = (
                f"\n用户偏好：max_time_minutes={preferences.max_time_minutes}, "
                f"servings={preferences.servings}, "
                f"dietary_restrictions={preferences.dietary_restrictions}"
            )
        # 兼容旧探测脚本的最小单轮 schema
        legacy_system = (
            PARSE_SYSTEM
            + "\n本轮无会话上下文时：把用户输入当作首次 generate；"
            "从消息提取 ingredients/meal/time/servings/dietary 到 ops.set 与 ingredients.replace；"
            "并填写 search_queries。"
        )
        result = await self.llm.chat_json(
            system=legacy_system,
            user=json.dumps(
                {
                    "current_message": message,
                    "recent_turns": [],
                    "session_state": None,
                    "last_recipe": None,
                    "user_defaults": {},
                    "legacy_preferences_note": pref_note,
                },
                ensure_ascii=False,
            ),
            purpose="parse",
        )
        self._append_thinking(thinking_parts, result.reasoning)
        data = await self._maybe_repair(result.data, thinking_parts=thinking_parts)

        # 优先新 ParseResult 形态；否则回退旧 UserConstraints 形态
        if "ops" in data or "intent" in data:
            parsed = ParseResult.model_validate(data)
            merge = apply_state_ops(empty_state(), empty_overrides(), parsed.ops)
            constraints = self._state_to_constraints(merge.state, parsed.search_queries)
        else:
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

    def _state_to_constraints(
        self,
        state: SessionState,
        search_queries: list[str],
        *,
        allergies: list[str] | None = None,
    ) -> UserConstraints:
        """将会话状态转为总结阶段用的 UserConstraints。"""
        return UserConstraints(
            ingredients=list(state.ingredients),
            meal=state.meal,
            max_time_minutes=state.max_time_minutes,
            servings=state.servings,
            cuisine=state.cuisine,
            dietary_restrictions=list(state.dietary_restrictions),
            allergies=[a.strip() for a in (allergies or []) if a and a.strip()][:10],
            search_queries=[q for q in search_queries if q and q.strip()][:4],
        )

    def _build_queries(
        self, constraints: UserConstraints, state: SessionState | None
    ) -> list[str]:
        """构造检索 query：优先模型给出的，否则按食材启发式生成。"""
        queries = [q.strip() for q in constraints.search_queries if q and q.strip()]
        if queries:
            built = queries[:4]
        else:
            names = [i.name for i in constraints.ingredients if i.name]
            if not names:
                return []
            if len(names) >= 3:
                built = [f"{name} 家常菜 做法" for name in names[:3]]
                if constraints.dietary_restrictions:
                    built[0] = f"{built[0]} {constraints.dietary_restrictions[0]}"
            else:
                base = "、".join(names[:5]) + " 菜谱 做法"
                extras: list[str] = []
                if constraints.max_time_minutes:
                    extras.append(f"{constraints.max_time_minutes}分钟")
                if constraints.dietary_restrictions:
                    extras.append(" ".join(constraints.dietary_restrictions[:2]))
                if constraints.meal:
                    extras.append(constraints.meal)
                built = [f"{base} {' '.join(extras)}".strip() if extras else base]

        if constraints.allergies:
            avoid = "不含" + "、".join(constraints.allergies[:3])
            built = [f"{q} {avoid}" for q in built]

        if state and state.excluded_recipe_titles:
            # 查询里给软提示；总结 prompt 也会强制排除
            exclude = "排除 " + "、".join(state.excluded_recipe_titles[-3:])
            built = [f"{q} {exclude}" for q in built]
        return built[:4]

    async def _search_all(self, queries: list[str]) -> list[SearchResult]:
        """对最多 3 条 query 分别检索并合并结果。"""
        all_results: list[SearchResult] = []
        for query in queries[:3]:
            results = await self.tavily.search(query)
            all_results.extend(results)
        return all_results

    async def _summarize(
        self,
        constraints: UserConstraints,
        results: list[SearchResult],
        request_id: str = "-",
        *,
        thinking_parts: list[str],
        target_recipe: dict[str, Any] | None = None,
        excluded_titles: list[str] | None = None,
    ) -> Recipe | None:
        """根据检索结果总结菜谱；来源必须落在白名单 URL 内。"""
        allowed = allowed_source_urls(results)
        # 只用显式累积的排除列表；不要仅因 revise（改人数/时间/口味）就自动排除上一道菜
        exclusions = list(excluded_titles or [])
        payload: dict[str, Any] = {
            "constraints": {
                **constraints.model_dump(),
                "excluded_recipe_titles": exclusions[-10:],
            },
            "search_results": [r.model_dump() for r in results],
        }
        if target_recipe:
            payload["previous_recipe_summary"] = {
                "title": target_recipe.get("title"),
                "summary": target_recipe.get("summary"),
                "note": "参考上一份菜谱的约束调整；除非 excluded_recipe_titles 含其标题，否则不要刻意换菜。",
            }

        result = await self.llm.chat_json(
            system=SUMMARIZE_SYSTEM,
            user=json.dumps(payload, ensure_ascii=False),
            purpose="summarize",
        )
        self._append_thinking(thinking_parts, result.reasoning)
        data = await self._maybe_repair(result.data, thinking_parts=thinking_parts)

        if data.get("insufficient") is True:
            logger.info(
                "request_id=%s summarize marked insufficient reason=%s; retrying partial menu",
                request_id,
                preview_text(str(data.get("reason") or "")),
            )
            retry = await self.llm.chat_json(
                system=SUMMARIZE_SYSTEM
                + "\n特别要求：禁止返回 insufficient。必须基于现有 search_results 输出至少一道有来源的菜。"
                "未覆盖的菜只能写在 tips，不能编造步骤。",
                user=json.dumps(
                    {
                        "constraints": payload["constraints"],
                        "search_results": [r.model_dump() for r in results],
                        "previous_refusal": data,
                    },
                    ensure_ascii=False,
                ),
                purpose="summarize_partial",
            )
            self._append_thinking(thinking_parts, retry.reasoning)
            data = await self._maybe_repair(retry.data, thinking_parts=thinking_parts)
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
        self._append_thinking(thinking_parts, repaired.reasoning)
        return self._validate_recipe(repaired.data, allowed, request_id=request_id)

    def _validate_recipe(
        self,
        data: dict[str, Any],
        allowed: set[str],
        request_id: str = "-",
    ) -> Recipe | None:
        """校验菜谱结构，并过滤非白名单来源 URL。"""
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
        """去掉标题里的「可核验来源」等展示噪声。"""
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
        """清理摘要等展示文本中的来源噪声词。"""
        cleaned = re.sub(r"[（(]\s*可核验来源版?\s*[）)]", "", text)
        cleaned = re.sub(r"可核验来源版?", "", cleaned)
        return re.sub(r"\s{2,}", " ", cleaned).strip()

    async def _maybe_repair(
        self,
        data: Any,
        *,
        thinking_parts: list[str] | None = None,
    ) -> dict[str, Any]:
        """若模型未返回 dict，再请求一次修复为 JSON 对象。"""
        if isinstance(data, dict):
            return data
        repaired = await self.llm.chat_json(
            system=REPAIR_SYSTEM,
            user=str(data),
            purpose="repair_json",
        )
        if thinking_parts is not None:
            self._append_thinking(thinking_parts, repaired.reasoning)
        if not isinstance(repaired.data, dict):
            raise LLMError("Failed to repair model JSON")
        return repaired.data

    @staticmethod
    async def _emit(on_progress: ProgressCallback | None, text: str | None) -> None:
        """向流式回调推送一段 thinking 文本。"""
        if not on_progress or not text:
            return
        cleaned = text.strip()
        if cleaned:
            await on_progress(cleaned)

    @staticmethod
    def _append_thinking(parts: list[str], text: str | None) -> None:
        """追加不重复的 thinking 片段。"""
        if not text:
            return
        cleaned = text.strip()
        if cleaned and cleaned not in parts:
            parts.append(cleaned)

    @staticmethod
    def _join_thinking(parts: list[str]) -> str | None:
        """合并 thinking 片段供响应返回。"""
        if not parts:
            return None
        return "\n\n".join(parts)

    @staticmethod
    def _elapsed(started: float) -> int:
        """自 started 起的耗时毫秒。"""
        return int((time.perf_counter() - started) * 1000)

    @staticmethod
    def _user_facing_upstream_error(exc: Exception) -> str:
        """将上游异常映射为面向用户的中文提示。"""
        if isinstance(exc, TavilyError):
            return "菜谱搜索暂时不可用，请稍后重试。"
        if isinstance(exc, LLMError):
            return "模型服务暂时不可用，请稍后重试。"
        return "服务暂时不可用，请稍后重试。"
