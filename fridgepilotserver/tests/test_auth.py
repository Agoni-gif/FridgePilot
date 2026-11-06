from __future__ import annotations


def _register(client, username="alice", password="password123", email="alice@example.com"):
    return client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": password, "email": email},
    )


def test_register_and_me(client):
    res = _register(client)
    assert res.status_code == 200
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["username"] == "alice"
    assert body["access_token"]

    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["username"] == "alice"


def test_register_duplicate_username(client):
    assert _register(client).status_code == 200
    again = _register(client, email="other@example.com")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "USERNAME_TAKEN"


def test_login_with_username_or_email(client):
    _register(client)
    by_user = client.post(
        "/api/v1/auth/login",
        json={"account": "alice", "password": "password123"},
    )
    assert by_user.status_code == 200
    by_email = client.post(
        "/api/v1/auth/login",
        json={"account": "alice@example.com", "password": "password123"},
    )
    assert by_email.status_code == 200


def test_login_wrong_password(client):
    _register(client)
    res = client.post(
        "/api/v1/auth/login",
        json={"account": "alice", "password": "wrong-password"},
    )
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_chat_requires_auth(client):
    res = client.post("/api/v1/chat", json={"message": "番茄鸡蛋"})
    assert res.status_code == 401


def test_chat_session_owned_by_user(client, monkeypatch):
    from app.agent.orchestrator import AgentOutcome

    async def fake_run(self, message, preferences, request_id="-"):
        return AgentOutcome(
            status="error",
            recipe=None,
            message="mocked",
            search_used=False,
            elapsed_ms=1,
            prompt_version="test",
        )

    monkeypatch.setattr(
        "app.agent.orchestrator.AgentOrchestrator.run",
        fake_run,
    )

    alice = _register(client, username="alice", email="a@example.com").json()
    bob = _register(
        client, username="bob", password="password123", email="b@example.com"
    ).json()

    chat = client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {alice['access_token']}"},
        json={"message": "番茄鸡蛋"},
    )
    assert chat.status_code == 200
    session_id = chat.json()["session_id"]

    hijack = client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {bob['access_token']}"},
        json={"message": "继续", "session_id": session_id},
    )
    assert hijack.status_code == 403
    assert hijack.json()["error"]["code"] == "SESSION_FORBIDDEN"


def test_phone_and_oauth_reserved(client):
    phone = client.post("/api/v1/auth/phone/send-code", json={"phone": "13800138000"})
    assert phone.status_code == 501
    oauth = client.get("/api/v1/auth/oauth/github/start")
    assert oauth.status_code == 501
