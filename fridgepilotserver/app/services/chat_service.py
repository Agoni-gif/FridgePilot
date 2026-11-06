from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.agent.orchestrator import AgentOrchestrator, AgentOutcome
from app.common.config import Settings
from app.common.logging_setup import preview_text
from app.db.models import MessageRecord, RecipeRecord, SessionRecord
from app.schemas.chat import ChatMeta, ChatPreferences, ChatResponse

logger = logging.getLogger(__name__)


class SessionAccessError(Exception):
    """Raised when a client tries to resume another user's chat session."""


class ChatService:
    def __init__(self, settings: Settings, orchestrator: AgentOrchestrator) -> None:
        self.settings = settings
        self.orchestrator = orchestrator

    async def handle_chat(
        self,
        *,
        db: Session,
        message: str,
        session_id: str | None,
        preferences: ChatPreferences | None,
        user_id: str,
        request_id: str = "-",
    ) -> ChatResponse:
        session = self._get_or_create_session(db, session_id, user_id=user_id)
        created = session_id != session.id
        logger.info(
            "request_id=%s user_id=%s session %s id=%s",
            request_id,
            user_id,
            "created" if created or not session_id else "resumed",
            session.id,
        )
        self._add_message(db, session.id, "user", message)

        outcome = await self.orchestrator.run(
            message,
            preferences,
            request_id=request_id,
        )
        response = self._to_response(session.id, outcome)

        assistant_text = response.message or (
            response.recipe.title if response.recipe else response.status
        )
        self._add_message(db, session.id, "assistant", assistant_text)

        if outcome.recipe is not None:
            self._save_recipe(db, session.id, outcome)
            logger.info(
                "request_id=%s recipe saved title=%r sources=%s",
                request_id,
                outcome.recipe.title,
                len(outcome.recipe.sources),
            )

        session.last_active_at = datetime.now(timezone.utc)
        db.commit()
        logger.debug(
            "request_id=%s db commit ok assistant=%r",
            request_id,
            preview_text(assistant_text),
        )
        return response

    def _get_or_create_session(
        self, db: Session, session_id: str | None, *, user_id: str
    ) -> SessionRecord:
        if session_id:
            existing = db.get(SessionRecord, session_id)
            if existing:
                if existing.user_id and existing.user_id != user_id:
                    raise SessionAccessError("无权访问该会话。")
                if existing.user_id is None:
                    existing.user_id = user_id
                return existing
        new_id = secrets.token_urlsafe(16)
        record = SessionRecord(id=new_id, user_id=user_id)
        db.add(record)
        db.flush()
        return record

    def _add_message(self, db: Session, session_id: str, role: str, content: str) -> None:
        db.add(MessageRecord(session_id=session_id, role=role, content=content))

    def _save_recipe(self, db: Session, session_id: str, outcome: AgentOutcome) -> None:
        assert outcome.recipe is not None
        db.add(
            RecipeRecord(
                session_id=session_id,
                recipe_json=outcome.recipe.model_dump_json(),
                sources_json=json.dumps(
                    [s.model_dump() for s in outcome.recipe.sources],
                    ensure_ascii=False,
                ),
                prompt_version=outcome.prompt_version,
            )
        )

    def _to_response(self, session_id: str, outcome: AgentOutcome) -> ChatResponse:
        return ChatResponse(
            session_id=session_id,
            status=outcome.status,  # type: ignore[arg-type]
            recipe=outcome.recipe,
            message=outcome.message,
            meta=ChatMeta(
                search_used=outcome.search_used,
                elapsed_ms=outcome.elapsed_ms,
                prompt_version=outcome.prompt_version,
                detail=outcome.message if outcome.status != "completed" else None,
            ),
        )
