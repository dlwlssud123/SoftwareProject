"""출처 있는 무게가 없을 때의 추정·근사 규칙 (estimated_amounts.json, 매핑 규칙 확장, 레시피 단위 g 추정)."""

import dataclasses

import pytest

from agetech_data.nutrition.build import build_recipe_nutrition
from agetech_data.nutrition.estimates import Estimates, load_estimates, usage_table
from agetech_data.nutrition.match import (
    FoodIndex,
    _dried_food,
    _last_word,
    match_ingredient,
    prep_alias,
    tidy_name,
)
from agetech_data.nutrition.units import to_grams
from agetech_data.recipes.ingredients import parse_item

EST = Estimates(
    qualitative={"참깨": {"small": 1.0, "normal": 3.0, "n": 9}},
    counts={("크래미", "줄"): {"ingredient": "크래미", "unit": "줄", "grams": 17, "source": "estimate",
                              "evidence": "게맛살 1줄 약 17 g"}},
    sources={"estimate": "어림값"},
    frying_ratio=0.09,
    frying_source="estimate",
)


def _recipe(seq, parts, way=None):
    row = {"RCP_SEQ": seq, "RCP_NM": f"시험{seq}", "RCP_PARTS_DTLS": parts, "RCP_WAY2": way, "MANUAL01": "1. 만든다"}
    row.update({f"MANUAL{i:02d}": "" for i in range(2, 21)})
    return row


def _food(base, code, name, kcal):
    nutrients = dict.fromkeys(base.nutrients, 0.0)
    nutrients["energy_kcal"] = kcal
    return dataclasses.replace(base, food_code=code, name=name, db_group="원재료성", nutrients=nutrients)


@pytest.fixture
def foods(sample_foods):
    base = next(f for f in sample_foods if f.name == "양파, 생것")
    return sample_foods + [
        _food(base, "R114-022000000-0000", "콩기름", 900.0),
        _food(base, "R106-186000001-0000", "토마토, 생것", 19.0),
        _food(base, "R101-030000002-0000", "스파게티면, 말린것", 380.0),
        _food(base, "R107-027000001-0000", "표고버섯, 배지재배, 생것", 22.0),
        _food(base, "R118-020030000-0000", "소금, 정제염", 0.0),
    ]


def _entry(ingredient, code, **extra):
    return {"ingredient": ingredient, "food_code": code, "rationale": "시험", **extra}


ENTRIES = (
    _entry("감자", "R102-001140001-0000"),
    _entry("스파게티", "R101-030000002-0000"),
    _entry("식용유", "R114-022000000-0000"),
    _entry("포도씨유", "R114-022000000-0000"),
    _entry("말린 토마토", "R106-186000001-0000", food_factor=14.7),
    _entry("생표고버섯", "R107-027000001-0000"),
    _entry("표고버섯", "R107-027000001-0000"),
    _entry("소금", "R118-020030000-0000"),
    _entry("굵은소금", "R118-020030000-0000"),
)


def _by_name(recipe):
    return {i["name"]: i for i in recipe["ingredients"]}


def test_estimated_counts_qualitative_and_text_mass():
    lemon = to_grams(parse_item("레몬(1/4개)"))                      # 실제 추정표: USDA 레몬 1개 58 g
    assert (lemon.status, lemon.grams) == ("estimated", 14.5) and "USDA" in lemon.basis
    assert (to_grams(parse_item("참깨 약간"), estimates=EST).grams,
            to_grams(parse_item("참깨 적당량"), estimates=EST).grams) == (1.0, 3.0)
    crab = to_grams(parse_item("크래미(2줄)"), estimates=EST)           # 재료 파서가 못 읽는 단위 '줄'
    assert (crab.status, crab.grams) == ("estimated", 34.0)
    onion = to_grams(parse_item("양파 1cm 정사각형 14g"), estimates=EST)  # 크기 표기 뒤의 g
    assert (onion.status, onion.grams) == ("direct", 14.0)
    assert set(load_estimates().sources) >= {"usda_fdc_sr", "khidi_2007_portion", "estimate"}


def test_name_tidy_prep_and_section_words():
    assert [tidy_name(n) for n in ("소금①", '"배추', "- 육수", "버터10g", "두부1.2cm", "사과작은것", "12g")] == [
        "소금", "배추", "육수", "버터", "두부", "사과", "12g"]
    assert prep_alias("굵게 다진 사과") == "다진 사과" and prep_alias("간 양파") == "다진 양파"
    assert prep_alias("다진 양파") is None and prep_alias("납작 썬 마늘") == "마늘"
    assert _last_word("소스1 발사믹식초") == "발사믹식초"
    assert _last_word("주먹밥 데친 꼬막살") == "데친 꼬막살"
    assert _last_word("사과드레싱 식초") == "식초"            # 바로 앞말이 구획 이름이면 '식초' 도 뗌
    assert _last_word("쌀 국수") is None and _last_word("노란색 파프리카") is None


