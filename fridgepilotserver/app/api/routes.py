from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.agent.orchestrator import AgentOrchestrator
from app.api.deps import get_current_user
from app.common.api_codes import ApiCode
from app.common.config import Settings, get_settings
from app.common.logging_setup import preview_text
from app.common.response import api_error, error_detail
from app.db.models import User
from app.db.session import get_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.context import PublicContext
from app.schemas.session import SessionListResponse, SessionMessagesResponse
from app.services.chat_service import (
    ChatService,
    SessionAccessError,
    SessionBusyError,
    SessionConflictError,
    SessionNotFoundError,
)

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger(__name__)


def get_orchestrator(settings: Settings = Depends(get_settings)) -> AgentOrchestrator:
    return AgentOrchestrator(settings)


def get_chat_service(
    settings: Settings = Depends(get_settings),
    orchestrator: AgentOrchestrator = Depends(get_orchestrator),
) -> ChatService:
    return ChatService(settings, orchestrator)


@router.get("/health")
async def health() -> dict[str, str]:
    from app.db.session import engine

    return {"status": "ok", "db": engine.dialect.name}


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    db: Session = Depends(get_db),
    service: ChatService = Depends(get_chat_service),
    user: User = Depends(get_current_user),
) -> SessionListResponse:
    return SessionListResponse(sessions=service.list_sessions(db, user_id=user.id))


@router.get("/sessions/{session_id}/messages", response_model=SessionMessagesResponse)
async def get_session_messages(
    session_id: str,
    db: Session = Depends(get_db),
    service: ChatService = Depends(get_chat_service),
    user: User = Depends(get_current_user),
) -> SessionMessagesResponse:
    try:
        return service.get_session_messages(db, session_id=session_id, user_id=user.id)
    except SessionNotFoundError as exc:
        raise api_error(ApiCode.SESSION_NOT_FOUND, str(exc)) from exc


@router.get("/sessions/{session_id}/context", response_model=PublicContext)
async def get_session_context(
    session_id: str,
    db: Session = Depends(get_db),
    service: ChatService = Depends(get_chat_service),
    user: User = Depends(get_current_user),
) -> PublicContext:
    try:
        return service.get_context(db, session_id=session_id, user_id=user.id)
    except SessionNotFoundError as exc:
        raise api_error(ApiCode.SESSION_NOT_FOUND, str(exc)) from exc


@router.delete("/sessions/{session_id}/context", response_model=PublicContext)
async def clear_session_context(
    session_id: str,
    db: Session = Depends(get_db),
    service: ChatService = Depends(get_chat_service),
    user: User = Depends(get_current_user),
) -> PublicContext:
    try:
        return service.clear_context(db, session_id=session_id, user_id=user.id)
    except SessionNotFoundError as exc:
        raise api_error(ApiCode.SESSION_NOT_FOUND, str(exc)) from exc


@router.delete("/sessions/{session_id}", status_code=204, response_class=Response)
async def delete_session(
    session_id: str,
    db: Session = Depends(get_db),
    service: ChatService = Depends(get_chat_service),
    user: User = Depends(get_current_user),
) -> Response:
    try:
        service.delete_session(db, session_id=session_id, user_id=user.id)
    except SessionNotFoundError as exc:
        raise api_error(ApiCode.SESSION_NOT_FOUND, str(exc)) from exc
    return Response(status_code=204)


def _validate_chat_length(body: ChatRequest, settings: Settings, request_id: str) -> None:
    if len(body.message) > settings.max_message_length:
        logger.warning(
            "request_id=%s chat rejected: input too long len=%s",
            request_id,
            len(body.message),
        )
        raise api_error(
            ApiCode.INPUT_TOO_LONG,
            f"输入过长，最多 {settings.max_message_length} 个字符。",
        )


