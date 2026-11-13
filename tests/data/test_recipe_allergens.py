import pytest
from agetech_data.recipes.allergens import app_detect, detect, load_rules, match_name
from agetech_data.recipes.ingredients import parse_ingredients
from agetech_data.recipes.validate import check_recipe


def _detect(text):
    return detect(parse_ingredients(text))


def _names(name):
    return [a for a, _, _ in match_name(name)]


def test_rules_follow_19_legal_items():
    rules = load_rules()
    assert len(rules.allergens) == 19 and rules.standard["checked_at"] == "2026-11-05"
    assert [r.name for r in rules.allergens if not r.determinable] == ["아황산류"]


# 실제 재료명(COOKRCP01 1,156건)에서 찾은 오탐 사례
@pytest.mark.parametrize("name,expected", [
    ("스파게티", ["밀"]), ("바게트", ["밀"]), ("멍게살", []), ("꽃게", ["게"]), ("게", ["게"]), ("게피", []),
    ("겨잣가루", []), ("잣가루", ["잣"]),
    ("땅콩호박", []), ("땅콩버터", ["땅콩"]), ("피넷버터", ["땅콩"]),
    ("돼지호박", []), ("돼지감자가루", []), ("돈나물", []), ("우삼겹", ["쇠고기"]), ("우목심", ["쇠고기"]),
    ("따뜻한 우유", ["우유"]),                       # '따뜻한우유' 안의 '한우'
    ("굴림만두 새송이버섯", []), ("굴비", []), ("굴", ["조개류"]),
    ("메밀가루", ["메밀"]), ("메밀면", ["메밀", "밀"]), ("호밀가루", []), ("삶은 쌀소면", []), ("곤약국수", []),
    ("코코넛밀크", []), ("아몬드우유", []), ("두유", ["대두"]), ("노두유", ["대두"]),
    ("토마토콩카세", ["토마토"]), ("완두콩", []), ("검은콩", ["대두"]), ("병아리콩", []),
    ("치커리", []), ("백도라지", []), ("알배추", []), ("날치알", []), ("메추리알", ["알류"]),
    ("크림치즈 > 우유", ["우유"]),                   # '>' 앞은 구성 머리말
])
def test_match_name_known_traps(name, expected):
    assert _names(name) == expected


def test_kind_follows_longest_term():
    assert match_name("간장") == [("대두", "간장", "usually"), ("밀", "간장", "usually")]
    assert match_name("굴소스")[-1] == ("조개류", "굴소스", "usually")
    assert match_name("게맛살") == [("게", "게맛살", "direct")] and match_name("맛살") == [("게", "맛살", "usually")]


def test_detect_aggregates_kind_and_marks_incomplete():
    r = _detect("두부 100g, 저염간장 5g, 밀가루(30g")
    assert [(d["allergen"], d["kind"]) for d in r.detected] == [("대두", "direct"), ("밀", "direct")]
    assert [e["ingredient"] for e in r.detected[0]["evidence"]] == ["두부", "저염간장"]
    assert r.complete is False                       # 괄호 미닫힘 → 재료명이 잘렸을 수 있음
    assert r.not_determinable == ["아황산류"]
    only_sauce = _detect("저염간장 5g")
    assert [(d["allergen"], d["kind"]) for d in only_sauce.detected] == [("대두", "usually"), ("밀", "usually")]


def test_ambiguous_goes_to_needs_check_not_detected():
    r = _detect("찜갈비 300g, 콩 50g, 완두콩 10g, 소라살 30g, 육수 200ml, 멸치육수 100ml")
    assert r.detected == []
    assert [(n["ingredient"], n["candidates"]) for n in r.needs_check] == [
        ("찜갈비", ["쇠고기", "돼지고기"]), ("콩", ["대두"]), ("소라살", ["조개류"]),
        ("육수", ["쇠고기", "닭고기", "돼지고기"])]
    assert _detect("돼지갈비 300g").needs_check == []    # 물질이 정해지면 needs_check 아님


def test_item_text_and_section_title_fallback():
    # 원문 섹션이 줄 중간에 있는 경우 (970 생선살 완자 찹쌀 찜): 파서가 나눠서 재료 이름으로 바로 잡힌다
    r = _detect("흰살생선 100g [흰 살생선 양념] 달걀흰자 15g, 생강즙 2g")
    assert r.detected[0]["allergen"] == "알류"
    assert r.detected[0]["evidence"][0]["ingredient"] == "달걀흰자" and "from" not in r.detected[0]["evidence"][0]
    # 괄호 안 설명이 물질을 정해 준다 (이름에는 없고 항목 원문에만 있음)
    r = _detect("다진고기(돼지고기) 100g")
    assert r.names == ["돼지고기"] and r.detected[0]["evidence"][0]["from"] == "item_text"
    # '(…재료)' 머리말 조각은 근거로 쓰지 않고, 괄호 조각은 항목 전체의 제외 단어와 함께 본다
    assert "밀" not in _detect("(비스킷재료) 박력 쌀가루 100g").names
    assert _detect("양고기(부채살) 200g").names == []
    # 제목 줄로 읽힌 재료 (354 '고명 : 파마산치즈')
    r = _detect("곁들이채소 : 어린채소 30g\n고명 : 파마산치즈")
    assert r.names == ["우유"] and r.detected[0]["evidence"][0]["from"] == "section_title"


def test_app_rule_comparison():
    # 앱 규칙은 원문 전체에서 '콩'을 찾아 땅콩을 대두로 본다
    assert "대두" in app_detect("땅콩(50g)") and _detect("땅콩(50g)").names == ["땅콩"]
    assert app_detect("호밀가루 50g") == {"밀"} and _detect("호밀가루 50g").names == []


def test_check_recipe_includes_allergens():
    row = {"RCP_SEQ": "1", "RCP_NM": "새우두부조림", "RCP_PARTS_DTLS": "새우 50g, 두부 100g", "MANUAL01": "1. 굽는다"}
    d = check_recipe(row).to_dict()["allergens"]
    assert d["basis"] == "ingredient_name" and [x["allergen"] for x in d["detected"]] == ["대두", "새우"]


@pytest.mark.parametrize("text,expected", [
    ("땅콩버터(우유 함유) 50g", ["우유", "땅콩"]),
    ("메밀가루(밀가루 혼합) 50g", ["메밀", "밀"]),
    ("양고기(쇠고기 혼합) 50g", ["쇠고기"]),
    ("소고기(돼지고기 혼합) 50g", ["돼지고기", "쇠고기"]),
])
def test_explicit_components_survive_other_segment_exclusions(text, expected):
    assert _detect(text).names == expected


def test_detected_milk_does_not_resolve_ambiguous_meat():
    result = _detect("찜갈비(우유) 300g")
    assert result.names == ["우유"]
    assert result.needs_check == [{"ingredient": "찜갈비", "term": "갈비", "candidates": ["쇠고기", "돼지고기"]}]
    assert _detect("다진고기(돼지고기) 100g").needs_check == []
