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
