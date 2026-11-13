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
    # 이름에 붙여 쓴 분량 (RCP_SEQ 396·808): 앞이 글자이고 단위가 있으며 끝이나 괄호 앞일 때만
    ("버터15g", "버터", "15g", [], "measured", "name_amount", 15, "g"),
    ("물60g(1/4컵)", "물", "60g(1/4컵)", ["1/4컵"], "measured", "name_amount", 60, "g"),
    ("곁들이채소1", "곁들이채소1", "", [], "none", "none", None, None),
    # 숫자로 시작하는 이름 (RCP_SEQ 429·724): 맨 앞 숫자는 분량이 아님
    ("2가지색 미니파프리카 30g", "2가지색 미니파프리카", "30g", [], "measured", "name_amount", 30, "g"),
    ("3배 식초 0.5g", "3배 식초", "0.5g", [], "measured", "name_amount", 0.5, "g"),
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


def _sna(r):
    return [(i.section, i.name, i.amount_text) for i in r.ingredients]


def _assert_raw_preserved(r):
    for i in r.ingredients:
        assert i.raw_item.startswith(i.name_raw) and i.raw_item.endswith(i.amount_text), i
        assert i.raw_item[len(i.name_raw):len(i.raw_item) - len(i.amount_text)].strip() == ""


def test_mid_line_bracket_section_does_not_swallow_next_item():
    # 쉼표 없이 '[소스소개]' 가 줄 중간에 오면 앞 재료 분량에 다음 재료가 붙던 문제 (RCP_SEQ 849 등 83건)
    r = parse_ingredients("닭가슴살 60g, 양송이버섯 9g [소스소개] 소스:양파다진것 6g, 케첩 9g")
    assert _sna(r) == [("", "닭가슴살", "60g"), ("", "양송이버섯", "9g"), ("소스", "양파다진것", "6g"),
                       ("소스", "케첩", "9g")]
    assert [(s.title, s.style) for s in r.sections] == [("소스소개", "bracket"), ("소스", "colon")]
    assert _codes(r).count("ingredient_section_mid_line") == 1
    _assert_raw_preserved(r)
    # 대괄호 뒤가 바로 재료, 앞에 붙은 '>' (RCP_SEQ 925·819)
    assert _sna(parse_ingredients("마요네즈 5g[초대리] 식초 5g, 소금적당량")) == [
        ("", "마요네즈", "5g"), ("초대리", "식초", "5g"), ("초대리", "소금", "적당량")]
    assert _sna(parse_ingredients("샐러리 20g >[소스소개] 저나트륨내채소스:대추 1g")) == [
        ("", "샐러리", "20g"), ("저나트륨내채소스", "대추", "1g")]
    # 분량 없는 재료 뒤 (RCP_SEQ 995), 닫는 괄호가 빠진 대괄호 (RCP_SEQ 808)
    assert _sna(parse_ingredients("버터 2g, 유산지 [허브버터] 버터 2g")) == [
        ("", "버터", "2g"), ("", "유산지", ""), ("허브버터", "버터", "2g")]
    assert _sna(parse_ingredients("오이 10g [소스소개 단촛물:물60g, 식초 1.5g")) == [
        ("", "오이", "10g"), ("단촛물", "물", "60g"), ("단촛물", "식초", "1.5g")]
    # '[1인분]' 분량 기준 표기는 구획이 아님
    assert _sna(parse_ingredients("[1인분]두부 50g")) == [("", "두부", "50g")]


def test_mid_line_colon_section_after_amount():
    # RCP_SEQ 677: 줄 머리 '- 주재료 :' 의 대시는 구획 이름에 넣지 않는다
    r = parse_ingredients("- 주재료 : 민어 50g, 소금 0.5g - 양념장 : 간 홍고추 10g, 맛술 5g")
    assert _sna(r) == [("주재료", "민어", "50g"), ("주재료", "소금", "0.5g"), ("양념장", "간 홍고추", "10g"),
                       ("양념장", "맛술", "5g")]
    _assert_raw_preserved(r)
    # 구획 이름에 공백 (RCP_SEQ 867), 단위 없는 분량 뒤 (RCP_SEQ 750), 괄호 분량 뒤 (RCP_SEQ 682·779)
    assert _sna(parse_ingredients("매운소스:간장 2g, 설탕 5g 저나트륨 두부 된장소스:두부 15g")) == [
        ("매운소스", "간장", "2g"), ("매운소스", "설탕", "5g"), ("저나트륨 두부 된장소스", "두부", "15g")]
    assert _sna(parse_ingredients("완자: 계란 5, 다진 마늘 2 국물: 멸치다시마국물(물 300, 건멸치 2.5)")) == [
        ("완자", "계란", "5"), ("완자", "다진 마늘", "2"), ("국물", "멸치다시마국물", "(물 300, 건멸치 2.5)")]
    assert _sna(parse_ingredients("주재료 : 소금물(물 100g, 소금 3g) - 양념장 : 까나리액젓 1.5g")) == [
        ("주재료", "소금물", "(물 100g, 소금 3g)"), ("양념장", "까나리액젓", "1.5g")]
    # 쉼표 바로 뒤 '- 구획 :' (RCP_SEQ 690), 분량 기준 표기가 붙은 구획 이름 (RCP_SEQ 805)
    assert _sna(parse_ingredients("근대쌈밥 : 쌀 70g, - 멸치견과류쌈장 : 다시마국물 10g")) == [
        ("근대쌈밥", "쌀", "70g"), ("멸치견과류쌈장", "다시마국물", "10g")]
    assert _sna(parse_ingredients("[소스소개] 볶음고추장(5인분):고추장 7.5g, 쇠고기 20g  고기양념(5인분):파 2.5g")) == [
        ("볶음고추장(5인분)", "고추장", "7.5g"), ("볶음고추장(5인분)", "쇠고기", "20g"), ("고기양념(5인분)", "파", "2.5g")]
    # 숫자가 붙은 구획 이름 (RCP_SEQ 429)
    assert _sna(parse_ingredients("곁들이채소2 : 2가지색 미니파프리카 30g, 양파 60g")) == [
        ("곁들이채소2", "2가지색 미니파프리카", "30g"), ("곁들이채소2", "양파", "60g")]


