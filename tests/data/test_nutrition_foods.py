import pytest

from agetech_data.nutrition.fields import NUTRIENT_FIELDS, official_labels
from agetech_data.nutrition.foods import clean_food, parse_basis, parse_value


def _by_code(foods):
    return {f.food_code: f for f in foods}


def test_nutrient_fields_match_official_spec():
    labels = official_labels()
    for key, (field, label) in NUTRIENT_FIELDS.items():
        assert labels[field] == label, key
    # 03 판본 회귀: 22=비타민 D, 23=콜레스테롤, 24=포화지방산 (한 칸 밀린 매핑 방지)
    assert NUTRIENT_FIELDS["cholesterol_mg"][0] == "AMT_NUM23"
    assert NUTRIENT_FIELDS["sat_fat_g"][0] == "AMT_NUM24"


@pytest.mark.parametrize("raw,expected", [
    ("137.000", (137.0, True)), ("1,670.000", (1670.0, True)), ("", (None, True)),
    (None, (None, True)), ("None", (None, True)), ("abc", (None, False)), ("0.00", (0.0, True)),
])
def test_parse_value(raw, expected):
    assert parse_value(raw) == expected


def test_parse_basis():
    assert parse_basis("100g") == (100.0, "g")
    assert parse_basis("100mL") == (100.0, "mL")
    assert parse_basis("4㎍ RAE") == (None, None)


def test_clean_food_values_from_real_row(sample_foods):
    gukbap = _by_code(sample_foods)["D101-004160000-0001"]  # 국밥_돼지머리, 100g
    n = gukbap.nutrients
    assert (gukbap.basis_amount, gukbap.basis_unit) == (100.0, "g")
    assert n["energy_kcal"] == 137.0 and n["sodium_mg"] == 181.0
    assert n["fat_g"] == 5.16 and n["sat_fat_g"] == 1.47 and n["cholesterol_mg"] == 23.82
    assert n["sat_fat_g"] <= n["fat_g"]
    assert gukbap.food_weight_amount == 900.0 and gukbap.food_weight_unit == "g"
    assert len(gukbap.raw_sha256) == 64


def test_quality_flags(sample_foods):
    by = _by_code(sample_foods)
    test_row = by["D117-707000000-0001"]
    assert {"invalid_basis", "suspicious_name"} <= set(test_row.quality_flags)
    assert "sat_fat_exceeds_fat" in by["P101-004000400-F003-000"].quality_flags  # 딸기도넛 표시값
    assert "same_name_multiple_rows" in by["D101-006000000-0001"].quality_flags  # 기장밥 100g/100mL
    assert by["D401-006000000-0001"].basis_unit == "mL"


def test_missing_values_are_none_not_zero():
    row = {"FOOD_CD": "X1", "FOOD_NM_KR": "시험", "SERVING_SIZE": "100g", "AMT_NUM1": "50", "AMT_NUM13": ""}
    r = clean_food(row)
    assert r.nutrients["sodium_mg"] is None and "missing_sodium" in r.quality_flags
