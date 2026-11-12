import re

import pytest

from agetech_data.recipes.ingredients import parse_ingredients, parse_item


def _codes(result):
    return [i.code for i in result.issues]


@pytest.mark.parametrize("item,name_raw,amount_text,parens,kind,fmt,amount,unit", [
    # 형식 A: 이름 뒤 분량 + 보조 분량 괄호
    ("연두부 75g(3/4모)", "연두부", "75g(3/4모)", ["3/4모"], "measured", "name_amount", 75, "g"),
    # 이름 쪽 설명 괄호는 이름에 그대로 남는다
    ("황태(채) 15g(10개)", "황태(채)", "15g(10개)", ["채", "10개"], "measured", "name_amount", 15, "g"),
    # 형식 B: 분량이 괄호 안
    ("돼지고기(50g)", "돼지고기", "(50g)", ["50g"], "measured", "paren_amount", 50, "g"),
    # 형식 C: 괄호 안 설명 + 분량
    ("닭고기(가슴살, 120g)", "닭고기", "(가슴살, 120g)", ["가슴살, 120g"], "measured", "paren_amount", 120, "g"),
    # 수식어는 지우지 않는다
    ("다진 마늘 2g(1/3작은술)", "다진 마늘", "2g(1/3작은술)", ["1/3작은술"], "measured", "name_amount", 2, "g"),
    # 분수 문자
    ("물 300ml(1½컵)", "물", "300ml(1½컵)", ["1½컵"], "measured", "name_amount", 300, "ml"),
    ("두유 50g(3⅓큰술)", "두유", "50g(3⅓큰술)", ["3⅓큰술"], "measured", "name_amount", 50, "g"),
    ("호두 1/2알", "호두", "1/2알", [], "measured", "name_amount", 0.5, "알"),
    # 정성 분량
    ("참깨 약간", "참깨", "약간", [], "qualitative", "qualitative", None, None),
    # 분량 없음
    ("표고버섯 기둥", "표고버섯 기둥", "", [], "none", "none", None, None),
])
def test_parse_item_preserves_text(item, name_raw, amount_text, parens, kind, fmt, amount, unit):
    p = parse_item(item)
    assert (p["name_raw"], p["amount_text"], p["paren_texts"]) == (name_raw, amount_text, parens)
    assert (p["amount_kind"], p["amount_format"], p["amount"], p["unit"]) == (kind, fmt, amount, unit)
    # 원문 복원: name_raw + amount_text 사이 공백만 다를 수 있음
    assert re.sub(r"\s", "", item) == re.sub(r"\s", "", p["name_raw"] + p["amount_text"])


def test_unclosed_paren_keeps_rest_as_paren_text():
    p = parse_item("후춧가루(0.5g")
    assert p["unclosed"] and p["paren_texts"] == ["0.5g"]
    assert p["name_raw"] == "후춧가루" and p["amount"] == 0.5


def test_bullet_colon_sections_and_title_line():
    text = "새우두부계란찜\n연두부 75g(3/4모), 달걀 30g(1/2개)\n고명\n시금치 10g(3줄기)"
    r = parse_ingredients(text)
    assert [(i.section, i.name_raw) for i in r.ingredients] == [
        ("새우두부계란찜", "연두부"), ("새우두부계란찜", "달걀"), ("고명", "시금치")]
    assert [s.style for s in r.sections] == ["title_line", "title_line"]


def test_colon_section_with_items_on_next_line():
    text = "●방울토마토 소박이 : \n방울토마토 150g(5개)\n●양념장 : \n통깨 약간"
    r = parse_ingredients(text)
    assert [(i.section, i.name_raw) for i in r.ingredients] == [
        ("방울토마토 소박이", "방울토마토"), ("양념장", "통깨")]
    assert "ingredient_qualitative_amount" in _codes(r)


def test_inline_section_word_without_colon_and_continuation_lines():
    text = "재료 닭가슴살(60g), 애호박(30g)\n김치(120g), 참기름(20g)\n육수 다시마(5g), 물(300g)"
    r = parse_ingredients(text)
    assert [(i.section, i.name_raw, i.line_no) for i in r.ingredients] == [
        ("재료", "닭가슴살", 1), ("재료", "애호박", 1), ("재료", "김치", 2), ("재료", "참기름", 2),
        ("육수", "다시마", 3), ("육수", "물", 3)]
    assert [s.style for s in r.sections] == ["inline_word", "inline_word"]


