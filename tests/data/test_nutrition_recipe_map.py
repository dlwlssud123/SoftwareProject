"""DB 활성 판본 → 레시피 재료 식품 매핑 행 (nutrition.recipe_map) — 백엔드 map_recipe_foods 의 입력."""

import json

from agetech_data.nutrition.build import build_recipe_nutrition
from agetech_data.nutrition.recipe_map import food_records, map_sha256, recipe_map_rows
from agetech_data.recipes.validate import check_recipe


def _recipe(seq, parts):
    row = {"RCP_SEQ": seq, "RCP_NM": f"시험{seq}", "RCP_PARTS_DTLS": parts, "MANUAL01": "1. 만든다"}
    row.update({f"MANUAL{i:02d}": "" for i in range(2, 21)})
    return row


def _db_recipe(row):
    """DB recipe_ingredients.parsed 와 같은 형태(JSON 왕복)로 재료를 넘긴다."""
    check = json.loads(json.dumps(check_recipe(row).to_dict(), ensure_ascii=False))
    return {"recipe_id": check["source_id"], "ingredients": check["ingredients"]}


ENTRY = {"ingredient": "저염간장", "food_code": "P112-005000400-F002-001", "rationale": "저염 간장",
         "reviewed_by": "최재영", "reviewed_at": "2026-11-09"}


def test_db_shape_gives_the_same_result_as_the_file_build(sample_foods):
    rows = [_recipe("1", "양파 50g, 물 300ml, 감자 100g, 대파(1대), 저염간장 10g"),
            _recipe("2", "양파 50g, 다진 마늘 5g, 물 100ml")]
    expected = {r["source_id"]: r for r in build_recipe_nutrition(rows, sample_foods, (ENTRY,))}
    foods = food_records(json.loads(json.dumps([f.to_dict() for f in sample_foods], ensure_ascii=False)))
    got = recipe_map_rows([_db_recipe(r) for r in rows], foods, (ENTRY,))
    for row in got:
        ref = expected[row["recipe_id"]]
        assert [{k: v for k, v in i.items() if k != "review"} for i in row["ingredients"]] == ref["ingredients"]
        assert (row["computed"], row["coverage"], row["computed_missing"]) == (
            ref["computed"], ref["coverage"], ref["computed_missing"])


def test_reviewed_manual_mapping_carries_reviewer_and_order(sample_foods):
    recipe = _db_recipe(_recipe("1", "양파 50g, 저염간장 10g"))
    recipe["ingredients"].reverse()                        # DB 조회 순서와 무관하게 order_no 순
    [row] = recipe_map_rows([recipe], sample_foods, (ENTRY,))
    onion, soy = row["ingredients"]
    assert onion["order_no"] < soy["order_no"] and onion["review"] is None
    assert soy["match"]["status"] == "reviewed" and soy["review"] == {"by": "최재영", "on": "2026-11-09"}
    [curated] = recipe_map_rows([recipe], sample_foods, ({**ENTRY, "reviewed_by": None},))
    assert curated["ingredients"][1]["match"]["status"] == "curated" and curated["ingredients"][1]["review"] is None
    assert curated["content_sha256"] != row["content_sha256"]


def test_content_hash_tracks_food_values_and_map(sample_foods):
    recipe = _db_recipe(_recipe("1", "양파 50g"))
    [first] = recipe_map_rows([recipe], sample_foods, ())
    [again] = recipe_map_rows([recipe], sample_foods, ())
    assert first["content_sha256"] == again["content_sha256"]
    changed = [f.to_dict() for f in sample_foods]
    onion = next(f for f in changed if f["name"] == "양파, 생것")
    onion["nutrients"]["energy_kcal"] = (onion["nutrients"]["energy_kcal"] or 0) + 10
    [moved] = recipe_map_rows([recipe], food_records(changed), ())
    assert moved["content_sha256"] != first["content_sha256"]
    assert map_sha256(()) != map_sha256((ENTRY,))