def test_state_rules_follow_base_mapping_only_when_not_dried(foods):
    index = FoodIndex(foods)
    boiled = match_ingredient("삶은 감자", index, [], ENTRIES)
    assert (boiled.rule, boiled.food_code) == ("상태근사+manual", "R102-001140001-0000")
    suffix = match_ingredient("감자삶은것", index, [], ENTRIES)
    assert suffix.rule == "어순+상태근사+manual"
    # 말린 식품에 '삶은'을 그대로 대면 물 무게까지 마른 영양으로 쳐서 커지므로 기본 매핑을 따르지 않는다
    assert not match_ingredient("삶은 스파게티", index, [], ENTRIES).usable
    tidy = match_ingredient("소금①", index, [], ENTRIES)
    assert (tidy.status, tidy.rule) == ("curated", "정리+manual")
    assert _dried_food("병아리콩, 말린것") and _dried_food("대두, 콩가루")
    assert not _dried_food("무청, 시래기, 말린것, 삶은것") and not _dried_food("멥쌀, 백미, 생것")


def test_food_factor_split_amount_and_glued_amount(foods):
    rows = [_recipe("1", "말린 토마토 10g, 포도씨유, 12g, 양파 50g, (토핑) 버터10g")]   # 원문 그대로의 붙은 분량
    [r] = build_recipe_nutrition(rows, foods, ENTRIES, estimates=EST)
    by = _by_name(r)
    # 말린 토마토 1g = 생토마토 14.7g (수분 환산) → 10g × 14.7 × 19kcal/100g
    assert by["말린 토마토"]["contribution"]["energy_kcal"] == pytest.approx(10 * 14.7 * 19 / 100)
    assert (by["포도씨유"]["grams"]["status"], by["포도씨유"]["grams"]["grams"]) == ("estimated", 12.0)
    assert by["12g"]["match"]["status"] == "excluded"
    assert by["12g"]["match"]["rule"] == "split_amount:counted_elsewhere"
    assert (by["버터10g"]["grams"]["status"], by["버터10g"]["grams"]["grams"]) == ("direct", 10.0)


def test_bare_numbers_read_as_grams_or_counts(foods):
    mostly_g = _recipe("1", "양파 50g, 감자 100g, 마늘 5g, 소금 0.2, 달걀 2")
    all_bare = _recipe("2", "양파 50, 감자 100, 계란 5")
    got = {r["source_id"]: _by_name(r) for r in build_recipe_nutrition([mostly_g, all_bare], foods, ENTRIES,
                                                                       estimates=EST)}
    assert got["1"]["소금"]["grams"]["grams"] == 0.2 and got["1"]["소금"]["grams"]["status"] == "estimated"
    assert got["1"]["달걀"]["grams"]["grams"] == 120.0               # 나머지가 g 인 레시피의 '달걀 2' = 2개
    assert got["2"]["계란"]["grams"]["grams"] == 5.0                 # 숫자만 적은 레시피의 '계란 5' = 5g


def test_frying_oil_detected_from_amount_or_cooking_method(foods):
    rows = [_recipe("1", "양파 100g, 식용유 500g"),
            _recipe("2", "양파 1000g, 식용유 150g"),
            _recipe("3", "양파 1000g, 식용유 150g", way="튀기기"),
            _recipe("4", "양파 100g, 식용유 30g")]
    got = {r["source_id"]: _by_name(r)["식용유"]["grams"] for r in
           build_recipe_nutrition(rows, foods, ENTRIES, estimates=EST)}
    assert (got["1"]["grams"], got["1"]["status"]) == (9.0, "estimated")      # 다른 재료 100g × 0.09
    assert got["2"]["grams"] == 150.0                                         # 15% — 볶음 기름으로 봄
    assert got["3"]["grams"] == 90.0 and "튀기기" in got["3"]["basis"]
    assert got["4"]["grams"] == 30.0                                          # 100g 미만은 먹는 기름


def test_food_level_fallbacks_use_the_mapped_food(foods):
    est = dataclasses.replace(EST, by_food={"R118-020030000-0000": {"name": "소금, 정제염", "small": 0.3,
                                                                       "normal": 1.0, "n": 7}})
    rows = [_recipe("1", "생표고버섯(5개), 굵은소금 적당량, 소금, 양파 50g")]
    by = _by_name(build_recipe_nutrition(rows, foods, ENTRIES, estimates=est)[0])
    # 환산표의 '표고버섯' 1개 16.4g 을 같은 식품으로 매핑되는 '생표고버섯'에도 씀
    assert by["생표고버섯"]["grams"]["grams"] == pytest.approx(82.0)
    assert "같은 식품 '표고버섯'" in by["생표고버섯"]["grams"]["basis"]
    assert by["굵은소금"]["grams"]["grams"] == 1.0 and by["소금"]["grams"]["grams"] == 1.0
    assert "분량 표기 없음" in by["소금"]["grams"]["basis"]


def test_usage_table_by_name_and_by_food():
    def item(name, code, grams=None, status="direct", basis=""):
        return {"name": name, "grams": {"status": status, "grams": grams, "basis": basis},
                "match": {"food_code": code, "food_name": "소금, 정제염"}}
    recipes = [{"ingredients": [item("소금", "S", g)]} for g in (0.5, 1, 1, 2, 3)]
    recipes.append({"ingredients": [item("굵은소금", "S", status="qualitative"), item("소금", "S", status="missing")]})
    by_name, by_food = usage_table(recipes)
    assert by_name == {}                                  # '소금' 줄엔 정성 분량이 없음
    assert by_food["S"] == {"name": "소금, 정제염", "small": 0.5, "normal": 1, "n": 5}
