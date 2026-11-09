from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.common.api_codes import ApiCode
from app.common.response import api_error
from app.db.models import User
from app.db.session import get_db
from app.schemas.preferences import UserPreferencesPatch, UserPreferencesResponse
from app.services.preference_service import PreferenceConflictError, PreferenceService

router = APIRouter(prefix="/api/v1/me", tags=["preferences"])
_service = PreferenceService()


@router.get("/preferences", response_model=UserPreferencesResponse)
async def get_my_preferences(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UserPreferencesResponse:
    return _service.get(db, user_id=user.id)


@router.patch("/preferences", response_model=UserPreferencesResponse)
async def patch_my_preferences(
    body: UserPreferencesPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UserPreferencesResponse:
    try:
        return _service.patch(db, user_id=user.id, body=body)
    except PreferenceConflictError as exc:
        raise api_error(ApiCode.PREFERENCE_VERSION_CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise api_error(ApiCode.PREFERENCE_INVALID, str(exc)) from exc


@router.delete("/preferences", response_model=UserPreferencesResponse)
async def delete_my_preferences(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UserPreferencesResponse:
    return _service.delete(db, user_id=user.id)
