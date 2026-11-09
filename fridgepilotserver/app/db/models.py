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
    preference: Mapped[UserPreferenceRecord | None] = relationship(
        back_populates="user", uselist=False
    )


class UserPreferenceRecord(Base):
    """用户长期做饭偏好：一位用户至多一条。"""

    __tablename__ = "user_preferences"
    __table_args__ = ({"comment": "用户长期做饭偏好表"},)

    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id"),
        primary_key=True,
        comment="用户主键，同时作为唯一外键",
    )
    enabled: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", comment="是否用于生成：0 否 1 是"
    )
    preferences_json: Mapped[str] = mapped_column(
        Text, comment="白名单偏好与过敏声明 JSON"
    )
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", comment="乐观锁版本"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        comment="最近更新时间",
    )

    user: Mapped[User] = relationship(back_populates="preference")


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
    context_version: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", comment="上下文版本（清除/提交时递增）"
    )
    context_start_message_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="清除上下文后仅使用大于此 ID 的消息"
    )
    state_json: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="当前验证后的任务状态 JSON"
    )
    session_overrides_json: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="显式设置与清除标记 JSON"
    )
    active_request_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="当前占用生成请求 ID"
    )
    active_request_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="生成占用过期时间"
    )
    summary_json: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="长对话背景摘要 JSON（不覆盖任务状态）"
    )
    summary_until_message_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="摘要已覆盖的最大消息 ID（与近期窗口不重叠）"
    )
    summary_version: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", comment="摘要版本（提交校验用）"
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
    thinking: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="模型真实思考过程原文"
    )
    reply_to_message_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("messages.id"),
        nullable=True,
        comment="助手回复对应的用户消息 ID",
    )
    response_status: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="completed / clarification / insufficient_sources / error",
    )
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
    assistant_message_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("messages.id"),
        nullable=True,
        unique=True,
        comment="关联的助手消息 ID",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间"
    )

    session: Mapped[SessionRecord] = relationship(back_populates="recipes")
