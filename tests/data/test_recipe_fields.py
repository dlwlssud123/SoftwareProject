from agetech_data.recipes.fields import (
    SOURCE_FIELDS,
    check_nutrition,
    energy_bucket,
    field_issues,
    missing_fields,
    read_number,
)
from agetech_data.recipes.validate import check_recipe


def _row(**kw):
    row = {"RCP_SEQ": "1", "RCP_NM": "두부조림", "RCP_PARTS_DTLS": "두부 100g", "MANUAL01": "1. 굽는다",
           "INFO_ENG": "100", "INFO_CAR": "10", "INFO_PRO": "5", "INFO_FAT": "4.4", "INFO_NA": "200",
           "INFO_WGT": "", "ATT_FILE_NO_MAIN": "http://img/s.png", "ATT_FILE_NO_MK": "http://img/l.png"}
    row.update(kw)
    return row


def _codes(issues):
    return [i.code for i in issues]


def test_missing_fields_follow_spec_order():
    row = _row(HASH_TAG="", RCP_NA_TIP=None)
    missing = missing_fields(row)
    assert missing == [f for f in SOURCE_FIELDS if f in {"RCP_WAY2", "RCP_PAT2", "INFO_WGT", "HASH_TAG", "RCP_NA_TIP"}]


def test_read_number():
    assert read_number("1,670.5") == 1670.5 and read_number(" 250 ") == 250.0
    assert read_number("") is None and read_number(None) is None and read_number("약 200") is None


def test_nutrition_ok_keeps_values_and_marks_basis():
    n = check_nutrition(_row(INFO_WGT="250"))
    assert n.values == {"energy_kcal": 100.0, "carbohydrate_g": 10.0, "protein_g": 5.0, "fat_g": 4.4, "sodium_mg": 200.0}
    assert n.serving_weight_g == 250.0 and n.energy_from_macros_kcal == 99.6 and n.energy_ratio == 1.0
    assert n.issues == [] and not n.suspect
    d = n.to_dict()
    assert d["basis"] == "per_serving_unverified" and d["suspect"] is False


def test_nutrition_flags_missing_weight_and_servings_marker():
    n = check_nutrition(_row(RCP_PARTS_DTLS="[ 2인분 ] 두부(200g), 간장 1큰술"))
    assert _codes(n.issues) == ["serving_weight_missing", "ingredient_servings_stated"]
    assert n.ingredient_servings == 2.0 and n.issues[1].detail == {"servings": [2.0]}
    many = check_nutrition(_row(RCP_PARTS_DTLS="[1인분] 두부 50g\n[2인분] 두부 100g"))
    assert many.ingredient_servings is None and many.issues[-1].detail == {"servings": [1.0, 2.0]}


def test_energy_mismatch_is_a_warning_not_a_fix():
    # 생선찜 채소말이(1019)처럼 원문 열량 163kcal인데 탄수화물·단백질·지방으로는 7,445kcal
    row = _row(INFO_ENG="163", INFO_CAR="1500", INFO_PRO="300", INFO_FAT="27.2")
    n = check_nutrition(row)
    assert n.suspect and n.values["energy_kcal"] == 163.0          # 원문 값은 그대로
    assert n.issues[-1].detail["ratio"] == round(n.energy_from_macros_kcal / 163, 2)
    assert check_recipe(row).status == "flagged"
    low = check_nutrition(_row(INFO_ENG="500", INFO_CAR="10", INFO_PRO="5", INFO_FAT="4.4"))
    assert low.suspect and energy_bucket(low) == "0.5 미만"
    zero = check_nutrition(_row(INFO_ENG="0"))
    assert zero.suspect and zero.energy_ratio is None and energy_bucket(zero) == "원문 열량 0"


def test_invalid_nutrition_value_is_a_warning():
    n = check_nutrition(_row(INFO_NA="", INFO_ENG="약 100"))
    assert _codes(n.issues)[:2] == ["nutrition_value_invalid", "nutrition_value_invalid"]
    assert n.values["sodium_mg"] is None and n.energy_ratio is None and energy_bucket(n) == "계산 불가"
    assert check_recipe(_row(INFO_NA="")).status == "flagged"


def test_image_missing_is_info_only():
    row = _row(ATT_FILE_NO_MAIN="", ATT_FILE_NO_MK=" ")
    assert _codes(field_issues(row)) == ["image_missing"]
    assert field_issues(_row(ATT_FILE_NO_MAIN="")) == []          # 둘 중 하나만 있어도 됨
    assert check_recipe(row).status == "ok"
