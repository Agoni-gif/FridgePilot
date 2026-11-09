from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.common.config import Settings
from app.db.models import MessageRecord, RecipeRecord, SessionRecord
from app.schemas.context import (
    AssembledContext,
    PublicContext,
    RecentTurn,
    SessionOverrides,
    SessionState,
)
from app.schemas.recipe import Recipe
from app.services.state_merge import parse_overrides_json, parse_state_json

logger = logging.getLogger(__name__)

# Conservative: ~2 chars per token for mixed Chinese/English.
_CHARS_PER_TOKEN = 2
_STEP_INDEX_RE = re.compile(r"第\s*([0-9一二三四五六七八九十两]+)\s*步")
_LABELED_STEP_RE = re.compile(r"^第\s*(\d+)\s*步")


class ContextBudgetExceededError(Exception):
    """Raised when hard context (message/state/overrides) cannot fit the budget."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message
            or "当前做饭条件过长，请简化食材、忌口或其他要求后再试。"
        )


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)


def load_session_state(session: SessionRecord) -> SessionState | None:
    return parse_state_json(session.state_json)


def load_session_overrides(session: SessionRecord) -> SessionOverrides:
    return parse_overrides_json(session.session_overrides_json)


def load_last_recipe(
    db: Session,
    session: SessionRecord,
    state: SessionState | None,
    *,
    current_message: str = "",
    recipe_token_budget: int | None = None,
) -> tuple[RecipeRecord | None, Recipe | None, dict[str, Any] | None]:
    """Load last recipe by validated state pointer; fall back to latest in session."""
    record: RecipeRecord | None = None
    if state and state.last_recipe_id is not None:
        candidate = db.get(RecipeRecord, state.last_recipe_id)
        if candidate and candidate.session_id == session.id:
            record = candidate
    if record is None:
        record = (
            db.query(RecipeRecord)
            .filter(RecipeRecord.session_id == session.id)
            .order_by(RecipeRecord.id.desc())
            .first()
        )
        # Respect context boundary: recipe must be linked to a message after the start.
        if record and session.context_start_message_id is not None:
            if (
                record.assistant_message_id is not None
                and record.assistant_message_id <= session.context_start_message_id
            ):
                record = None
            elif record.assistant_message_id is None:
                # Old unpaired recipes: only use if created after clear is unknowable;
                # when a clear boundary exists and state has no last_recipe_id, skip.
                if not state or state.last_recipe_id is None:
                    record = None

    if record is None:
        return None, None, None
    try:
        recipe = Recipe.model_validate_json(record.recipe_json)
    except Exception:
        logger.warning("invalid recipe_json id=%s", record.id)
        return record, None, None

    summary = build_recipe_summary(
        record.id,
        recipe,
        current_message=current_message,
        token_budget=recipe_token_budget,
    )
    return record, recipe, summary


def build_recipe_summary(
    recipe_id: int,
    recipe: Recipe,
    *,
    current_message: str = "",
    token_budget: int | None = None,
) -> dict[str, Any]:
    """Build a last_recipe payload, selecting steps by focus and fitting budget."""
    focus_idx = _parse_step_index(current_message)
    focused = select_steps_for_focus(recipe.steps, current_message)
    summary: dict[str, Any] = {
        "id": recipe_id,
        "title": recipe.title,
        "summary": recipe.summary,
        "ingredients": list(recipe.ingredients),
        "steps": focused,
        "servings": recipe.servings,
        "sources": [s.model_dump() for s in recipe.sources],
    }
    if token_budget is None:
        return summary
    return shrink_recipe_summary(
        summary, token_budget, focus_step_index=focus_idx
    )


def select_steps_for_focus(steps: list[str], focus: str) -> list[str]:
    """Prefer referenced step(s); otherwise keep all steps (budget trims later)."""
    if not steps:
        return []
    idx = _parse_step_index(focus)
    if idx is None:
        return list(steps)
    # 1-based index from user language
    zero = max(0, min(len(steps) - 1, idx - 1))
    start = max(0, zero - 1)
    end = min(len(steps), zero + 2)
    selected = []
    for i in range(start, end):
        selected.append(f"第{i + 1}步：{steps[i]}")
    # If focus asked for a step beyond list, still include last step note.
    if idx > len(steps):
        selected.append(f"（菜谱共 {len(steps)} 步，没有第{idx}步）")
    return selected


def shrink_recipe_summary(
    summary: dict[str, Any],
    token_budget: int,
    *,
    focus_step_index: int | None = None,
) -> dict[str, Any]:
    """Trim recipe payload; always prefer keeping the user-referenced step."""
    current = dict(summary)
    if estimate_tokens(json.dumps(current, ensure_ascii=False)) <= token_budget:
        return current

    # Drop sources first (can be long URLs).
    current["sources"] = []
    if estimate_tokens(json.dumps(current, ensure_ascii=False)) <= token_budget:
        return current

    steps = list(current.get("steps") or [])
    ingredients = list(current.get("ingredients") or [])
    focus_idx = focus_step_index or _focus_index_from_steps(steps)

    while estimate_tokens(json.dumps(current, ensure_ascii=False)) > token_budget and (
        len(steps) > 1 or len(ingredients) > 1 or current.get("summary")
    ):
        # Prefer dropping non-focus steps before ingredients / summary.
        if len(steps) > 1:
            drop_at = _pick_non_focus_step_index(steps, focus_idx)
            if drop_at is not None:
                steps.pop(drop_at)
                current["steps"] = steps
                continue
        if len(ingredients) > 1:
            ingredients = ingredients[:-1]
            current["ingredients"] = ingredients
            continue
        if current.get("summary"):
            current["summary"] = ""
            continue
        break

    if estimate_tokens(json.dumps(current, ensure_ascii=False)) > token_budget:
        focus_step = _extract_focus_step(steps, focus_idx)
        current = {
            "id": summary.get("id"),
            "title": summary.get("title"),
            "summary": "",
            "ingredients": ingredients[:3],
            "steps": [focus_step] if focus_step else steps[:1],
            "servings": summary.get("servings"),
            "sources": [],
        }
    return current


def turns_token_count(turns: list[RecentTurn]) -> int:
    return _turns_tokens(turns)


def load_recent_turns(
    db: Session,
    session: SessionRecord,
    *,
    max_turns: int,
    token_budget: int,
    reserved_tokens: int = 0,
    after_message_id: int | None = None,
) -> list[RecentTurn]:
    """Load completed user/assistant turns after context/summary boundary, newest-trimmed.

    Messages with id <= after_message_id (typically summary_until_message_id) are
    excluded so the recent window never overlaps the summarized range.
    """
    query = db.query(MessageRecord).filter(MessageRecord.session_id == session.id)
    lower_bound: int | None = None
    if session.context_start_message_id is not None:
        lower_bound = session.context_start_message_id
    if after_message_id is not None:
        lower_bound = (
            after_message_id
            if lower_bound is None
            else max(lower_bound, after_message_id)
        )
    if lower_bound is not None:
        query = query.filter(MessageRecord.id > lower_bound)
    messages = query.order_by(MessageRecord.id.asc()).all()

    turns: list[RecentTurn] = []
    pending_user: MessageRecord | None = None
    recipe_titles = _recipe_titles_by_message(db, session.id)

    for msg in messages:
        if msg.role == "user":
            pending_user = msg
            continue
        if msg.role != "assistant":
            continue
        status = msg.response_status
        content = msg.content
        if status == "error":
            content = "上一轮生成失败。"
        elif status == "insufficient_sources":
            content = content[:200] if content else "上一轮没有足够来源。"

        if pending_user is not None:
            turns.append(
                RecentTurn(
                    role="user",
                    content=pending_user.content[:1000],
                    message_id=pending_user.id,
                )
            )
            pending_user = None
        turns.append(
            RecentTurn(
                role="assistant",
                content=content[:1500],
                response_status=status,
                recipe_title=recipe_titles.get(msg.id),
                message_id=msg.id,
            )
        )

    max_messages = max_turns * 2
    if len(turns) > max_messages:
        turns = turns[-max_messages:]

    budget = max(0, token_budget - reserved_tokens)
    while turns and _turns_tokens(turns) > budget:
        if len(turns) >= 2 and turns[0].role == "user":
            turns = turns[2:]
        else:
            turns = turns[1:]
    return turns


@dataclass
class ContextBudgetPlan:
    """Shared budget split used by assemble_context and summary overflow selection."""

    total_budget: int
    hard_tokens: int
    summary_text: str | None
    summary_until: int | None
    summary_reserve: int
    body_budget: int
    recipe_budget: int
    turns_budget: int
    last_recipe_summary: dict[str, Any] | None
    state: SessionState | None
    overrides: SessionOverrides


def plan_context_budgets(
    db: Session,
    session: SessionRecord,
    *,
    current_message: str,
    settings: Settings,
) -> ContextBudgetPlan:
    """Compute the same turns budget assemble_context will use for the recent window.

    Summary overflow selection must call this so covered range and recent window
    meet without a gap.
    """
    from app.services.conversation_summary import parse_summary_json

    state = load_session_state(session)
    overrides = load_session_overrides(session)
    total_budget = settings.context_token_budget

    stored_summary = parse_summary_json(session.summary_json)
    summary_text = stored_summary.text if stored_summary else None
    summary_until = session.summary_until_message_id
    if summary_until is None and stored_summary is not None:
        summary_until = stored_summary.covered_until_message_id

    hard_tokens = (
        estimate_tokens(current_message)
        + estimate_tokens(state.model_dump_json() if state else "")
        + estimate_tokens(overrides.model_dump_json())
        + 80
    )
    remaining = max(0, total_budget - hard_tokens)
    # Reserve summary space even before a summary exists, so overflow selection and
    # post-commit assemble use the same turns budget (avoids mid-history gaps).
    summary_reserve = 0
    if settings.context_summary_enabled and remaining > 0:
        cap = max(60, remaining // 6)
        actual = estimate_tokens(summary_text) if summary_text else 0
        projected = estimate_tokens("x" * settings.context_summary_max_chars)
        summary_reserve = min(max(actual, projected), cap)
    body_budget = max(0, remaining - summary_reserve)
    recipe_budget = max(120, body_budget // 2) if body_budget else 0

    _record, _recipe, last_recipe_summary = load_last_recipe(
        db,
        session,
        state,
        current_message=current_message,
        recipe_token_budget=recipe_budget or None,
    )
    recipe_tokens = estimate_tokens(
        json.dumps(last_recipe_summary, ensure_ascii=False) if last_recipe_summary else ""
    )
    turns_budget = max(0, body_budget - recipe_tokens)

    return ContextBudgetPlan(
        total_budget=total_budget,
        hard_tokens=hard_tokens,
        summary_text=summary_text,
        summary_until=summary_until,
        summary_reserve=summary_reserve,
        body_budget=body_budget,
        recipe_budget=recipe_budget,
        turns_budget=turns_budget,
        last_recipe_summary=last_recipe_summary,
        state=state,
        overrides=overrides,
    )


def projected_summary_placeholder(settings: Settings, existing: str | None) -> str | None:
    """Summary text used when probing final payload size before/without a stored summary."""
    if existing:
        return existing
    if not settings.context_summary_enabled:
        return None
    return "x" * settings.context_summary_max_chars


def payload_token_count(
    *,
    current_message: str,
    recent_turns: list[RecentTurn],
    session_state: SessionState | None,
    session_overrides: SessionOverrides,
    last_recipe: dict[str, Any] | None,
    conversation_summary: str | None,
    user_defaults: dict[str, Any] | None = None,
    allergies: list[str] | None = None,
) -> int:
    """Estimate tokens of the final serialized parse payload (includes JSON overhead)."""
    ctx = AssembledContext(
        current_message=current_message,
        recent_turns=recent_turns,
        session_state=session_state,
        session_overrides=session_overrides,
        last_recipe=last_recipe,
        conversation_summary=conversation_summary,
        user_defaults=dict(user_defaults or {}),
        allergies=list(allergies or []),
    )
    return estimate_tokens(json.dumps(_payload_dict(ctx), ensure_ascii=False))


def fit_recent_turns_to_payload(
    turns: list[RecentTurn],
    *,
    max_turns: int,
    token_budget: int,
    probe_tokens,
) -> list[RecentTurn]:
    """Shrink recent turns from the oldest complete pair until full payload fits.

    May return an empty list when even the newest complete turn cannot fit — matching
    select_recent_and_overflow, which then puts that turn in the summary overflow.
    """
    if not turns:
        return []
    # turns are [user, asst, user, asst, ...]; max_turns counts pairs.
    max_messages = max(1, max_turns) * 2
    if len(turns) > max_messages:
        turns = turns[-max_messages:]

    while turns and probe_tokens(turns) > token_budget:
        if len(turns) >= 2 and turns[0].role == "user":
            turns = turns[2:]
        else:
            turns = turns[1:]
    return turns


def assemble_context(
    db: Session,
    session: SessionRecord,
    *,
    current_message: str,
    settings: Settings,
    user_defaults: dict[str, Any] | None = None,
    allergies: list[str] | None = None,
    session_state: SessionState | None = None,
) -> AssembledContext:
    """Assemble context by fitting recent turns to the final serialized payload.

    Optional user_defaults/allergies/session_state must match what the request will
    send to the model so summary overflow selection and assemble agree.
    """
    plan = plan_context_budgets(
        db, session, current_message=current_message, settings=settings
    )
    state = session_state if session_state is not None else plan.state
    defaults = dict(user_defaults or {})
    allergy_list = list(allergies or [])

    # Load complete turns after summary boundary, then fit by final JSON payload
    # (not content-only estimates) so enforce_payload_budget won't drop more turns.
    from app.services.conversation_summary import (
        load_complete_turns,
        turns_to_recent,
    )

    complete = load_complete_turns(db, session, after_message_id=plan.summary_until)
    candidate = turns_to_recent(complete)
    summary_for_probe = projected_summary_placeholder(settings, plan.summary_text)

    def _probe(turns: list[RecentTurn]) -> int:
        return payload_token_count(
            current_message=current_message,
            recent_turns=turns,
            session_state=state,
            session_overrides=plan.overrides,
            last_recipe=plan.last_recipe_summary,
            conversation_summary=summary_for_probe,
            user_defaults=defaults,
            allergies=allergy_list,
        )

    recent = fit_recent_turns_to_payload(
        candidate,
        max_turns=settings.context_max_turns,
        token_budget=plan.total_budget,
        probe_tokens=_probe,
    )

    ctx = AssembledContext(
        current_message=current_message,
        recent_turns=recent,
        session_state=state,
        session_overrides=plan.overrides,
        last_recipe=plan.last_recipe_summary,
        conversation_summary=plan.summary_text,
        summary_until_message_id=plan.summary_until,
        user_defaults=defaults,
        allergies=allergy_list,
        context_version=session.context_version or 0,
        context_start_message_id=session.context_start_message_id,
    )
    return enforce_payload_budget(ctx, plan.total_budget)


def enforce_payload_budget(ctx: AssembledContext, token_budget: int) -> AssembledContext:
    """Final guard: drop summary, shrink recipe, then turns until payload fits.

    Turns are trimmed last so window boundaries chosen by final-payload fitting
    are preserved whenever recipe/summary can absorb the overflow. If hard fields
    alone still exceed the budget, raise ContextBudgetExceededError.
    """
    payload = _payload_dict(ctx)
    if estimate_tokens(json.dumps(payload, ensure_ascii=False)) <= token_budget:
        return ctx

    turns = list(ctx.recent_turns)
    recipe = dict(ctx.last_recipe) if ctx.last_recipe else None
    summary = ctx.conversation_summary
    focus_idx = _parse_step_index(ctx.current_message)

    while (
        estimate_tokens(
            json.dumps(
                _payload_dict_parts(ctx, turns, recipe, summary),
                ensure_ascii=False,
            )
        )
        > token_budget
    ):
        # Lowest priority: drop or truncate background summary first.
        if summary:
            if len(summary) > 120:
                summary = summary[: max(80, len(summary) // 2)].rstrip() + "…"
            else:
                summary = None
            continue
        # Prefer shrinking recipe before dropping recent turns (keeps summary boundary).
        if recipe:
            recipe = shrink_recipe_summary(
                recipe,
                max(80, token_budget // 4),
                focus_step_index=focus_idx,
            )
            if (
                estimate_tokens(
                    json.dumps(
                        _payload_dict_parts(ctx, turns, recipe, summary),
                        ensure_ascii=False,
                    )
                )
                > token_budget
            ):
                recipe = {
                    "id": recipe.get("id"),
                    "title": recipe.get("title"),
                }
            if (
                estimate_tokens(
                    json.dumps(
                        _payload_dict_parts(ctx, turns, recipe, summary),
                        ensure_ascii=False,
                    )
                )
                > token_budget
            ):
                # Only drop recipe entirely after title-only still overflows.
                title_only = {"id": recipe.get("id"), "title": recipe.get("title")}
                if (
                    estimate_tokens(
                        json.dumps(
                            _payload_dict_parts(ctx, turns, title_only, summary),
                            ensure_ascii=False,
                        )
                    )
                    <= token_budget
                ):
                    recipe = title_only
                    continue
                recipe = None
                continue
            continue
        if turns:
            if len(turns) >= 2 and turns[0].role == "user":
                turns = turns[2:]
            else:
                turns = turns[1:]
            continue
        break

    trimmed = AssembledContext(
        current_message=ctx.current_message,
        recent_turns=turns,
        session_state=ctx.session_state,
        session_overrides=ctx.session_overrides,
        last_recipe=recipe,
        conversation_summary=summary,
        summary_until_message_id=ctx.summary_until_message_id,
        user_defaults=ctx.user_defaults,
        allergies=list(ctx.allergies or []),
        long_term_preferences_applied=ctx.long_term_preferences_applied,
        long_term_preferences_version=ctx.long_term_preferences_version,
        context_version=ctx.context_version,
        context_start_message_id=ctx.context_start_message_id,
    )
    final_tokens = estimate_tokens(json.dumps(_payload_dict(trimmed), ensure_ascii=False))
    if final_tokens > token_budget:
        logger.warning(
            "context budget exceeded after trim tokens=%s budget=%s",
            final_tokens,
            token_budget,
        )
        raise ContextBudgetExceededError()
    return trimmed


def to_public_context(
    session: SessionRecord,
    *,
    long_term_preferences_applied: bool = False,
    long_term_preferences_version: int | None = None,
    effective_state: SessionState | None = None,
) -> PublicContext:
    return PublicContext(
        context_version=session.context_version or 0,
        context_start_message_id=session.context_start_message_id,
        state=effective_state if effective_state is not None else load_session_state(session),
        long_term_preferences_applied=long_term_preferences_applied,
        long_term_preferences_version=long_term_preferences_version,
    )


def serialize_state(state: SessionState | None) -> str | None:
    if state is None:
        return None
    return state.model_dump_json()


def serialize_overrides(overrides: SessionOverrides | None) -> str | None:
    if overrides is None:
        return None
    if not overrides.set_fields and not overrides.cleared_fields:
        return None
    return overrides.model_dump_json()


def build_parse_user_payload(ctx: AssembledContext) -> str:
    """Structured data for the parse LLM call (not system instructions)."""
    return json.dumps(_payload_dict(ctx), ensure_ascii=False)


def _payload_dict(ctx: AssembledContext) -> dict[str, Any]:
    return _payload_dict_parts(
        ctx, ctx.recent_turns, ctx.last_recipe, ctx.conversation_summary
    )


def _payload_dict_parts(
    ctx: AssembledContext,
    turns: list[RecentTurn],
    last_recipe: dict[str, Any] | None,
    conversation_summary: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "current_message": ctx.current_message,
        "recent_turns": [t.model_dump(exclude={"message_id"}) for t in turns],
        "session_state": ctx.session_state.model_dump() if ctx.session_state else None,
        "session_overrides": ctx.session_overrides.model_dump(),
        "last_recipe": last_recipe,
        "user_defaults": ctx.user_defaults,
    }
    if conversation_summary:
        payload["conversation_summary"] = conversation_summary
    return payload


def _turns_tokens(turns: list[RecentTurn]) -> int:
    return sum(estimate_tokens(t.content) + 8 for t in turns)


def _focus_index_from_steps(steps: list[str]) -> int | None:
    """Infer focus from a single labeled step list, if unambiguous."""
    indices = []
    for step in steps:
        match = _LABELED_STEP_RE.match(str(step).strip())
        if match:
            indices.append(int(match.group(1)))
    if len(indices) == 1:
        return indices[0]
    return None


def _pick_non_focus_step_index(
    steps: list[str], focus_step_index: int | None
) -> int | None:
    """Choose a step index to drop, never the focused one when identifiable."""
    if not steps:
        return None
    if focus_step_index is None:
        return len(steps) - 1

    focus_positions = [
        i
        for i, step in enumerate(steps)
        if _labeled_step_number(step) == focus_step_index
    ]
    if not focus_positions:
        # No labeled match — drop farthest from middle / end.
        return len(steps) - 1

    focus_pos = focus_positions[0]
    # Drop neighbors first (farther end preferred), never the focus itself.
    candidates = [i for i in range(len(steps)) if i != focus_pos]
    if not candidates:
        return None
    # Prefer dropping the farthest neighbor from the focus.
    return max(candidates, key=lambda i: abs(i - focus_pos))


def _extract_focus_step(steps: list[str], focus_step_index: int | None) -> str | None:
    if not steps:
        return None
    if focus_step_index is None:
        return steps[0]
    for step in steps:
        if _labeled_step_number(step) == focus_step_index:
            return step
    return steps[0]


def _labeled_step_number(step: str) -> int | None:
    match = _LABELED_STEP_RE.match(str(step).strip())
    if not match:
        return None
    return int(match.group(1))


def _parse_step_index(text: str) -> int | None:
    if not text:
        return None
    match = _STEP_INDEX_RE.search(text)
    if not match:
        return None
    raw = match.group(1)
    if raw.isdigit():
        return int(raw)
    mapping = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    if raw in mapping:
        return mapping[raw]
    if raw.startswith("十") and len(raw) == 2 and raw[1] in mapping:
        return 10 + mapping[raw[1]]
    if len(raw) == 3 and raw[1] == "十" and raw[0] in mapping and raw[2] in mapping:
        # e.g. 二十三
        return mapping[raw[0]] * 10 + mapping[raw[2]]
    if len(raw) == 2 and raw[1] == "十" and raw[0] in mapping:
        return mapping[raw[0]] * 10
    return None


def _recipe_titles_by_message(db: Session, session_id: str) -> dict[int, str]:
    rows = (
        db.query(RecipeRecord)
        .filter(
            RecipeRecord.session_id == session_id,
            RecipeRecord.assistant_message_id.isnot(None),
        )
        .all()
    )
    result: dict[int, str] = {}
    for row in rows:
        if row.assistant_message_id is None:
            continue
        try:
            recipe = Recipe.model_validate_json(row.recipe_json)
            result[row.assistant_message_id] = recipe.title
        except Exception:
            continue
    return result
