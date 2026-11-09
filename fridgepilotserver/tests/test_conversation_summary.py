from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.orchestrator import AgentOutcome
from app.common.config import Settings
from app.db.models import MessageRecord, SessionRecord, User
from app.db.session import Base
from app.providers.llm import LLMJsonResult
from app.schemas.context import ConversationSummary, SessionState
from app.schemas.recipe import Ingredient, Recipe, RecipeSource
from app.services.conversation_context import (
    assemble_context,
    build_parse_user_payload,
    estimate_tokens,
)
from app.services.conversation_context import plan_context_budgets
from app.services.conversation_summary import (
    clear_summary_fields,
    commit_summary_if_version_matches,
    estimate_summary_input_tokens,
    load_complete_turns,
    maybe_refresh_conversation_summary,
    select_recent_and_overflow,
    select_summary_batch,
)


def _engine_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk(dbapi_connection, _connection_record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return engine, SessionLocal


def _settings(**kwargs) -> Settings:
    base = dict(
        llm_api_key="x",
        tavily_api_key="x",
        session_memory_enabled=True,
        context_summary_enabled=True,
        context_max_turns=2,
        context_token_budget=4000,
        database_url="sqlite://",
        app_env="test",
    )
    base.update(kwargs)
    return Settings(**base)


def _seed_long_session(db, *, pairs: int = 6) -> SessionRecord:
    db.add(
        User(
            id="u-sum",
            username="sum_user",
            email="sum@example.com",
            password_hash="x",
        )
    )
    session = SessionRecord(
        id="s-sum",
        user_id="u-sum",
        context_version=1,
        state_json=SessionState(
            ingredients=[Ingredient(name="番茄"), Ingredient(name="鸡蛋")],
            servings=2,
        ).model_dump_json(),
    )
    db.add(session)
    db.flush()
    for i in range(pairs):
        u = MessageRecord(
            session_id=session.id,
            role="user",
            content=f"第{i + 1}轮：{'番茄鸡蛋 ' * 8}还有其他要求{i}",
        )
        db.add(u)
        db.flush()
        a = MessageRecord(
            session_id=session.id,
            role="assistant",
            content=f"第{i + 1}轮菜谱说明 " + ("步骤内容。" * 20),
            reply_to_message_id=u.id,
            response_status="completed",
        )
        db.add(a)
        db.flush()
    db.commit()
    db.refresh(session)
    return session


def test_select_recent_and_overflow_keeps_newest_only():
    from app.services.conversation_summary import CompleteTurn

    turns = [
        CompleteTurn(
            user_message_id=i * 2 + 1,
            user_content=f"user-{i}",
            assistant_message_id=i * 2 + 2,
            assistant_content=f"asst-{i}",
            response_status="completed",
        )
        for i in range(5)
    ]
    recent, overflow = select_recent_and_overflow(
        turns, max_turns=2, token_budget=10_000
    )
    assert len(overflow) == 3
    assert overflow[-1].assistant_message_id == 6
    assert recent[0].content == "user-3"
    assert recent[-1].content == "asst-4"
    # No overlap between overflow coverage and recent message ids.
    recent_ids = {t.message_id for t in recent if t.message_id is not None}
    overflow_ids = {t.user_message_id for t in overflow} | {
        t.assistant_message_id for t in overflow
    }
    assert recent_ids.isdisjoint(overflow_ids)


def test_select_recent_and_overflow_allows_empty_when_newest_does_not_fit():
    from app.services.conversation_summary import CompleteTurn

    turns = [
        CompleteTurn(
            user_message_id=1,
            user_content="old",
            assistant_message_id=2,
            assistant_content="old-a",
            response_status="completed",
        ),
        CompleteTurn(
            user_message_id=19,
            user_content="newest-user",
            assistant_message_id=20,
            assistant_content="newest-asst",
            response_status="completed",
        ),
    ]

    def _never_fits(_recent):
        return 10_000

    recent, overflow = select_recent_and_overflow(
        turns,
        max_turns=2,
        token_budget=100,
        probe_tokens=_never_fits,
    )
    assert recent == []
    assert len(overflow) == 2
    assert overflow[-1].assistant_message_id == 20


@pytest.mark.asyncio
async def test_summary_covers_overflow_without_overlapping_recent():
    _engine, SessionLocal = _engine_db()
    db = SessionLocal()
    session = _seed_long_session(db, pairs=5)
    settings = _settings(context_max_turns=2)
    current_message = "改成四人份"

    llm = AsyncMock()
    llm.chat_json = AsyncMock(
        return_value=LLMJsonResult(
            data={"summary": "早先讨论过番茄鸡蛋两人份，做过几轮调整。"}
        )
    )

    result = await maybe_refresh_conversation_summary(
        db,
        session,
        llm=llm,
        settings=settings,
        started_version=1,
        current_message=current_message,
    )
    assert result.committed is True
    assert result.overflow_turns >= 1
    db.refresh(session)
    assert session.summary_until_message_id is not None
    assert session.summary_json

    ctx = assemble_context(
        db, session, current_message=current_message, settings=settings
    )
    assert ctx.conversation_summary
    assert "番茄" in ctx.conversation_summary
    # Recent turns must all be after summary_until.
    for turn in ctx.recent_turns:
        assert turn.message_id is None or turn.message_id > session.summary_until_message_id
    # State remains authoritative — summary does not mutate it.
    assert ctx.session_state is not None
    assert ctx.session_state.servings == 2
    assert [i.name for i in ctx.session_state.ingredients] == ["番茄", "鸡蛋"]
    db.close()


@pytest.mark.asyncio
async def test_unified_budget_leaves_no_gap_when_batch_covers_overflow():
    """Final JSON payload fitting must keep summary coverage contiguous with recent."""
    from app.services.conversation_context import (
        payload_token_count,
        projected_summary_placeholder,
    )
    from app.services.conversation_summary import turns_to_recent

    _engine, SessionLocal = _engine_db()
    db = SessionLocal()
    session = _seed_long_session(db, pairs=12)
    settings = _settings(
        context_max_turns=2,
        context_token_budget=900,
        context_summary_input_token_budget=50_000,
    )
    current_message = "继续刚才的两人份番茄鸡蛋"

    plan = plan_context_budgets(
        db, session, current_message=current_message, settings=settings
    )
    uncovered = load_complete_turns(db, session)
    summary_probe = projected_summary_placeholder(settings, plan.summary_text)

    def _probe(recent):
        return payload_token_count(
            current_message=current_message,
            recent_turns=recent,
            session_state=plan.state,
            session_overrides=plan.overrides,
            last_recipe=plan.last_recipe_summary,
            conversation_summary=summary_probe,
        )

    # Content-only estimate keeps more pairs than final JSON payload can.
    content_recent, _ = select_recent_and_overflow(
        uncovered,
        max_turns=settings.context_max_turns,
        token_budget=plan.turns_budget,
    )
    payload_recent, overflow = select_recent_and_overflow(
        uncovered,
        max_turns=settings.context_max_turns,
        token_budget=plan.total_budget,
        probe_tokens=_probe,
    )
    assert overflow
    assert len(payload_recent) <= len(content_recent)

    llm = AsyncMock()
    llm.chat_json = AsyncMock(
        return_value=LLMJsonResult(data={"summary": "早先多轮番茄鸡蛋讨论。"})
    )
    result = await maybe_refresh_conversation_summary(
        db,
        session,
        llm=llm,
        settings=settings,
        started_version=1,
        current_message=current_message,
    )
    assert result.committed is True
    assert result.batch_turns == result.overflow_turns
    db.refresh(session)

    ctx = assemble_context(
        db, session, current_message=current_message, settings=settings
    )
    # Safety net must not reopen a gap after payload-based selection.
    assert estimate_tokens(build_parse_user_payload(ctx)) <= settings.context_token_budget
    recent_ids = sorted(
        mid for mid in (t.message_id for t in ctx.recent_turns) if mid is not None
    )
    assert recent_ids, "expected a non-empty recent window"
    assert session.summary_until_message_id is not None
    assert recent_ids[0] == session.summary_until_message_id + 1

    orphan = (
        db.query(MessageRecord)
        .filter(
            MessageRecord.session_id == session.id,
            MessageRecord.id > session.summary_until_message_id,
            MessageRecord.id < recent_ids[0],
        )
        .count()
    )
    assert orphan == 0
    db.close()


def test_summary_batch_is_bounded_by_input_budget():
    from app.services.conversation_summary import CompleteTurn

    overflow = [
        CompleteTurn(
            user_message_id=i * 2 + 1,
            user_content=("用户请求内容。" * 40),
            assistant_message_id=i * 2 + 2,
            assistant_content=("助手回复内容。" * 60),
            response_status="completed",
        )
        for i in range(100)
    ]
    full_tokens = estimate_summary_input_tokens(
        None, overflow, max_chars=800
    )
    assert full_tokens > 10_000

    batch = select_summary_batch(
        overflow,
        previous_summary=None,
        input_token_budget=2500,
        max_chars=800,
    )
    assert 1 <= len(batch) < len(overflow)
    batch_tokens = estimate_summary_input_tokens(None, batch, max_chars=800)
    assert batch_tokens <= 2500
    # Contiguous from the oldest end.
    assert batch[0].user_message_id == overflow[0].user_message_id
    assert batch[-1].assistant_message_id == overflow[len(batch) - 1].assistant_message_id


def test_summary_batch_skips_when_first_turn_exceeds_budget():
    from app.services.conversation_summary import CompleteTurn

    huge = CompleteTurn(
        user_message_id=1,
        user_content=("超长用户输入。" * 200),
        assistant_message_id=2,
        assistant_content=("超长助手回复。" * 300),
        response_status="completed",
    )
    alone = estimate_summary_input_tokens(None, [huge], max_chars=800)
    assert alone > 1000

    batch = select_summary_batch(
        [huge],
        previous_summary=None,
        input_token_budget=1000,
        max_chars=800,
    )
    assert batch == []


@pytest.mark.asyncio
async def test_newest_turn_enters_overflow_when_it_cannot_fit_recent():
    """Do not force-keep newest as recent if assemble would drop it anyway."""
    _engine, SessionLocal = _engine_db()
    db = SessionLocal()
    session = _seed_long_session(db, pairs=10)
    # Inflate the newest pair so it cannot fit a tiny total budget with hard fields.
    last_user = (
        db.query(MessageRecord)
        .filter(MessageRecord.session_id == session.id, MessageRecord.role == "user")
        .order_by(MessageRecord.id.desc())
        .first()
    )
    last_asst = (
        db.query(MessageRecord)
        .filter(
            MessageRecord.session_id == session.id, MessageRecord.role == "assistant"
        )
        .order_by(MessageRecord.id.desc())
        .first()
    )
    assert last_user and last_asst
    last_user.content = "最新一轮用户。" * 80
    last_asst.content = "最新一轮助手。" * 120
    db.commit()
    newest_user_id = last_user.id
    newest_asst_id = last_asst.id

    settings = _settings(
        context_max_turns=2,
        context_token_budget=350,
        context_summary_input_token_budget=50_000,
        context_summary_max_chars=120,
    )
    current_message = "继续"

    llm = AsyncMock()
    llm.chat_json = AsyncMock(
        return_value=LLMJsonResult(data={"summary": "含最新一轮的背景摘要"})
    )
    result = await maybe_refresh_conversation_summary(
        db,
        session,
        llm=llm,
        settings=settings,
        started_version=1,
        current_message=current_message,
    )
    assert result.committed is True
    # Newest pair must have been in overflow (not stranded outside summary+recent).
    assert result.overflow_turns >= 1
    db.refresh(session)
    assert session.summary_until_message_id is not None
    assert session.summary_until_message_id >= newest_asst_id

    ctx = assemble_context(
        db, session, current_message=current_message, settings=settings
    )
    recent_ids = [
        mid for mid in (t.message_id for t in ctx.recent_turns) if mid is not None
    ]
    # Newest messages are covered by summary; they must not appear as orphans.
    assert newest_user_id not in recent_ids
    assert newest_asst_id not in recent_ids
    orphan = (
        db.query(MessageRecord)
        .filter(
            MessageRecord.session_id == session.id,
            MessageRecord.id > session.summary_until_message_id,
        )
        .count()
    )
    # Any message after coverage must be in recent (or there are none).
    if orphan:
        assert recent_ids
        assert min(recent_ids) == session.summary_until_message_id + 1
    db.close()


@pytest.mark.asyncio
async def test_oversize_turn_does_not_advance_coverage_pointer():
    _engine, SessionLocal = _engine_db()
    db = SessionLocal()
    session = _seed_long_session(db, pairs=3)
    # Inflate the oldest turn so a single summary request exceeds a tight budget.
    first_user = (
        db.query(MessageRecord)
        .filter(MessageRecord.session_id == session.id, MessageRecord.role == "user")
        .order_by(MessageRecord.id.asc())
        .first()
    )
    first_asst = (
        db.query(MessageRecord)
        .filter(
            MessageRecord.session_id == session.id, MessageRecord.role == "assistant"
        )
        .order_by(MessageRecord.id.asc())
        .first()
    )
    assert first_user and first_asst
    first_user.content = "用户长文。" * 400
    first_asst.content = "助手长文。" * 600
    db.commit()
    db.refresh(session)

    settings = _settings(
        context_max_turns=1,
        context_token_budget=4000,
        context_summary_input_token_budget=1000,
    )
    llm = AsyncMock()
    llm.chat_json = AsyncMock(
        return_value=LLMJsonResult(data={"summary": "不应被调用"})
    )

    result = await maybe_refresh_conversation_summary(
        db,
        session,
        llm=llm,
        settings=settings,
        started_version=1,
        current_message="继续",
    )
    assert result.committed is False
    assert result.skipped_reason == "batch_over_budget"
    assert result.input_tokens > 1000
    llm.chat_json.assert_not_called()
    db.refresh(session)
    assert session.summary_until_message_id is None
    assert session.summary_json is None
    db.close()


@pytest.mark.asyncio
async def test_summary_pointer_advances_only_through_bounded_batch():
    _engine, SessionLocal = _engine_db()
    db = SessionLocal()
    session = _seed_long_session(db, pairs=30)
    settings = _settings(
        context_max_turns=2,
        context_token_budget=2000,
        context_summary_input_token_budget=800,
    )
    current_message = "还是两人份"

    captured: dict = {}

    async def fake_chat_json(*, system, user, purpose="chat_json", **_kwargs):
        payload = json.loads(user)
        captured["turns"] = payload.get("turns_to_compress") or []
        captured["input_tokens"] = estimate_tokens(user)
        return LLMJsonResult(data={"summary": "有界批次摘要"})

    llm = AsyncMock()
    llm.chat_json = fake_chat_json

    result = await maybe_refresh_conversation_summary(
        db,
        session,
        llm=llm,
        settings=settings,
        started_version=1,
        current_message=current_message,
    )
    assert result.committed is True
    assert result.overflow_turns > result.batch_turns
    assert result.batch_turns == len(captured["turns"])
    assert result.input_tokens <= settings.context_summary_input_token_budget
    assert captured["input_tokens"] <= settings.context_summary_input_token_budget + 50

    db.refresh(session)
    # Pointer stopped at the batch, not the full overflow tail.
    uncovered_after = load_complete_turns(
        db, session, after_message_id=session.summary_until_message_id
    )
    assert uncovered_after  # remaining history still awaits later batches
    db.close()


@pytest.mark.asyncio
async def test_summary_failure_does_not_block_refresh():
    _engine, SessionLocal = _engine_db()
    db = SessionLocal()
    session = _seed_long_session(db, pairs=4)
    settings = _settings(context_max_turns=1)

    llm = AsyncMock()
    llm.chat_json = AsyncMock(side_effect=RuntimeError("boom"))

    result = await maybe_refresh_conversation_summary(
        db,
        session,
        llm=llm,
        settings=settings,
        started_version=1,
        turns_token_budget=10_000,
    )
    assert result.committed is False
    assert result.skipped_reason == "llm_error"
    db.refresh(session)
    assert session.summary_json is None

    # Assemble still works from state + recent messages.
    ctx = assemble_context(db, session, current_message="继续", settings=settings)
    assert ctx.session_state is not None
    assert ctx.conversation_summary is None
    assert ctx.recent_turns
    db.close()


def test_clear_context_wipes_summary_and_version_blocks_stale_commit():
    _engine, SessionLocal = _engine_db()
    db = SessionLocal()
    session = _seed_long_session(db, pairs=3)
    summary = ConversationSummary(
        text="旧摘要：番茄鸡蛋",
        covered_from_message_id=1,
        covered_until_message_id=4,
    )
    assert commit_summary_if_version_matches(
        db, session_id=session.id, started_version=1, summary=summary
    )
    db.refresh(session)
    assert session.summary_until_message_id == 4
    started = session.context_version

    # Simulate clear_context.
    clear_summary_fields(session)
    session.context_start_message_id = (
        db.query(MessageRecord.id)
        .filter(MessageRecord.session_id == session.id)
        .order_by(MessageRecord.id.desc())
        .first()[0]
    )
    session.state_json = None
    session.context_version = started + 1
    db.commit()
    db.refresh(session)
    assert session.summary_json is None
    assert session.summary_until_message_id is None

    stale = ConversationSummary(
        text="清除前生成的摘要不应复活",
        covered_from_message_id=1,
        covered_until_message_id=6,
    )
    ok = commit_summary_if_version_matches(
        db,
        session_id=session.id,
        started_version=started,  # pre-clear version
        summary=stale,
    )
    assert ok is False
    db.refresh(session)
    assert session.summary_json is None
    db.close()


@pytest.mark.asyncio
async def test_summary_reduces_tokens_vs_raw_history():
    _engine, SessionLocal = _engine_db()
    db = SessionLocal()
    session = _seed_long_session(db, pairs=8)
    settings = _settings(context_max_turns=2, context_token_budget=8000)

    # Baseline: all complete turns dumped as recent-style content.
    all_turns = load_complete_turns(db, session)
    raw_blob = json.dumps(
        [
            {"user": t.user_content, "assistant": t.assistant_content}
            for t in all_turns
        ],
        ensure_ascii=False,
    )
    raw_tokens = estimate_tokens(raw_blob)

    llm = AsyncMock()
    llm.chat_json = AsyncMock(
        return_value=LLMJsonResult(
            data={"summary": "多轮讨论番茄鸡蛋，保留两人份与家常做法背景。"}
        )
    )
    t0 = time.perf_counter()
    result = await maybe_refresh_conversation_summary(
        db,
        session,
        llm=llm,
        settings=settings,
        started_version=1,
        turns_token_budget=500,
    )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    assert result.committed is True
    db.refresh(session)

    ctx = assemble_context(
        db, session, current_message="还是两人份继续", settings=settings
    )
    payload = build_parse_user_payload(ctx)
    summarized_tokens = estimate_tokens(payload)

    assert summarized_tokens < raw_tokens
    assert result.elapsed_ms >= 0
    assert elapsed_ms < 5000  # fake LLM; just a sanity bound
    # Benefit log for local inspection when running with -s.
    print(
        f"summary_benefit raw_tokens={raw_tokens} "
        f"summarized_tokens={summarized_tokens} "
        f"saved={raw_tokens - summarized_tokens} "
        f"summary_elapsed_ms={result.elapsed_ms}"
    )
    db.close()


def test_chat_clear_context_clears_summary_via_api(client, monkeypatch):
    async def fake_run(self, msg, preferences=None, request_id="-", on_progress=None, **kwargs):
        return AgentOutcome(
            status="completed",
            recipe=Recipe(
                title="番茄炒蛋",
                summary="家常",
                prep_time_minutes=5,
                cook_time_minutes=8,
                servings=2,
                ingredients=["番茄", "鸡蛋"],
                steps=["炒"],
                tips=[],
                sources=[RecipeSource(title="示例", url="https://example.com/r")],
                confidence="medium",
            ),
            thinking="t",
            prompt_version="t",
            merged_state=SessionState(ingredients=[Ingredient(name="番茄")]),
            commit_state=True,
            update_last_recipe=True,
            intent="generate",
        )

    monkeypatch.setattr("app.agent.orchestrator.AgentOrchestrator.run", fake_run)

    async def no_summary(*_a, **_k):
        from app.services.conversation_summary import SummaryAttemptResult

        return SummaryAttemptResult(committed=False, skipped_reason="test")

    monkeypatch.setattr(
        "app.services.chat_service.maybe_refresh_conversation_summary",
        no_summary,
    )

    reg = client.post(
        "/api/v1/auth/register",
        json={
            "username": "sumclr",
            "password": "password123",
            "email": "sumclr@example.com",
        },
    )
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    chat = client.post(
        "/api/v1/chat", headers=headers, json={"message": "番茄鸡蛋"}
    )
    assert chat.status_code == 200
    session_id = chat.json()["session_id"]

    from app.db.session import get_db

    override = client.app.dependency_overrides[get_db]

    def _with_db(fn):
        gen = override()
        db = next(gen)
        try:
            return fn(db)
        finally:
            try:
                next(gen)
            except StopIteration:
                pass

    def _inject(db):
        row = db.get(SessionRecord, session_id)
        assert row is not None
        row.summary_json = ConversationSummary(
            text="应被清除的摘要",
            covered_until_message_id=1,
        ).model_dump_json()
        row.summary_until_message_id = 1
        row.summary_version = 2
        db.commit()

    _with_db(_inject)

    cleared = client.delete(f"/api/v1/sessions/{session_id}/context", headers=headers)
    assert cleared.status_code == 200

    def _assert_cleared(db):
        row2 = db.get(SessionRecord, session_id)
        assert row2 is not None
        assert row2.summary_json is None
        assert row2.summary_until_message_id is None
        assert (row2.summary_version or 0) == 0

    _with_db(_assert_cleared)
