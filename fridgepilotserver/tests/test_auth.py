from __future__ import annotations

from app.services.captcha_service import CaptchaError, CaptchaService, TOLERANCE_PX, get_captcha_service


def _register(client, username="alice", password="password123", email="alice@example.com"):
    return client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": password, "email": email},
    )


def _captcha_offset(captcha_id: str) -> int:
    """测试专用：读取内存中的偏移，不暴露生产 API。"""
    svc = get_captcha_service()
    with svc._lock:
        challenge = svc._challenges.get(captcha_id)
        assert challenge is not None
        return challenge.offset_x


def _login_payload(client, account: str, password: str) -> dict:
    challenge = client.get("/api/v1/auth/captcha").json()
    offset = _captcha_offset(challenge["captcha_id"])
    return {
        "account": account,
        "password": password,
        "captcha_id": challenge["captcha_id"],
        "captcha_x": float(offset),
    }


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


def test_captcha_challenge_shape(client):
    res = client.get("/api/v1/auth/captcha")
    assert res.status_code == 200
    body = res.json()
    assert body["captcha_id"]
    assert body["bg_image"].startswith("data:image/png;base64,")
    assert body["piece_image"].startswith("data:image/png;base64,")
    assert body["bg_width"] == 320
    assert body["piece_size"] == 60
    assert body["piece_pad"] == 10


def test_login_requires_captcha(client):
    _register(client)
    res = client.post(
        "/api/v1/auth/login",
        json={"account": "alice", "password": "password123"},
    )
    assert res.status_code == 422


def test_login_with_username_or_email(client):
    _register(client)
    by_user = client.post(
        "/api/v1/auth/login",
        json=_login_payload(client, "alice", "password123"),
    )
    assert by_user.status_code == 200
    by_email = client.post(
        "/api/v1/auth/login",
        json=_login_payload(client, "alice@example.com", "password123"),
    )
    assert by_email.status_code == 200


def test_login_wrong_password(client):
    _register(client)
    res = client.post(
        "/api/v1/auth/login",
        json=_login_payload(client, "alice", "wrong-password"),
    )
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_wrong_captcha(client):
    _register(client)
    challenge = client.get("/api/v1/auth/captcha").json()
    res = client.post(
        "/api/v1/auth/login",
        json={
            "account": "alice",
            "password": "password123",
            "captcha_id": challenge["captcha_id"],
            "captcha_x": 0,
        },
    )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "CAPTCHA_FAILED"


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


def test_captcha_tolerance_and_nan():
    svc = CaptchaService()
    assert svc._bg_paths, "backend assets/captcha must contain backgrounds"
    data = svc.create(client_key="tol-test")
    cid = data["captcha_id"]
    with svc._lock:
        truth = svc._challenges[cid].offset_x

    svc.check(cid, float(truth + TOLERANCE_PX), client_key="tol-ok")
    svc.verify_and_consume(cid, float(truth + TOLERANCE_PX), client_key="tol-ok")

    data2 = svc.create(client_key="tol-test-2")
    cid2 = data2["captcha_id"]
    with svc._lock:
        truth2 = svc._challenges[cid2].offset_x
    try:
        svc.check(cid2, float(truth2 + TOLERANCE_PX + 1), client_key="tol-bad")
        assert False, "expected mismatch"
    except CaptchaError as exc:
        assert exc.code == "CAPTCHA_FAILED"

    data3 = svc.create(client_key="tol-test-3")
    try:
        svc.check(data3["captcha_id"], float("nan"), client_key="nan-test")
        assert False, "expected nan reject"
    except CaptchaError as exc:
        assert exc.code == "CAPTCHA_FAILED"


def test_captcha_verify_endpoint(client):
    challenge = client.get("/api/v1/auth/captcha").json()
    offset = _captcha_offset(challenge["captcha_id"])
    bad = client.post(
        "/api/v1/auth/captcha/verify",
        json={"captcha_id": challenge["captcha_id"], "captcha_x": 0},
    )
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "CAPTCHA_FAILED"

    challenge = client.get("/api/v1/auth/captcha").json()
    offset = _captcha_offset(challenge["captcha_id"])
    ok = client.post(
        "/api/v1/auth/captcha/verify",
        json={"captcha_id": challenge["captcha_id"], "captcha_x": float(offset)},
    )
    assert ok.status_code == 200
    assert ok.json()["ok"] is True


def test_captcha_missing_assets_message():
    svc = CaptchaService()
    svc._bg_paths = []
    try:
        svc.create(client_key="missing-assets")
        assert False, "expected missing assets"
    except CaptchaError as exc:
        assert exc.code == "CAPTCHA_ASSET_MISSING"
        assert "app/assets/captcha" in exc.message.replace("\\", "/")
