from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.schemas.chat import ChatPreferences
from app.schemas.context import (
    CLEARABLE_FIELDS,
    SETTABLE_SCALAR_FIELDS,
    PreferencePatch,
    SessionOverrides,
    SessionState,
    StateOps,
)
from app.schemas.recipe import Ingredient, Recipe


# Opposite dietary phrases that should replace each other rather than coexist.
_DIETARY_OPPOSITES: list[tuple[set[str], set[str]]] = [
    ({"不辣", "不要辣", "忌辣", "少辣"}, {"可以辣", "要辣", "能辣", "放辣"}),
    ({"不吃香菜", "不要香菜", "忌香菜"}, {"可以香菜", "能放香菜", "这次可以放香菜"}),
]


@dataclass
class MergeResult:
    state: SessionState
    overrides: SessionOverrides
    ok: bool = True
    clarification: str | None = None


def empty_state() -> SessionState:
    return SessionState()


def empty_overrides() -> SessionOverrides:
    return SessionOverrides()


def persistable_session_state(
    before: SessionState | None,
    after: SessionState,
    overrides: SessionOverrides,
) -> SessionState:
    """Persist only session-owned fields; leave default-only fills out of state_json.

    Ingredients / excluded titles / last_recipe always come from the merged result.
    Scalars and dietary lists persist only when explicitly set or cleared this session.
    """
    out = (before or empty_state()).model_copy(deep=True)
    out.ingredients = list(after.ingredients)
    out.excluded_recipe_titles = list(after.excluded_recipe_titles)
    out.last_recipe_id = after.last_recipe_id
    out.schema_version = after.schema_version

    touched = set(overrides.set_fields) | set(overrides.cleared_fields)
    if "dietary_restrictions" in touched:
        out.dietary_restrictions = list(after.dietary_restrictions)
    for field in ("servings", "max_time_minutes", "cuisine", "meal"):
        if field in touched:
            setattr(out, field, getattr(after, field))
    return out


def parse_state_json(raw: str | None) -> SessionState | None:
    if not raw:
        return None
    try:
        return SessionState.model_validate_json(raw)
    except Exception:
        return None


def parse_overrides_json(raw: str | None) -> SessionOverrides:
    if not raw:
        return empty_overrides()
    try:
        return SessionOverrides.model_validate_json(raw)
    except Exception:
        return empty_overrides()


def preferences_to_ops(preferences: ChatPreferences | None) -> StateOps:
    """Legacy preferences: only non-empty values become set ops; null/[] ignored."""
    from app.schemas.context import DietaryOps

    ops = StateOps()
    if not preferences:
        return ops
    if preferences.max_time_minutes is not None:
        ops.set["max_time_minutes"] = preferences.max_time_minutes
    if preferences.servings is not None:
        ops.set["servings"] = preferences.servings
    if preferences.dietary_restrictions:
        ops.dietary_restrictions = DietaryOps(add=list(preferences.dietary_restrictions))
    return ops


def preference_patch_to_ops(patch: PreferencePatch | None) -> StateOps:
    if not patch:
        return StateOps()
    return StateOps(set=dict(patch.set), clear=list(patch.clear))


