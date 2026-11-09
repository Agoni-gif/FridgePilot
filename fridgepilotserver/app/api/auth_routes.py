"""认证相关 HTTP 路由：验证码、注册、登录、当前用户与预留登录方式。"""

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
    """下发滑块验证码题目。"""
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
    """仅校验滑块位置（不消费，供前端预检）。"""
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
    """用户注册并返回访问令牌。"""
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
    """用户登录（需验证码）并返回访问令牌。"""
    try:
        return service.login(db, body, client_key=client_key(request))
    except AuthError as exc:
        raise api_error_from_exc(exc) from exc


@router.get("/me", response_model=UserPublic)
def me(
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> UserPublic:
    """返回当前登录用户公开信息。"""
    return service.to_public(user)


@router.post("/logout", status_code=204)
def logout(_user: User = Depends(get_current_user)) -> Response:
    """登出占位：客户端清 token；服务端吊销留待后续。"""
    return Response(status_code=204)


# --- 预留：手机号登录（未实现） ---


@router.post("/phone/send-code")
def phone_send_code(_body: PhoneSendCodeRequest) -> None:
    """发送手机验证码（未实现）。"""
    raise api_error(ApiCode.NOT_IMPLEMENTED)


@router.post("/phone/login")
def phone_login(_body: PhoneLoginRequest) -> None:
    """手机号登录（未实现）。"""
    raise api_error(ApiCode.NOT_IMPLEMENTED)


# --- 预留：OAuth（未实现） ---


@router.get("/oauth/{provider}/start")
def oauth_start(provider: str) -> None:
    """第三方登录跳转入口（未实现）。"""
    if provider not in {"wechat", "github", "google"}:
        raise api_error(ApiCode.UNKNOWN_PROVIDER)
    raise api_error(ApiCode.NOT_IMPLEMENTED)


@router.get("/oauth/{provider}/callback")
def oauth_callback(provider: str) -> None:
    """第三方登录回调（未实现）。"""
    if provider not in {"wechat", "github", "google"}:
        raise api_error(ApiCode.UNKNOWN_PROVIDER)
    raise api_error(ApiCode.NOT_IMPLEMENTED)
