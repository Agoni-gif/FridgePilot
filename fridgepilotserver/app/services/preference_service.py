"""用户长期做饭偏好业务。

读写走 preference_repository；乐观锁冲突与 commit/rollback 由本层处理。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import UserPreferenceRecord
from app.repositories import preference_repository
from app.schemas.preferences import (
    PreferenceValues,
    UserPreferencesPatch,
    UserPreferencesResponse,
)

logger = logging.getLogger(__name__)

# 允许通过 patch.set 写入的字段白名单
_SETTABLE = frozenset(
    {"servings", "max_time_minutes", "cuisine", "dietary_restrictions", "allergies"}
)


class PreferenceConflictError(Exception):
    """偏好版本乐观锁冲突（并发写入或客户端 version 过期）。"""


class PreferenceLoadError(Exception):
    """生成流程需要偏好但读取失败（含损坏 JSON）。"""


class PreferenceService:
    """偏好查询、补丁更新与删除。"""

    def get(self, db: Session, *, user_id: str) -> UserPreferencesResponse:
        """读取偏好；不存在时返回空默认结构（exists=False）。"""
        row = preference_repository.get_by_user_id(db, user_id)
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
        """返回已启用的偏好值与版本；未启用/不存在则 (None, None)。

        已启用但 JSON 损坏时抛 PreferenceLoadError，避免生成静默丢掉忌口约束。
        """
        try:
            row = preference_repository.get_by_user_id(db, user_id)
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
        """按 version 补丁更新；首次创建或条件更新失败均映射为冲突。"""
        row = preference_repository.get_by_user_id(db, user_id)
        if row is None:
            # 首次创建必须带 version=0，否则视为客户端过期
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
            preference_repository.add(db, row)
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                # 并发首次创建：唯一约束冲突，输家视为版本冲突
                raise PreferenceConflictError("偏好版本已变化，请刷新后重试。") from exc
            db.refresh(row)
            return self._to_response(row)

        # 基于当前行拼出下一版，再用 user_id+version 条件 UPDATE，避免丢更新
        values = PreferenceValues.model_validate_json(row.preferences_json)
        self._apply_patch(values, body)
        next_enabled = row.enabled if body.enabled is None else (1 if body.enabled else 0)
        next_version = body.version + 1
        now = datetime.now(timezone.utc)

        updated = preference_repository.update_if_version(
            db,
            user_id=user_id,
            expected_version=body.version,
            enabled=next_enabled,
            preferences_json=values.model_dump_json(),
            next_version=next_version,
            updated_at=now,
        )
        if updated != 1:
            db.rollback()
            raise PreferenceConflictError("偏好版本已变化，请刷新后重试。")
        db.commit()
        refreshed = preference_repository.get_by_user_id(db, user_id)
        assert refreshed is not None
        return self._to_response(refreshed)

    def delete(self, db: Session, *, user_id: str) -> UserPreferencesResponse:
        """删除偏好；不存在时也返回空默认结构。"""
        row = preference_repository.get_by_user_id(db, user_id)
        if row is not None:
            preference_repository.delete(db, row)
            db.commit()
        return UserPreferencesResponse(
            enabled=False,
            preferences=PreferenceValues(),
            version=0,
            updated_at=None,
            exists=False,
        )

    def _apply_patch(self, values: PreferenceValues, body: UserPreferencesPatch) -> None:
        """先 clear 再 set，最后再校验取值范围。"""
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
        # 再次校验取值范围
        PreferenceValues.model_validate(values.model_dump())

    @staticmethod
    def _to_response(row: UserPreferenceRecord) -> UserPreferencesResponse:
        """ORM 行转 API 响应；JSON 损坏时降级为空偏好。"""
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
