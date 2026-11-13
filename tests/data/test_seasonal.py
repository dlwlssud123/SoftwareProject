"""이달의 식재료 수집·레시피 재료 연결 (실제 응답 발췌 표본 + 가짜 HTTP)."""

import json
from pathlib import Path

import pytest

from agetech_data.collect.seasonal import collect_seasonal, parse
from agetech_data.net import CollectError, Fatal, QuotaExceededError, Retry
from agetech_data.textutil import sha256_json
from agetech_data.seasonal.normalize import (
    Matcher,
    build_records,
    clean_ingredient,
    load_rules,
    official_terms,
)

FIXTURE = Path(__file__).parent / "fixtures" / "seasonal_sample.json"


@pytest.fixture(scope="module")
def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def matcher(payload):
    return Matcher(payload["items"], load_rules())


def _ok(body):
    return json.dumps({"response": {"header": {"resultCode": "200", "resultMsg": "정상"}, "body": body}},
                      ensure_ascii=False)


# ── 수집 ────────────────────────────────────────────────────────────────

def test_parse_ok_and_gateway_codes():
    assert parse(200, _ok({"totalCount": 1, "items": {"item": [{"fdmtNm": "잣"}]}}))["totalCount"] == 1
    gw = json.dumps({"OpenAPI_ServiceResponse": {"cmmMsgHeader": {"returnReasonCode": "{}", "returnAuthMsg": "x"}}})
    with pytest.raises(Retry):                 # 23 = 초당 한도 → 쉬고 다시
        parse(429, gw.replace("{}", "23"))
    with pytest.raises(Fatal):                 # 12 = 서비스 없음(경로 틀림)
        parse(400, gw.replace("{}", "12"))
    with pytest.raises(Fatal):
        parse(200, json.dumps({"response": {"header": {"resultCode": "99", "resultMsg": "오류"}, "body": {}}}))


def test_collect_months_details_pacing_and_throttle_retry():
    calls, sleeps = [], []
    throttled = {"done": False}
    gw23 = json.dumps({"OpenAPI_ServiceResponse": {"cmmMsgHeader": {"returnReasonCode": "23"}}})

    def fetch(url):
        calls.append(url)
        if "/foodList" in url:
            m = int(url.split("srchMonth=")[1].split("&")[0])
            return 200, _ok({"totalCount": 1, "items": {"item": {"fdmtSn": str(100 + m), "fdmtNm": f"재료{m}"}}})
        if not throttled["done"]:              # 첫 상세에서 한 번 초당 한도
            throttled["done"] = True
            return 429, gw23
        return 200, _ok({"stdInfo": {"fdmtNm": "x"}, "ntkInfo": {}, "connRecipeList": {"recipeInfo": []}})

    got = collect_seasonal("KEY", fetch=fetch, sleep=sleeps.append, log=lambda m: None)
    assert got["meta"]["item_count"] == 12 and [i["row_id"] for i in got["items"]][:2] == ["m1-101", "m2-102"]
    assert all(i["detail_status"] == "ok" for i in got["items"])
    assert got["meta"]["complete"] is True and got["meta"]["items_sha256"] == sha256_json(got["items"])
    assert len(calls) == 12 + 12 + 1                       # 목록 12 + 상세 12 + 한도 재시도 1
    assert 0.5 in sleeps and 15.0 in sleeps                # 호출 간격, 23 뒤 오래 쉼


def test_failed_detail_marks_snapshot_incomplete_for_db_import():
    def fetch(url):
        if "/foodList" in url:
            m = int(url.split("srchMonth=")[1].split("&")[0])
            return 200, _ok({"totalCount": 1, "items": {"item": {"fdmtSn": str(100 + m), "fdmtNm": f"재료{m}"}}})
        if "srchFdmtSn=101" in url:                       # 1월 식재료 상세만 실패(키·경로 문제처럼)
            return 200, json.dumps({"response": {"header": {"resultCode": "99", "resultMsg": "오류"}, "body": {}}})
        return 200, _ok({"stdInfo": {}, "ntkInfo": {}, "connRecipeList": {}})

    got = collect_seasonal("KEY", fetch=fetch, sleep=lambda s: None, log=lambda m: None)
    assert got["meta"]["details"]["failed"] == 1 and got["meta"]["complete"] is False
    assert [i["detail_status"] for i in got["items"]].count("failed") == 1


