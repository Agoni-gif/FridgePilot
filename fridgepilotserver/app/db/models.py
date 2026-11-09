from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class User(Base):
    """用户表：账号、凭证与预留的第三方登录字段。"""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("oauth_provider", "oauth_subject", name="uq_users_oauth"),
        {"comment": "用户账号表"},
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="用户主键 ID")
    username: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, comment="用户名（唯一）"
    )
    email: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True, index=True, comment="邮箱（可选，唯一）"
    )
    password_hash: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="密码哈希（第三方登录可为空）"
    )
    # 预留：手机号 / OAuth 登录（尚未实现）
    phone: Mapped[str | None] = mapped_column(
        String(32), unique=True, nullable=True, index=True, comment="手机号（预留）"
    )
    oauth_provider: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="第三方登录提供方（预留，如 wechat/github）"
    )
    oauth_subject: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="第三方登录主体标识（预留）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )

    sessions: Mapped[list[SessionRecord]] = relationship(back_populates="user")


class SessionRecord(Base):
    """会话表：一次对话线程，归属可选用户。"""

    __tablename__ = "sessions"
    __table_args__ = ({"comment": "聊天会话表"},)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="会话主键 ID")
    user_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("users.id"),
        nullable=True,
        index=True,
        comment="所属用户 ID（可为空）",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        comment="最近活跃时间",
    )

    user: Mapped[User | None] = relationship(back_populates="sessions")
    messages: Mapped[list[MessageRecord]] = relationship(back_populates="session")
    recipes: Mapped[list[RecipeRecord]] = relationship(back_populates="session")


class MessageRecord(Base):
    """消息表：会话内的用户 / 助手消息。"""

    __tablename__ = "messages"
    __table_args__ = ({"comment": "会话消息表"},)

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="消息主键 ID"
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id"), index=True, comment="所属会话 ID"
    )
    role: Mapped[str] = mapped_column(String(20), comment="角色：user / assistant / system")
    content: Mapped[str] = mapped_column(Text, comment="消息正文")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )

    session: Mapped[SessionRecord] = relationship(back_populates="messages")


class RecipeRecord(Base):
    """菜谱记录表：某次会话生成的结构化菜谱与来源。"""

    __tablename__ = "recipes"
    __table_args__ = ({"comment": "菜谱生成记录表"},)

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="菜谱记录主键 ID"
    )
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id"), index=True, comment="所属会话 ID"
    )
    recipe_json: Mapped[str] = mapped_column(Text, comment="结构化菜谱 JSON")
    sources_json: Mapped[str] = mapped_column(Text, comment="检索来源 JSON")
    prompt_version: Mapped[str] = mapped_column(String(32), comment="提示词 / 编排版本号")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )

    session: Mapped[SessionRecord] = relationship(back_populates="recipes")
