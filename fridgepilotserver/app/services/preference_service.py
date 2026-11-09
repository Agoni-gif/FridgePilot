from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import UserPreferenceRecord
from app.schemas.preferences import (
    PreferenceValues,
    UserPreferencesPatch,
    UserPreferencesResponse,
)

logger = logging.getLogger(__name__)

_SETTABLE = frozenset(
    {"servings", "max_time_minutes", "cuisine", "dietary_restrictions", "allergies"}
)


class PreferenceConflictError(Exception):
    """Optimistic lock conflict on preferences version."""


class PreferenceLoadError(Exception):
    """Failed to load preferences when they are required for generation."""


class PreferenceService:
    def get(self, db: Session, *, user_id: str) -> UserPreferencesResponse:
        row = db.get(UserPreferenceRecord, user_id)
        if not row:
            return UserPreferencesResponse(
                enabled=False,
                preferences=PreferenceValues(),
                version=0,
                updated_at=None,
                exists=False,
            )
        return self._to_response(row)

    def get_enabled_values(
        self, db: Session, *, user_id: str
    ) -> tuple[PreferenceValues | None, int | None]:
        """Return (values, version) when enabled; (None, None) when absent/disabled.

        Raises PreferenceLoadError on corrupt JSON for an enabled record so generation
        does not silently omit hard dietary constraints.
        """
        try:
            row = db.get(UserPreferenceRecord, user_id)
        except Exception as exc:
            raise PreferenceLoadError("读取做饭偏好失败，请稍后重试。") from exc
        if not row or not row.enabled:
            return None, None
        try:
            values = PreferenceValues.model_validate_json(row.preferences_json)
        except Exception as exc:
            logger.exception("corrupt preferences_json user_id=%s", user_id)
            raise PreferenceLoadError(
                "做饭偏好数据异常，请到「我的做饭偏好」检查后重试。"
            ) from exc
        return values, row.version

    def patch(
        self, db: Session, *, user_id: str, body: UserPreferencesPatch
    ) -> UserPreferencesResponse:
        row = db.get(UserPreferenceRecord, user_id)
        if row is None:
            if body.version != 0:
                raise PreferenceConflictError("偏好版本已变化，请刷新后重试。")
            values = PreferenceValues()
            self._apply_patch(values, body)
            enabled = 0 if body.enabled is None else (1 if body.enabled else 0)
            row = UserPreferenceRecord(
                user_id=user_id,
                enabled=enabled,
                preferences_json=values.model_dump_json(),
                version=1,
                updated_at=datetime.now(timezone.utc),
            )
            db.add(row)
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                # Concurrent first-time create lost the race.
                raise PreferenceConflictError("偏好版本已变化，请刷新后重试。") from exc
            db.refresh(row)
            return self._to_response(row)

        # Build next values from the currently observed row, then commit with a
        # version-conditioned UPDATE so concurrent writers cannot both succeed.
        values = PreferenceValues.model_validate_json(row.preferences_json)
        self._apply_patch(values, body)
        next_enabled = row.enabled if body.enabled is None else (1 if body.enabled else 0)
        next_version = body.version + 1
        now = datetime.now(timezone.utc)

        updated = (
            db.query(UserPreferenceRecord)
            .filter(
                UserPreferenceRecord.user_id == user_id,
                UserPreferenceRecord.version == body.version,
            )
            .update(
                {
                    UserPreferenceRecord.enabled: next_enabled,
                    UserPreferenceRecord.preferences_json: values.model_dump_json(),
                    UserPreferenceRecord.version: next_version,
                    UserPreferenceRecord.updated_at: now,
                },
                synchronize_session=False,
            )
        )
        if updated != 1:
            db.rollback()
            raise PreferenceConflictError("偏好版本已变化，请刷新后重试。")
        db.commit()
        refreshed = db.get(UserPreferenceRecord, user_id)
        assert refreshed is not None
        return self._to_response(refreshed)

    def delete(self, db: Session, *, user_id: str) -> UserPreferencesResponse:
        row = db.get(UserPreferenceRecord, user_id)
        if row is not None:
            db.delete(row)
            db.commit()
        return UserPreferencesResponse(
            enabled=False,
            preferences=PreferenceValues(),
            version=0,
            updated_at=None,
            exists=False,
        )

    def _apply_patch(self, values: PreferenceValues, body: UserPreferencesPatch) -> None:
        for key in body.clear:
            if key == "dietary_restrictions":
                values.dietary_restrictions = []
            elif key == "allergies":
                values.allergies = []
            elif key in {"servings", "max_time_minutes", "cuisine"}:
                setattr(values, key, None)

        for key, raw in body.set.items():
            if key not in _SETTABLE:
                continue
            if key == "servings":
                values.servings = int(raw) if raw is not None else None
            elif key == "max_time_minutes":
                values.max_time_minutes = int(raw) if raw is not None else None
            elif key == "cuisine":
                values.cuisine = str(raw).strip() if raw else None
            elif key == "dietary_restrictions":
                if isinstance(raw, list):
                    values.dietary_restrictions = [
                        str(x).strip() for x in raw if str(x).strip()
                    ][:10]
            elif key == "allergies":
                if isinstance(raw, list):
                    values.allergies = [
                        str(x).strip() for x in raw if str(x).strip()
                    ][:10]
        # Re-validate ranges
        PreferenceValues.model_validate(values.model_dump())

    @staticmethod
    def _to_response(row: UserPreferenceRecord) -> UserPreferencesResponse:
        try:
            prefs = PreferenceValues.model_validate_json(row.preferences_json)
        except Exception:
            prefs = PreferenceValues()
        return UserPreferencesResponse(
            enabled=bool(row.enabled),
            preferences=prefs,
            version=row.version,
            updated_at=row.updated_at,
            exists=True,
        )