def test_collect_fails_on_empty_month_and_daily_quota():
    with pytest.raises(CollectError):
        collect_seasonal("KEY", fetch=lambda url: (200, _ok({"totalCount": 0, "items": ""})),
                         sleep=lambda s: None, log=lambda m: None)
    gw22 = json.dumps({"OpenAPI_ServiceResponse": {"cmmMsgHeader": {"returnReasonCode": "22"}}})
    with pytest.raises(QuotaExceededError):
        collect_seasonal("KEY", fetch=lambda url: (429, gw22), sleep=lambda s: None, log=lambda m: None)


def test_refresh_source_registered():
    from agetech_data.refresh.sources import SOURCES

    src = SOURCES["seasonal_foods"]
    assert src.id_field == "row_id" and src.latest.name == "food_month.json"


def test_refresh_change_detection_ignores_related_recipe_order():
    import copy

    from agetech_data.refresh.changes import diff
    from agetech_data.refresh.sources import SOURCES

    src = SOURCES["seasonal_foods"]
    old = [{"row_id": "m1-1", "month": 1, "fdmtSn": "1", "fdmtNm": "곶감", "detail_status": "ok",
            "detail": {"stdInfo": {"fdmtNm": "곶감"}, "ntkInfo": {},
                       "connRecipeList": {"recipeInfo": [{"recipeSn": "9", "recipeNm": "곶감장아찌"},
                                                         {"recipeSn": "12", "recipeNm": "곶감토르티야피자"}]}}},
           {"row_id": "m1-2", "month": 1, "fdmtSn": "2", "fdmtNm": "무", "detail": None, "detail_status": "failed"}]
    new = copy.deepcopy(old)
    new[0]["detail"]["connRecipeList"]["recipeInfo"].reverse()
    assert diff(old, new, src.id_of, content_of=src.content_of)["changed"] == 0
    assert new[0]["detail"]["connRecipeList"]["recipeInfo"][0]["recipeSn"] == "12"     # 수집본은 받은 그대로
    new[0]["detail"]["stdInfo"]["fdmtNm"] = "곶감(바뀜)"
    assert diff(old, new, src.id_of, content_of=src.content_of)["changed"] == 1


# ── 연결 규칙 ────────────────────────────────────────────────────────────

def test_official_terms_and_ingredient_cleaning():
    assert official_terms("풋콩/껍질콩") == ["풋콩", "껍질콩"]
    assert official_terms("돼지고기(수제 소시지)") == ["돼지고기"]
    assert official_terms("늙은 호박") == ["늙은호박"]
    assert clean_ingredient("[추가 재료] 양배추") == "양배추"
    assert clean_ingredient("호두10g") == "호두" and clean_ingredient("다진 쇠고기") == "다진쇠고기"


@pytest.mark.parametrize("ingredient,expected", [
    ("무", {"무"}), ("무염버터", set()), ("배추", {"배추"}), ("감자전분", set()), ("단감", {"감"}),
    ("다진 쇠고기", {"소고기"}), ("계란20g", {"달걀"}), ("수삼", {"인삼(수삼)"}),
    ("단호박", {"단호박"}), ("애호박", {"애호박"}), ("호박", {"호박"}), ("호박고구마", {"고구마"}),
    ("옥수수", {"옥수수"}), ("옥수수전분", set()), ("볶은수수", {"수수"}),
    ("찹쌀가루", {"찹쌀"}), ("쌀가루", {"쌀"}), ("겨잣가루", set()), ("잣가루", {"잣"}),
    ("삶은 밤고구마", {"고구마"}), ("깐밤", {"밤"}),
    ("홍고추", {"고추"}), ("고추장", set()), ("고추냉이", set()), ("고춧가루", set()),
    ("냉이", {"냉이"}), ("진달래꽃", set()), ("2가지색 파프리카", set()), ("가지", {"가지"}),
    ("깻잎장아찌", {"깻잎", "장아찌"}), ("미더덕", set()), ("돼지고기 목살", {"돼지고기(수제 소시지)"}),
    ("그린빈", {"풋콩/껍질콩"}), ("그린빈스", {"풋콩/껍질콩"}), ("흰강낭콩", set()),
])
def test_matcher_rules(matcher, payload, ingredient, expected):
    names = {i["row_id"]: i["fdmtNm"] for i in payload["items"]}
    assert {names[k] for k, _, _ in matcher.match(ingredient)} == expected