def merge_ops(*ops_list: StateOps) -> StateOps:
    """Merge multiple op batches; later ops win for the same scalar set/clear."""
    from app.schemas.context import DietaryOps, IngredientOps

    merged = StateOps()
    ing = IngredientOps()
    diet = DietaryOps()
    has_ing = False
    has_diet = False

    for ops in ops_list:
        for key, value in ops.set.items():
            merged.set[key] = value
            if key in merged.clear:
                merged.clear = [c for c in merged.clear if c != key]
        for key in ops.clear:
            if key not in merged.clear:
                merged.clear.append(key)
            merged.set.pop(key, None)
        if ops.ingredients is not None:
            has_ing = True
            if ops.ingredients.replace is not None:
                ing = IngredientOps(
                    add=list(ops.ingredients.add),
                    remove=list(ops.ingredients.remove),
                    replace=list(ops.ingredients.replace),
                )
            else:
                if ing.replace is not None and not (
                    ops.ingredients.add or ops.ingredients.remove
                ):
                    pass
                # Accumulate add/remove onto current replace or add lists.
                if ing.replace is not None:
                    # Apply remove/add onto the replace list as working set.
                    working = _apply_ingredient_delta(
                        list(ing.replace),
                        add=ops.ingredients.add,
                        remove=ops.ingredients.remove,
                    )
                    ing = IngredientOps(replace=working)
                else:
                    ing.add = _merge_ingredients(ing.add, ops.ingredients.add)
                    for name in ops.ingredients.remove:
                        if name not in ing.remove:
                            ing.remove.append(name)
                        ing.add = [i for i in ing.add if not _same_ingredient(i.name, name)]
        if ops.dietary_restrictions is not None:
            has_diet = True
            d = ops.dietary_restrictions
            if d.replace is not None:
                diet = DietaryOps(
                    add=list(d.add),
                    remove=list(d.remove),
                    replace=list(d.replace),
                )
            elif diet.replace is not None:
                working = _apply_dietary_delta(
                    list(diet.replace), add=d.add, remove=d.remove
                )
                diet = DietaryOps(replace=working)
            else:
                diet.add = _merge_dietary(diet.add, d.add)
                for name in d.remove:
                    if name not in diet.remove:
                        diet.remove.append(name)
                    diet.add = [x for x in diet.add if not _same_text(x, name)]
        if ops.exclude_recipe_title:
            merged.exclude_recipe_title = ops.exclude_recipe_title

    if has_ing:
        merged.ingredients = ing
    if has_diet:
        merged.dietary_restrictions = diet
    return merged


def apply_long_term_defaults(
    current: SessionState | None,
    overrides: SessionOverrides | None,
    defaults: Any | None,
) -> SessionState:
    """Fill unset session fields from enabled long-term defaults.

    Cleared fields and already-set session values are not overwritten.
    Does not write allergies into session state (allergies are protective only).
    """
    base = (current or empty_state()).model_copy(deep=True)
    if defaults is None:
        return base
    cleared = set((overrides or empty_overrides()).cleared_fields)

    servings = getattr(defaults, "servings", None)
    if "servings" not in cleared and base.servings is None and servings is not None:
        base.servings = servings

    max_time = getattr(defaults, "max_time_minutes", None)
    if (
        "max_time_minutes" not in cleared
        and base.max_time_minutes is None
        and max_time is not None
    ):
        base.max_time_minutes = max_time

    cuisine = getattr(defaults, "cuisine", None)
    if "cuisine" not in cleared and base.cuisine is None and cuisine:
        base.cuisine = cuisine

    diet = list(getattr(defaults, "dietary_restrictions", None) or [])
    if "dietary_restrictions" not in cleared and not base.dietary_restrictions and diet:
        base.dietary_restrictions = diet[:10]

    return base


_ALLERGY_HARD_HINT = "请移除冲突食材；如声明有误，请到「我的做饭偏好」修改。"


def detect_allergy_conflict(
    allergies: list[str] | None,
    ops: StateOps,
) -> str | None:
    """Return a blocking clarification when this round conflicts with allergies.

    Allergies are hard constraints: chat cannot temporarily override them.
    Conflicts:
    - dietary text that allows an allergen (e.g. allergy=香菜, add=可以放香菜)
    - removing a restriction that mentions the allergen
    - adding/replacing ingredients whose name matches an allergen
    """
    if not allergies:
        return None
    allergy_names = [a.strip() for a in allergies if a and a.strip()]
    if not allergy_names:
        return None

    diet_texts: list[str] = []
    if ops.dietary_restrictions is not None:
        d = ops.dietary_restrictions
        diet_texts.extend(d.add)
        if d.replace is not None:
            diet_texts.extend(d.replace)
        for removed in d.remove:
            for allergy in allergy_names:
                if allergy in removed or removed in allergy or _same_text(removed, allergy):
                    return (
                        f"你保存了「{allergy}」过敏声明，不能在对话里临时忽略。"
                        f"{_ALLERGY_HARD_HINT}"
                    )

    for text in diet_texts:
        for allergy in allergy_names:
            if _allows_allergen(text, allergy):
                return (
                    f"你保存了「{allergy}」过敏声明，与本轮「{text}」冲突。"
                    f"{_ALLERGY_HARD_HINT}"
                )

    ingredient_names: list[str] = []
    if ops.ingredients is not None:
        ingredient_names.extend(i.name for i in ops.ingredients.add)
        if ops.ingredients.replace is not None:
            ingredient_names.extend(i.name for i in ops.ingredients.replace)

    for name in ingredient_names:
        for allergy in allergy_names:
            if (
                _same_ingredient(name, allergy)
                or allergy in name
                or name in allergy
            ):
                return (
                    f"你保存了「{allergy}」过敏声明，本轮食材含「{name}」。"
                    f"{_ALLERGY_HARD_HINT}"
                )
    return None


