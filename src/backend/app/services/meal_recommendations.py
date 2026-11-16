from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from statistics import median
from uuid import UUID

from agetech_data.nutrition.match import prep_alias
from agetech_data.textutil import nfc

from app.schemas.catalog import RecipeRecommendationRequest, RecipeRecord, SeasonalMatch
from app.schemas.profile import Preferences

RULES_VERSION = "meal-rules-4"
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
    soft_match: bool
    simple_match: bool


def _is_soft_menu(record: RecipeRecord) -> bool:
    name = _key(record.name)
    if name.endswith(("죽", "미음")) and not name.endswith(("반죽", "가죽")):
        return True
    method = _key(record.cooking_method)
    if method == "찌기" and name.endswith(("계란찜", "달걀찜", "두부찜")):
        return True
    if method == "끓이기" and name.endswith(("스프", "수프")):
        for step in record.steps:
            text = _key(step.text)
            blended = "믹서" in text and any(
                word in text for word in ("갈아", "간다", "간뒤")
            )
            if blended or ("으깨" in text and "체에거" in text):
                return True
    return False


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
) -> list[Candidate]:
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
        soft_match = (preferences.soft_food or payload.soft_food) and _is_soft_menu(
            record
        )
        simple_match = (
            payload.simple_cooking
            and bool(record.ingredients)
            and len(record.ingredients) <= 6
            and 1 <= len(record.steps) <= 4
            and not record.missing_step_nos
        )
        reasons = []
        if exclusions:
            reasons.append("선택한 제외 재료가 재료 목록에 표시되지 않아요.")
        if favorites:
            reasons.append(f"좋아하는 재료 {', '.join(favorites[:2])}가 들어 있어요.")
        if time_match:
            reasons.append("선택한 식사 시간에 맞는 메뉴 유형이에요.")
        if soft_match:
            reasons.append("메뉴 이름과 조리법을 참고해 부드러운 요리로 골랐어요.")
        if simple_match:
            reasons.append(
                f"재료 {len(record.ingredients)}가지, 조리 {len(record.steps)}단계예요."
            )
        if recent and not recent_match and ingredients:
            reasons.append("최근 식사 기록에 이름이 일치하는 메뉴나 재료가 없어요.")
        score = 6 * min(len(favorites), 2) + 3 * int(time_match)
        was_featured = (
            record.recipe_id in featured_ids or _key(record.name) in featured_names
        )
        score -= 7 * int(recent_match) + 5 * int(was_featured)
        if seasonal.get(record.source.revision_id):
            score += 1
            reasons.append("이달의 식재료가 들어 있어요.")
        pool.append(
            Candidate(record, category, score, reasons, soft_match, simple_match)
        )

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
                    f"공개 레시피를 비교했을 때 {label} 표기량이 낮은 편이에요."
                )

    used_categories: Counter[str] = Counter()
    used_names: set[str] = set()
    results = []
    while pool and len(results) < payload.limit:
        best = min(
            pool,
            key=lambda entry: (
                -int(entry.soft_match) - int(entry.simple_match),
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
        results.append(best)
    return results
