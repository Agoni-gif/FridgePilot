from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.orchestrator import AgentOrchestrator, AgentOutcome
from app.common.config import Settings
from app.db.models import MessageRecord, RecipeRecord, SessionRecord
from app.db.session import Base, get_db
from app.schemas.context import AssembledContext, SessionOverrides, SessionState
from app.schemas.recipe import Ingredient, Recipe, RecipeSource, SearchResult
from app.services.chat_service import ChatService, SessionConflictError
from app.services.conversation_context import (
    ContextBudgetExceededError,
    enforce_payload_budget,
    estimate_tokens,
    select_steps_for_focus,
    shrink_recipe_summary,
)


def _register(client, *, username="alice", password="password123", email="a@example.com"):
    return client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": password, "email": email},
    )


def _recipe(title: str = "番茄炒蛋", steps: list[str] | None = None) -> Recipe:
    return Recipe(
        title=title,
        summary="家常快手菜",
        prep_time_minutes=5,
        cook_time_minutes=8,
        servings=2,
        ingredients=["番茄", "鸡蛋"],
        steps=steps or ["打蛋", "炒熟"],
        tips=[],
        sources=[RecipeSource(title="示例", url="https://example.com/recipe")],
        confidence="medium",
    )


def test_delete_session_with_recipe_message_fk(client, monkeypatch):
    """Deleting a session that has recipes.assistant_message_id must not FK-fail."""

    async def fake_run(self, msg, preferences=None, request_id="-", on_progress=None, **kwargs):
        return AgentOutcome(
            status="completed",
            recipe=_recipe(),
            thinking="t",
            elapsed_ms=1,
            prompt_version="t",
            merged_state=SessionState(ingredients=[Ingredient(name="番茄")]),
            merged_overrides=SessionOverrides(),
            commit_state=True,
            update_last_recipe=True,
            intent="generate",
        )

    monkeypatch.setattr("app.agent.orchestrator.AgentOrchestrator.run", fake_run)

    # Force FK checks on the test app's sqlite connection(s).
    app = client.app
    override = app.dependency_overrides[get_db]
    gen = override()
    db = next(gen)
    try:
        db.execute(text("PRAGMA foreign_keys=ON"))
        db.commit()
        bind = db.get_bind()

        @event.listens_for(bind, "connect")
        def _fk(dbapi_connection, _connection_record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    finally:
        try:
            next(gen)
        except StopIteration:
            pass

    alice = _register(client, username="deluser", email="del@example.com").json()
    headers = {"Authorization": f"Bearer {alice['access_token']}"}
    chat = client.post("/api/v1/chat", headers=headers, json={"message": "番茄"})
    assert chat.status_code == 200
    session_id = chat.json()["session_id"]

    deleted = client.delete(f"/api/v1/sessions/{session_id}", headers=headers)
    assert deleted.status_code == 204
    listed = client.get("/api/v1/sessions", headers=headers)
    assert listed.json()["sessions"] == []


@pytest.mark.asyncio
async def test_summarize_does_not_auto_exclude_previous_on_revise():
    settings = Settings(
        llm_api_key="x",
        tavily_api_key="x",
        session_memory_enabled=True,
        database_url="sqlite://",
        app_env="test",
    )
    orch = AgentOrchestrator(settings, llm=AsyncMock(), tavily=AsyncMock())
    captured: dict = {}

    async def fake_chat_json(*, system, user, purpose="chat_json", **_kwargs):
        if purpose == "summarize":
            captured["user"] = json.loads(user)
            from app.providers.llm import LLMJsonResult

            return LLMJsonResult(
                data={
                    "title": "番茄炒蛋",
                    "summary": "家常",
                    "prep_time_minutes": 5,
                    "cook_time_minutes": 8,
                    "servings": 4,
                    "ingredients": ["番茄", "鸡蛋"],
                    "steps": ["打蛋", "炒熟"],
                    "tips": [],
                    "sources": [{"title": "示例", "url": "https://example.com/a"}],
                    "confidence": "medium",
                },
                reasoning="ok",
            )
        from app.providers.llm import LLMJsonResult

        return LLMJsonResult(data={}, reasoning=None)

    orch.llm.chat_json = fake_chat_json  # type: ignore[method-assign]
    # Whitelist needs the URL present in search results.
    results = [
        SearchResult(title="示例", url="https://example.com/a", content="番茄炒蛋")
    ]
    recipe = await orch._summarize(
        __import__("app.schemas.recipe", fromlist=["UserConstraints"]).UserConstraints(
            ingredients=[Ingredient(name="番茄"), Ingredient(name="鸡蛋")],
            servings=4,
        ),
        results,
        thinking_parts=[],
        target_recipe={"title": "番茄炒蛋", "summary": "旧版"},
        excluded_titles=[],  # no explicit swap
    )
    assert recipe is not None
    exclusions = captured["user"]["constraints"]["excluded_recipe_titles"]
    assert "番茄炒蛋" not in exclusions
    assert "previous_recipe_summary" in captured["user"]


@pytest.mark.asyncio
async def test_parse_invalid_does_not_fallback_to_empty_ops():
    settings = Settings(
        llm_api_key="x",
        tavily_api_key="x",
        session_memory_enabled=True,
        database_url="sqlite://",
        app_env="test",
    )
    orch = AgentOrchestrator(settings, llm=AsyncMock(), tavily=AsyncMock())
    from app.providers.llm import LLMJsonResult

    async def fake_chat_json(*, system, user, purpose="chat_json", **_kwargs):
        # Always return schema-invalid payload (ops is a string).
        return LLMJsonResult(
            data={"intent": "revise", "ops": "not-an-object", "search_queries": []},
            reasoning="bad",
        )

    orch.llm.chat_json = fake_chat_json  # type: ignore[method-assign]
    ctx = AssembledContext(current_message="不要辣")
    parsed = await orch._parse_contextual(ctx, thinking_parts=[])
    assert parsed is None

    # Full run should return error, not generate with empty ops.
    outcome = await orch.run(
        "不要辣",
        context=ctx,
        memory_enabled=True,
        request_id="t",
    )
    assert outcome.status == "error"
    assert outcome.commit_state is False


def test_commit_rejects_stale_version_atomically():
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
    db = SessionLocal()
    settings = Settings(
        llm_api_key="x",
        tavily_api_key="x",
        session_memory_enabled=True,
        database_url="sqlite://",
        app_env="test",
    )
    service = ChatService(settings, AgentOrchestrator(settings))
    session = SessionRecord(
        id="s1",
        user_id=None,
        context_version=1,
        active_request_id="req-a",
        active_request_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        state_json=SessionState(ingredients=[Ingredient(name="番茄")]).model_dump_json(),
    )
    db.add(session)
    db.commit()

    # Simulate clear_context bumping version while request still holds occupy id.
    session.context_version = 2
    session.active_request_id = "req-a"
    db.commit()

    outcome = AgentOutcome(
        status="completed",
        recipe=_recipe(),
        thinking="t",
        prompt_version="t",
        merged_state=SessionState(
            ingredients=[Ingredient(name="番茄")],
            servings=4,
        ),
        merged_overrides=SessionOverrides(),
        commit_state=True,
        update_last_recipe=True,
        intent="revise",
    )
    with pytest.raises(SessionConflictError):
        service._commit_outcome(
            db,
            session=session,
            message="改成四人份",
            outcome=outcome,
            request_id="req-a",
            started_version=1,  # stale
            occupy_id="req-a",
        )

    db.refresh(session)
    assert session.context_version == 2
    assert db.query(MessageRecord).filter(MessageRecord.session_id == "s1").count() == 0
    assert db.query(RecipeRecord).filter(RecipeRecord.session_id == "s1").count() == 0
    db.close()
    Base.metadata.drop_all(bind=engine)


def test_select_steps_includes_step_sixteen():
    steps = [f"步骤{i}" for i in range(1, 21)]
    selected_cn = select_steps_for_focus(steps, "第十六步是什么意思")
    selected_num = select_steps_for_focus(steps, "第16步是什么意思")
    assert any("步骤16" in s or "第16步" in s for s in selected_cn)
    assert any("步骤16" in s or "第16步" in s for s in selected_num)


def test_shrink_keeps_focused_step_over_long_neighbor():
    """Long neighboring steps must be dropped before the referenced step."""
    summary = {
        "id": 1,
        "title": "大菜",
        "summary": "摘要",
        "ingredients": ["盐"],
        "steps": [
            "第15步：" + ("很长的前一步说明" * 40),
            "第16步：这里是用户真正在问的步骤",
            "第17步：" + ("很长的后一步说明" * 40),
        ],
        "servings": 2,
        "sources": [],
    }
    # Budget large enough for focus step + identity, too small for all three.
    shrunk = shrink_recipe_summary(summary, token_budget=120, focus_step_index=16)
    steps = shrunk.get("steps") or []
    assert any("第16步" in s for s in steps)
    assert not any("第15步" in s for s in steps)
    assert not any("第17步" in s for s in steps)


def test_payload_budget_trims_recipe_and_turns():
    steps = [f"很长的烹饪步骤内容" * 20 + str(i) for i in range(30)]
    big_recipe = {
        "id": 1,
        "title": "大菜",
        "summary": "摘要" * 50,
        "ingredients": [f"食材{i}" for i in range(20)],
        "steps": steps,
        "servings": 2,
        "sources": [{"title": "s", "url": "https://example.com/" + ("x" * 200)}],
    }
    shrunk = shrink_recipe_summary(big_recipe, token_budget=200)
    assert estimate_tokens(json.dumps(shrunk, ensure_ascii=False)) <= 220
    assert len(shrunk.get("steps") or []) < len(steps)

    ctx = AssembledContext(
        current_message="继续",
        recent_turns=[],
        session_state=SessionState(ingredients=[Ingredient(name="番茄")]),
        last_recipe=big_recipe,
    )
    from app.schemas.context import RecentTurn

    ctx.recent_turns = [
        RecentTurn(role="user", content="用户消息" * 80),
        RecentTurn(role="assistant", content="助手回复" * 80),
    ] * 6
    enforced = enforce_payload_budget(ctx, token_budget=300)
    payload = json.dumps(
        {
            "current_message": enforced.current_message,
            "recent_turns": [t.model_dump() for t in enforced.recent_turns],
            "session_state": enforced.session_state.model_dump()
            if enforced.session_state
            else None,
            "last_recipe": enforced.last_recipe,
        },
        ensure_ascii=False,
    )
    assert estimate_tokens(payload) <= 360


def test_enforce_payload_budget_raises_when_hard_fields_overflow():
    """Legal-length hard fields that still exceed budget must not be returned silently."""
    # Schema caps: 30 ingredients × max name/quantity, 10 dietary — still oversized.
    huge_ingredients = [
        Ingredient(name=("食材名" + str(i))[:50].ljust(50, "甲"), quantity="一" * 50)
        for i in range(30)
    ]
    huge_restrictions = [("忌口说明" + str(i)).ljust(40, "辣") for i in range(10)]
    ctx = AssembledContext(
        current_message=("请继续根据以上全部条件帮我做菜，不要遗漏。" * 20)[:1000],
        recent_turns=[],
        session_state=SessionState(
            ingredients=huge_ingredients,
            dietary_restrictions=huge_restrictions,
            meal="晚饭",
            cuisine="家常",
            servings=4,
            max_time_minutes=30,
        ),
        last_recipe=None,
    )
    hard = estimate_tokens(
        json.dumps(
            {
                "current_message": ctx.current_message,
                "session_state": ctx.session_state.model_dump() if ctx.session_state else None,
                "session_overrides": ctx.session_overrides.model_dump(),
            },
            ensure_ascii=False,
        )
    )
    assert hard > 2000
    with pytest.raises(ContextBudgetExceededError):
        enforce_payload_budget(ctx, token_budget=2000)
