"""聊天会话表数据访问（含租约与版本条件更新）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import SessionRecord


def get_by_id(db: Session, session_id: str) -> SessionRecord | None:
    """按会话 ID 查询。"""
    return db.get(SessionRecord, session_id)


def list_by_user(db: Session, user_id: str) -> list[SessionRecord]:
    """列出用户会话，按最近活跃时间倒序。"""
    return (
        db.query(SessionRecord)
        .filter(SessionRecord.user_id == user_id)
        .order_by(SessionRecord.last_active_at.desc(), SessionRecord.created_at.desc())
        .all()
    )


def add(db: Session, record: SessionRecord) -> SessionRecord:
    """新增会话（不提交；通常随后 flush 以拿到持久化状态）。"""
    db.add(record)
    return record


def delete(db: Session, session: SessionRecord) -> None:
    """删除会话行（不提交；调用前需先清菜谱与消息）。"""
    db.delete(session)


def try_acquire_lease(
    db: Session,
    *,
    session_id: str,
    occupy_id: str,
    expires_at: datetime,
    now: datetime,
) -> int:
    """尝试获取生成租约：仅当空闲或已过期时可占用。

    返回受影响行数；1 表示抢占成功，否则会话忙。
    """
    return (
        db.query(SessionRecord)
        .filter(
            SessionRecord.id == session_id,
            or_(
                SessionRecord.active_request_id.is_(None),
                SessionRecord.active_request_expires_at.is_(None),
                SessionRecord.active_request_expires_at < now,
            ),
        )
        .update(
            {
                SessionRecord.active_request_id: occupy_id,
                SessionRecord.active_request_expires_at: expires_at,
            },
            synchronize_session=False,
        )
    )


def release_lease(db: Session, *, session_id: str, occupy_id: str) -> int:
    """释放本请求持有的租约（仅当 active_request_id 仍匹配时）。"""
    return (
        db.query(SessionRecord)
        .filter(
            SessionRecord.id == session_id,
            SessionRecord.active_request_id == occupy_id,
        )
        .update(
            {
                SessionRecord.active_request_id: None,
                SessionRecord.active_request_expires_at: None,
            },
            synchronize_session=False,
        )
    )


def update_state_if_version_and_lease(
    db: Session,
    *,
    session_id: str,
    expected_version: int,
    occupy_id: str,
    state_json: str | None,
    overrides_json: str | None,
    next_version: int,
    last_active_at: datetime,
) -> int:
    """最终写入门禁：context_version 与租约均未变才更新状态。

    用于挡住清除上下文或并发请求导致的脏写；返回受影响行数。
    """
    return (
        db.query(SessionRecord)
        .filter(
            SessionRecord.id == session_id,
            SessionRecord.context_version == expected_version,
            SessionRecord.active_request_id == occupy_id,
        )
        .update(
            {
                SessionRecord.state_json: state_json,
                SessionRecord.session_overrides_json: overrides_json,
                SessionRecord.context_version: next_version,
                SessionRecord.last_active_at: last_active_at,
            },
            synchronize_session=False,
        )
    )


def update_summary_if_version(
    db: Session,
    *,
    session_id: str,
    expected_version: int,
    summary_json: str,
    summary_until_message_id: int,
) -> int:
    """摘要条件写入：仅当 context_version 仍匹配时提交摘要。

    防止清除上下文后，旧的后台摘要任务把过期摘要写回。
    """
    return (
        db.query(SessionRecord)
        .filter(
            SessionRecord.id == session_id,
            SessionRecord.context_version == expected_version,
        )
        .update(
            {
                SessionRecord.summary_json: summary_json,
                SessionRecord.summary_until_message_id: summary_until_message_id,
                SessionRecord.summary_version: SessionRecord.summary_version + 1,
            },
            synchronize_session=False,
        )
    )
