from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.agent.orchestrator import AgentOrchestrator
from app.common.config import Settings, get_settings
from app.common.logging_setup import preview_text
from app.db.session import get_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import ChatService

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
    return {"status": "ok"}


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    request_id = getattr(request.state, "request_id", "-")
    if len(body.message) > settings.max_message_length:
        logger.warning(
            "request_id=%s chat rejected: input too long len=%s",
            request_id,
            len(body.message),
        )
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INPUT_TOO_LONG",
                "message": f"输入过长，最多 {settings.max_message_length} 个字符。",
            },
        )

    logger.info(
        "request_id=%s chat start session_id=%s message=%r prefs=%s",
        request_id,
        body.session_id or "(new)",
        preview_text(body.message),
        body.preferences.model_dump() if body.preferences else None,
    )

    response = await service.handle_chat(
        db=db,
        message=body.message,
        session_id=body.session_id,
        preferences=body.preferences,
        request_id=request_id,
    )

    logger.info(
        "request_id=%s chat done status=%s session_id=%s elapsed_ms=%s recipe=%s",
        request_id,
        response.status,
        response.session_id,
        response.meta.elapsed_ms,
        response.recipe.title if response.recipe else None,
    )
    return response
