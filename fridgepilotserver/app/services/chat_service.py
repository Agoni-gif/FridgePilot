"""聊天会话业务：列表、消息、上下文、生成租约与结果落库。

数据访问走 session_repository / conversation_repository；
租约获取/释放、版本条件提交、flush 时机均由本层协调。
"""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.agent.orchestrator import AgentOrchestrator, AgentOutcome, ProgressCallback
from app.common.config import Settings
from app.common.logging_setup import preview_text
from app.db.models import MessageRecord, RecipeRecord, SessionRecord
from app.repositories import conversation_repository, session_repository
from app.schemas.chat import ChatMeta, ChatPreferences, ChatResponse
from app.schemas.context import PreferencePatch, PublicContext, SessionState
from app.schemas.recipe import Recipe
from app.schemas.session import SessionMessage, SessionMessagesResponse, SessionSummary
from app.schemas.preferences import PreferenceValues
from app.services.conversation_context import (
    ContextBudgetExceededError,
    assemble_context,
    load_session_overrides,
    load_session_state,
    serialize_overrides,
    serialize_state,
    to_public_context,
)
from app.services.conversation_summary import (
    clear_summary_fields,
    maybe_refresh_conversation_summary,
)
from app.services.preference_service import PreferenceLoadError, PreferenceService
from app.services.state_merge import (
    apply_long_term_defaults,
    empty_overrides,
    persistable_session_state,
)

logger = logging.getLogger(__name__)

# 会话列表标题最大展示长度
_TITLE_MAX = 36


class SessionAccessError(Exception):
    """尝试恢复他人会话。"""


class SessionNotFoundError(Exception):
    """会话不存在或不属于当前用户。"""


class SessionBusyError(Exception):
    """会话已有进行中的生成租约。"""


class SessionConflictError(Exception):
    """落库前 context_version / 租约已变化。"""


