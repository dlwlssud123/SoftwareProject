"""레시피 계산 영양 → 앱 API 응답 블록(`computed_nutrition`, 정의서 3.4).

레시피 응답의 `nutrition`은 원천이 적은 1인분 값(근거 없는 1인분, `per_serving_unverified`)이고, 이 블록은
재료 목록 전체를 식품 DB로 계산한 값이다(`whole_recipe`). 입력은 둘 중 하나:

- 파일: `build.py`가 쓴 레시피 레코드(`computed`, `computed_missing`, `density`, `coverage`)
- DB: 뷰 `recipe_nutrition_active`(또는 `recipe_computed_nutrition`) 한 행 — 비교 값이 칸 4개로 따로 있음

몇 인분인지는 재료 원문에 'N인분'이 있을 때만 안다(레시피 계약 `nutrition.ingredient_servings`). 그때만
`per_serving` = 합계 ÷ N 이고, 없으면 1인분을 지어내지 않고 null 이다.
"""

from __future__ import annotations

from collections.abc import Mapping

from agetech_data.nutrition.build import DENSITY

BASIS = "whole_recipe"
# 앱 영양 화면 다섯 성분이 앞, 나머지는 DB에 있는 순서. 다섯 성분은 원천에 빈 값이 없게 채웠다(정의서 2.1)
NUTRIENTS = (
    "energy_kcal", "carbohydrate_g", "protein_g", "fat_g", "sodium_mg",
    "sugars_g", "fiber_g", "sat_fat_g", "cholesterol_mg", "potassium_mg", "calcium_mg",
)
NUTRIENT_LABELS = {
    "energy_kcal": "열량", "carbohydrate_g": "탄수화물", "protein_g": "단백질", "fat_g": "지방",
    "sodium_mg": "나트륨", "sugars_g": "당류", "fiber_g": "식이섬유", "sat_fat_g": "포화지방",
    "cholesterol_mg": "콜레스테롤", "potassium_mg": "칼륨", "calcium_mg": "칼슘",
}
# 화면 안내 — code 는 고정, label 은 화면에 그대로 써도 되는 문장(재료 이름은 items 로 따로)
NOTICES = {
    "partial": "일부 재료만 계산한 값이에요",
    "qualitative_not_counted": "'약간·적당량'이라 양을 모르는 재료는 계산에 넣지 않았어요",
    "amount_unknown": "양을 몰라 계산에 넣지 않은 재료가 있어요",
    "estimated_amount": "일부 재료는 양을 추정했어요",
    "filled_value": "일부 식품의 성분은 다른 자료로 채운 값이에요",
}


def _round(value) -> float | None:
    return None if value is None else round(float(value), 1)


def _items(rows, keys: tuple[str, ...]) -> list[dict]:
    return [{k: row[k] for k in keys if row.get(k) is not None} for row in rows or []]


def computed_nutrition_block(summary: Mapping, servings: float | None = None) -> dict:
    """계산 영양 한 레시피 → API 블록. `servings` 는 재료 원문의 'N인분'(없으면 None)."""
    computed = summary.get("computed") or {}
    missing = summary.get("computed_missing") or {}
    coverage = summary.get("coverage") or {}
    density = summary.get("density") or {k: summary.get(k) for k in DENSITY}
    complete = bool(summary["complete"] if "complete" in summary else coverage.get("complete"))
    total = {k: _round(computed.get(k)) for k in NUTRIENTS}
    per_serving = None
    if servings:
        per_serving = {k: None if computed.get(k) is None else round(float(computed[k]) / servings, 1)
                       for k in NUTRIENTS}
    notices = []
    if not complete:
        notices.append(("partial", []))
    notices += [
        ("qualitative_not_counted", _items(coverage.get("qualitative_items"), ("name", "amount_text"))),
        ("amount_unknown", _items(coverage.get("missing_items"), ("name", "amount_text", "reason"))),
        ("estimated_amount", _items(coverage.get("estimated_items"), ("name", "amount_text", "grams"))),
        ("filled_value", _items(coverage.get("filled_items"), ("name", "food_name", "nutrients"))),
    ]
    return {
        "basis": BASIS,
        "servings": servings or None,
        "total": total,
        "per_serving": per_serving,
        # 값이 없는 재료가 있어 그 성분은 일부 재료 합계 — 비교·판정에 쓰지 않는다
        "partial_nutrients": [k for k in NUTRIENTS if missing.get(k)],
        "complete": complete,
        "density": {k: _round(density.get(k)) for k in DENSITY},
        "notices": [{"code": code, "label": NOTICES[code], "items": items}
                    for code, items in notices if code == "partial" or items],
        "version": summary.get("mapper_version"),
    }
