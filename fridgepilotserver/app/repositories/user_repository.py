"""用户表数据访问。"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import User


def get_by_id(db: Session, user_id: str) -> User | None:
    """按主键查询用户。"""
    return db.get(User, user_id)


def get_by_username(db: Session, username: str) -> User | None:
    """按用户名查询（注册查重）。"""
    return db.scalar(select(User).where(User.username == username))


def get_by_email(db: Session, email: str) -> User | None:
    """按邮箱查询（注册查重）。"""
    return db.scalar(select(User).where(User.email == email))


def get_by_account(db: Session, account: str) -> User | None:
    """登录账号解析：用户名或邮箱命中其一即可。"""
    return db.scalar(
        select(User).where(or_(User.username == account, User.email == account))
    )


def add(db: Session, user: User) -> User:
    """将用户加入当前 Session（不提交）。"""
    db.add(user)
    return user
