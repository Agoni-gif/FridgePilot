from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.agent.orchestrator import AgentOutcome
from app.db.models import SessionRecord
from app.db.session import get_db
from app.schemas.context import SessionOverrides, SessionState
from app.schemas.recipe import Ingredient, Recipe, RecipeSource


def _register(client, *, username="alice", password="password123", email="a@example.com"):
    return client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": password, "email": email},
    )


def _recipe(title: str = "番茄炒蛋") -> Recipe:
    return Recipe(
        title=title,
        summary="家常快手菜",
        prep_time_minutes=5,
        cook_time_minutes=8,
        servings=2,
        ingredients=["番茄", "鸡蛋"],
        steps=["打蛋", "炒熟"],
        tips=[],
        sources=[RecipeSource(title="示例", url="https://example.com/recipe")],
        confidence="medium",
    )


def _mock_run(monkeypatch, outcome_factory):
    async def fake_run(self, msg, preferences=None, request_id="-", on_progress=None, **kwargs):
        if on_progress is not None:
            await on_progress("mock thinking")
        return outcome_factory(msg, kwargs.get("context"), preferences, kwargs.get("preference_patch"))

    monkeypatch.setattr("app.agent.orchestrator.AgentOrchestrator.run", fake_run)


def test_unknown_session_id_returns_404(client, monkeypatch):
    _mock_run(
        monkeypatch,
        lambda *_args: AgentOutcome(status="completed", recipe=_recipe(), prompt_version="t"),
    )
    alice = _register(client).json()
    headers = {"Authorization": f"Bearer {alice['access_token']}"}
    res = client.post(
        "/api/v1/chat",
        headers=headers,
        json={"message": "你好", "session_id": "does-not-exist"},
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_context_get_and_clear(client, monkeypatch):
    state = SessionState(
        ingredients=[Ingredient(name="番茄"), Ingredient(name="鸡蛋")],
        servings=2,
        dietary_restrictions=["不辣"],
    )

    def factory(msg, context, preferences, patch):
        return AgentOutcome(
            status="completed",
            recipe=_recipe(),
            thinking="t",
            search_used=True,
            elapsed_ms=1,
            prompt_version="t",
            merged_state=state,
            merged_overrides=SessionOverrides(set_fields={"servings": 2}),
            commit_state=True,
            update_last_recipe=True,
            intent="generate",
        )

    _mock_run(monkeypatch, factory)
    alice = _register(client).json()
    headers = {"Authorization": f"Bearer {alice['access_token']}"}

    chat = client.post("/api/v1/chat", headers=headers, json={"message": "番茄鸡蛋两人份"})
    assert chat.status_code == 200
    body = chat.json()
    session_id = body["session_id"]
    assert body["context"]["state"]["servings"] == 2
    assert [i["name"] for i in body["context"]["state"]["ingredients"]] == ["番茄", "鸡蛋"]

    got = client.get(f"/api/v1/sessions/{session_id}/context", headers=headers)
    assert got.status_code == 200
    assert got.json()["state"]["servings"] == 2
    version_before = got.json()["context_version"]

    cleared = client.delete(f"/api/v1/sessions/{session_id}/context", headers=headers)
    assert cleared.status_code == 200
    cleared_body = cleared.json()
    assert cleared_body["state"] is None
    assert cleared_body["context_version"] == version_before + 1
    assert cleared_body["context_start_message_id"] is not None

    # History still readable
    history = client.get(f"/api/v1/sessions/{session_id}/messages", headers=headers)
    assert history.status_code == 200
    assert len(history.json()["messages"]) == 2


def test_empty_preferences_do_not_wipe_state(client, monkeypatch):
    calls: list = []

    def factory(msg, context, preferences, patch):
        calls.append((preferences, context.session_state if context else None))
        base = context.session_state if context and context.session_state else SessionState(
            ingredients=[Ingredient(name="番茄")],
            servings=2,
        )
        # Mark session-owned fields so persistable_session_state keeps them.
        overrides = SessionOverrides(
            set_fields={
                "servings": base.servings,
                "ingredients": [i.model_dump() for i in base.ingredients],
            }
        )
        return AgentOutcome(
            status="completed",
            recipe=_recipe(),
            thinking="t",
            elapsed_ms=1,
            prompt_version="t",
            merged_state=base,
            merged_overrides=overrides,
            commit_state=True,
            update_last_recipe=True,
            intent="generate",
        )

    _mock_run(monkeypatch, factory)
    alice = _register(client).json()
    headers = {"Authorization": f"Bearer {alice['access_token']}"}

    first = client.post(
        "/api/v1/chat",
        headers=headers,
        json={"message": "番茄两人份"},
    )
    session_id = first.json()["session_id"]

    second = client.post(
        "/api/v1/chat",
        headers=headers,
        json={
            "message": "换一道",
            "session_id": session_id,
            "preferences": {
                "max_time_minutes": None,
                "servings": None,
                "dietary_restrictions": [],
            },
        },
    )
    assert second.status_code == 200
    assert second.json()["context"]["state"]["servings"] == 2
    assert [i["name"] for i in second.json()["context"]["state"]["ingredients"]] == ["番茄"]


def test_preference_patch_clear_time(client, monkeypatch):
    def factory(msg, context, preferences, patch):
        from app.services.state_merge import apply_state_ops, preference_patch_to_ops

        base = context.session_state if context and context.session_state else SessionState(
            ingredients=[Ingredient(name="番茄")],
            max_time_minutes=20,
            servings=2,
        )
        merge = apply_state_ops(base, None, preference_patch_to_ops(patch))
        return AgentOutcome(
            status="completed",
            recipe=_recipe(),
            thinking="t",
            elapsed_ms=1,
            prompt_version="t",
            merged_state=merge.state,
            merged_overrides=merge.overrides,
            commit_state=True,
            update_last_recipe=True,
            intent="revise",
        )

    _mock_run(monkeypatch, factory)
    alice = _register(client).json()
    headers = {"Authorization": f"Bearer {alice['access_token']}"}
    first = client.post("/api/v1/chat", headers=headers, json={"message": "番茄二十分钟"})
    session_id = first.json()["session_id"]
    # Seed time via second call with patch
    second = client.post(
        "/api/v1/chat",
        headers=headers,
        json={
            "message": "不限时间了",
            "session_id": session_id,
            "preference_patch": {"clear": ["max_time_minutes"], "set": {}},
        },
    )
    assert second.status_code == 200
    assert second.json()["context"]["state"]["max_time_minutes"] is None


def test_clarification_does_not_commit_state(client, monkeypatch):
    def factory(msg, context, preferences, patch):
        return AgentOutcome(
            status="clarification",
            message="请问你有哪些食材？",
            thinking="t",
            elapsed_ms=1,
            prompt_version="t",
            intent="clarify",
            commit_state=False,
        )

    _mock_run(monkeypatch, factory)
    alice = _register(client).json()
    headers = {"Authorization": f"Bearer {alice['access_token']}"}
    res = client.post("/api/v1/chat", headers=headers, json={"message": "换一道"})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "clarification"
    assert body["recipe"] is None
    assert body["message"] == "请问你有哪些食材？"
    assert body["context"]["state"] is None


def test_session_busy_returns_409(client, monkeypatch):
    _mock_run(
        monkeypatch,
        lambda *_a: AgentOutcome(status="completed", recipe=_recipe(), prompt_version="t"),
    )
    alice = _register(client).json()
    headers = {"Authorization": f"Bearer {alice['access_token']}"}
    first = client.post("/api/v1/chat", headers=headers, json={"message": "番茄"})
    session_id = first.json()["session_id"]

    # Manually mark session busy via DB override used by the test app.
    # Access the same override session factory through a chat that holds lease:
    from app.main import create_app

    app = client.app
    override = app.dependency_overrides.get(get_db)
    assert override is not None
    gen = override()
    db = next(gen)
    try:
        row = db.get(SessionRecord, session_id)
        assert row is not None
        row.active_request_id = "other-request"
        row.active_request_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        db.commit()
    finally:
        try:
            next(gen)
        except StopIteration:
            pass

    busy = client.post(
        "/api/v1/chat",
        headers=headers,
        json={"message": "再来", "session_id": session_id},
    )
    assert busy.status_code == 409
    assert busy.json()["error"]["code"] == "SESSION_BUSY"


def test_recipe_linked_to_assistant_message(client, monkeypatch):
    def factory(msg, context, preferences, patch):
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

    _mock_run(monkeypatch, factory)
    alice = _register(client).json()
    headers = {"Authorization": f"Bearer {alice['access_token']}"}
    chat = client.post("/api/v1/chat", headers=headers, json={"message": "番茄"})
    session_id = chat.json()["session_id"]
    history = client.get(f"/api/v1/sessions/{session_id}/messages", headers=headers).json()
    assistant = history["messages"][1]
    assert assistant["recipe"]["title"] == "番茄炒蛋"

    ctx = client.get(f"/api/v1/sessions/{session_id}/context", headers=headers).json()
    assert ctx["state"]["last_recipe_id"] is not None


def test_other_user_cannot_clear_context(client, monkeypatch):
    def factory(msg, context, preferences, patch):
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

    _mock_run(monkeypatch, factory)
    alice = _register(client, username="alice2", email="a2@example.com").json()
    bob = _register(client, username="bob2", email="b2@example.com").json()
    chat = client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {alice['access_token']}"},
        json={"message": "番茄"},
    )
    session_id = chat.json()["session_id"]
    res = client.delete(
        f"/api/v1/sessions/{session_id}/context",
        headers={"Authorization": f"Bearer {bob['access_token']}"},
    )
    assert res.status_code == 404
