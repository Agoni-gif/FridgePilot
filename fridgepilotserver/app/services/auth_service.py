from __future__ import annotations

import secrets

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.common.api_codes import ApiCode
from app.common.config import Settings
from app.common.response import ApiException
from app.common.security import create_access_token, hash_password, verify_password
from app.db.models import User
from app.schemas.auth import AuthTokenResponse, LoginRequest, RegisterRequest, UserPublic
from app.services.captcha_service import CaptchaError, CaptchaService


class AuthError(ApiException):
    """Auth-domain API error."""


class AuthService:
    def __init__(self, settings: Settings, captcha: CaptchaService) -> None:
        self.settings = settings
        self.captcha = captcha

    def register(self, db: Session, body: RegisterRequest) -> AuthTokenResponse:
        if self._find_by_username(db, body.username):
            raise AuthError(ApiCode.USERNAME_TAKEN)
        if body.email and self._find_by_email(db, str(body.email)):
            raise AuthError(ApiCode.EMAIL_TAKEN)

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
            raise AuthError(
                exc.code, exc.message, status_code=exc.status_code
            ) from exc

        user = self._find_by_account(db, body.account)
        if not user or not verify_password(body.password, user.password_hash):
            raise AuthError(ApiCode.INVALID_CREDENTIALS)
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
