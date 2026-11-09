from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.common.config import Settings, get_settings
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
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "请先登录。"},
        )

    try:
        user_id = decode_access_token(credentials.credentials, settings)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_TOKEN", "message": "登录已失效，请重新登录。"},
        ) from None

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "请先登录。"},
        )

    request.state.user_id = user.id
    return user
