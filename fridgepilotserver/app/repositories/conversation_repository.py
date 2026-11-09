"""会话内消息与菜谱数据访问。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import MessageRecord, RecipeRecord


def list_messages(db: Session, session_id: str) -> list[MessageRecord]:
    """按时间正序列出会话全部消息。"""
    return (
        db.query(MessageRecord)
        .filter(MessageRecord.session_id == session_id)
        .order_by(MessageRecord.created_at.asc(), MessageRecord.id.asc())
        .all()
    )


def list_messages_after(
    db: Session,
    session_id: str,
    *,
    after_message_id: int | None = None,
) -> list[MessageRecord]:
    """列出 id 大于 after_message_id 的消息（用于上下文边界/摘要覆盖之后）。"""
    query = db.query(MessageRecord).filter(MessageRecord.session_id == session_id)
    if after_message_id is not None:
        query = query.filter(MessageRecord.id > after_message_id)
    return query.order_by(MessageRecord.id.asc()).all()


def list_recipes(db: Session, session_id: str) -> list[RecipeRecord]:
    """按时间正序列出会话菜谱。"""
    return (
        db.query(RecipeRecord)
        .filter(RecipeRecord.session_id == session_id)
        .order_by(RecipeRecord.created_at.asc(), RecipeRecord.id.asc())
        .all()
    )


def list_recipes_with_assistant_message(
    db: Session, session_id: str
) -> list[RecipeRecord]:
    """列出已关联助手消息的菜谱（用于标题映射）。"""
    return (
        db.query(RecipeRecord)
        .filter(
            RecipeRecord.session_id == session_id,
            RecipeRecord.assistant_message_id.isnot(None),
        )
        .all()
    )


def get_recipe(db: Session, recipe_id: int) -> RecipeRecord | None:
    """按主键取菜谱。"""
    return db.get(RecipeRecord, recipe_id)


def get_latest_recipe(db: Session, session_id: str) -> RecipeRecord | None:
    """取会话内最新一条菜谱（回退指针用）。"""
    return (
        db.query(RecipeRecord)
        .filter(RecipeRecord.session_id == session_id)
        .order_by(RecipeRecord.id.desc())
        .first()
    )


def has_messages(db: Session, session_id: str) -> bool:
    """会话是否已有消息（空会话列表过滤用）。"""
    return (
        db.query(MessageRecord.id)
        .filter(MessageRecord.session_id == session_id)
        .limit(1)
        .first()
        is not None
    )


def get_first_user_message(db: Session, session_id: str) -> MessageRecord | None:
    """取首条用户消息（生成会话标题）。"""
    return (
        db.query(MessageRecord)
        .filter(MessageRecord.session_id == session_id, MessageRecord.role == "user")
        .order_by(MessageRecord.created_at.asc(), MessageRecord.id.asc())
        .first()
    )


def get_last_message_id(db: Session, session_id: str) -> int | None:
    """取最大消息 ID（清除上下文时作为新边界）。"""
    row = (
        db.query(MessageRecord.id)
        .filter(MessageRecord.session_id == session_id)
        .order_by(MessageRecord.id.desc())
        .first()
    )
    return row[0] if row else None


def add_message(db: Session, row: MessageRecord) -> MessageRecord:
    """加入消息（通常随后 flush 以生成自增 ID）。"""
    db.add(row)
    return row


def add_recipe(db: Session, row: RecipeRecord) -> RecipeRecord:
    """加入菜谱（通常随后 flush 以生成自增 ID）。"""
    db.add(row)
    return row


def delete_recipes_for_session(db: Session, session_id: str) -> int:
    """删除会话下全部菜谱（删除会话步骤 1）。"""
    return (
        db.query(RecipeRecord).filter(RecipeRecord.session_id == session_id).delete()
    )


def clear_message_reply_refs(db: Session, session_id: str) -> int:
    """解除消息自引用外键，便于批量删除（删除会话步骤 2）。"""
    return (
        db.query(MessageRecord)
        .filter(MessageRecord.session_id == session_id)
        .update(
            {MessageRecord.reply_to_message_id: None},
            synchronize_session=False,
        )
    )


def delete_messages_for_session(db: Session, session_id: str) -> int:
    """删除会话下全部消息（删除会话步骤 3）。"""
    return (
        db.query(MessageRecord).filter(MessageRecord.session_id == session_id).delete()
    )
