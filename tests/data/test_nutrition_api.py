"""레시피 계산 영양 → 앱 API 블록 (agetech_data.nutrition.api, 정의서 3.4)."""

from decimal import Decimal

import pytest

from agetech_data.nutrition.api import NOTICES, NUTRIENTS, computed_nutrition_block
from agetech_data.nutrition.build import DENSITY, build_recipe_nutrition


def _recipe(seq, parts):
    row = {"RCP_SEQ": seq, "RCP_NM": f"시험{seq}", "RCP_PARTS_DTLS": parts, "MANUAL01": "1. 만든다"}
    row.update({f"MANUAL{i:02d}": "" for i in range(2, 21)})
    return row


def test_complete_recipe_gives_totals_and_per_serving_only_with_servings(sample_foods):
    [rec] = build_recipe_nutrition([_recipe("1", "양파 100g, 물 200ml")], sample_foods, [])
    block = computed_nutrition_block(rec)
    assert block["basis"] == "whole_recipe" and block["complete"]
    assert list(block["total"]) == list(NUTRIENTS)
    assert block["total"]["energy_kcal"] == round(rec["computed"]["energy_kcal"], 1)
    assert block["servings"] is None and block["per_serving"] is None   # 몇 인분인지 모르면 1인분을 만들지 않음
    halves = computed_nutrition_block(rec, servings=2)
    assert halves["per_serving"]["energy_kcal"] == round(rec["computed"]["energy_kcal"] / 2, 1)
    assert set(block["density"]) == set(DENSITY)
    # 원문 g 과 물뿐이라 알릴 것이 없음 — 안내는 해당하는 것만
    assert block["notices"] == []


def test_partial_recipe_lists_what_was_left_out_or_estimated():
    summary = {
        "computed": {"energy_kcal": 300.04, "sodium_mg": 812.26, "sugars_g": 3.0},
        "computed_missing": {"sugars_g": 2},
        "density": {"sodium_mg_per_1000kcal": None},
        "coverage": {
            "complete": False,
            "qualitative_items": [{"name": "소금", "amount_text": "약간", "food_code": "R1"}],
            "missing_items": [{"name": "비밀소스", "amount_text": "1봉", "reason": "grams_unknown", "note": "…"}],
            "estimated_items": [{"name": "레몬", "amount_text": "(1/4개)", "grams": 14.5, "basis": "…"}],
            "filled_items": [{"name": "전복", "food_name": "전복, 북방전복, 생것", "nutrients": ["sodium_mg"]}],
        },
    }
    block = computed_nutrition_block(summary)
    assert not block["complete"] and block["partial_nutrients"] == ["sugars_g"]
    assert block["total"]["sodium_mg"] == 812.3 and block["total"]["protein_g"] is None
    by_code = {n["code"]: n for n in block["notices"]}
    assert list(by_code) == ["partial", "qualitative_not_counted", "amount_unknown", "estimated_amount", "filled_value"]
    assert all(n["label"] == NOTICES[n["code"]] for n in block["notices"])
    # 화면에 필요한 칸만: 근거 문장(basis·note)과 식품 코드는 빼고 이름·분량·이유
    assert by_code["qualitative_not_counted"]["items"] == [{"name": "소금", "amount_text": "약간"}]
    assert by_code["amount_unknown"]["items"] == [{"name": "비밀소스", "amount_text": "1봉", "reason": "grams_unknown"}]
    assert by_code["estimated_amount"]["items"] == [{"name": "레몬", "amount_text": "(1/4개)", "grams": 14.5}]
    assert by_code["filled_value"]["items"][0]["nutrients"] == ["sodium_mg"]


def test_db_row_with_density_columns_reads_the_same():
    row = {
        "computed": {"energy_kcal": 236.0, "protein_g": 4.4, "sodium_mg": 100.2},
        "computed_missing": {},
        "coverage": {"complete": True},
        "complete": True,
        "sodium_mg_per_1000kcal": Decimal("424.6"),
        "protein_energy_pct": Decimal("7.5"),
        "carbohydrate_energy_pct": None,
        "fat_energy_pct": None,
        "mapper_version": "recipe-food-map-v8",
    }
    block = computed_nutrition_block(row)
    assert block["density"] == {"sodium_mg_per_1000kcal": 424.6, "carbohydrate_energy_pct": None,
                                "protein_energy_pct": 7.5, "fat_energy_pct": None}
    assert block["version"] == "recipe-food-map-v8" and block["complete"]


@pytest.mark.parametrize("servings", [0, None])
def test_zero_or_missing_servings_means_unknown(servings):
    block = computed_nutrition_block({"computed": {"energy_kcal": 100}, "coverage": {"complete": True}}, servings)
    assert block["servings"] is None and block["per_serving"] is None
