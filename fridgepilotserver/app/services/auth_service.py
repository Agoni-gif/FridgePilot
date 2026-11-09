"""认证业务：注册、登录、签发访问令牌。

数据读写走 user_repository；commit / refresh 由本层负责。
"""

from __future__ import annotations

import secrets

from sqlalchemy.orm import Session

from app.common.api_codes import ApiCode
from app.common.config import Settings
from app.common.response import ApiException
from app.common.security import create_access_token, hash_password, verify_password
from app.db.models import User
from app.repositories import user_repository
from app.schemas.auth import AuthTokenResponse, LoginRequest, RegisterRequest, UserPublic
from app.services.captcha_service import CaptchaError, CaptchaService


class AuthError(ApiException):
    """认证域业务异常，映射为统一 API 错误码。"""


class AuthService:
    """用户注册 / 登录服务。"""

    def __init__(self, settings: Settings, captcha: CaptchaService) -> None:
        self.settings = settings
        self.captcha = captcha

    def register(self, db: Session, body: RegisterRequest) -> AuthTokenResponse:
        """注册新用户：查重 → 写入 → 提交 → 返回令牌。"""
        if user_repository.get_by_username(db, body.username):
            raise AuthError(ApiCode.USERNAME_TAKEN)
        if body.email and user_repository.get_by_email(db, str(body.email)):
            raise AuthError(ApiCode.EMAIL_TAKEN)

        user = User(
            id=secrets.token_urlsafe(16),
            username=body.username,
            email=str(body.email) if body.email else None,
            password_hash=hash_password(body.password),
        )
        # Repository 只挂到 Session；提交与刷新由 Service 控制事务边界。
        user_repository.add(db, user)
        db.commit()
        db.refresh(user)
        return self._token_response(user)

    def login(
        self,
        db: Session,
        body: LoginRequest,
        *,
        client_key: str = "unknown",
    ) -> AuthTokenResponse:
        """登录：校验滑块验证码 → 校验账号密码 → 返回令牌。"""
        try:
            self.captcha.verify_and_consume(
                body.captcha_id,
                body.captcha_x,
                client_key=client_key,
            )
        except CaptchaError as exc:
            raise AuthError(
                exc.code, exc.message, status_code=exc.status_code
            ) from exc

        user = user_repository.get_by_account(db, body.account)
        if not user or not verify_password(body.password, user.password_hash):
            raise AuthError(ApiCode.INVALID_CREDENTIALS)
        return self._token_response(user)

    def to_public(self, user: User) -> UserPublic:
        """转为对外公开的用户信息（不含密码哈希）。"""
        return UserPublic(id=user.id, username=user.username, email=user.email)

    def _token_response(self, user: User) -> AuthTokenResponse:
        """签发 JWT 并组装登录/注册响应。"""
        return AuthTokenResponse(
            access_token=create_access_token(user_id=user.id, settings=self.settings),
            user=self.to_public(user),
        )
