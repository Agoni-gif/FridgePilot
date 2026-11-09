from __future__ import annotations

import secrets

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.common.config import Settings
from app.common.security import create_access_token, hash_password, verify_password
from app.db.models import User
from app.schemas.auth import AuthTokenResponse, LoginRequest, RegisterRequest, UserPublic
from app.services.captcha_service import CaptchaError, CaptchaService


class AuthError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class AuthService:
    def __init__(self, settings: Settings, captcha: CaptchaService) -> None:
        self.settings = settings
        self.captcha = captcha

    def register(self, db: Session, body: RegisterRequest) -> AuthTokenResponse:
        if self._find_by_username(db, body.username):
            raise AuthError("USERNAME_TAKEN", "用户名已被占用", status_code=409)
        if body.email and self._find_by_email(db, str(body.email)):
            raise AuthError("EMAIL_TAKEN", "邮箱已被注册", status_code=409)

        user = User(
            id=secrets.token_urlsafe(16),
            username=body.username,
            email=str(body.email) if body.email else None,
            password_hash=hash_password(body.password),
        )
        db.add(user)
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
        try:
            self.captcha.verify_and_consume(
                body.captcha_id,
                body.captcha_x,
                client_key=client_key,
            )
        except CaptchaError as exc:
            raise AuthError(exc.code, exc.message, status_code=exc.status_code) from exc

        user = self._find_by_account(db, body.account)
        if not user or not verify_password(body.password, user.password_hash):
            raise AuthError("INVALID_CREDENTIALS", "账号或密码错误", status_code=401)
        return self._token_response(user)

    def to_public(self, user: User) -> UserPublic:
        return UserPublic(id=user.id, username=user.username, email=user.email)

    def _token_response(self, user: User) -> AuthTokenResponse:
        return AuthTokenResponse(
            access_token=create_access_token(user_id=user.id, settings=self.settings),
            user=self.to_public(user),
        )

    def _find_by_username(self, db: Session, username: str) -> User | None:
        return db.scalar(select(User).where(User.username == username))

    def _find_by_email(self, db: Session, email: str) -> User | None:
        return db.scalar(select(User).where(User.email == email))

    def _find_by_account(self, db: Session, account: str) -> User | None:
        return db.scalar(
            select(User).where(or_(User.username == account, User.email == account))
        )
