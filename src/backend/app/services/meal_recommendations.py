from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from agetech_data.textutil import nfc

from app.schemas.catalog import RecipeRecommendationRequest, RecipeRecord
from app.schemas.profile import Preferences

RULES_VERSION = "meal-rules-1"

TIME_CATEGORIES = {
    "breakfast": {"밥", "국&찌개"},
    "lunch": {"밥", "일품"},
    "dinner": {"국&찌개", "반찬", "일품"},
    "snack": {"후식"},
}


def _key(text: str | None) -> str:
    return "".join(nfc(text).casefold().split())


@dataclass
class Candidate:
    record: RecipeRecord
    category: str
    score: int
    reasons: list[str]


def recommend(
    records: Iterable[RecipeRecord],
    payload: RecipeRecommendationRequest,
    preferences: Preferences,
    recent_foods: Iterable[str],
) -> list[tuple[RecipeRecord, list[str]]]:
    exclusions = {
        _key(name)
        for name in (*payload.exclude_ingredients, *preferences.excluded_ingredients)
    } - {""}
    preferred = {_key(name) for name in preferences.preferred_ingredients} - {""}
    recent = {_key(name) for name in recent_foods} - {""}
    has_allergies = bool(payload.exclude_allergens or preferences.exclude_allergens)
    pool = []
    for record in records:
        ingredients = {_key(item.name) for item in record.ingredients} - {""}
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
        favorite = bool(ingredients & preferred)
        time_match = category in TIME_CATEGORIES[payload.meal_time]
        recent_match = bool(ingredients & recent or _key(record.name) in recent)
        soft_match = preferences.soft_food and record.name.endswith("죽")
        reasons = []
        if has_allergies:
            reasons.append("재료 정보에서 선택한 알레르기 제외 조건을 확인했어요.")
        if exclusions:
            reasons.append("선택한 제외 재료가 재료 목록에 표시되지 않아요.")
        if favorite:
            reasons.append("좋아하는 재료가 들어 있어요.")
        if time_match:
            reasons.append("선택한 식사 시간에 맞는 메뉴 유형이에요.")
        if soft_match:
            reasons.append("부드러운 음식을 선호해서 죽 메뉴를 우선했어요.")
        if recent and not recent_match and ingredients:
            reasons.append("최근 식사 기록에 이름이 일치하는 메뉴나 재료가 없어요.")
        score = 4 * int(favorite) + 3 * int(time_match) + 3 * int(bool(soft_match))
        score -= 4 * int(recent_match)
        pool.append(Candidate(record, category, score, reasons))

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
