"""FastAPI 依赖注入：认证服务、当前用户解析。"""

from __future__ import annotations

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.common.api_codes import ApiCode
from app.common.config import Settings, get_settings
from app.common.response import api_error
from app.common.security import decode_access_token
from app.db.models import User
from app.db.session import get_db
from app.repositories import user_repository
from app.services.auth_service import AuthService
from app.services.captcha_service import CaptchaService, get_captcha_service

# 不自动抛 403，便于统一返回业务错误码
bearer_scheme = HTTPBearer(auto_error=False)


def get_auth_service(
    settings: Settings = Depends(get_settings),
    captcha: CaptchaService = Depends(get_captcha_service),
) -> AuthService:
    """构造 AuthService 实例。"""
    return AuthService(settings, captcha)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    """从 Bearer JWT 解析并加载当前用户；失败抛统一未授权错误。"""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise api_error(ApiCode.UNAUTHORIZED)

    try:
        user_id = decode_access_token(credentials.credentials, settings)
    except jwt.PyJWTError:
        raise api_error(ApiCode.INVALID_TOKEN) from None

    user = user_repository.get_by_id(db, user_id)
    if user is None:
        raise api_error(ApiCode.UNAUTHORIZED)

    request.state.user_id = user.id
    return user
