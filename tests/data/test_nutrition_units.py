import pytest

from agetech_data.nutrition.estimates import Estimates
from agetech_data.nutrition.units import to_grams
from agetech_data.recipes.ingredients import parse_item


NO_EST = Estimates({}, {}, {}, None, None)   # 출처 있는 환산만 (추정 없음)


def _item(raw):
    return parse_item(raw)


@pytest.mark.parametrize("raw,grams,status", [
    ("연두부 75g(3/4모)", 75.0, "direct"),
    ("돼지고기(50g)", 50.0, "direct"),
    ("닭고기(가슴살, 120g)", 120.0, "direct"),
    ("후춧가루 0.1g", 0.1, "direct"),
    ("물 300ml(1½컵)", 300.0, "approx_ml"),
    ("아스파라거스(3개)", None, "count_unit"),
    ("인삼(1뿌리)", None, "count_unit"),
    ("참깨 약간", None, "qualitative"),
    ("표고버섯 기둥", None, "missing"),
])
def test_to_grams_from_parsed_items(raw, grams, status):
    g = to_grams(_item(raw), estimates=NO_EST)
    assert (g.grams, g.status) == (grams, status)
    assert g.basis  # 근거 문장이 항상 있다


def test_paren_mass_used_when_main_unit_is_count():
    item = {"amount": 1.0, "unit": "개", "amount_kind": "measured", "amount_text": "1개(50g)", "paren_texts": ["50g"]}
    g = to_grams(item)
    assert (g.grams, g.status) == (50.0, "direct_paren")


@pytest.mark.parametrize("raw,grams", [
    ("올리브유(1Ts)", 15.0), ("후춧가루(0.3Ts)", 4.5), ("소금(1/2ts)", 2.5), ("설탕 1T", 15.0),
    ("꿀 2작은술", 10.0), ("간장 1큰술", 15.0), ("우유 1컵", 200.0),
])
def test_measuring_spoons_and_cup_are_ml_approximations(raw, grams):
    g = to_grams(_item(raw))
    assert (g.grams, g.status) == (grams, "approx_ml")
    assert "1mL≈1g" in g.basis


@pytest.mark.parametrize("raw,grams,unit", [
    ("달걀(1개)", 60.0, "개"), ("달걀 2개", 120.0, "개"), ("계란 1/2개", 30.0, "개"), ("사과 ½개", 100.0, "개"),
    ("밥 1공기", 210.0, "공기"),
])
def test_count_units_with_a_sourced_unit_weight(raw, grams, unit):
    g = to_grams(_item(raw))
    assert (g.grams, g.status) == (grams, "unit_weight")
    assert f"1{unit}=" in g.basis and "식품의약품안전처" in g.basis


@pytest.mark.parametrize("raw,grams", [
    ("양파 1개", 181.0), ("애호박(1/2개)", 113.35), ("깻잎(3장)", 5.49), ("단호박 1/4개", 198.7),
    ("마늘 2쪽", 17.8), ("대파(1대)", 55.7), ("새송이버섯 1개", 53.0), ("메추리알 5알", 51.5),
])
def test_count_units_from_the_khidi_portion_db(raw, grams):
    # 한국보건산업진흥원 2007 눈대중량 DB(가식부 중량, 크기 미기재는 '중')
    g = to_grams(_item(raw))
    assert (g.status, g.grams) == ("unit_weight", pytest.approx(grams))
    assert "한국보건산업진흥원" in g.basis and "별첨" in g.basis


def test_unsourced_counts_and_paren_mass_stay_as_before():
    # 출처 있는 환산표만 쓰면(추정 없음) 표에 없는 개수 단위는 그대로 — 추정은 test_nutrition_estimates
    assert to_grams(_item("레몬(1/4개)"), estimates=NO_EST).status == "count_unit"
    assert to_grams(_item("새우(3마리)"), estimates=NO_EST).status == "count_unit"   # 크기 폭이 넓어 환산표엔 없음
    assert to_grams(_item("달걀노른자 1개"), estimates=NO_EST).status == "count_unit"  # 재료명이 정확히 같을 때만
    g = to_grams(_item("달걀 1개(50g)"))                                  # 원문 괄호 g가 표보다 먼저
    assert (g.grams, g.status) == (50.0, "direct_paren")
    assert to_grams(_item("다진 마늘 1")).status == "unparsed"            # 단위 없는 숫자는 여전히 못 읽음
    assert to_grams(_item("참깨 약간"), estimates=NO_EST).status == "qualitative"


def test_unit_weight_table_lists_only_sourced_rows():
    import json

    from agetech_data.nutrition.units import UNIT_WEIGHTS_FILE

    data = json.loads(UNIT_WEIGHTS_FILE.read_text(encoding="utf-8"))
    for row in data["count_units"]:
        assert row["grams"] > 0 and row["source"] in data["sources"] and row["evidence"]
    for row in data["volume_units"]:
        assert row["ml"] > 0 and row["source"] in data["sources"]


def test_kg_and_mg():
    assert to_grams({"amount": 1.5, "unit": "kg", "amount_kind": "measured", "amount_text": "1.5kg",
                     "paren_texts": []}).grams == 1500.0
    assert to_grams({"amount": 500, "unit": "mg", "amount_kind": "measured", "amount_text": "500mg",
                     "paren_texts": []}).grams == 0.5
