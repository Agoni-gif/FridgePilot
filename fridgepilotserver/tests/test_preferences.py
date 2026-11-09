from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.orchestrator import AgentOrchestrator, AgentOutcome
from app.common.config import Settings
from app.db.models import User, UserPreferenceRecord
from app.db.session import Base
from app.schemas.context import SessionOverrides, SessionState, StateOps
from app.schemas.context import DietaryOps, IngredientOps
from app.schemas.preferences import PreferenceValues, UserPreferencesPatch
from app.schemas.recipe import Ingredient, Recipe, RecipeSource, SearchResult, UserConstraints
from app.services.preference_service import PreferenceConflictError, PreferenceService
from app.services.state_merge import (
    apply_long_term_defaults,
    detect_allergy_conflict,
    empty_overrides,
    persistable_session_state,
    recipe_conflicts_with_allergies,
)


def _register(client, *, username="alice", password="password123", email="a@example.com"):
    return client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": password, "email": email},
    )


def _recipe() -> Recipe:
    return Recipe(
        title="番茄炒蛋",
        summary="家常",
        prep_time_minutes=5,
        cook_time_minutes=8,
        servings=2,
        ingredients=["番茄", "鸡蛋"],
        steps=["打蛋", "炒熟"],
        tips=[],
        sources=[RecipeSource(title="示例", url="https://example.com/r")],
        confidence="medium",
    )


