import pytest

from agetech_data.nutrition.match import FoodIndex, match_ingredient, search_dishes


@pytest.fixture(scope="module")
def index(sample_foods):
    return FoodIndex(sample_foods)


@pytest.fixture(scope="module")
def dishes(sample_foods):
    return FoodIndex(sample_foods, ("음식",))


@pytest.mark.parametrize("name,food,rule", [
    ("양파", "양파, 생것", "raw"),
    ("대파", "파, 대파, 생것", "variety"),
    ("순두부", "두부, 순두부", "variety"),
    ("애호박", "호박, 애호박, 생것", "variety"),
    ("청양고추", "고추, 청양고추, 생것", "variety"),
    ("새송이버섯", "큰느타리버섯(새송이버섯), 생것", "alias"),
    ("다진 마늘", "마늘, 다진것", "다진+state"),
    ("다진 파", "파, 생것", "다진+raw"),
    ("두부", "두부", "full"),  # 가공식품 '두부' 2행보다 원재료성 '두부' 우선
])
def test_exact_rules(index, name, food, rule):
    m = match_ingredient(name, index, entries=())
    assert (m.status, m.food_name, m.rule) == ("exact", food, rule)
    assert m.usable


@pytest.mark.parametrize("name,wrong", [
    ("감자", "수제비면, 감자, 생것"),   # 상위 이름이 재료명에 없음
    ("닭고기", "샌드위치, 닭고기"),
    ("땅콩", "땅콩"),                  # 과자류 가공식품 — 원재료 '땅콩, …' 계열이 있음
    ("검은콩", "검은콩"),              # 두유 음료(100mL) — 원재료 '두유, 검은콩' 계열이 있음
])
def test_no_false_exact(index, name, wrong):
    m = match_ingredient(name, index, entries=())
    assert m.status != "exact" and m.food_name != wrong
    assert not m.usable


def test_water(index):
    m = match_ingredient("물", index, entries=())
    assert m.status == "water" and not m.usable


def test_manual_map_precedence_and_paren(index):
    entries = (
        {"ingredient": "감자", "food_code": "R102-001140001-0000", "rationale": "품종 미기재", "reviewed_by": None},
        {"ingredient": "닭고기", "when_paren": "가슴살", "food_code": "R109-008000401-0000",
         "rationale": "괄호에 부위", "reviewed_by": "최재영", "reviewed_at": "2026-11-01"},
        {"ingredient": "땅콩", "food_code": None, "rationale": "매핑하지 않음"},
        {"ingredient": "양파", "food_code": "NOPE", "rationale": "오타"},
    )
    m = match_ingredient("감자", index, entries=entries)
    assert (m.status, m.food_name, m.rationale) == ("curated", "감자, 수미, 생것", "품종 미기재") and m.usable
    m = match_ingredient("닭고기", index, ["가슴살, 120g"], entries=entries)
    assert (m.status, m.food_name) == ("reviewed", "닭고기, 가슴, 생것")
    assert match_ingredient("닭고기", index, ["1마리"], entries=entries).status != "reviewed"  # 괄호 조건 불일치
    assert match_ingredient("땅콩", index, entries=entries).rule == "manual:no_match"
    m = match_ingredient("양파", index, entries=entries)
    assert (m.status, m.rule) == ("unmapped", "manual:missing_code")


def test_candidates_are_not_usable(index):
    m = match_ingredient("감자", index, entries=())
    assert m.status == "candidate" and not m.usable
    names = [c["name"] for c in m.candidates]
    assert "감자, 수미, 생것" in names and "감자, 대지, 생것" in names


def test_search_dishes_prefers_gram_basis(dishes):
    r = search_dishes("기장밥", dishes, aliases={})
    assert [c["basis_unit"] for c in r[:2]] == ["g", "mL"] and r[0]["food_code"] == "D101-006000000-0001"


def test_search_dishes_alias_and_egg(dishes):
    assert search_dishes("계란말이", dishes, aliases={})[0]["name"] == "달걀말이"
    r = search_dishes("돼지머리국밥", dishes, aliases={})
    assert r[0]["name"] == "국밥_돼지머리"
    assert search_dishes("김치찌게", dishes, aliases={"김치찌게": "김치찌개"})[0]["name"] == "김치찌개"
    assert search_dishes("", dishes, aliases={}) == []


def _dish(code, name, unit="g", ref=None, group="음식"):
    return {"food_code": code, "name": name, "db_group": group, "basis_unit": unit, "ref_name": ref}


def test_search_dishes_family_beats_contained_shorter_dish():
    # '순두부찌개' 단독 행이 없을 때, 이름 안에 들어 있는 '두부찌개'보다 세부 종류가 앞에 와야 한다
    foods = [_dish("D1", "두부찌개", "mL", "두부찌개"), _dish("D2", "순두부찌개_해물", "mL", "순두부찌개"),
             _dish("D3", "순두부찌개_김치", "g", "순두부찌개")]
    r = search_dishes("순두부찌개", FoodIndex(foods, ("음식",)), aliases={})
    assert [(c["name"], c["match"]) for c in r[:2]] == [("순두부찌개_김치", "family"), ("순두부찌개_해물", "family")]
    assert r[2]["name"] == "두부찌개" and r[2]["match"] == "partial"


def test_search_dishes_exact_name_beats_family(dishes):
    r = search_dishes("기장밥", dishes, aliases={})
    assert r[0]["match"] == "name" and r[0]["db_group"] == "음식"


