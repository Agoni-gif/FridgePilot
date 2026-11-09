from __future__ import annotations

import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.agent.orchestrator import AgentOrchestrator, AgentOutcome, ProgressCallback
from app.common.config import Settings
from app.common.logging_setup import preview_text
from app.db.models import MessageRecord, RecipeRecord, SessionRecord
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

_TITLE_MAX = 36


class SessionAccessError(Exception):
    """Raised when a client tries to resume another user's chat session."""


class SessionNotFoundError(Exception):
    """Raised when a session does not exist or is not owned by the user."""


class SessionBusyError(Exception):
    """Raised when the session already has an active generation request."""


class SessionConflictError(Exception):
    """Raised when context_version changed before commit."""


class ChatService:
    def __init__(self, settings: Settings, orchestrator: AgentOrchestrator) -> None:
        self.settings = settings
        self.orchestrator = orchestrator
        self.preferences = PreferenceService()

    def list_sessions(self, db: Session, *, user_id: str) -> list[SessionSummary]:
        rows = (
            db.query(SessionRecord)
            .filter(SessionRecord.user_id == user_id)
            .order_by(SessionRecord.last_active_at.desc(), SessionRecord.created_at.desc())
            .all()
        )
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
        session = self._require_owned_session(db, session_id, user_id)
        messages = (
            db.query(MessageRecord)
            .filter(MessageRecord.session_id == session_id)
            .order_by(MessageRecord.created_at.asc(), MessageRecord.id.asc())
            .all()
        )
        recipes = (
            db.query(RecipeRecord)
            .filter(RecipeRecord.session_id == session_id)
            .order_by(RecipeRecord.created_at.asc(), RecipeRecord.id.asc())
            .all()
        )
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
        """Validate ownership and reject if an active lease is held (pre-stream check)."""
        if not session_id:
            return
        session = self._require_owned_session(db, session_id, user_id)
        now = datetime.now(timezone.utc)
        expires = session.active_request_expires_at
        if session.active_request_id and expires is not None:
            # Normalize naive timestamps from SQLite.
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires >= now:
                raise SessionBusyError("此对话正在生成，请稍后再试。")

    def clear_context(self, db: Session, *, session_id: str, user_id: str) -> PublicContext:
        session = self._require_owned_session(db, session_id, user_id)
        last_msg = (
            db.query(MessageRecord.id)
            .filter(MessageRecord.session_id == session_id)
            .order_by(MessageRecord.id.desc())
            .first()
        )
        session.context_start_message_id = last_msg[0] if last_msg else 0
        session.state_json = None
        session.session_overrides_json = None
        clear_summary_fields(session)
        session.context_version = (session.context_version or 0) + 1
        # Invalidate any in-flight generation for this session.
        session.active_request_id = None
        session.active_request_expires_at = None
        session.last_active_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(session)
        # After clear, long-term defaults may again apply on next turn.
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
        session = self._require_owned_session(db, session_id, user_id)
        # recipes.assistant_message_id → messages.id; clear recipes before messages.
        db.query(RecipeRecord).filter(RecipeRecord.session_id == session_id).delete()
        # messages.reply_to_message_id is self-referential; null before bulk delete.
        db.query(MessageRecord).filter(MessageRecord.session_id == session_id).update(
            {MessageRecord.reply_to_message_id: None},
            synchronize_session=False,
        )
        db.query(MessageRecord).filter(MessageRecord.session_id == session_id).delete()
        db.delete(session)
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
                # Seed long-term defaults before summary/assemble so final payload
                # fitting (and overflow coverage) matches what the model will see.
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

                # P2: compress older complete turns when they fall outside the
                # recent window. Soft-fail — never block the main request.
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
        """Persist results only if version + occupy lease still match (atomic gate)."""
        try:
            user_msg = self._add_message(db, session.id, "user", message)
            db.flush()

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

            # State commit rules per PRD §12.2
            state_json = session.state_json
            overrides_json = session.session_overrides_json
            next_version = started_version
            if outcome.commit_state and outcome.merged_state is not None:
                merged_overrides = outcome.merged_overrides or empty_overrides()
                new_state = outcome.merged_state.model_copy(deep=True)
                if outcome.update_last_recipe and recipe_id is not None:
                    # Only exclude previous title when user explicitly asked to swap.
                    if outcome.exclude_previous_recipe and outcome.recipe:
                        titles = [
                            t
                            for t in new_state.excluded_recipe_titles
                            if t.strip().casefold()
                            != outcome.recipe.title.strip().casefold()
                        ]
                        prev = None
                        if new_state.last_recipe_id is not None:
                            prev_row = db.get(RecipeRecord, new_state.last_recipe_id)
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
                # Do not freeze long-term-default-only fills into session state.
                before_state = load_session_state(session)
                persisted = persistable_session_state(
                    before_state, new_state, merged_overrides
                )
                state_json = serialize_state(persisted)
                overrides_json = serialize_overrides(merged_overrides)
                next_version = started_version + 1
                # Response panel should still show the effective merged constraints.
                outcome.merged_state = new_state

            # Final eligibility gate: version and occupy must still match.
            updated = (
                db.query(SessionRecord)
                .filter(
                    SessionRecord.id == session.id,
                    SessionRecord.context_version == started_version,
                    SessionRecord.active_request_id == occupy_id,
                )
                .update(
                    {
                        SessionRecord.state_json: state_json,
                        SessionRecord.session_overrides_json: overrides_json,
                        SessionRecord.context_version: next_version,
                        SessionRecord.last_active_at: datetime.now(timezone.utc),
                    },
                    synchronize_session=False,
                )
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
        now = datetime.now(timezone.utc)
        lease = timedelta(seconds=max(60.0, self.settings.request_timeout_seconds * 3))
        expires = now + lease

        # Conditional update: free or expired.
        updated = (
            db.query(SessionRecord)
            .filter(
                SessionRecord.id == session.id,
                or_(
                    SessionRecord.active_request_id.is_(None),
                    SessionRecord.active_request_expires_at.is_(None),
                    SessionRecord.active_request_expires_at < now,
                ),
            )
            .update(
                {
                    SessionRecord.active_request_id: occupy_id,
                    SessionRecord.active_request_expires_at: expires,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        if updated != 1:
            raise SessionBusyError("此对话正在生成，请稍后再试。")

    def _release_occupy(self, db: Session, session_id: str, occupy_id: str) -> None:
        try:
            db.query(SessionRecord).filter(
                SessionRecord.id == session_id,
                SessionRecord.active_request_id == occupy_id,
            ).update(
                {
                    SessionRecord.active_request_id: None,
                    SessionRecord.active_request_expires_at: None,
                },
                synchronize_session=False,
            )
            db.commit()
        except Exception:
            logger.exception("failed to release occupy session_id=%s", session_id)
            db.rollback()

    def _get_or_create_session(
        self, db: Session, session_id: str | None, *, user_id: str
    ) -> SessionRecord:
        if session_id:
            existing = db.get(SessionRecord, session_id)
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
        db.add(record)
        db.flush()
        return record

    def _require_owned_session(
        self, db: Session, session_id: str, user_id: str
    ) -> SessionRecord:
        session = db.get(SessionRecord, session_id)
        if not session or session.user_id != user_id:
            raise SessionNotFoundError("会话不存在。")
        return session

    def _session_has_messages(self, db: Session, session_id: str) -> bool:
        return (
            db.query(MessageRecord.id)
            .filter(MessageRecord.session_id == session_id)
            .limit(1)
            .first()
            is not None
        )

    def _session_title(self, db: Session, session_id: str) -> str:
        first = (
            db.query(MessageRecord)
            .filter(MessageRecord.session_id == session_id, MessageRecord.role == "user")
            .order_by(MessageRecord.created_at.asc(), MessageRecord.id.asc())
            .first()
        )
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
        paired: dict[int, Recipe] = {}
        used: set[int] = set()

        # Prefer explicit assistant_message_id links.
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

        # Legacy heuristic pairing for old rows without explicit links.
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
        row = MessageRecord(
            session_id=session_id,
            role=role,
            content=content,
            thinking=thinking,
            reply_to_message_id=reply_to_message_id,
            response_status=response_status,
        )
        db.add(row)
        return row

    def _save_recipe(
        self,
        db: Session,
        session_id: str,
        outcome: AgentOutcome,
        *,
        assistant_message_id: int | None = None,
    ) -> RecipeRecord:
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
        db.add(row)
        return row

    def _to_response(
        self,
        session: SessionRecord,
        outcome: AgentOutcome,
        *,
        long_term_applied: bool = False,
        long_term_version: int | None = None,
    ) -> ChatResponse:
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