def test_preferences_crud_and_version_conflict(client):
    alice = _register(client).json()
    headers = {"Authorization": f"Bearer {alice['access_token']}"}

    empty = client.get("/api/v1/me/preferences", headers=headers)
    assert empty.status_code == 200
    body = empty.json()
    assert body["exists"] is False
    assert body["enabled"] is False
    assert body["version"] == 0

    created = client.patch(
        "/api/v1/me/preferences",
        headers=headers,
        json={
            "version": 0,
            "enabled": True,
            "set": {
                "servings": 2,
                "max_time_minutes": 20,
                "cuisine": "家常",
                "dietary_restrictions": ["不辣"],
                "allergies": ["香菜"],
            },
            "clear": [],
        },
    )
    assert created.status_code == 200
    assert created.json()["version"] == 1
    assert created.json()["enabled"] is True
    assert created.json()["preferences"]["allergies"] == ["香菜"]

    conflict = client.patch(
        "/api/v1/me/preferences",
        headers=headers,
        json={"version": 0, "enabled": False, "set": {}, "clear": []},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "PREFERENCE_VERSION_CONFLICT"

    updated = client.patch(
        "/api/v1/me/preferences",
        headers=headers,
        json={
            "version": 1,
            "set": {"servings": 4},
            "clear": ["max_time_minutes"],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["preferences"]["servings"] == 4
    assert updated.json()["preferences"]["max_time_minutes"] is None

    deleted = client.delete("/api/v1/me/preferences", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["exists"] is False
    # Idempotent delete
    again = client.delete("/api/v1/me/preferences", headers=headers)
    assert again.status_code == 200


def test_preferences_are_user_isolated(client):
    alice = _register(client, username="pref_a", email="pa@example.com").json()
    bob = _register(client, username="pref_b", email="pb@example.com").json()
    a_headers = {"Authorization": f"Bearer {alice['access_token']}"}
    b_headers = {"Authorization": f"Bearer {bob['access_token']}"}

    client.patch(
        "/api/v1/me/preferences",
        headers=a_headers,
        json={
            "version": 0,
            "enabled": True,
            "set": {"servings": 2, "allergies": ["花生"]},
            "clear": [],
        },
    )
    bob_view = client.get("/api/v1/me/preferences", headers=b_headers).json()
    assert bob_view["exists"] is False
    assert bob_view["preferences"]["servings"] is None


def test_disabled_preferences_not_applied_in_chat(client, monkeypatch):
    captured = {}

    async def fake_run(self, msg, preferences=None, request_id="-", on_progress=None, **kwargs):
        ctx = kwargs.get("context")
        captured["defaults"] = ctx.user_defaults if ctx else None
        captured["servings"] = ctx.session_state.servings if ctx and ctx.session_state else None
        return AgentOutcome(
            status="completed",
            recipe=_recipe(),
            thinking="t",
            prompt_version="t",
            merged_state=SessionState(ingredients=[Ingredient(name="番茄")], servings=2),
            merged_overrides=SessionOverrides(set_fields={"ingredients": []}),
            commit_state=True,
            update_last_recipe=True,
            intent="generate",
        )

    monkeypatch.setattr("app.agent.orchestrator.AgentOrchestrator.run", fake_run)
    alice = _register(client, username="pref_dis", email="dis@example.com").json()
    headers = {"Authorization": f"Bearer {alice['access_token']}"}
    client.patch(
        "/api/v1/me/preferences",
        headers=headers,
        json={
            "version": 0,
            "enabled": False,
            "set": {"servings": 8},
            "clear": [],
        },
    )
    res = client.post("/api/v1/chat", headers=headers, json={"message": "番茄怎么做"})
    assert res.status_code == 200
    assert not captured["defaults"]


def test_enabled_preferences_seed_session_and_temp_override(client, monkeypatch):
    captured = {}

    async def fake_run(self, msg, preferences=None, request_id="-", on_progress=None, **kwargs):
        ctx = kwargs.get("context")
        captured["defaults"] = dict(ctx.user_defaults) if ctx else None
        captured["state_servings"] = (
            ctx.session_state.servings if ctx and ctx.session_state else None
        )
        # Simulate user saying 改成四人份 via ops already applied by orchestrator;
        # here we just assert seeding happened before run.
        return AgentOutcome(
            status="completed",
            recipe=_recipe(),
            thinking="t",
            prompt_version="t",
            merged_state=SessionState(
                ingredients=[Ingredient(name="番茄")],
                servings=4,
                dietary_restrictions=["不辣"],
            ),
            merged_overrides=SessionOverrides(
                set_fields={"servings": 4, "ingredients": []}
            ),
            commit_state=True,
            update_last_recipe=True,
            intent="revise",
        )

    monkeypatch.setattr("app.agent.orchestrator.AgentOrchestrator.run", fake_run)
    alice = _register(client, username="pref_en", email="en@example.com").json()
    headers = {"Authorization": f"Bearer {alice['access_token']}"}
    client.patch(
        "/api/v1/me/preferences",
        headers=headers,
        json={
            "version": 0,
            "enabled": True,
            "set": {
                "servings": 2,
                "dietary_restrictions": ["不辣"],
                "allergies": ["香菜"],
            },
            "clear": [],
        },
    )
    res = client.post("/api/v1/chat", headers=headers, json={"message": "番茄两人份"})
    assert res.status_code == 200
    assert captured["defaults"]["servings"] == 2
    assert captured["defaults"]["allergies"] == ["香菜"]
    assert captured["state_servings"] == 2
    assert res.json()["context"]["long_term_preferences_applied"] is True

    # After explicit servings override persisted in overrides, clear context then
    # defaults can apply again on a fresh task.
    session_id = res.json()["session_id"]
    cleared = client.delete(f"/api/v1/sessions/{session_id}/context", headers=headers)
    assert cleared.status_code == 200
    assert cleared.json()["long_term_preferences_applied"] is True
    assert cleared.json()["state"]["servings"] == 2


def test_deleted_preferences_stop_applying(client, monkeypatch):
    captured = {}

    async def fake_run(self, msg, preferences=None, request_id="-", on_progress=None, **kwargs):
        ctx = kwargs.get("context")
        captured["defaults"] = ctx.user_defaults if ctx else None
        return AgentOutcome(
            status="completed",
            recipe=_recipe(),
            thinking="t",
            prompt_version="t",
            merged_state=SessionState(ingredients=[Ingredient(name="番茄")]),
            merged_overrides=SessionOverrides(),
            commit_state=True,
            update_last_recipe=True,
            intent="generate",
        )

    monkeypatch.setattr("app.agent.orchestrator.AgentOrchestrator.run", fake_run)
    alice = _register(client, username="pref_del", email="delp@example.com").json()
    headers = {"Authorization": f"Bearer {alice['access_token']}"}
    client.patch(
        "/api/v1/me/preferences",
        headers=headers,
        json={
            "version": 0,
            "enabled": True,
            "set": {"servings": 2},
            "clear": [],
        },
    )
    client.delete("/api/v1/me/preferences", headers=headers)
    res = client.post("/api/v1/chat", headers=headers, json={"message": "番茄"})
    assert res.status_code == 200
    assert not captured["defaults"]
    assert res.json()["context"]["long_term_preferences_applied"] is False


def test_allergy_conflict_detection():
    q = detect_allergy_conflict(
        ["香菜"],
        StateOps(dietary_restrictions=DietaryOps(add=["这次可以放香菜"])),
    )
    assert q and "香菜" in q
    assert "破例" not in q
    assert "我的做饭偏好" in q

    q2 = detect_allergy_conflict(
        ["花生"],
        StateOps(ingredients=IngredientOps(add=[Ingredient(name="花生酱")])),
    )
    assert q2 and "花生" in q2
    assert "移除冲突食材" in q2

    q3 = detect_allergy_conflict(
        ["香菜"],
        StateOps(dietary_restrictions=DietaryOps(add=["不吃香菜"])),
    )
    assert q3 is None


def test_long_term_defaults_respect_clears_and_persistable():
    defaults = PreferenceValues(servings=2, max_time_minutes=20, dietary_restrictions=["不辣"])
    seeded = apply_long_term_defaults(None, empty_overrides(), defaults)
    assert seeded.servings == 2
    assert seeded.max_time_minutes == 20

    cleared = apply_long_term_defaults(
        SessionState(),
        SessionOverrides(cleared_fields=["max_time_minutes"]),
        defaults,
    )
    assert cleared.servings == 2
    assert cleared.max_time_minutes is None

    after = SessionState(
        ingredients=[Ingredient(name="番茄")],
        servings=2,
        max_time_minutes=20,
        dietary_restrictions=["不辣"],
    )
    overrides = SessionOverrides(set_fields={"ingredients": []})
    persisted = persistable_session_state(None, after, overrides)
    assert persisted.ingredients[0].name == "番茄"
    assert persisted.servings is None  # default-only, not session-owned
    assert persisted.max_time_minutes is None
    assert persisted.dietary_restrictions == []


def test_preference_atomic_version_blocks_concurrent_overwrite():
    """Two sessions both read version 1; only the first UPDATE may succeed."""
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
    setup = SessionLocal()
    setup.add(
        User(
            id="u1",
            username="pref_race",
            email="pref_race@example.com",
            password_hash="x",
        )
    )
    setup.add(
        UserPreferenceRecord(
            user_id="u1",
            enabled=1,
            preferences_json=PreferenceValues(servings=2).model_dump_json(),
            version=1,
            updated_at=datetime.now(timezone.utc),
        )
    )
    setup.commit()
    setup.close()

    svc = PreferenceService()
    db_a = SessionLocal()
    db_b = SessionLocal()
    # Both observe version 1 before either writes.
    assert db_a.get(UserPreferenceRecord, "u1").version == 1
    assert db_b.get(UserPreferenceRecord, "u1").version == 1

    first = svc.patch(
        db_a,
        user_id="u1",
        body=UserPreferencesPatch(version=1, set={"servings": 3}, clear=[]),
    )
    assert first.version == 2
    assert first.preferences.servings == 3

    with pytest.raises(PreferenceConflictError):
        svc.patch(
            db_b,
            user_id="u1",
            body=UserPreferencesPatch(version=1, set={"servings": 8}, clear=[]),
        )

    verify = SessionLocal()
    row = verify.get(UserPreferenceRecord, "u1")
    assert row is not None
    assert row.version == 2
    assert PreferenceValues.model_validate_json(row.preferences_json).servings == 3
    verify.close()
    db_a.close()
    db_b.close()


def test_recipe_conflicts_with_allergies_detects_peanut():
    safe = _recipe()
    assert recipe_conflicts_with_allergies(safe, ["花生"]) is None

    bad = Recipe(
        title="宫保鸡丁",
        summary="含花生碎",
        prep_time_minutes=10,
        cook_time_minutes=15,
        servings=2,
        ingredients=["鸡胸肉", "花生"],
        steps=["炒花生", "下鸡丁"],
        tips=[],
        sources=[RecipeSource(title="示例", url="https://example.com/r")],
        confidence="medium",
    )
    assert recipe_conflicts_with_allergies(bad, ["花生"]) == "花生"


def test_allergies_flow_into_constraints_and_queries():
    settings = Settings(
        llm_api_key="x",
        tavily_api_key="x",
        session_memory_enabled=True,
        database_url="sqlite://",
        app_env="test",
    )
    orch = AgentOrchestrator(settings, llm=AsyncMock(), tavily=AsyncMock())
    state = SessionState(ingredients=[Ingredient(name="番茄"), Ingredient(name="鸡蛋")])
    constraints = orch._state_to_constraints(state, [], allergies=["花生"])
    assert constraints.allergies == ["花生"]
    queries = orch._build_queries(constraints, state)
    assert queries
    assert any("不含花生" in q for q in queries)


@pytest.mark.asyncio
async def test_search_and_summarize_rejects_allergen_recipe():
    settings = Settings(
        llm_api_key="x",
        tavily_api_key="x",
        session_memory_enabled=True,
        database_url="sqlite://",
        app_env="test",
    )
    orch = AgentOrchestrator(settings, llm=AsyncMock(), tavily=AsyncMock())
    allergen_recipe = Recipe(
        title="花生酱凉面",
        summary="花生酱拌面",
        prep_time_minutes=5,
        cook_time_minutes=5,
        servings=1,
        ingredients=["面条", "花生酱"],
        steps=["拌匀"],
        tips=[],
        sources=[RecipeSource(title="示例", url="https://example.com/r")],
        confidence="medium",
    )

    async def fake_search_all(_queries):
        return [
            SearchResult(
                title="花生酱凉面",
                url="https://example.com/r",
                content="花生酱",
                score=0.9,
            )
        ]

    async def fake_summarize(*_args, **_kwargs):
        return allergen_recipe

    orch._search_all = fake_search_all  # type: ignore[method-assign]
    orch._summarize = fake_summarize  # type: ignore[method-assign]

    constraints = UserConstraints(
        ingredients=[Ingredient(name="面条")],
        allergies=["花生"],
        search_queries=["凉面 做法 不含花生"],
    )
    outcome = await orch._search_and_summarize(
        constraints=constraints,
        queries=["凉面 做法 不含花生"],
        ingredient_names=["面条"],
        merged_state=SessionState(ingredients=[Ingredient(name="面条")]),
        merged_overrides=SessionOverrides(),
        intent="generate",
        commit_state=True,
        request_id="allergy-test",
        on_progress=None,
        started=__import__("time").time(),
        thinking_parts=[],
        target_recipe=None,
        excluded_titles=[],
    )
    assert outcome.status == "insufficient_sources"
    assert outcome.recipe is None
    assert outcome.update_last_recipe is False
    assert "花生" in (outcome.message or "")
