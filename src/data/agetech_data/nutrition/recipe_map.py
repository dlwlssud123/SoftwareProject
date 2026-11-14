"""DB 활성 판본(레시피 재료·식품) → 레시피 재료 식품 매핑·계산 영양 행 (backend app.jobs.map_recipe_foods 의 입력).

    from agetech_data.nutrition.recipe_map import food_records, recipe_map_rows
    rows = recipe_map_rows(recipes, food_records(normalized_foods))
    # recipes = [{"recipe_id": 원천 ID, "ingredients": [recipe_ingredients.parsed, …]}]
    # normalized_foods = [food_revisions.normalized, …]   (= nutrition.foods.FoodRecord.to_dict())

- 매핑·g 환산·기여량 계산은 nutrition.build.ingredient_nutrition 그대로다(docs/data/food_nutrition_contract.md 3절).
  파일 산출물(recipe_ingredient_nutrition.json)과 같은 함수라 같은 입력이면 같은 값이 나온다.
- 수동 매핑표(resources/ingredient_food_map.json)로 정한 재료는 확인자·확인일(review)을 같이 넘긴다 — 정의서 6절
  "curated → reviewed 전환 이력". 매핑표 자체의 변경 이력은 git 에 있다.
- content_sha256 = 레시피 하나의 매핑·계산 결과 해시. 레시피·식품·매핑표 중 무엇이 바뀌어 결과가 달라졌는지 가린다.
"""

from __future__ import annotations

from agetech_data.nutrition.build import ingredient_nutrition
from agetech_data.nutrition.foods import FoodRecord
from agetech_data.nutrition.match import FoodIndex, load_ingredient_map, manual_entry
from agetech_data.textutil import sha256_json

MAPPER_VERSION = "recipe-food-map-v5"  # v2: 계량 단위·출처 있는 개당 중량(unit_weight) 환산
#                                        v3: coverage 에 정성 분량(qualitative_items·complete_except_qualitative)
#                                        v4: 손질 표기(○○다진것·○○채썬것)·'다진 ○○' 이 기본 재료 매핑을 따름,
#                                            먹지 않는 재료 excluded(0 으로 취급)·coverage.missing_items·excluded_items
#                                        v5: 출처 없는 g 추정(gram status estimated, estimated_amounts.json)·
#                                            coverage.estimated_items, 매핑표 food_factor, 튀김기름 자동 판정(조리방법),
#                                            이름 정리·상태근사·어순·구획 끝말 규칙 확장


def food_records(normalized: list[dict]) -> list[FoodRecord]:
    """DB food_revisions.normalized → 정제 식품 레코드(clean_foods 결과와 같은 형태, 보정 반영됨)."""
    return [FoodRecord(**record) for record in normalized]


def map_sha256(entries) -> str:
    return sha256_json(list(entries))


def _review(item: dict, ingredient: dict, entries) -> dict | None:
    rule = item["match"]["rule"] or ""
    if rule != "manual" and not rule.endswith("+manual"):   # 손질+manual·다진+manual = 기본 재료의 매핑표 결정
        return None
    parens = ingredient.get("paren_texts") or []
    # 갈라진 앞말을 붙여 찾은 줄('미니' / '양배추(5개)' → '미니 양배추')은 매칭에 쓴 이름(item)으로 찾는다
    entry = manual_entry(item.get("name") or ingredient["name"], parens, entries) or manual_entry(
        ingredient["name"], parens, entries)
    if not entry or not entry.get("reviewed_by"):
        return None
    return {"by": entry["reviewed_by"], "on": entry.get("reviewed_at")}


def recipe_map_rows(recipes: list[dict], foods: list[FoodRecord], entries=None) -> list[dict]:
    """레시피마다 {recipe_id, ingredients[…, review], computed, computed_missing, coverage, content_sha256}."""
    entries = load_ingredient_map() if entries is None else entries
    index = FoodIndex(foods)
    by_code = {f.food_code: f for f in foods}
    cache: dict = {}
    out = []
    for recipe in recipes:
        ingredients = sorted(recipe["ingredients"], key=lambda i: i["order_no"])
        result = ingredient_nutrition(ingredients, index, by_code, entries, cache,
                                      cooking_method=recipe.get("cooking_method"), recipe_id=recipe["recipe_id"])
        for item, ingredient in zip(result["ingredients"], ingredients, strict=True):
            item["review"] = _review(item, ingredient, entries)
        out.append({"recipe_id": recipe["recipe_id"], **result, "content_sha256": sha256_json(result)})
    return out
