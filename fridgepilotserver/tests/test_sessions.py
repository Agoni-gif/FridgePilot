from __future__ import annotations

from app.agent.orchestrator import AgentOutcome
from app.schemas.recipe import Recipe, RecipeSource


def _register(client, *, username="alice", password="password123", email="a@example.com"):
    return client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": password, "email": email},
    )


def _mock_run(monkeypatch, *, recipe: Recipe | None = None, message: str | None = None):
    status = "completed" if recipe else "error"
    text = message if message is not None else ("mocked" if not recipe else None)

    async def fake_run(self, msg, preferences=None, request_id="-", on_progress=None, **kwargs):
        if on_progress is not None:
            await on_progress("mock thinking: 识别到食材并准备搜索")
        return AgentOutcome(
            status=status,
            recipe=recipe,
            message=text,
            thinking="mock thinking: 识别到食材并准备搜索",
            search_used=bool(recipe),
            elapsed_ms=1,
            prompt_version="test",
        )

    monkeypatch.setattr("app.agent.orchestrator.AgentOrchestrator.run", fake_run)


def test_list_and_load_and_delete_sessions(client, monkeypatch):
    recipe = Recipe(
        title="番茄炒蛋",
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
    _mock_run(monkeypatch, recipe=recipe)

    alice = _register(client).json()
    headers = {"Authorization": f"Bearer {alice['access_token']}"}

    chat = client.post("/api/v1/chat", headers=headers, json={"message": "番茄鸡蛋怎么做"})
    assert chat.status_code == 200
    session_id = chat.json()["session_id"]

    listed = client.get("/api/v1/sessions", headers=headers)
    assert listed.status_code == 200
    sessions = listed.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["id"] == session_id
    assert "番茄鸡蛋" in sessions[0]["title"]

    history = client.get(f"/api/v1/sessions/{session_id}/messages", headers=headers)
    assert history.status_code == 200
    body = history.json()
    assert body["session_id"] == session_id
    assert len(body["messages"]) == 2
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][1]["recipe"]["title"] == "番茄炒蛋"

    deleted = client.delete(f"/api/v1/sessions/{session_id}", headers=headers)
    assert deleted.status_code == 204
    listed_after = client.get("/api/v1/sessions", headers=headers)
    assert listed_after.json()["sessions"] == []


def test_chat_stream_emits_thinking_and_done(client, monkeypatch):
    recipe = Recipe(
        title="番茄炒蛋",
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
    _mock_run(monkeypatch, recipe=recipe)

    alice = _register(client).json()
    headers = {"Authorization": f"Bearer {alice['access_token']}"}
    res = client.post(
        "/api/v1/chat/stream",
        headers=headers,
        json={"message": "番茄鸡蛋怎么做"},
    )
    assert res.status_code == 200
    assert "text/event-stream" in res.headers.get("content-type", "")

    events = []
    for block in res.text.split("\n\n"):
        line = next((part for part in block.splitlines() if part.startswith("data:")), None)
        if not line:
            continue
        import json

        events.append(json.loads(line.removeprefix("data:").strip()))

    assert any(e.get("type") == "thinking" and e.get("content") for e in events)
    done = next(e for e in events if e.get("type") == "done")
    assert done["data"]["status"] == "completed"
    assert done["data"]["recipe"]["title"] == "番茄炒蛋"
    assert done["data"]["thinking"]


def test_session_messages_forbidden_for_other_user(client, monkeypatch):
    _mock_run(monkeypatch, message="ok")

    alice = _register(client, username="alice", email="a@example.com").json()
    bob = _register(
        client, username="bob", password="password123", email="b@example.com"
    ).json()

    chat = client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {alice['access_token']}"},
        json={"message": "四菜一汤"},
    )
    session_id = chat.json()["session_id"]

    res = client.get(
        f"/api/v1/sessions/{session_id}/messages",
        headers={"Authorization": f"Bearer {bob['access_token']}"},
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "SESSION_NOT_FOUND"