def test_modifier_word_at_line_start_is_not_a_section():
    r = parse_ingredients("재료 두부(40g)\n다진 돼지고기(등심, 60g), 새우젓(5g)")
    assert [i.name_raw for i in r.ingredients] == ["두부", "다진 돼지고기", "새우젓"]
    assert r.ingredients[1].section == "재료"
    assert r.ingredients[1].paren_texts == ["등심, 60g"]


def test_serving_prefix_and_commas_inside_paren():
    r = parse_ingredients("[1인분]조선부추 50g, 날콩가루 7g(1⅓작은술)\n·양념장 : 오리고기(훈제오리 가슴살, 150g), 참깨 약간")
    assert [i.name_raw for i in r.ingredients] == ["조선부추", "날콩가루", "오리고기", "참깨"]
    assert r.ingredients[2].section == "양념장"


def test_new_format_serving_line_bracket_sections_and_br_tags():
    # 2026-11 수집본의 새 형식(예: RCP_SEQ 3459): 'N인분 기준' 줄, '• [구획] …', 줄 끝 <br>
    text = ("2인분 기준<br>\n\n• [가정 간편식 재료] 누들 떡볶이 떡(20개, 130g), 어묵(1장, 40g)<br>\n\n"
            "• [추가 재료] 쌈두부(100g), 식용유(2큰술)")
    r = parse_ingredients(text)
    assert [(i.section, i.name, i.amount_text, i.line_no) for i in r.ingredients] == [
        ("가정 간편식 재료", "누들 떡볶이 떡", "(20개, 130g)", 3),
        ("가정 간편식 재료", "어묵", "(1장, 40g)", 3),
        ("추가 재료", "쌈두부", "(100g)", 5),
        ("추가 재료", "식용유", "(2큰술)", 5),
    ]
    assert [(s.title, s.style) for s in r.sections] == [("가정 간편식 재료", "bracket"), ("추가 재료", "bracket")]
    assert all("<" not in i.raw_item for i in r.ingredients)


def test_mid_line_br_and_strong_tags_are_line_breaks():
    # 줄 중간 태그는 줄바꿈: 뒤의 '조림장:' 이 섹션이 되고 '[드래싱]' 은 대괄호 섹션이 된다 (RCP_SEQ 851·986)
    r = parse_ingredients("양념:요구르트 6g, 후춧가루 0.03g<br /> 조림장:간장 3g, 설탕 5g")
    assert [(i.section, i.name, i.amount_text) for i in r.ingredients] == [
        ("양념", "요구르트", "6g"), ("양념", "후춧가루", "0.03g"), ("조림장", "간장", "3g"), ("조림장", "설탕", "5g")]
    r = parse_ingredients("캔참치 20g<strong>[드래싱]</strong> 올리브오일 2g, 설탕적당량")
    assert [(i.section, i.name, i.amount_text) for i in r.ingredients] == [
        ("", "캔참치", "20g"), ("드래싱", "올리브오일", "2g"), ("드래싱", "설탕", "적당량")]


def test_format_anomalies_detected():
    r = parse_ingredients(
        "돼지고기(50g), 당근(20g),\n표고버섯(2개), 후춧가루(0.5g\n"
        "황파프리카 10g(1/10개),청파프리카 10g(1/10개), 겨자가루(10g)."
    )
    codes = _codes(r)
    assert "ingredient_unclosed_paren" in codes
    assert "ingredient_no_space_after_comma" in codes
    assert "ingredient_trailing_period" in codes
    # 줄 끝 쉼표(다음 줄로 이어 씀)는 빈 항목을 만들지 않는다
    assert [i.name_raw for i in r.ingredients] == [
        "돼지고기", "당근", "표고버섯", "후춧가루", "황파프리카", "청파프리카", "겨자가루"]


def test_empty_text():
    assert _codes(parse_ingredients("")) == ["ingredients_none"]
    assert _codes(parse_ingredients(None)) == ["ingredients_none"]
