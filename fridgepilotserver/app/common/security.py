"""密码哈希与 JWT 签发/校验。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from app.common.config import Settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    """对明文密码做 bcrypt 哈希。"""
    return pwd_context.hash(password)


def verify_password(plain: str, password_hash: str | None) -> bool:
    """校验明文与哈希；无哈希时直接失败。"""
    if not password_hash:
        return False
    return pwd_context.verify(plain, password_hash)


def create_access_token(*, user_id: str, settings: Settings) -> str:
    """签发访问令牌，sub 为用户 ID。"""
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expire_hours)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> str:
    """从有效 JWT 取出 user_id；无效时抛 jwt.PyJWTError。"""
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise jwt.InvalidTokenError("missing sub")
    return sub
