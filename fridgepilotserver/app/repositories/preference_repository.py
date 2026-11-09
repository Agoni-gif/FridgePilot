"""用户长期做饭偏好数据访问。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import UserPreferenceRecord


def get_by_user_id(db: Session, user_id: str) -> UserPreferenceRecord | None:
    """按用户 ID 读取偏好（一位用户至多一条）。"""
    return db.get(UserPreferenceRecord, user_id)


def add(db: Session, row: UserPreferenceRecord) -> UserPreferenceRecord:
    """新增偏好行（不提交；并发首次创建冲突由 Service 处理）。"""
    db.add(row)
    return row


def update_if_version(
    db: Session,
    *,
    user_id: str,
    expected_version: int,
    enabled: int,
    preferences_json: str,
    next_version: int,
    updated_at: datetime,
) -> int:
    """乐观锁条件更新：仅当 version 仍等于 expected_version 时写入。

    返回受影响行数；Service 据此判断是否冲突（应为 1）。
    synchronize_session=False：避免批量更新后 Session 内实体状态被错误同步。
    """
    return (
        db.query(UserPreferenceRecord)
        .filter(
            UserPreferenceRecord.user_id == user_id,
            UserPreferenceRecord.version == expected_version,
        )
        .update(
            {
                UserPreferenceRecord.enabled: enabled,
                UserPreferenceRecord.preferences_json: preferences_json,
                UserPreferenceRecord.version: next_version,
                UserPreferenceRecord.updated_at: updated_at,
            },
            synchronize_session=False,
        )
    )


def delete(db: Session, row: UserPreferenceRecord) -> None:
    """删除偏好行（不提交）。"""
    db.delete(row)
