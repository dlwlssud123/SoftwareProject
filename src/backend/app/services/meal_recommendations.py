from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from statistics import median
from uuid import UUID

from agetech_data.nutrition.match import prep_alias
from agetech_data.textutil import nfc

from app.schemas.catalog import RecipeRecommendationRequest, RecipeRecord, SeasonalMatch
from app.schemas.profile import Preferences

RULES_VERSION = "meal-rules-3"
HEALTH_METRICS = {
    "hypertension": ("sodium_mg", "나트륨"),
    "diabetes": ("carbohydrate_g", "탄수화물"),
}

TIME_CATEGORIES = {
    "breakfast": {"밥", "국&찌개"},
    "lunch": {"밥", "일품"},
    "dinner": {"국&찌개", "반찬", "일품"},
    "snack": {"후식"},
}
INGREDIENT_ALIASES = {"계란": "달걀"}


def _key(text: str | None) -> str:
    return "".join(nfc(text).casefold().split())


def _ingredient_keys(name: str) -> set[str]:
    keys = {_key(name)}
    if alias := prep_alias(name):
        keys.add(_key(alias))
        name = alias
    for prefix in ("다진 ", "데친 ", "손질한 "):
        if name.startswith(prefix):
            keys.add(_key(name.removeprefix(prefix)))
    return {INGREDIENT_ALIASES.get(key, key) for key in keys if key}


def _preference_key(name: str) -> str:
    return min(
        _ingredient_keys(name), key=lambda value: (len(value), value), default=""
    )


@dataclass
class Candidate:
    record: RecipeRecord
    category: str
    score: int
    reasons: list[str]


def _nutrient(record: RecipeRecord, field: str) -> float | None:
    value = getattr(record.nutrition, field)
    # The public source uses unverified serving sizes and may contain zero placeholders.
    return (
        value
        if not record.nutrition.suspect and value is not None and value > 0
        else None
    )


def recommend(
    records: Iterable[RecipeRecord],
    payload: RecipeRecommendationRequest,
    preferences: Preferences,
    recent_foods: Iterable[str],
    seasonal: dict[UUID, list[SeasonalMatch]],
    recently_featured: Iterable[tuple[str, str]],
    recently_eaten_revisions: set[UUID],
) -> list[tuple[RecipeRecord, list[str]]]:
    exclusions = {
        key
        for name in (*payload.exclude_ingredients, *preferences.excluded_ingredients)
        for key in {_key(name), *_ingredient_keys(name)}
        if key
    }
    preferred = tuple(
        dict.fromkeys(
            _preference_key(name)
            for name in (
                *payload.preferred_ingredients,
                *preferences.preferred_ingredients,
            )
            if _key(name)
        )
    )
    recent = {
        key for name in recent_foods for key in _ingredient_keys(name.partition(",")[0])
    }
    featured_ids, featured_names = set(), set()
    for source_id, name in recently_featured:
        featured_ids.add(source_id)
        featured_names.add(_key(name))
    has_allergies = bool(payload.exclude_allergens or preferences.exclude_allergens)
    pool = []
    for record in records:
        ingredients = set().union(
            *(_ingredient_keys(item.name) for item in record.ingredients)
        )
        category = record.category or ""
        ingredient_text = ingredients | {
            _key(record.ingredients_text),
            _key(record.name),
            *(_key(item.name_raw) for item in record.ingredients),
        }
        if exclusions and (
            not ingredients
            or any(name in source for name in exclusions for source in ingredient_text)
        ):
            continue
        names_by_key = {
            _preference_key(item.name): item.name for item in record.ingredients
        }
        favorites = [names_by_key[key] for key in preferred if key in names_by_key]
        time_match = category in TIME_CATEGORIES[payload.meal_time]
        recent_match = (
            record.source.revision_id in recently_eaten_revisions
            or bool(ingredients & recent)
            or _key(record.name) in recent
        )
        soft_match = (
            preferences.soft_food or payload.soft_food
        ) and record.name.endswith("죽")
        simple_match = (
            payload.simple_cooking
            and bool(record.ingredients)
            and len(record.ingredients) <= 6
            and 1 <= len(record.steps) <= 4
            and not record.missing_step_nos
        )
        reasons = []
        if has_allergies:
            reasons.append("재료 정보에서 선택한 알레르기 제외 조건을 확인했어요.")
        if exclusions:
            reasons.append("선택한 제외 재료가 재료 목록에 표시되지 않아요.")
        if favorites:
            reasons.append(f"좋아하는 재료 {', '.join(favorites[:2])}가 들어 있어요.")
        if time_match:
            reasons.append("선택한 식사 시간에 맞는 메뉴 유형이에요.")
        if soft_match:
            reasons.append("부드러운 음식을 골라 죽 메뉴에 가점을 줬어요.")
        if simple_match:
            reasons.append(
                f"재료 {len(record.ingredients)}가지, 조리 {len(record.steps)}단계예요."
            )
        if recent and not recent_match and ingredients:
            reasons.append("최근 식사 기록에 이름이 일치하는 메뉴나 재료가 없어요.")
        score = 6 * min(len(favorites), 2) + 3 * int(time_match)
        score += 6 * int(bool(soft_match)) + 6 * int(simple_match)
        was_featured = (
            record.recipe_id in featured_ids or _key(record.name) in featured_names
        )
        score -= 7 * int(recent_match) + 5 * int(was_featured)
        if seasonal.get(record.source.revision_id):
            score += 1
            reasons.append("이달의 식재료가 들어 있어요.")
        pool.append(Candidate(record, category, score, reasons))

    for condition in dict.fromkeys(payload.health_conditions):
        field, label = HEALTH_METRICS[condition]
        known = [
            (entry, value)
            for entry in pool
            if (value := _nutrient(entry.record, field)) is not None
        ]
        if len({value for _, value in known}) < 2:
            continue
        middle = median(value for _, value in known)
        for entry, value in known:
            if value < middle:
                entry.score += 2
                entry.reasons.append(
                    f"공개 수치가 있는 후보 중 {label} 표기량이 중간값보다 낮아요."
                )

    used_categories: Counter[str] = Counter()
    used_names: set[str] = set()
    results = []
    while pool and len(results) < payload.limit:
        best = min(
            pool,
            key=lambda entry: (
                -entry.score + 4 * used_categories[entry.category],
                int(entry.record.recipe_id),
                entry.record.recipe_id,
            ),
        )
        pool.remove(best)
        name = _key(best.record.name)
        if name in used_names:
            continue
        used_names.add(name)
        used_categories[best.category] += 1
        results.append((best.record, best.reasons or ["현재 공개된 레시피예요."]))
    return results