class ChatService:
    """会话与聊天主流程。"""

    def __init__(self, settings: Settings, orchestrator: AgentOrchestrator) -> None:
        self.settings = settings
        self.orchestrator = orchestrator
        self.preferences = PreferenceService()

    def list_sessions(self, db: Session, *, user_id: str) -> list[SessionSummary]:
        """列出有消息的会话摘要（过滤空会话）。"""
        rows = session_repository.list_by_user(db, user_id)
        return [
            SessionSummary(
                id=row.id,
                title=self._session_title(db, row.id),
                created_at=row.created_at,
                last_active_at=row.last_active_at,
            )
            for row in rows
            if self._session_has_messages(db, row.id)
        ]

    def get_session_messages(
        self, db: Session, *, session_id: str, user_id: str
    ) -> SessionMessagesResponse:
        """按时间顺序返回消息，并尽量把菜谱挂到对应助手消息。"""
        session = self._require_owned_session(db, session_id, user_id)
        messages = conversation_repository.list_messages(db, session_id)
        recipes = conversation_repository.list_recipes(db, session_id)
        recipe_by_message = self._pair_recipes(messages, recipes)

        return SessionMessagesResponse(
            session_id=session.id,
            title=self._session_title(db, session.id),
            messages=[
                SessionMessage(
                    id=msg.id,
                    role=msg.role,
                    content=msg.content,
                    thinking=msg.thinking,
                    created_at=msg.created_at,
                    recipe=recipe_by_message.get(msg.id),
                )
                for msg in messages
            ],
        )

    def get_context(self, db: Session, *, session_id: str, user_id: str) -> PublicContext:
        """读取对外公开的会话上下文（含长期偏好叠加后的有效状态）。"""
        session = self._require_owned_session(db, session_id, user_id)
        defaults, pref_version = self.preferences.get_enabled_values(db, user_id=user_id)
        state = load_session_state(session)
        overrides = load_session_overrides(session)
        effective = apply_long_term_defaults(state, overrides, defaults)
        applied = defaults is not None
        return to_public_context(
            session,
            long_term_preferences_applied=applied,
            long_term_preferences_version=pref_version if applied else None,
            effective_state=effective if (state is not None or applied) else None,
        )

    def ensure_session_available(
        self, db: Session, *, session_id: str | None, user_id: str
    ) -> None:
        """流式接口前置检查：校验归属，若租约未过期则拒绝。"""
        if not session_id:
            return
        session = self._require_owned_session(db, session_id, user_id)
        now = datetime.now(timezone.utc)
        expires = session.active_request_expires_at
        if session.active_request_id and expires is not None:
            # SQLite 可能返回无时区时间戳，按 UTC 归一
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires >= now:
                raise SessionBusyError("此对话正在生成，请稍后再试。")

    def clear_context(self, db: Session, *, session_id: str, user_id: str) -> PublicContext:
        """清除会话上下文：抬高消息边界、清空状态/摘要、递增版本并作废租约。"""
        session = self._require_owned_session(db, session_id, user_id)
        last_msg_id = conversation_repository.get_last_message_id(db, session_id)
        session.context_start_message_id = last_msg_id if last_msg_id is not None else 0
        session.state_json = None
        session.session_overrides_json = None
        clear_summary_fields(session)
        session.context_version = (session.context_version or 0) + 1
        # 作废进行中的生成，避免旧请求再写入
        session.active_request_id = None
        session.active_request_expires_at = None
        session.last_active_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(session)
        # 清除后下一轮可再次套用长期偏好默认值
        defaults, pref_version = self.preferences.get_enabled_values(db, user_id=user_id)
        applied = defaults is not None
        effective = apply_long_term_defaults(None, empty_overrides(), defaults) if applied else None
        return to_public_context(
            session,
            long_term_preferences_applied=applied,
            long_term_preferences_version=pref_version if applied else None,
            effective_state=effective,
        )

    def delete_session(self, db: Session, *, session_id: str, user_id: str) -> None:
        """删除会话：菜谱 → 解除消息自引用 → 消息 → 会话，同一事务提交。"""
        session = self._require_owned_session(db, session_id, user_id)
        # 菜谱外键指向消息，必须先删菜谱
        conversation_repository.delete_recipes_for_session(db, session_id)
        # 消息自引用外键需先置空再批量删除
        conversation_repository.clear_message_reply_refs(db, session_id)
        conversation_repository.delete_messages_for_session(db, session_id)
        session_repository.delete(db, session)
        db.commit()

    async def handle_chat(
        self,
        *,
        db: Session,
        message: str,
        session_id: str | None,
        preferences: ChatPreferences | None,
        user_id: str,
        request_id: str = "-",
        on_progress: ProgressCallback | None = None,
        preference_patch: PreferencePatch | None = None,
    ) -> ChatResponse:
        """主聊天流程：占租约 →（可选）摘要/组装上下文 → 调用模型 → 条件落库 → 释放租约。"""
        occupy_id = request_id if request_id and request_id != "-" else uuid.uuid4().hex
        session: SessionRecord | None = None
        occupied = False
        started_version = 0

        try:
            session = self._get_or_create_session(db, session_id, user_id=user_id)
            created = session_id != session.id
            logger.info(
                "request_id=%s user_id=%s session %s id=%s",
                request_id,
                user_id,
                "created" if created or not session_id else "resumed",
                session.id,
            )

            started_version = session.context_version or 0
            self._try_occupy(db, session, occupy_id)
            occupied = True
            db.refresh(session)

            long_term_applied = False
            long_term_version: int | None = None
            user_defaults: PreferenceValues | None = None
            try:
                user_defaults, long_term_version = self.preferences.get_enabled_values(
                    db, user_id=user_id
                )
                long_term_applied = user_defaults is not None
            except PreferenceLoadError as exc:
                outcome = AgentOutcome(
                    status="error",
                    message=str(exc),
                    elapsed_ms=0,
                    commit_state=False,
                    intent="clarify",
                )
                return self._commit_outcome(
                    db,
                    session=session,
                    message=message,
                    outcome=outcome,
                    request_id=request_id,
                    started_version=started_version,
                    occupy_id=occupy_id,
                    long_term_applied=False,
                    long_term_version=None,
                )

            context = None
            if self.settings.session_memory_enabled:
                # 摘要/组装前先套长期默认，使最终 payload 拟合与溢出覆盖与模型所见一致
                defaults_dump = (
                    user_defaults.model_dump() if user_defaults is not None else None
                )
                allergies = (
                    list(user_defaults.allergies or [])
                    if user_defaults is not None
                    else None
                )
                seeded_state = None
                if user_defaults is not None:
                    seeded_state = apply_long_term_defaults(
                        load_session_state(session),
                        load_session_overrides(session),
                        user_defaults,
                    )

                # 近期窗口外的旧轮次按需摘要；软失败，不阻断主请求
                try:
                    summary_result = await maybe_refresh_conversation_summary(
                        db,
                        session,
                        llm=self.orchestrator.llm,
                        settings=self.settings,
                        started_version=started_version,
                        current_message=message,
                        user_defaults=defaults_dump,
                        allergies=allergies,
                        session_state=seeded_state,
                    )
                    if summary_result.committed:
                        db.refresh(session)
                except Exception:
                    logger.exception(
                        "request_id=%s conversation summary unexpected error",
                        request_id,
                    )

                try:
                    context = assemble_context(
                        db,
                        session,
                        current_message=message,
                        settings=self.settings,
                        user_defaults=defaults_dump,
                        allergies=allergies,
                        session_state=seeded_state,
                    )
                except ContextBudgetExceededError as exc:
                    outcome = AgentOutcome(
                        status="error",
                        message=str(exc),
                        elapsed_ms=0,
                        commit_state=False,
                        intent="clarify",
                    )
                    return self._commit_outcome(
                        db,
                        session=session,
                        message=message,
                        outcome=outcome,
                        request_id=request_id,
                        started_version=started_version,
                        occupy_id=occupy_id,
                        long_term_applied=long_term_applied,
                        long_term_version=long_term_version if long_term_applied else None,
                    )

            outcome = await self.orchestrator.run(
                message,
                preferences,
                request_id=request_id,
                on_progress=on_progress,
                context=context,
                preference_patch=preference_patch,
                memory_enabled=self.settings.session_memory_enabled,
            )

            response = self._commit_outcome(
                db,
                session=session,
                message=message,
                outcome=outcome,
                request_id=request_id,
                started_version=started_version,
                occupy_id=occupy_id,
                long_term_applied=long_term_applied,
                long_term_version=long_term_version if long_term_applied else None,
            )
            return response
        finally:
            if occupied and session is not None:
                self._release_occupy(db, session.id, occupy_id)

    def _commit_outcome(
        self,
        db: Session,
        *,
        session: SessionRecord,
        message: str,
        outcome: AgentOutcome,
        request_id: str,
        started_version: int,
        occupy_id: str,
        long_term_applied: bool = False,
        long_term_version: int | None = None,
    ) -> ChatResponse:
        """仅当 context_version 与租约仍匹配时才持久化本轮结果（原子门禁）。"""
        try:
            user_msg = self._add_message(db, session.id, "user", message)
            db.flush()  # 需要自增 message.id 供助手消息引用

            assistant_text = outcome.message or (
                outcome.recipe.title if outcome.recipe else outcome.status
            )
            assistant_msg = self._add_message(
                db,
                session.id,
                "assistant",
                assistant_text,
                thinking=outcome.thinking,
                reply_to_message_id=user_msg.id,
                response_status=outcome.status,
            )
            db.flush()

            recipe_id: int | None = None
            if outcome.recipe is not None and outcome.status == "completed":
                recipe_row = self._save_recipe(
                    db,
                    session.id,
                    outcome,
                    assistant_message_id=assistant_msg.id,
                )
                db.flush()
                recipe_id = recipe_row.id
                logger.info(
                    "request_id=%s recipe saved title=%r sources=%s",
                    request_id,
                    outcome.recipe.title,
                    len(outcome.recipe.sources),
                )

            # 状态落库规则见 PRD §12.2
            state_json = session.state_json
            overrides_json = session.session_overrides_json
            next_version = started_version
            if outcome.commit_state and outcome.merged_state is not None:
                merged_overrides = outcome.merged_overrides or empty_overrides()
                new_state = outcome.merged_state.model_copy(deep=True)
                if outcome.update_last_recipe and recipe_id is not None:
                    # 仅当用户明确要求换菜时，才把上一道菜名加入排除列表
                    if outcome.exclude_previous_recipe and outcome.recipe:
                        titles = [
                            t
                            for t in new_state.excluded_recipe_titles
                            if t.strip().casefold()
                            != outcome.recipe.title.strip().casefold()
                        ]
                        prev = None
                        if new_state.last_recipe_id is not None:
                            prev_row = conversation_repository.get_recipe(
                                db, new_state.last_recipe_id
                            )
                            if prev_row and prev_row.session_id == session.id:
                                try:
                                    prev = Recipe.model_validate_json(
                                        prev_row.recipe_json
                                    ).title
                                except Exception:
                                    prev = None
                        if prev and not any(
                            t.strip().casefold() == prev.strip().casefold()
                            for t in titles
                        ):
                            titles.append(prev)
                        new_state.excluded_recipe_titles = titles[-10:]
                    new_state.last_recipe_id = recipe_id
                # 不要把「仅来自长期默认」的填充冻进会话 state_json
                before_state = load_session_state(session)
                persisted = persistable_session_state(
                    before_state, new_state, merged_overrides
                )
                state_json = serialize_state(persisted)
                overrides_json = serialize_overrides(merged_overrides)
                next_version = started_version + 1
                # 响应面板仍展示合并后的有效约束
                outcome.merged_state = new_state

            # 最终门禁：版本与租约仍匹配才写入状态
            updated = session_repository.update_state_if_version_and_lease(
                db,
                session_id=session.id,
                expected_version=started_version,
                occupy_id=occupy_id,
                state_json=state_json,
                overrides_json=overrides_json,
                next_version=next_version,
                last_active_at=datetime.now(timezone.utc),
            )
            if updated != 1:
                db.rollback()
                raise SessionConflictError("会话上下文已变化，请重试。")

            db.commit()
            db.refresh(session)
            logger.debug(
                "request_id=%s db commit ok assistant=%r",
                request_id,
                preview_text(assistant_text),
            )
            return self._to_response(
                session,
                outcome,
                long_term_applied=long_term_applied,
                long_term_version=long_term_version,
            )
        except SessionConflictError:
            raise
        except Exception:
            db.rollback()
            raise

    def _try_occupy(self, db: Session, session: SessionRecord, occupy_id: str) -> None:
        """条件抢占生成租约；失败抛 SessionBusyError。抢占成功后立即 commit。"""
        now = datetime.now(timezone.utc)
        lease = timedelta(seconds=max(60.0, self.settings.request_timeout_seconds * 3))
        expires = now + lease

        # 空闲或已过期才可占用
        updated = session_repository.try_acquire_lease(
            db,
            session_id=session.id,
            occupy_id=occupy_id,
            expires_at=expires,
            now=now,
        )
        db.commit()
        if updated != 1:
            raise SessionBusyError("此对话正在生成，请稍后再试。")

    def _release_occupy(self, db: Session, session_id: str, occupy_id: str) -> None:
        """释放本请求租约；失败只记日志，不向上抛。"""
        try:
            session_repository.release_lease(
                db, session_id=session_id, occupy_id=occupy_id
            )
            db.commit()
        except Exception:
            logger.exception("failed to release occupy session_id=%s", session_id)
            db.rollback()

    def _get_or_create_session(
        self, db: Session, session_id: str | None, *, user_id: str
    ) -> SessionRecord:
        """恢复已有会话或创建新会话；无主会话会补写 user_id。"""
        if session_id:
            existing = session_repository.get_by_id(db, session_id)
            if not existing:
                raise SessionNotFoundError("会话不存在。")
            if existing.user_id and existing.user_id != user_id:
                raise SessionAccessError("无权访问该会话。")
            if existing.user_id is None:
                existing.user_id = user_id
                db.flush()
            return existing
        new_id = secrets.token_urlsafe(16)
        record = SessionRecord(id=new_id, user_id=user_id, context_version=0)
        session_repository.add(db, record)
        db.flush()
        return record

    def _require_owned_session(
        self, db: Session, session_id: str, user_id: str
    ) -> SessionRecord:
        """要求会话存在且归属当前用户，否则视为不存在。"""
        session = session_repository.get_by_id(db, session_id)
        if not session or session.user_id != user_id:
            raise SessionNotFoundError("会话不存在。")
        return session

    def _session_has_messages(self, db: Session, session_id: str) -> bool:
        """是否至少有一条消息。"""
        return conversation_repository.has_messages(db, session_id)

    def _session_title(self, db: Session, session_id: str) -> str:
        """用首条用户消息截断生成标题。"""
        first = conversation_repository.get_first_user_message(db, session_id)
        if not first or not first.content.strip():
            return "新对话"
        text = " ".join(first.content.strip().split())
        if len(text) <= _TITLE_MAX:
            return text
        return text[: _TITLE_MAX - 1].rstrip() + "…"

    def _pair_recipes(
        self,
        messages: list[MessageRecord],
        recipes: list[RecipeRecord],
    ) -> dict[int, Recipe]:
        """将菜谱配对到助手消息：优先显式外键，否则按标题/顺序回退。"""
        paired: dict[int, Recipe] = {}
        used: set[int] = set()

        # 优先使用 assistant_message_id 显式关联
        for record in recipes:
            if record.assistant_message_id is None:
                continue
            try:
                recipe = Recipe.model_validate_json(record.recipe_json)
            except Exception:
                logger.warning("skip invalid recipe_json id=%s", record.id)
                continue
            paired[record.assistant_message_id] = recipe
            used.add(record.id)

        # 旧数据无显式外键时的启发式配对
        parsed: list[tuple[RecipeRecord, Recipe]] = []
        for record in recipes:
            if record.id in used:
                continue
            try:
                recipe = Recipe.model_validate_json(record.recipe_json)
            except Exception:
                logger.warning("skip invalid recipe_json id=%s", record.id)
                continue
            parsed.append((record, recipe))

        for msg in messages:
            if msg.role != "assistant" or msg.id in paired:
                continue
            for record, recipe in parsed:
                if record.id in used:
                    continue
                if msg.content == recipe.title:
                    paired[msg.id] = recipe
                    used.add(record.id)
                    break

        remaining = [(r, recipe) for r, recipe in parsed if r.id not in used]
        if remaining:
            unpaired = [
                msg
                for msg in messages
                if msg.role == "assistant" and msg.id not in paired
            ]
            for msg, (_record, recipe) in zip(unpaired, remaining):
                paired[msg.id] = recipe

        return paired

    def _add_message(
        self,
        db: Session,
        session_id: str,
        role: str,
        content: str,
        *,
        thinking: str | None = None,
        reply_to_message_id: int | None = None,
        response_status: str | None = None,
    ) -> MessageRecord:
        """构造消息行并加入 Session（调用方负责 flush/commit）。"""
        row = MessageRecord(
            session_id=session_id,
            role=role,
            content=content,
            thinking=thinking,
            reply_to_message_id=reply_to_message_id,
            response_status=response_status,
        )
        return conversation_repository.add_message(db, row)

    def _save_recipe(
        self,
        db: Session,
        session_id: str,
        outcome: AgentOutcome,
        *,
        assistant_message_id: int | None = None,
    ) -> RecipeRecord:
        """将 Agent 产出的菜谱写入 Session（调用方负责 flush/commit）。"""
        assert outcome.recipe is not None
        row = RecipeRecord(
            session_id=session_id,
            recipe_json=outcome.recipe.model_dump_json(),
            sources_json=json.dumps(
                [s.model_dump() for s in outcome.recipe.sources],
                ensure_ascii=False,
            ),
            prompt_version=outcome.prompt_version,
            assistant_message_id=assistant_message_id,
        )
        return conversation_repository.add_recipe(db, row)

    def _to_response(
        self,
        session: SessionRecord,
        outcome: AgentOutcome,
        *,
        long_term_applied: bool = False,
        long_term_version: int | None = None,
    ) -> ChatResponse:
        """将 AgentOutcome 组装为 API ChatResponse。"""
        effective = outcome.merged_state
        return ChatResponse(
            session_id=session.id,
            status=outcome.status,  # type: ignore[arg-type]
            recipe=outcome.recipe,
            message=outcome.message,
            thinking=outcome.thinking,
            meta=ChatMeta(
                search_used=outcome.search_used,
                elapsed_ms=outcome.elapsed_ms,
                prompt_version=outcome.prompt_version,
                detail=outcome.message if outcome.status != "completed" else None,
            ),
            context=to_public_context(
                session,
                long_term_preferences_applied=long_term_applied,
                long_term_preferences_version=long_term_version,
                effective_state=effective,
            ),
        )
