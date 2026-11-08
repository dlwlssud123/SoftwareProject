from dataclasses import replace

import pytest

from agetech_data.nutrition.fields import SUM_NUTRIENTS
from agetech_data.nutrition.portion import meal_total, portion_nutrients, serving_reference

G_ROW = "D101-006000000-0001"    # 기장밥, 100g 기준 (분석)
ML_ROW = "D401-006000000-0001"   # 기장밥, 100mL 기준 (산출)
BAD_BASIS = "D117-707000000-0001"  # 기준량 '4㎍ RAE' → invalid_basis


@pytest.fixture(scope="module")
def foods(sample_foods):
    return {f.food_code: f for f in sample_foods}


def test_same_unit_is_computed(foods):
    f = foods[G_ROW]
    p = portion_nutrients(f, 210, "g")
    assert (p.status, p.amount, p.amount_unit, p.factor, p.approx_ml) == ("computed", 210.0, "g", 2.1, False)
    assert p.nutrients["energy_kcal"] == round(f.nutrients["energy_kcal"] * 2.1, 2)
    assert set(p.nutrients) == set(SUM_NUTRIENTS)
    assert p.basis == {"amount": 100.0, "unit": "g", "text": "100g"}
    assert p.input == {"amount": 210, "unit": "g"}       # 사용자가 확인한 값 그대로


def test_ml_on_ml_row_and_unit_scaling(foods):
    p = portion_nutrients(foods[ML_ROW], 0.25, "L")
    assert (p.status, p.amount, p.amount_unit, p.factor) == ("computed", 250.0, "mL", 2.5)
    assert portion_nutrients(foods[G_ROW], 0.2, "kg").amount == 200.0


@pytest.mark.parametrize("code,unit,base", [(G_ROW, "mL", "mL"), (ML_ROW, "g", "g"), (ML_ROW, "cc", "mL")])
def test_unit_mismatch_is_approx_ml(foods, code, unit, base):
    f = foods[code]
    p = portion_nutrients(f, 100, unit)
    if base == f.basis_unit:
        assert p.status == "computed" and not p.approx_ml
    else:
        assert p.status == "approx_ml" and p.approx_ml and p.calculated
        assert "1mL≈1g" in p.note
        assert p.nutrients["energy_kcal"] == f.nutrients["energy_kcal"]


@pytest.mark.parametrize("unit", ["인분", "그릇", "공기"])
def test_serving_without_source_is_unconvertible(foods, unit):
    f = foods[G_ROW]
    assert f.dish_serving_text is None and f.serving_ref_text is None
    assert f.food_weight_text  # 식품중량은 있지만 1인분 근거로 쓰지 않는다
    p = portion_nutrients(f, 1, unit)
    assert p.status == "unconvertible" and p.nutrients is None and p.amount is None and not p.calculated
    assert "g 또는 mL" in p.note


def test_serving_with_source_is_converted(foods):
    f = replace(foods[G_ROW], dish_serving_text="250g")
    p = portion_nutrients(f, 2, "인분")
    assert (p.status, p.amount, p.amount_unit) == ("computed", 500.0, "g")
    assert p.serving == {"field": "DISH_ONE_SERVING", "label": "1회분량 참고량", "text": "250g"}
    # 1회분량 참고량이 없으면 1회 섭취참고량을 쓴다. mL 로 적혀 있으면 g 기준 식품에는 근사 표시
    f2 = replace(foods[G_ROW], serving_ref_text="200ml")
    assert serving_reference(f2)[:2] == (200.0, "mL")
    p2 = portion_nutrients(f2, 1, "인분")
    assert p2.status == "approx_ml" and p2.serving["field"] == "NUTRI_AMOUNT_SERVING"


@pytest.mark.parametrize("unit", ["개", "조각", "마리", ""])
def test_count_or_missing_unit_is_unconvertible(foods, unit):
    p = portion_nutrients(foods[G_ROW], 2, unit)
    assert p.status == "unconvertible" and p.nutrients is None


@pytest.mark.parametrize("amount", [0, -5, "abc", None, True, float("nan"), float("inf")])
def test_bad_amount_is_invalid(foods, amount):
    p = portion_nutrients(foods[G_ROW], amount, "g")
    assert p.status == "invalid" and p.nutrients is None and not p.calculated


def test_numeric_string_amount_is_accepted(foods):
    assert portion_nutrients(foods[G_ROW], "150", "g").amount == 150.0


def test_invalid_basis_food_is_not_calculated(foods):
    f = foods[BAD_BASIS]
    assert "invalid_basis" in f.quality_flags
    p = portion_nutrients(f, 100, "g")
    assert p.status == "invalid" and p.basis is None and "기준량" in p.note


def test_missing_nutrient_stays_null(foods):
    f = foods[G_ROW]
    f = replace(f, nutrients={**f.nutrients, "sugars_g": None, "sodium_mg": None})
    p = portion_nutrients(f, 100, "g")
    assert p.nutrients["sugars_g"] is None and p.nutrients["sodium_mg"] is None
    assert p.missing == ["sugars_g", "sodium_mg"] and "null" in p.note
    assert p.status == "computed"


def test_meal_total(foods):
    g, ml = foods[G_ROW], foods[ML_ROW]
    no_sugar = replace(g, food_code="X", nutrients={**g.nutrients, "sugars_g": None})
    items = [portion_nutrients(g, 100, "g"), portion_nutrients(ml, 100, "g"),
             portion_nutrients(no_sugar, 100, "g"), portion_nutrients(g, 1, "인분")]
    t = meal_total(items)
    assert (t["items"], t["items_calculated"], t["complete"], t["approx_ml_items"]) == (4, 3, False, 1)
    assert [e["index"] for e in t["excluded"]] == [3] and t["excluded"][0]["status"] == "unconvertible"
    assert t["nutrients"]["energy_kcal"] == round(2 * g.nutrients["energy_kcal"] + ml.nutrients["energy_kcal"], 2)
    # 결측은 0 으로 채우지 않고, 값이 있는 음식만 더한 뒤 빠진 음식 수를 남긴다
    assert t["nutrients"]["sugars_g"] == round(g.nutrients["sugars_g"] + ml.nutrients["sugars_g"], 2)
    assert t["missing_items"] == {"sugars_g": 1}


def test_meal_total_all_missing_and_empty(foods):
    g = foods[G_ROW]
    f = replace(g, nutrients={**g.nutrients, "fiber_g": None})
    t = meal_total([portion_nutrients(f, 100, "g")])
    assert t["nutrients"]["fiber_g"] is None and t["missing_items"] == {"fiber_g": 1} and t["complete"]
    empty = meal_total([])
    assert empty["complete"] is False and empty["nutrients"]["energy_kcal"] is None
