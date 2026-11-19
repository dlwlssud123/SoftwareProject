"""Build shopping amounts from immutable planned recipe revisions, without serving guesses."""

import hashlib
import json
import math
import re
import unicodedata
from decimal import Decimal
from fractions import Fraction
from urllib.parse import urlencode

from sqlalchemy import case, select

from app.jobs.import_public_data import RECIPE_PROVIDER
from app.models import (
    MealPlanEntry,
    Recipe,
    RecipeIngredient,
    RecipeRevision,
    ShoppingCheck,
)
from app.schemas.meal_plan import MealSlot
from app.schemas.shopping import ShoppingItem, ShoppingList, ShoppingSource

_UNITS = {
    "g": ("g", Fraction(1)),
    "kg": ("g", Fraction(1000)),
    "mg": ("g", Fraction(1, 1000)),
    "mL": ("mL", Fraction(1)),
    "ml": ("mL", Fraction(1)),
    "cc": ("mL", Fraction(1)),
    "L": ("mL", Fraction(1000)),
}
for _unit in (
    "개",
    "알",
    "장",
    "쪽",
    "뿌리",
    "줄기",
    "대",
    "송이",
    "마리",
    "톨",
    "큰술",
    "작은술",
    "컵",
    "Ts",
    "ts",
    "T",
    "t",
    "Tbsp",
    "tsp",
):
    _UNITS[_unit] = (_unit, Fraction(1))
_QUANTITY = re.compile(r"(?P<amount>\d+(?:\.\d+)?(?:/\d+)?)\s*(?P<unit>[^\s\d]+)")


def _hash(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _name(value):
    return " ".join(unicodedata.normalize("NFC", value).split())


def shopping_url(name):
    # Only public ingredient names enter the vendor URL; never profile or location fields.
    return "https://www.coupang.com/np/search?" + urlencode({"q": name})


def _quantity(item):
    parsed = item.parsed
    match = _QUANTITY.fullmatch((item.amount_text or "").strip())
    if parsed.get("amount_kind") != "measured" or match is None:
        return None, None
    raw_unit = match["unit"]
    if raw_unit not in _UNITS or raw_unit != parsed.get("unit"):
        return None, None
    try:
        amount = Fraction(match["amount"])
        if amount <= 0 or not math.isclose(
            float(amount), float(parsed["amount"]), rel_tol=1e-9, abs_tol=1e-9
        ):
            return None, None
        unit, multiplier = _UNITS[raw_unit]
        return amount * multiplier, unit
    except (ValueError, TypeError, KeyError, ZeroDivisionError, OverflowError):
        return None, None


def _display(amount):
    denominator = amount.denominator
    for factor in (2, 5):
        while denominator % factor == 0:
            denominator //= factor
    if denominator != 1:
        return f"{amount.numerator}/{amount.denominator}"
    return (
        format(Decimal(amount.numerator) / Decimal(amount.denominator), "f")
        .rstrip("0")
        .rstrip(".")
        if amount.denominator != 1
        else str(amount.numerator)
    )


def build_shopping_list(db, user_id, plan_date):
    rows = db.execute(
        select(MealPlanEntry, Recipe, RecipeRevision, RecipeIngredient)
        .join(RecipeRevision, RecipeRevision.id == MealPlanEntry.recipe_revision_id)
        .join(Recipe, Recipe.id == RecipeRevision.recipe_id)
        .outerjoin(
            RecipeIngredient, RecipeIngredient.recipe_revision_id == RecipeRevision.id
        )
        .where(
            MealPlanEntry.user_id == user_id,
            MealPlanEntry.plan_date == plan_date,
            Recipe.provider == RECIPE_PROVIDER,
        )
        .order_by(
            case(
                {slot.value: i for i, slot in enumerate(MealSlot)},
                value=MealPlanEntry.meal_slot,
            ),
            RecipeIngredient.order_no,
        )
    )
    groups, meals, warnings = {}, set(), []
    for entry, recipe, revision, ingredient in rows:
        meals.add(entry.id)
        active = (
            recipe.active_revision_id == revision.id
            and revision.quality_status != "hold"
        )
        if (
            not active
            and "저장한 레시피가 변경된 메뉴가 있어요. 식단에서 확인해 주세요."
            not in warnings
        ):
            warnings.append(
                "저장한 레시피가 변경된 메뉴가 있어요. 식단에서 확인해 주세요."
            )
        if ingredient is None:
            message = (
                f"{revision.name}: 원천에 재료 정보가 없어요. 레시피를 확인해 주세요."
            )
            if message not in warnings:
                warnings.append(message)
            continue
        name = _name(ingredient.name_raw or ingredient.name)
        amount, unit = _quantity(ingredient)
        key = _hash([name, unit])
        group = groups.setdefault(
            key, {"name": name, "unit": unit, "amount": Fraction(0), "sources": []}
        )
        if amount is not None:
            group["amount"] += amount
        group["sources"].append(
            ShoppingSource(
                plan_entry_id=entry.id,
                meal_slot=entry.meal_slot,
                recipe_id=recipe.source_id,
                recipe_name=revision.name,
                recipe_revision_id=revision.id,
                ingredient_id=ingredient.id,
                section=ingredient.section or None,
                name_raw=ingredient.name_raw,
                amount_text=ingredient.amount_text or None,
                is_active=active,
            )
        )
    checks = {
        row.item_key: row
        for row in db.scalars(
            select(ShoppingCheck).where(
                ShoppingCheck.user_id == user_id, ShoppingCheck.plan_date == plan_date
            )
        )
    }
    items = []
    for key, group in sorted(
        groups.items(), key=lambda pair: (pair[1]["name"], pair[1]["unit"] or "")
    ):
        sources = group["sources"]
        source_hash = _hash([source.model_dump(mode="json") for source in sources])
        total = group["amount"]
        combined = group["unit"] is not None
        try:
            numeric = float(total) if combined else None
            combined = combined and math.isfinite(numeric)
        except OverflowError:
            numeric, combined = None, False
        item = ShoppingItem(
            item_key=key,
            source_hash=source_hash,
            name=group["name"],
            amount=numeric if combined else None,
            unit=group["unit"] if combined else None,
            amount_text=f"{_display(total)} {group['unit']}"
            if combined
            else " / ".join(source.amount_text or "분량 미제공" for source in sources),
            combined=combined,
            checked=key in checks
            and checks[key].source_hash == source_hash
            and checks[key].checked,
            shopping_search_url=shopping_url(group["name"]),
            sources=sources,
        )
        items.append(item)
    return ShoppingList(
        plan_date=plan_date, planned_meals=len(meals), items=items, warnings=warnings
    )
