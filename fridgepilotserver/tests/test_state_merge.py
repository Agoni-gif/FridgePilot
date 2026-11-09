from __future__ import annotations

from app.schemas.chat import ChatPreferences
from app.schemas.context import (
    DietaryOps,
    IngredientOps,
    PreferencePatch,
    SessionState,
    StateOps,
)
from app.schemas.recipe import Ingredient
from app.services.state_merge import (
    apply_state_ops,
    empty_state,
    preference_patch_to_ops,
    preferences_to_ops,
)


def _names(state: SessionState) -> list[str]:
    return [i.name for i in state.ingredients]


def test_add_then_remove_ingredients():
    base = SessionState(
        ingredients=[Ingredient(name="番茄"), Ingredient(name="鸡蛋")],
        servings=2,
    )
    added = apply_state_ops(
        base,
        None,
        StateOps(ingredients=IngredientOps(add=[Ingredient(name="土豆")])),
    )
    assert added.ok
    assert _names(added.state) == ["番茄", "鸡蛋", "土豆"]

    removed = apply_state_ops(
        added.state,
        added.overrides,
        StateOps(ingredients=IngredientOps(remove=["鸡蛋"])),
    )
    assert removed.ok
    assert _names(removed.state) == ["番茄", "土豆"]

    # Idempotent remove
    again = apply_state_ops(
        removed.state,
        removed.overrides,
        StateOps(ingredients=IngredientOps(remove=["鸡蛋"])),
    )
    assert again.ok
    assert _names(again.state) == ["番茄", "土豆"]


def test_replace_all_ingredients():
    base = SessionState(
        ingredients=[Ingredient(name="番茄"), Ingredient(name="鸡蛋")],
    )
    result = apply_state_ops(
        base,
        None,
        StateOps(
            ingredients=IngredientOps(
                replace=[Ingredient(name="牛肉"), Ingredient(name="土豆")]
            )
        ),
    )
    assert result.ok
    assert _names(result.state) == ["牛肉", "土豆"]


def test_update_servings_and_time_keeps_ingredients():
    base = SessionState(
        ingredients=[Ingredient(name="番茄"), Ingredient(name="鸡蛋")],
        servings=2,
    )
    result = apply_state_ops(
        base,
        None,
        StateOps(set={"servings": 4, "max_time_minutes": 20}),
    )
    assert result.ok
    assert result.state.servings == 4
    assert result.state.max_time_minutes == 20
    assert _names(result.state) == ["番茄", "鸡蛋"]


def test_clear_time_does_not_revive():
    base = SessionState(
        ingredients=[Ingredient(name="番茄")],
        max_time_minutes=20,
    )
    cleared = apply_state_ops(
        base,
        None,
        StateOps(clear=["max_time_minutes"]),
    )
    assert cleared.ok
    assert cleared.state.max_time_minutes is None
    assert "max_time_minutes" in cleared.overrides.cleared_fields

    # Later unrelated set should not restore time
    next_round = apply_state_ops(
        cleared.state,
        cleared.overrides,
        StateOps(set={"servings": 3}),
    )
    assert next_round.state.max_time_minutes is None
    assert next_round.state.servings == 3


def test_dietary_opposite_replace():
    base = SessionState(dietary_restrictions=["不要辣"])
    result = apply_state_ops(
        base,
        None,
        StateOps(dietary_restrictions=DietaryOps(add=["可以辣"])),
    )
    assert result.ok
    assert result.state.dietary_restrictions == ["可以辣"]


def test_exclude_recipe_title_capped_at_10():
    base = empty_state()
    state = base
    overrides = None
    for i in range(12):
        merged = apply_state_ops(
            state,
            overrides,
            StateOps(exclude_recipe_title=f"菜{i}"),
        )
        state = merged.state
        overrides = merged.overrides
    assert len(state.excluded_recipe_titles) == 10
    assert state.excluded_recipe_titles[0] == "菜2"
    assert state.excluded_recipe_titles[-1] == "菜11"


def test_legacy_empty_preferences_do_not_clear():
    base = SessionState(
        ingredients=[Ingredient(name="番茄")],
        servings=2,
        dietary_restrictions=["不辣"],
    )
    ops = preferences_to_ops(
        ChatPreferences(max_time_minutes=None, servings=None, dietary_restrictions=[])
    )
    result = apply_state_ops(base, None, ops)
    assert result.ok
    assert result.state.servings == 2
    assert result.state.dietary_restrictions == ["不辣"]


def test_preference_patch_clear_and_set():
    base = SessionState(servings=2, max_time_minutes=20)
    ops = preference_patch_to_ops(
        PreferencePatch(set={"servings": 4}, clear=["max_time_minutes"])
    )
    result = apply_state_ops(base, None, ops)
    assert result.ok
    assert result.state.servings == 4
    assert result.state.max_time_minutes is None


def test_same_name_ingredient_quantity_override():
    base = SessionState(ingredients=[Ingredient(name="番茄", quantity="1个")])
    result = apply_state_ops(
        base,
        None,
        StateOps(ingredients=IngredientOps(add=[Ingredient(name="番茄", quantity="2个")])),
    )
    assert result.ok
    assert len(result.state.ingredients) == 1
    assert result.state.ingredients[0].quantity == "2个"


def test_illegal_servings_rejected():
    result = apply_state_ops(
        empty_state(),
        None,
        StateOps(set={"servings": 99}),
    )
    assert not result.ok
    assert result.clarification