@pytest.mark.parametrize("ingredient,linked", [
    ("무청시래기 불린 것", True), ("시래기", True), ("호박고지", True), ("건가지", True), ("묵나물", True),
    ("고사리", False), ("도라지", False), ("가지", False),   # 생것과 이름이 같아 묵은나물로 보지 않음
])
def test_dried_vegetable_aliases_for_mugeun_namul(ingredient, linked):
    # 공식 상세 글: 묵은나물은 호박고지·가지·고사리·도라지·시래기 등 말려 둔 채소로 만듦 — 말린 것만 뜻하는 이름만 별칭
    m = Matcher([{"row_id": "m3-1", "fdmtNm": "묵은나물"}], load_rules())
    assert bool(m.match(ingredient)) is linked


def test_build_records_links_recipes_with_share_and_skips_hold(payload):
    recipes = [
        {"recipe_id": "1", "name": "시금치나물", "category": "반찬", "quality": {"status": "ok"},
         "ingredients": [{"name": "시금치", "amount": 200, "unit": "g", "amount_kind": "measured"},
                         {"name": "물", "amount": 1000, "unit": "g", "amount_kind": "measured"},
                         {"name": "다진 마늘", "amount": 5, "unit": "g", "amount_kind": "measured"},
                         {"name": "참기름", "amount": None, "unit": None, "amount_kind": "unmeasured"}]},
        {"recipe_id": "2", "name": "보류 레시피", "quality": {"status": "hold"},
         "ingredients": [{"name": "시금치", "amount": 100, "unit": "g", "amount_kind": "measured"}]},
        {"recipe_id": "3", "name": "고구마 밥", "quality": {"status": "flagged"},
         "ingredients": [{"name": "밤고구마", "amount": None, "unit": None, "amount_kind": "unmeasured"},
                         {"name": "쌀", "amount": 150, "unit": "g", "amount_kind": "measured"}]},
    ]
    records, by_recipe = build_records(payload, recipes)
    by = {r["name"]: r for r in records}
    spinach = by["시금치"]
    assert spinach["recipe_count"] == 1 and spinach["recipes"][0]["recipe_id"] == "1"   # hold 제외
    assert spinach["recipes"][0]["share"] == round(200 / 205, 3)                       # 물은 비중에서 뺌
    assert spinach["shopping_search_url"].startswith("https://www.coupang.com/np/search?q=")
    assert spinach["detail"]["intake"] and spinach["month"] == 12
    sweet = by["고구마"]["recipes"][0]
    assert sweet["recipe_id"] == "3" and sweet["share"] is None and sweet["quality_status"] == "flagged"
    assert sorted(by_recipe["3"]) == sorted([by["고구마"]["id"], by["쌀"]["id"]])
    assert by["늙은 호박"]["recipe_count"] == 0


def test_build_main_end_to_end(tmp_path, payload):
    from agetech_data.seasonal.build import main

    recipes = tmp_path / "recipes.json"
    recipes.write_text(json.dumps({"records": [
        {"recipe_id": "1", "name": "팥죽", "category": "일품", "quality": {"status": "ok"},
         "ingredients": [{"name": "팥", "amount": 100, "unit": "g", "amount_kind": "measured"},
                         {"name": "찹쌀가루", "amount": 50, "unit": "g", "amount_kind": "measured"}]}]},
        ensure_ascii=False), encoding="utf-8")
    raw = tmp_path / "raw.json"
    raw.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    out, rep, smp = tmp_path / "o.json", tmp_path / "r.md", tmp_path / "s.json"
    assert main(["--input", str(raw), "--recipes", str(recipes), "--output", str(out), "--report", str(rep),
                 "--sample", str(smp)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["recipe_months"]["1"] == [1, 12]                         # 찹쌀(1월)·팥(12월)
    assert "### 12월" in rep.read_text(encoding="utf-8")
    sample = json.loads(smp.read_text(encoding="utf-8"))["items"]
    red_bean = next(i for i in sample if i["name"] == "팥")
    assert red_bean["top_recipes"][0]["name"] == "팥죽" and red_bean["top_recipes"][0]["share"] == round(100 / 150, 3)