def recipe_conflicts_with_allergies(
    recipe: Recipe, allergies: list[str] | None
) -> str | None:
    """Return the first allergen found in recipe text, or None if clear."""
    if not allergies:
        return None
    haystack = " ".join(
        [
            recipe.title or "",
            recipe.summary or "",
            *[str(x) for x in recipe.ingredients],
            *[str(x) for x in recipe.steps],
            *[str(x) for x in recipe.tips],
        ]
    )
    for allergy in allergies:
        a = (allergy or "").strip()
        if a and a in haystack:
            return a
    return None


def _allows_allergen(text: str, allergy: str) -> bool:
    """Heuristic: phrases that permit an allergen despite allergy declaration."""
    t = text.strip()
    if not t or allergy not in t:
        return False
    deny_markers = ("不", "忌", "别", "勿", "过敏")
    if any(m in t for m in deny_markers):
        return False
    allow_markers = ("可以", "能", "要", "放", "加", "吃")
    return any(m in t for m in allow_markers)


def apply_state_ops(
    current: SessionState | None,
    overrides: SessionOverrides | None,
    ops: StateOps,
    *,
    require_ingredients_for_generate: bool = False,
) -> MergeResult:
    """Deterministically apply validated ops onto session state."""
    base = (current or empty_state()).model_copy(deep=True)
    ov = (overrides or empty_overrides()).model_copy(deep=True)

    # Validate scalar set keys / values first; reject whole batch on illegal ops.
    try:
        _validate_ops(ops)
    except ValueError as exc:
        return MergeResult(
            state=base,
            overrides=ov,
            ok=False,
            clarification=str(exc),
        )

    # Clear fields
    for field in ops.clear:
        _clear_field(base, field)
        if field not in ov.cleared_fields:
            ov.cleared_fields.append(field)
        ov.set_fields.pop(field, None)

    # Scalar sets
    for key, value in ops.set.items():
        if key not in SETTABLE_SCALAR_FIELDS:
            continue
        setattr(base, key, value)
        ov.set_fields[key] = value
        ov.cleared_fields = [c for c in ov.cleared_fields if c != key]

    # Ingredients
    if ops.ingredients is not None:
        ing_ops = ops.ingredients
        if ing_ops.replace is not None:
            base.ingredients = _normalize_ingredients(ing_ops.replace)
        else:
            if ing_ops.remove:
                base.ingredients = [
                    i
                    for i in base.ingredients
                    if not any(_same_ingredient(i.name, name) for name in ing_ops.remove)
                ]
            if ing_ops.add:
                base.ingredients = _merge_ingredients(base.ingredients, ing_ops.add)
        ov.set_fields["ingredients"] = [i.model_dump() for i in base.ingredients]
        ov.cleared_fields = [c for c in ov.cleared_fields if c != "ingredients"]
        if not base.ingredients and "ingredients" in ops.clear:
            pass

    # Dietary restrictions
    if ops.dietary_restrictions is not None:
        d_ops = ops.dietary_restrictions
        if d_ops.replace is not None:
            base.dietary_restrictions = _normalize_dietary(d_ops.replace)
        else:
            if d_ops.remove:
                base.dietary_restrictions = [
                    x
                    for x in base.dietary_restrictions
                    if not any(_same_text(x, name) for name in d_ops.remove)
                ]
            if d_ops.add:
                base.dietary_restrictions = _merge_dietary(
                    base.dietary_restrictions, d_ops.add
                )
        ov.set_fields["dietary_restrictions"] = list(base.dietary_restrictions)
        ov.cleared_fields = [
            c for c in ov.cleared_fields if c != "dietary_restrictions"
        ]

    if ops.exclude_recipe_title:
        title = ops.exclude_recipe_title.strip()
        if title:
            titles = [t for t in base.excluded_recipe_titles if not _same_text(t, title)]
            titles.append(title)
            base.excluded_recipe_titles = titles[-10:]

    if require_ingredients_for_generate and not base.ingredients:
        return MergeResult(
            state=base,
            overrides=ov,
            ok=False,
            clarification="还不知道你有哪些食材，请告诉我冰箱里有什么，或者想做什么菜。",
        )

    return MergeResult(state=base, overrides=ov, ok=True)


