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


def test_mapping_inherited_from_base_manual_entry_carries_its_reviewer(sample_foods):
    entry = {"ingredient": "감자", "food_code": "R102-001140001-0000", "rationale": "품종 미기재",
             "reviewed_by": "최재영", "reviewed_at": "2026-11-13"}
    [row] = recipe_map_rows([_db_recipe(_recipe("1", "감자다진것 50g, 다진 감자 20g, 감자채썬것 10g"))],
                            sample_foods, (entry,))
    assert [i["match"]["rule"] for i in row["ingredients"]] == ["손질+다진+manual", "다진+manual", "손질+manual"]
    assert all(i["match"]["status"] == "reviewed" and i["review"] == {"by": "최재영", "on": "2026-11-13"}
               for i in row["ingredients"])


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


def test_qualitative_seasonings_are_listed_and_kept_out_of_complete(sample_foods):
    # '약간·적당량'은 g을 지어내지 않는다. complete 는 엄격하게 두고, 그것만 빠졌는지를 따로 남긴다
    rows = [_recipe("1", "양파 50g, 소금 약간, 후춧가루 적당량"),
            _recipe("2", "양파 50g, 레몬(1개), 소금 약간"),
            _recipe("3", "양파 50g, 물 100ml")]
    got = {r["source_id"]: r["coverage"] for r in build_recipe_nutrition(rows, sample_foods, ())}
    assert (got["1"]["complete"], got["1"]["complete_except_qualitative"]) == (False, True)
    assert [(q["name"], q["amount_text"]) for q in got["1"]["qualitative_items"]] == [
        ("소금", "약간"), ("후춧가루", "적당량")]
    assert (got["2"]["complete"], got["2"]["complete_except_qualitative"]) == (False, False)  # 레몬 '1개'(환산표에 없음)
    assert (got["3"]["complete"], got["3"]["complete_except_qualitative"], got["3"]["qualitative_items"]) == (
        True, True, [])


def test_missing_items_say_why_and_excluded_items_count_as_zero(sample_foods):
    # 몰라서 뺀 재료는 이유와 함께 남기고, 먹지 않는 재료는 물처럼 0으로 쳐서 완전 판정을 막지 않는다
    entries = (
        {"ingredient": "월계수잎", "food_code": None, "exclude": "not_eaten", "rationale": "건져 냄"},
        {"ingredient": "튀김기름", "food_code": None, "rationale": "흡수량 모름"},
    )
    rows = [_recipe("1", "양파 50g, 월계수잎 1g, 물 100ml"),
            _recipe("2", "양파 50g, 튀김기름 200g, 이름없는재료 10g, 레몬(1개), 소금 약간")]
    got = {r["source_id"]: r for r in build_recipe_nutrition(rows, sample_foods, entries)}
    one = got["1"]["coverage"]
    assert one["complete"] and one["missing_items"] == []
    assert one["excluded_items"] == [{"name": "월계수잎", "amount_text": "1g", "note": "건져 냄"}]
    assert one["grams_converted"] == 50.0                       # 무게 비율에서도 물·월계수잎은 뺌
    assert [i["match"]["status"] for i in got["1"]["ingredients"]] == ["exact", "excluded", "water"]
    assert got["1"]["ingredients"][1]["match"]["rule"] == "manual:not_eaten"
    two = got["2"]["coverage"]
    assert not two["complete"] and [q["name"] for q in two["qualitative_items"]] == ["소금"]
    assert [(m["name"], m["reason"]) for m in two["missing_items"]] == [
        ("튀김기름", "no_food"), ("이름없는재료", "food_undecided"), ("레몬", "food_undecided")]
    assert two["missing_items"][0]["note"] == "흡수량 모름"
    # 식품은 정했지만 g을 모르는 재료 (개당 중량표에 '봉지'가 없음)
    [onion] = build_recipe_nutrition([_recipe("3", "양파 1봉지")], sample_foods, ())[0]["coverage"]["missing_items"]
    assert (onion["reason"], onion["amount_text"]) == ("grams_unknown", "1봉지") and "환산표에 없어" in onion["note"]
