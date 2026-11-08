"""사진·영양 API 입력 표본·음식명 검색 정답 표본 — 실제 수집본이 있을 때만 확인한다."""

import hashlib
import json

import pytest

from agetech_data import paths
from agetech_data.nutrition.dish_eval import load_gold
from agetech_data.nutrition.match import load_dish_aliases

needs_raw = pytest.mark.skipif(not paths.NUTRITION_RAW.is_file(), reason="수집 원본 없음 (client 실행 필요)")


@pytest.fixture(scope="module")
def real_foods():
    from agetech_data.nutrition.foods import clean_foods

    return clean_foods(json.loads(paths.NUTRITION_RAW.read_text(encoding="utf-8"))["items"])


def test_gold_file_shape():
    gold = load_gold()
    assert bool(gold["checked_by"]) == bool(gold["checked_at"])   # 확인자와 확인일은 함께 채운다
    queries = [e["query"] for e in gold["entries"]]
    assert len(queries) == len(set(queries)) and len(queries) >= 40
    assert all(e["accept"] and e.get("basis") in (None, "g", "mL") for e in gold["entries"])


@needs_raw
def test_alias_food_codes_exist(real_foods):
    codes = {f.food_code for f in real_foods}
    pinned = [a["food_code"] for a in load_dish_aliases().values() if a.get("food_code")]
    assert pinned and all(c in codes for c in pinned)


@needs_raw
def test_dish_search_gold(real_foods):
    from agetech_data.nutrition.dish_eval import evaluate

    r = evaluate(real_foods)
    wrong = [(row["query"], [c["name"] for c in row["candidates"]]) for row in r["rows"]
             if not row["top1"] and not row["known_miss"]]
    assert not wrong and r["unexpected"] == []
    # 한 글자 검색어가 엉뚱한 원재료성(떡조개·전어)을 내지 않는다
    rows = {row["query"]: row for row in r["rows"]}
    assert all(c["match"] != "ingredient" for q in ("떡", "전") for c in rows[q]["candidates"])


@needs_raw
def test_sample_build_is_complete_and_stable():
    from agetech_data.nutrition.sample import MEAL_CASES, SINGLE_CASES, build

    a, b = build(paths.NUTRITION_RAW), build(paths.NUTRITION_RAW)
    assert a == b and a["cases_not_found"] == []
    assert len(a["samples"]) == len(SINGLE_CASES) and len(a["meals"]) == len(MEAL_CASES)
    statuses = {s["result"]["status"] for s in a["samples"] if s["result"]}
    assert statuses == {"computed", "approx_ml", "unconvertible"}
    matches = {c["match"] for s in a["samples"] for c in s["search"]["candidates"]}
    assert {"name", "family", "partial", "alias_code", "ingredient", "category"} <= matches
    assert any(s["search"]["ask"] for s in a["samples"])
    assert any(s["result"] and s["result"]["missing"] for s in a["samples"])
    # 커밋한 표본이 같은 수집본으로 만든 것이면 지금 다시 만든 결과와 같아야 한다
    if paths.NUTRITION_API_SAMPLE.is_file():
        committed = json.loads(paths.NUTRITION_API_SAMPLE.read_text(encoding="utf-8"))
        if committed["input"]["sha256"] == hashlib.sha256(paths.NUTRITION_RAW.read_bytes()).hexdigest():
            assert committed == a
