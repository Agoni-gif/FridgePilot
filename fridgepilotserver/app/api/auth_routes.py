from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.api.deps import get_auth_service, get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas.auth import (
    AuthTokenResponse,
    LoginRequest,
    PhoneLoginRequest,
    PhoneSendCodeRequest,
    RegisterRequest,
    UserPublic,
)
from app.services.auth_service import AuthError, AuthService

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_NOT_IMPLEMENTED = {
    "code": "NOT_IMPLEMENTED",
    "message": "该登录方式即将开放，请使用用户名/邮箱登录。",
}


@router.post("/register", response_model=AuthTokenResponse)
def register(
    body: RegisterRequest,
    db: Session = Depends(get_db),
    service: AuthService = Depends(get_auth_service),
) -> AuthTokenResponse:
    try:
        return service.register(db, body)
    except AuthError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.post("/login", response_model=AuthTokenResponse)
def login(
    body: LoginRequest,
    db: Session = Depends(get_db),
    service: AuthService = Depends(get_auth_service),
) -> AuthTokenResponse:
    try:
        return service.login(db, body)
    except AuthError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.get("/me", response_model=UserPublic)
def me(
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> UserPublic:
    return service.to_public(user)


@router.post("/logout", status_code=204)
def logout(_user: User = Depends(get_current_user)) -> Response:
    # Client clears the token; reserved for future server-side revocation.
    return Response(status_code=204)


# --- Reserved: phone login (not implemented) ---


@router.post("/phone/send-code")
def phone_send_code(_body: PhoneSendCodeRequest) -> None:
    raise HTTPException(status_code=501, detail=_NOT_IMPLEMENTED)


@router.post("/phone/login")
def phone_login(_body: PhoneLoginRequest) -> None:
    raise HTTPException(status_code=501, detail=_NOT_IMPLEMENTED)


# --- Reserved: OAuth (not implemented) ---


@router.get("/oauth/{provider}/start")
def oauth_start(provider: str) -> None:
    if provider not in {"wechat", "github", "google"}:
        raise HTTPException(
            status_code=404,
            detail={"code": "UNKNOWN_PROVIDER", "message": "不支持的登录方式。"},
        )
    raise HTTPException(status_code=501, detail=_NOT_IMPLEMENTED)


@router.get("/oauth/{provider}/callback")
def oauth_callback(provider: str) -> None:
    if provider not in {"wechat", "github", "google"}:
        raise HTTPException(
            status_code=404,
            detail={"code": "UNKNOWN_PROVIDER", "message": "不支持的登录方式。"},
        )
    raise HTTPException(status_code=501, detail=_NOT_IMPLEMENTED)