def _http_from_session_error(exc: Exception):
    if isinstance(exc, SessionNotFoundError):
        return api_error(ApiCode.SESSION_NOT_FOUND, str(exc))
    if isinstance(exc, SessionAccessError):
        return api_error(ApiCode.SESSION_FORBIDDEN, str(exc))
    if isinstance(exc, SessionBusyError):
        return api_error(ApiCode.SESSION_BUSY, str(exc))
    if isinstance(exc, SessionConflictError):
        return api_error(ApiCode.SESSION_CONFLICT, str(exc))
    raise exc


def _sse_error(code: ApiCode, message: str | None = None) -> dict:
    return {"type": "error", **error_detail(code, message)}


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    service: ChatService = Depends(get_chat_service),
    user: User = Depends(get_current_user),
) -> ChatResponse:
    request_id = getattr(request.state, "request_id", "-")
    _validate_chat_length(body, settings, request_id)

    logger.info(
        "request_id=%s user_id=%s chat start session_id=%s message=%r prefs=%s",
        request_id,
        user.id,
        body.session_id or "(new)",
        preview_text(body.message),
        body.preferences.model_dump() if body.preferences else None,
    )

    try:
        response = await service.handle_chat(
            db=db,
            message=body.message,
            session_id=body.session_id,
            preferences=body.preferences,
            preference_patch=body.preference_patch,
            user_id=user.id,
            request_id=request_id,
        )
    except (
        SessionAccessError,
        SessionNotFoundError,
        SessionBusyError,
        SessionConflictError,
    ) as exc:
        raise _http_from_session_error(exc) from exc

    logger.info(
        "request_id=%s chat done status=%s session_id=%s elapsed_ms=%s recipe=%s",
        request_id,
        response.status,
        response.session_id,
        response.meta.elapsed_ms,
        response.recipe.title if response.recipe else None,
    )
    return response


@router.post("/chat/stream")
async def chat_stream(
    body: ChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    service: ChatService = Depends(get_chat_service),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    request_id = getattr(request.state, "request_id", "-")
    _validate_chat_length(body, settings, request_id)

    logger.info(
        "request_id=%s user_id=%s chat stream start session_id=%s message=%r",
        request_id,
        user.id,
        body.session_id or "(new)",
        preview_text(body.message),
    )

    user_id = user.id

    # Pre-validate ownership / busy lease before opening SSE so clients can get
    # HTTP 404/403/409 instead of only an in-band error event.
    try:
        service.ensure_session_available(
            db, session_id=body.session_id, user_id=user_id
        )
    except (
        SessionAccessError,
        SessionNotFoundError,
        SessionBusyError,
    ) as exc:
        raise _http_from_session_error(exc) from exc
    async def event_stream() -> AsyncIterator[str]:
        queue: asyncio.Queue[dict | None] = asyncio.Queue()

        async def on_progress(text: str) -> None:
            await queue.put({"type": "thinking", "content": text})

        async def worker() -> None:
            try:
                response = await service.handle_chat(
                    db=db,
                    message=body.message,
                    session_id=body.session_id,
                    preferences=body.preferences,
                    preference_patch=body.preference_patch,
                    user_id=user_id,
                    request_id=request_id,
                    on_progress=on_progress,
                )
                await queue.put(
                    {
                        "type": "done",
                        "data": response.model_dump(mode="json"),
                    }
                )
            except SessionBusyError as exc:
                await queue.put(_sse_error(ApiCode.SESSION_BUSY, str(exc)))
            except SessionConflictError as exc:
                await queue.put(_sse_error(ApiCode.SESSION_CONFLICT, str(exc)))
            except SessionAccessError as exc:
                await queue.put(_sse_error(ApiCode.SESSION_FORBIDDEN, str(exc)))
            except SessionNotFoundError as exc:
                await queue.put(_sse_error(ApiCode.SESSION_NOT_FOUND, str(exc)))
            except Exception:
                logger.exception("request_id=%s chat stream failed", request_id)
                await queue.put(_sse_error(ApiCode.INTERNAL_ERROR))
            finally:
                await queue.put(None)

        task = asyncio.create_task(worker())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        finally:
            await task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
