from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.common.config import Settings
from app.db.models import MessageRecord, SessionRecord
from app.providers.llm import LLMError, LLMProvider
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
    user_message_id: int
    user_content: str
    assistant_message_id: int
    assistant_content: str
    response_status: str | None
    recipe_title: str | None = None


@dataclass
class SummaryAttemptResult:
    committed: bool
    skipped_reason: str | None = None
    elapsed_ms: int = 0
    overflow_turns: int = 0
    batch_turns: int = 0
    summary_chars: int = 0
    input_tokens: int = 0


def parse_summary_json(raw: str | None) -> ConversationSummary | None:
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
    """Pair user/assistant messages after the context boundary into complete turns."""
    query = db.query(MessageRecord).filter(MessageRecord.session_id == session.id)
    boundary = session.context_start_message_id
    if boundary is not None:
        query = query.filter(MessageRecord.id > boundary)
    if after_message_id is not None:
        query = query.filter(MessageRecord.id > after_message_id)
    messages = query.order_by(MessageRecord.id.asc()).all()

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
    """Public alias for pairing complete turns into RecentTurn messages."""
    return _to_recent_turns(turns)


def select_recent_and_overflow(
    turns: list[CompleteTurn],
    *,
    max_turns: int,
    token_budget: int,
    probe_tokens=None,
) -> tuple[list[RecentTurn], list[CompleteTurn]]:
    """Keep newest complete turns in the recent window; older ones become overflow.

    When even the newest complete turn cannot fit the final payload, the recent
    window is empty and that turn is included in overflow (same rule as assemble's
    fit_recent_turns_to_payload). Do not force-keep an oversized newest turn here
    only for assemble to drop it later.

    When probe_tokens is provided, it must estimate the *final serialized payload*
    size for a candidate recent window (including JSON overhead). Otherwise falls
    back to content-only turn tokens (legacy/tests).
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
            # Empty recent always fits the content-only estimator.
            fits = (not recent) or turns_token_count(recent) <= token_budget
        if fits:
            return recent, turns[:start]
        start += 1

    # Hard fields alone already over budget: still treat all history as overflow.
    return [], list(turns)


def estimate_summary_input_tokens(
    previous_summary: str | None,
    turns: list[CompleteTurn],
    *,
    max_chars: int,
) -> int:
    payload = _summary_user_payload(previous_summary, turns, max_chars=max_chars)
    return estimate_tokens(json.dumps(payload, ensure_ascii=False))


def select_summary_batch(
    overflow: list[CompleteTurn],
    *,
    previous_summary: str | None,
    input_token_budget: int,
    max_chars: int,
) -> list[CompleteTurn]:
    """Take the oldest contiguous complete turns that fit the summary input budget.

    If even the first turn alone exceeds the budget, return an empty batch so the
    caller can skip without advancing the coverage pointer.
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
    """Persist summary only when context_version still matches (blocks post-clear revive)."""
    updated = (
        db.query(SessionRecord)
        .filter(
            SessionRecord.id == session_id,
            SessionRecord.context_version == started_version,
        )
        .update(
            {
                SessionRecord.summary_json: summary.model_dump_json(),
                SessionRecord.summary_until_message_id: summary.covered_until_message_id,
                SessionRecord.summary_version: SessionRecord.summary_version + 1,
            },
            synchronize_session=False,
        )
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
    """If older complete turns fall outside the recent window, summarize a bounded batch.

    Recent/overflow is decided by the final serialized payload size (same probe as
    assemble_context), so later enforce_payload_budget trimming does not open a gap.
    Only a budget-limited oldest batch is sent; the pointer advances only through
    turns actually accepted under the input budget.

    Failures are soft: caller continues with state + recent turns.
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

    # Prefer final-payload fitting; optional turns_token_budget only for legacy tests.
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
    # Hard gate before send: never mark coverage for an over-budget payload.
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
    # Only advance through turns actually sent to the model.
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
