from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.client_ip import client_key
from app.api.deps import get_auth_service, get_current_user
from app.common.api_codes import ApiCode
from app.common.response import api_error, api_error_from_exc
from app.db.models import User
from app.db.session import get_db
from app.schemas.auth import (
    AuthTokenResponse,
    CaptchaChallengeResponse,
    CaptchaVerifyRequest,
    CaptchaVerifyResponse,
    LoginRequest,
    PhoneLoginRequest,
    PhoneSendCodeRequest,
    RegisterRequest,
    UserPublic,
)
from app.services.auth_service import AuthError, AuthService
from app.services.captcha_service import CaptchaError, CaptchaService, get_captcha_service

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.get("/captcha", response_model=CaptchaChallengeResponse)
def create_captcha(
    request: Request,
    captcha: CaptchaService = Depends(get_captcha_service),
) -> CaptchaChallengeResponse:
    try:
        return CaptchaChallengeResponse(**captcha.create(client_key=client_key(request)))
    except CaptchaError as exc:
        raise api_error_from_exc(exc) from exc


@router.post("/captcha/verify", response_model=CaptchaVerifyResponse)
def verify_captcha(
    body: CaptchaVerifyRequest,
    request: Request,
    captcha: CaptchaService = Depends(get_captcha_service),
) -> CaptchaVerifyResponse:
    try:
        captcha.check(body.captcha_id, body.captcha_x, client_key=client_key(request))
    except CaptchaError as exc:
        raise api_error_from_exc(exc) from exc
    return CaptchaVerifyResponse(ok=True)


@router.post("/register", response_model=AuthTokenResponse)
def register(
    body: RegisterRequest,
    db: Session = Depends(get_db),
    service: AuthService = Depends(get_auth_service),
) -> AuthTokenResponse:
    try:
        return service.register(db, body)
    except AuthError as exc:
        raise api_error_from_exc(exc) from exc


@router.post("/login", response_model=AuthTokenResponse)
def login(
    body: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
    service: AuthService = Depends(get_auth_service),
) -> AuthTokenResponse:
    try:
        return service.login(db, body, client_key=client_key(request))
    except AuthError as exc:
        raise api_error_from_exc(exc) from exc


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
    raise api_error(ApiCode.NOT_IMPLEMENTED)


@router.post("/phone/login")
def phone_login(_body: PhoneLoginRequest) -> None:
    raise api_error(ApiCode.NOT_IMPLEMENTED)


# --- Reserved: OAuth (not implemented) ---


@router.get("/oauth/{provider}/start")
def oauth_start(provider: str) -> None:
    if provider not in {"wechat", "github", "google"}:
        raise api_error(ApiCode.UNKNOWN_PROVIDER)
    raise api_error(ApiCode.NOT_IMPLEMENTED)


@router.get("/oauth/{provider}/callback")
def oauth_callback(provider: str) -> None:
    if provider not in {"wechat", "github", "google"}:
        raise api_error(ApiCode.UNKNOWN_PROVIDER)
    raise api_error(ApiCode.NOT_IMPLEMENTED)