def test_search_dishes_raw_fallback(dishes, index):
    assert search_dishes("양파", dishes, aliases={}) == []          # 음식 DB군만 보면 없음
    r = search_dishes("양파", dishes, aliases={}, raw_index=index)
    assert (r[0]["name"], r[0]["match"], r[0]["db_group"]) == ("양파, 생것", "ingredient", "원재료성")
    # 음식명 일치가 있으면 원재료성 후보를 붙이지 않는다
    assert all(c["match"] != "ingredient" for c in search_dishes("달걀말이", dishes, aliases={}, raw_index=index))


def test_search_dishes_weak_raw_after_dish():
    foods = [_dish("D1", "소불고기", "g", "소불고기"), _dish("R1", "소불고기, 볶은것", "g", None, "원재료성")]
    r = search_dishes("불고기", FoodIndex(foods, ("음식",)), aliases={}, raw_index=FoodIndex(foods, ("원재료성",)))
    assert [(c["name"], c["match"]) for c in r] == [("소불고기", "partial"), ("소불고기, 볶은것", "ingredient")]


def test_search_dishes_alias_food_code(dishes, index):
    aliases = {"양파반찬": {"food_code": "R106-132000001-0000"}}
    r = search_dishes("양파반찬", dishes, aliases=aliases, raw_index=index)
    assert (r[0]["food_code"], r[0]["match"], r[0]["score"]) == ("R106-132000001-0000", "alias_code", 1.0)
    # 식품코드를 찾을 색인이 없으면 지정 후보 없이 일반 검색만 한다
    assert all(c["match"] != "alias_code" for c in search_dishes("양파반찬", dishes, aliases=aliases))


def test_normalize_dish_query():
    from agetech_data.nutrition.match import normalize_dish_query

    assert normalize_dish_query(" 계란 말이 ", {}) == ("달걀말이", None)
    assert normalize_dish_query("공깃밥", {"공깃밥": "쌀밥"}) == ("쌀밥", None)
    assert normalize_dish_query("김치", {"김치": {"food_code": "R1"}}) == ("김치", "R1")


def test_search_dishes_name_matches_prefer_gram_even_if_swapped():
    # 100g 기준은 이름 순서가 바뀐 '무국_소고기'에만 있을 때, 정확히 같은 이름의 100mL 행보다 앞에 둔다
    foods = [_dish("D5", "소고기 무국", "mL"), _dish("D1", "무국_소고기", "g", "무국")]
    r = search_dishes("소고기무국", FoodIndex(foods, ("음식",)), aliases={})
    assert [(c["name"], c["basis_unit"]) for c in r] == [("무국_소고기", "g"), ("소고기 무국", "mL")]


def test_raw_fallback_single_char_needs_same_head():
    foods = [_dish("R1", "떡조개, 생것", "g", None, "원재료성"), _dish("R2", "귤, 온주밀감, 생것", "g", None, "원재료성")]
    raw = FoodIndex(foods, ("원재료성",))
    empty = FoodIndex([], ("음식",))
    assert search_dishes("떡", empty, aliases={}, raw_index=raw) == []
    assert [c["name"] for c in search_dishes("귤", empty, aliases={}, raw_index=raw)] == ["귤, 온주밀감, 생것"]


def test_search_dishes_broad_name_returns_choices():
    from agetech_data.nutrition.match import dish_choice_question

    foods = [_dish("D1", "가래떡", "g"), _dish("D2", "송편_깨", "g", "송편"), _dish("D3", "떡볶이", "g"),
             _dish("D4", "수육_소고기", "g", "수육")]
    idx = FoodIndex(foods, ("음식",))
    broad = {"떡": {"ask": "어떤 떡인가요?", "choices": ["가래떡", "송편", "없는떡"]},
             "수육": {"ask": "어떤 수육인가요?", "choices": ["수육_소고기"]}}
    r = search_dishes("떡", idx, aliases={}, broad=broad, limit=1)
    # limit 와 상관없이 종류를 모두, 목록 순서대로. DB에 없는 종류는 뺀다. 세부 종류만 있으면 family 행
    assert [(c["name"], c["match"]) for c in r] == [("가래떡", "category"), ("송편_깨", "category")]
    assert [c["name"] for c in search_dishes("수육", idx, aliases={}, broad=broad)] == ["수육_소고기"]
    assert dish_choice_question("떡", aliases={}, broad=broad) == "어떤 떡인가요?"
    assert dish_choice_question("떡볶이", aliases={}, broad=broad) is None
    # 넓은 이름이 아니면 평소대로
    assert search_dishes("떡볶이", idx, aliases={}, broad=broad)[0]["match"] == "name"


def test_search_dishes_broad_name_falls_back_when_no_choice_found():
    foods = [_dish("D3", "떡볶이", "g")]
    r = search_dishes("떡볶이", FoodIndex(foods, ("음식",)), aliases={},
                      broad={"떡볶이": {"ask": "?", "choices": ["없는음식"]}})
    assert r and r[0]["match"] == "name"


def test_real_alias_file_shape():
    from agetech_data.nutrition.match import load_broad_names, load_dish_aliases

    aliases, broad = load_dish_aliases(), load_broad_names()
    assert all(a.get("name") or a.get("food_code") for a in aliases.values())
    assert broad and all(b["ask"].endswith("?") and len(b["choices"]) >= 2 for b in broad.values())
    assert not set(aliases) & set(broad)          # 같은 이름이 별칭과 넓은 이름에 동시에 있으면 안 됨