def test_spaced_angle_bracket_is_a_section_separator():
    # 2026-11 새 형식 (RCP_SEQ 3679~3691): "주재료 > 달걀흰자 180g", 쉼표 뒤 "초코크림 > …"
    r = parse_ingredients("주재료 > 달걀흰자 180g, 설탕① 50g\n쑥크림 > 생크림 150g, 소금 1g, 초코크림 > 아몬드가루 85g")
    assert _sna(r) == [("주재료", "달걀흰자", "180g"), ("주재료", "설탕①", "50g"), ("쑥크림", "생크림", "150g"),
                       ("쑥크림", "소금", "1g"), ("초코크림", "아몬드가루", "85g")]
    assert [s.style for s in r.sections] == ["colon", "colon", "colon"]
    # 공백 없이 붙은 '>' 는 구분 기호일 뿐 (RCP_SEQ 819 "20g >[소스소개]")
    assert _sna(parse_ingredients("샐러리 20g >[소스소개] 대추 1g")) == [("", "샐러리", "20g"), ("소스소개", "대추", "1g")]


def test_colon_that_is_not_a_section_is_left_alone():
    # 쉼표 뒤 '이름: 분량' 은 구획이 아니다
    r = parse_ingredients("간장 5g, 설탕: 2g")
    assert [i.raw_item for i in r.ingredients] == ["간장 5g", "설탕: 2g"]
    assert "ingredient_section_mid_line" not in _codes(r)


def test_comma_missing_between_items_is_split_after_amount():
    r = parse_ingredients("꼬막 60g(꼬막살 20g), 떡볶이떡 40g 고추장 8g, 소 채끝살 200g")
    assert _sna(r) == [("", "꼬막", "60g(꼬막살 20g)"), ("", "떡볶이떡", "40g"), ("", "고추장", "8g"),
                       ("", "소 채끝살", "200g")]
    assert _codes(r).count("ingredient_comma_missing") == 1
    _assert_raw_preserved(r)
    # 마침표로 이은 것 (RCP_SEQ 339), 붙여 쓴 것 (RCP_SEQ 881), 괄호 분량 (RCP_SEQ 548·3276)
    assert _sna(parse_ingredients("레드와인 200cc. 망고 50g")) == [("", "레드와인", "200cc"), ("", "망고", "50g")]
    assert _sna(parse_ingredients("흰후춧가루 0.1g레몬즙 5g")) == [("", "흰후춧가루", "0.1g"), ("", "레몬즙", "5g")]
    assert _sna(parse_ingredients("정종(5g) 양배추(10g), 치즈가루(1컵) 월계수잎(1장)")) == [
        ("", "정종", "(5g)"), ("", "양배추", "(10g)"), ("", "치즈가루", "(1컵)"), ("", "월계수잎", "(1장)")]
    # 붙은 쪽이 구획 낱말로 시작하면 구획 (RCP_SEQ 313·945)
    assert _sna(parse_ingredients("방울토마토(20g) 소스 통계피(20g), 생강(10g)")) == [
        ("", "방울토마토", "(20g)"), ("소스", "통계피", "(20g)"), ("소스", "생강", "(10g)")]


@pytest.mark.parametrize("item", [
    "양파 1cm 정사각형 14g",            # 크기 표기 (RCP_SEQ 939)
    "건도토리묵 30g(불린것 50g)",       # 괄호 보조 분량
    "잣 1g 설탕시럼 설탕과 물을 동량으로 하여 녹인다",  # 뒤에 단위 있는 분량 없음 (RCP_SEQ 952)
    "달걀 1개 노른자",                   # 뒤에 분량 없음
    "콩비지 50 다진 마늘 2",             # 앞 분량에 단위 없음
])
def test_comma_missing_split_needs_both_amounts_with_units(item):
    r = parse_ingredients(item)
    assert [i.raw_item for i in r.ingredients] == [item]
    assert "ingredient_comma_missing" not in _codes(r)


def test_inline_section_word_followed_by_amount_is_an_item_name():
    # '다시마육수 90g' 의 '다시마육수' 는 머리말이 아니라 재료 (RCP_SEQ 1043)
    assert _sna(parse_ingredients("[냉국 국물재료] 다시마육수 90g, 간장 4g")) == [
        ("냉국 국물재료", "다시마육수", "90g"), ("냉국 국물재료", "간장", "4g")]
    # 머리말 뒤 '1인분' 은 재료가 아님 (RCP_SEQ 774)
    assert _sna(parse_ingredients("재료 1인분 봄동 10g, 깻잎 6g")) == [("재료", "봄동", "10g"), ("재료", "깻잎", "6g")]


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
