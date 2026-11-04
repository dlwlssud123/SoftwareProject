import pytest

from agetech_data.nutrition.units import to_grams
from agetech_data.recipes.ingredients import parse_item


def _item(raw):
    return parse_item(raw)


@pytest.mark.parametrize("raw,grams,status", [
    ("연두부 75g(3/4모)", 75.0, "direct"),
    ("돼지고기(50g)", 50.0, "direct"),
    ("닭고기(가슴살, 120g)", 120.0, "direct"),
    ("후춧가루 0.1g", 0.1, "direct"),
    ("물 300ml(1½컵)", 300.0, "approx_ml"),
    ("애호박(1/2개)", None, "count_unit"),
    ("인삼(1뿌리)", None, "count_unit"),
    ("참깨 약간", None, "qualitative"),
    ("표고버섯 기둥", None, "missing"),
])
def test_to_grams_from_parsed_items(raw, grams, status):
    g = to_grams(_item(raw))
    assert (g.grams, g.status) == (grams, status)
    assert g.basis  # 근거 문장이 항상 있다


def test_paren_mass_used_when_main_unit_is_count():
    item = {"amount": 1.0, "unit": "개", "amount_kind": "measured", "amount_text": "1개(50g)", "paren_texts": ["50g"]}
    g = to_grams(item)
    assert (g.grams, g.status) == (50.0, "direct_paren")


def test_kg_and_mg():
    assert to_grams({"amount": 1.5, "unit": "kg", "amount_kind": "measured", "amount_text": "1.5kg",
                     "paren_texts": []}).grams == 1500.0
    assert to_grams({"amount": 500, "unit": "mg", "amount_kind": "measured", "amount_text": "500mg",
                     "paren_texts": []}).grams == 0.5
