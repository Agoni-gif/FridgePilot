"""会话历史摘要：溢出轮次压缩、版本条件写入。

摘要失败为软失败，不阻断主聊天请求。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.common.config import Settings
from app.db.models import MessageRecord, SessionRecord
from app.providers.llm import LLMError, LLMProvider
from app.repositories import conversation_repository, session_repository
from app.schemas.context import ConversationSummary, RecentTurn
from app.services.conversation_context import (
    estimate_tokens,
    payload_token_count,
    plan_context_budgets,
    projected_summary_placeholder,
    turns_token_count,
)

logger = logging.getLogger(__name__)


@dataclass
class CompleteTurn:
    """一对完整的用户/助手消息轮次。"""

    user_message_id: int
    user_content: str
    assistant_message_id: int
    assistant_content: str
    response_status: str | None
    recipe_title: str | None = None


@dataclass
class SummaryAttemptResult:
    """一次摘要尝试的结果统计（供日志与测试断言）。"""

    committed: bool
    skipped_reason: str | None = None
    elapsed_ms: int = 0
    overflow_turns: int = 0
    batch_turns: int = 0
    summary_chars: int = 0
    input_tokens: int = 0


def parse_summary_json(raw: str | None) -> ConversationSummary | None:
    """解析会话摘要 JSON；损坏则忽略。"""
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, str):
            return None
        return ConversationSummary.model_validate(data)
    except Exception:
        logger.warning("corrupt summary_json ignored")
        return None


def load_complete_turns(
    db: Session,
    session: SessionRecord,
    *,
    after_message_id: int | None = None,
) -> list[CompleteTurn]:
    """将上下文边界之后的用户/助手消息配对成完整轮次。"""
    lower_bound: int | None = None
    boundary = session.context_start_message_id
    if boundary is not None:
        lower_bound = boundary
    if after_message_id is not None:
        lower_bound = (
            after_message_id
            if lower_bound is None
            else max(lower_bound, after_message_id)
        )
    messages = conversation_repository.list_messages_after(
        db, session.id, after_message_id=lower_bound
    )

    from app.services.conversation_context import _recipe_titles_by_message

    recipe_titles = _recipe_titles_by_message(db, session.id)
    turns: list[CompleteTurn] = []
    pending_user: MessageRecord | None = None

    for msg in messages:
        if msg.role == "user":
            pending_user = msg
            continue
        if msg.role != "assistant" or pending_user is None:
            continue
        status = msg.response_status
        content = msg.content or ""
        if status == "error":
            content = "上一轮生成失败。"
        elif status == "insufficient_sources":
            content = content[:200] if content else "上一轮没有足够来源。"
        turns.append(
            CompleteTurn(
                user_message_id=pending_user.id,
                user_content=(pending_user.content or "")[:1000],
                assistant_message_id=msg.id,
                assistant_content=content[:1500],
                response_status=status,
                recipe_title=recipe_titles.get(msg.id),
            )
        )
        pending_user = None
    return turns


def turns_to_recent(turns: list[CompleteTurn]) -> list[RecentTurn]:
    """将完整轮次转为 RecentTurn 列表的公开别名。"""
    return _to_recent_turns(turns)


def select_recent_and_overflow(
    turns: list[CompleteTurn],
    *,
    max_turns: int,
    token_budget: int,
    probe_tokens=None,
) -> tuple[list[RecentTurn], list[CompleteTurn]]:
    """保留最新完整轮次进入近期窗口；更早的进入溢出区。

    若最新一轮也塞不进最终 payload，近期窗口为空，该轮计入溢出
    （与 assemble 的 fit_recent_turns_to_payload 一致），不要在这里强留超大最新轮。

    若提供 probe_tokens，须按候选近期窗口估算*最终序列化 payload*大小（含 JSON 开销）；
    否则退回仅内容 token 估算（兼容旧测试）。
    """
    if not turns:
        return [], []

    start = max(0, len(turns) - max(1, max_turns))
    while start <= len(turns):
        recent_slice = turns[start:]
        recent = _to_recent_turns(recent_slice)
        if probe_tokens is not None:
            fits = probe_tokens(recent) <= token_budget
        else:
            # 空近期窗口对「仅内容」估算器始终视为可装下
            fits = (not recent) or turns_token_count(recent) <= token_budget
        if fits:
            return recent, turns[:start]
        start += 1

    # 硬字段本身已超预算：全部历史仍记为溢出
    return [], list(turns)


def estimate_summary_input_tokens(
    previous_summary: str | None,
    turns: list[CompleteTurn],
    *,
    max_chars: int,
) -> int:
    """估算摘要输入 payload 的 token 数。"""
    payload = _summary_user_payload(previous_summary, turns, max_chars=max_chars)
    return estimate_tokens(json.dumps(payload, ensure_ascii=False))


def select_summary_batch(
    overflow: list[CompleteTurn],
    *,
    previous_summary: str | None,
    input_token_budget: int,
    max_chars: int,
) -> list[CompleteTurn]:
    """取能装进摘要输入预算的最旧连续完整轮次。

    若第一轮单独就超预算，返回空批次，调用方跳过且不推进覆盖指针。
    """
    if not overflow:
        return []
    budget = max(1, input_token_budget)
    batch: list[CompleteTurn] = []
    for turn in overflow:
        candidate = [*batch, turn]
        tokens = estimate_summary_input_tokens(
            previous_summary, candidate, max_chars=max_chars
        )
        if tokens > budget:
            break
        batch = candidate
    return batch


def _to_recent_turns(turns: list[CompleteTurn]) -> list[RecentTurn]:
    """完整轮次展开为交替的 user/assistant RecentTurn。"""
    out: list[RecentTurn] = []
    for turn in turns:
        out.append(
            RecentTurn(
                role="user",
                content=turn.user_content,
                message_id=turn.user_message_id,
            )
        )
        out.append(
            RecentTurn(
                role="assistant",
                content=turn.assistant_content,
                response_status=turn.response_status,
                recipe_title=turn.recipe_title,
                message_id=turn.assistant_message_id,
            )
        )
    return out


def clear_summary_fields(session: SessionRecord) -> None:
    """清空摘要相关字段（清除上下文时调用）。"""
    session.summary_json = None
    session.summary_until_message_id = None
    session.summary_version = 0


def commit_summary_if_version_matches(
    db: Session,
    *,
    session_id: str,
    started_version: int,
    summary: ConversationSummary,
) -> bool:
    """仅当 context_version 仍匹配时写入摘要，防止清除上下文后旧任务复活。"""
    updated = session_repository.update_summary_if_version(
        db,
        session_id=session_id,
        expected_version=started_version,
        summary_json=summary.model_dump_json(),
        summary_until_message_id=summary.covered_until_message_id,
    )
    if updated != 1:
        db.rollback()
        return False
    db.commit()
    return True


async def maybe_refresh_conversation_summary(
    db: Session,
    session: SessionRecord,
    *,
    llm: LLMProvider,
    settings: Settings,
    started_version: int,
    current_message: str = "",
    turns_token_budget: int | None = None,
    user_defaults: dict | None = None,
    allergies: list[str] | None = None,
    session_state=None,
) -> SummaryAttemptResult:
    """当更早完整轮次落在近期窗口外时，对有界批次做摘要。

    近期/溢出按最终序列化 payload 判定（与 assemble_context 同一探针），
    避免后续 enforce_payload_budget 裁剪后出现空洞。
    只发送预算内最旧批次；覆盖指针仅推进实际被接受的轮次。

    失败为软失败：调用方继续使用状态 + 近期轮次。
    """
    if not settings.session_memory_enabled or not settings.context_summary_enabled:
        return SummaryAttemptResult(committed=False, skipped_reason="disabled")

    existing = parse_summary_json(session.summary_json)
    after_id = session.summary_until_message_id
    if after_id is None and existing is not None:
        after_id = existing.covered_until_message_id

    uncovered = load_complete_turns(db, session, after_message_id=after_id)
    plan = plan_context_budgets(
        db, session, current_message=current_message, settings=settings
    )
    state = session_state if session_state is not None else plan.state
    defaults = dict(user_defaults or {})
    allergy_list = list(allergies or [])
    summary_for_probe = projected_summary_placeholder(settings, plan.summary_text)

    def _probe(recent: list[RecentTurn]) -> int:
        return payload_token_count(
            current_message=current_message,
            recent_turns=recent,
            session_state=state,
            session_overrides=plan.overrides,
            last_recipe=plan.last_recipe_summary,
            conversation_summary=summary_for_probe,
            user_defaults=defaults,
            allergies=allergy_list,
        )

    # 优先按最终 payload 拟合；turns_token_budget 仅兼容旧测试
    if turns_token_budget is not None:
        _recent, overflow = select_recent_and_overflow(
            uncovered,
            max_turns=settings.context_max_turns,
            token_budget=turns_token_budget,
        )
    else:
        _recent, overflow = select_recent_and_overflow(
            uncovered,
            max_turns=settings.context_max_turns,
            token_budget=plan.total_budget,
            probe_tokens=_probe,
        )
    if not overflow:
        return SummaryAttemptResult(committed=False, skipped_reason="no_overflow")

    previous_text = existing.text if existing else None
    input_budget = settings.context_summary_input_token_budget
    batch = select_summary_batch(
        overflow,
        previous_summary=previous_text,
        input_token_budget=input_budget,
        max_chars=settings.context_summary_max_chars,
    )
    if not batch:
        first_tokens = estimate_summary_input_tokens(
            previous_text, overflow[:1], max_chars=settings.context_summary_max_chars
        )
        logger.info(
            "conversation summary skipped oversize turn session=%s tokens=%s budget=%s",
            session.id,
            first_tokens,
            input_budget,
        )
        return SummaryAttemptResult(
            committed=False,
            skipped_reason="batch_over_budget",
            overflow_turns=len(overflow),
            input_tokens=first_tokens,
        )

    input_tokens = estimate_summary_input_tokens(
        previous_text, batch, max_chars=settings.context_summary_max_chars
    )
    # 发送前硬门槛：超预算绝不推进覆盖指针
    if input_tokens > input_budget:
        logger.info(
            "conversation summary hard-reject session=%s tokens=%s budget=%s",
            session.id,
            input_tokens,
            input_budget,
        )
        return SummaryAttemptResult(
            committed=False,
            skipped_reason="batch_over_budget",
            overflow_turns=len(overflow),
            batch_turns=len(batch),
            input_tokens=input_tokens,
        )

    started = time.perf_counter()
    try:
        text = await _summarize_overflow(
            llm,
            previous_summary=previous_text,
            overflow=batch,
            max_chars=settings.context_summary_max_chars,
        )
    except Exception as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        logger.warning(
            "conversation summary failed session=%s elapsed_ms=%s err=%s",
            session.id,
            elapsed,
            type(exc).__name__,
        )
        return SummaryAttemptResult(
            committed=False,
            skipped_reason="llm_error",
            elapsed_ms=elapsed,
            overflow_turns=len(overflow),
            batch_turns=len(batch),
            input_tokens=input_tokens,
        )

    elapsed = int((time.perf_counter() - started) * 1000)
    if not text:
        return SummaryAttemptResult(
            committed=False,
            skipped_reason="empty",
            elapsed_ms=elapsed,
            overflow_turns=len(overflow),
            batch_turns=len(batch),
            input_tokens=input_tokens,
        )

    covered_from = batch[0].user_message_id
    if existing and existing.covered_from_message_id is not None:
        covered_from = existing.covered_from_message_id
    # 覆盖指针只推进实际送进模型的轮次
    covered_until = batch[-1].assistant_message_id
    summary = ConversationSummary(
        text=text[: settings.context_summary_max_chars],
        covered_from_message_id=covered_from,
        covered_until_message_id=covered_until,
    )

    ok = commit_summary_if_version_matches(
        db,
        session_id=session.id,
        started_version=started_version,
        summary=summary,
    )
    if not ok:
        logger.info(
            "conversation summary discarded stale version session=%s started_version=%s",
            session.id,
            started_version,
        )
        return SummaryAttemptResult(
            committed=False,
            skipped_reason="version_conflict",
            elapsed_ms=elapsed,
            overflow_turns=len(overflow),
            batch_turns=len(batch),
            summary_chars=len(summary.text),
            input_tokens=input_tokens,
        )

    logger.info(
        "conversation summary committed session=%s until=%s overflow=%s batch=%s "
        "input_tokens=%s chars=%s elapsed_ms=%s",
        session.id,
        covered_until,
        len(overflow),
        len(batch),
        input_tokens,
        len(summary.text),
        elapsed,
    )
    return SummaryAttemptResult(
        committed=True,
        elapsed_ms=elapsed,
        overflow_turns=len(overflow),
        batch_turns=len(batch),
        summary_chars=len(summary.text),
        input_tokens=input_tokens,
    )


def _summary_user_payload(
    previous_summary: str | None,
    overflow: list[CompleteTurn],
    *,
    max_chars: int,
) -> dict[str, object]:
    """构造历史摘要 LLM 的用户侧 JSON 载荷。"""
    turns_payload = []
    for t in overflow:
        if t.response_status == "error":
            continue
        turns_payload.append(
            {
                "user": t.user_content,
                "assistant": t.assistant_content,
                "status": t.response_status,
                "recipe_title": t.recipe_title,
            }
        )
    return {
        "previous_summary": previous_summary,
        "turns_to_compress": turns_payload,
        "max_chars": max_chars,
    }


async def _summarize_overflow(
    llm: LLMProvider,
    *,
    previous_summary: str | None,
    overflow: list[CompleteTurn],
    max_chars: int,
) -> str:
    """调用 LLM 压缩溢出轮次，返回摘要文本（截断到 max_chars）。"""
    from app.agent.prompts import CONTEXT_HISTORY_SUMMARY_SYSTEM

    user_payload = _summary_user_payload(
        previous_summary, overflow, max_chars=max_chars
    )
    if not user_payload["turns_to_compress"] and previous_summary:
        return previous_summary[:max_chars]
    if not user_payload["turns_to_compress"]:
        return ""

    try:
        result = await llm.chat_json(
            system=CONTEXT_HISTORY_SUMMARY_SYSTEM,
            user=json.dumps(user_payload, ensure_ascii=False),
            purpose="context_summary",
        )
    except LLMError:
        raise

    text = str(result.data.get("summary") or "").strip()
    return text[:max_chars]