def state_to_constraints_dict(state: SessionState) -> dict[str, Any]:
    return {
        "ingredients": [i.model_dump() for i in state.ingredients],
        "meal": state.meal,
        "max_time_minutes": state.max_time_minutes,
        "servings": state.servings,
        "cuisine": state.cuisine,
        "dietary_restrictions": list(state.dietary_restrictions),
        "excluded_recipe_titles": list(state.excluded_recipe_titles),
    }


def _validate_ops(ops: StateOps) -> None:
    for key, value in ops.set.items():
        if key not in SETTABLE_SCALAR_FIELDS and key not in CLEARABLE_FIELDS:
            raise ValueError(f"不支持设置字段：{key}")
        if key == "servings":
            if not isinstance(value, int) or not (1 <= value <= 20):
                raise ValueError("人数需在 1–20 之间。")
        if key == "max_time_minutes":
            if not isinstance(value, int) or not (1 <= value <= 300):
                raise ValueError("时间上限需在 1–300 分钟之间。")
        if key in {"meal", "cuisine"}:
            if value is not None and (not isinstance(value, str) or len(value) > 50):
                raise ValueError(f"{key} 无效。")
    for key in ops.clear:
        if key not in CLEARABLE_FIELDS:
            raise ValueError(f"不支持清除字段：{key}")


def _clear_field(state: SessionState, field: str) -> None:
    if field == "ingredients":
        state.ingredients = []
    elif field == "dietary_restrictions":
        state.dietary_restrictions = []
    elif field in SETTABLE_SCALAR_FIELDS:
        setattr(state, field, None)


def _same_ingredient(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def _same_text(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def _normalize_ingredients(items: list[Ingredient]) -> list[Ingredient]:
    result: list[Ingredient] = []
    for item in items:
        name = item.name.strip()
        if not name:
            continue
        quantity = item.quantity.strip() if item.quantity else None
        merged = False
        for existing in result:
            if _same_ingredient(existing.name, name):
                existing.quantity = quantity if quantity else existing.quantity
                merged = True
                break
        if not merged:
            result.append(Ingredient(name=name, quantity=quantity))
    return result[:30]


def _merge_ingredients(
    current: list[Ingredient], additions: list[Ingredient]
) -> list[Ingredient]:
    return _normalize_ingredients([*current, *additions])


def _apply_ingredient_delta(
    current: list[Ingredient],
    *,
    add: list[Ingredient],
    remove: list[str],
) -> list[Ingredient]:
    working = [
        i
        for i in current
        if not any(_same_ingredient(i.name, name) for name in remove)
    ]
    return _merge_ingredients(working, add)


def _normalize_dietary(items: list[str]) -> list[str]:
    result: list[str] = []
    for raw in items:
        text = raw.strip()
        if not text:
            continue
        result = _add_dietary(result, text)
    return result[:10]


def _merge_dietary(current: list[str], additions: list[str]) -> list[str]:
    result = list(current)
    for raw in additions:
        text = raw.strip()
        if text:
            result = _add_dietary(result, text)
    return result[:10]


def _apply_dietary_delta(
    current: list[str], *, add: list[str], remove: list[str]
) -> list[str]:
    working = [
        x for x in current if not any(_same_text(x, name) for name in remove)
    ]
    return _merge_dietary(working, add)


def _add_dietary(current: list[str], text: str) -> list[str]:
    """Add a dietary restriction, replacing opposite phrases when detected."""
    result = list(current)
    for left, right in _DIETARY_OPPOSITES:
        in_left = any(_same_text(text, x) for x in left)
        in_right = any(_same_text(text, x) for x in right)
        if in_left:
            result = [x for x in result if not any(_same_text(x, y) for y in right)]
        if in_right:
            result = [x for x in result if not any(_same_text(x, y) for y in left)]
    if not any(_same_text(x, text) for x in result):
        result.append(text)
    return result
