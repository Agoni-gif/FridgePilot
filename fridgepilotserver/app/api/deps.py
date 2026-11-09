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
from app.services.auth_service import AuthService
from app.services.captcha_service import CaptchaService, get_captcha_service

bearer_scheme = HTTPBearer(auto_error=False)


def get_auth_service(
    settings: Settings = Depends(get_settings),
    captcha: CaptchaService = Depends(get_captcha_service),
) -> AuthService:
    return AuthService(settings, captcha)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise api_error(ApiCode.UNAUTHORIZED)

    try:
        user_id = decode_access_token(credentials.credentials, settings)
    except jwt.PyJWTError:
        raise api_error(ApiCode.INVALID_TOKEN) from None

    user = db.get(User, user_id)
    if user is None:
        raise api_error(ApiCode.UNAUTHORIZED)

    request.state.user_id = user.id
    return user
