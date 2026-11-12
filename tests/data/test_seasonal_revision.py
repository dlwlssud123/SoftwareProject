"""갱신 수집본 + 레시피 → DB 제철 행 (seasonal.revision) — 백엔드 import_seasonal 의 입력."""

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from agetech_data.seasonal.normalize import build_records
from agetech_data.seasonal.revision import LINK_FIELDS, PROVIDER, content_sha256, seasonal_rows

FIXTURE = Path(__file__).parent / "fixtures" / "seasonal_sample.json"
RECIPES = [
    {"recipe_id": "1", "name": "시금치나물", "category": "반찬", "quality": {"status": "ok"},
     "ingredients": [{"name": "시금치", "amount": 200, "unit": "g", "amount_kind": "measured"},
                     {"name": "다진 마늘", "amount": 5, "unit": "g", "amount_kind": "measured"}]},
    {"recipe_id": "2", "name": "보류 레시피", "quality": {"status": "hold"},
     "ingredients": [{"name": "시금치", "amount": 100, "unit": "g", "amount_kind": "measured"}]},
    {"recipe_id": "3", "name": "고구마 밥", "quality": {"status": "flagged"},
     "ingredients": [{"name": "밤고구마", "amount": None, "unit": None, "amount_kind": "unmeasured"},
                     {"name": "쌀", "amount": 150, "unit": "g", "amount_kind": "measured"}]},
]


@pytest.fixture(scope="module")
def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_rows_split_item_content_from_recipe_links(payload):
    rows = {r["name"]: r for r in seasonal_rows(payload, RECIPES)}
    spinach = rows["시금치"]
    assert spinach["source_id"].startswith("m12-") and spinach["month"] == 12 and PROVIDER == "data.go.kr:15168024"
    assert spinach["checked_on"] == date(2026, 11, 7) and spinach["is_published"] and spinach["detail_status"] == "ok"
    assert spinach["ingredients"] == [{"name": "시금치", "term": "시금치", "kind": "official"}]
    assert spinach["recipes"] == [{"recipe_id": "1", "ingredients": ["시금치"], "weight_g": 200.0,
                                   "share": round(200 / 205, 3)}]          # hold 레시피 2 는 연결 안 됨
    assert not set(LINK_FIELDS) & set(spinach["normalized"]) and spinach["normalized"]["detail"]["intake"]
    assert rows["고구마"]["recipes"][0]["share"] is None and rows["고구마"]["recipes"][0]["weight_g"] is None
    assert rows["늙은 호박"]["recipes"] == [] and rows["늙은 호박"]["ingredients"] == []


def test_content_hash_ignores_recipes_and_links_hash_tracks_them(payload):
    with_recipes = {r["source_id"]: r for r in seasonal_rows(payload, RECIPES)}
    without = {r["source_id"]: r for r in seasonal_rows(payload, [])}
    assert all(with_recipes[k]["content_sha256"] == without[k]["content_sha256"] for k in without)
    linked = [k for k in without if with_recipes[k]["links_sha256"] != without[k]["links_sha256"]]
    assert {with_recipes[k]["name"] for k in linked} == {"고구마", "쌀", "시금치"}
    record = next(r for r in build_records(payload, RECIPES)[0] if r["name"] == "시금치")
    assert content_sha256(record) == with_recipes[record["id"]]["content_sha256"]   # RAG 청크가 쓸 같은 해시


def test_detail_text_change_changes_content_hash(payload):
    before = {r["source_id"]: r["content_sha256"] for r in seasonal_rows(payload, RECIPES)}
    changed = copy.deepcopy(payload)
    item = next(i for i in changed["items"] if i["fdmtNm"] == "시금치")
    item["detail"]["ntkInfo"]["ntkMthDtl"] = "■ 바뀐 섭취 방법"
    after = {r["source_id"]: r["content_sha256"] for r in seasonal_rows(changed, RECIPES)}
    assert [k for k in before if before[k] != after[k]] == [item["row_id"]]


def test_related_recipe_order_from_source_does_not_change_content_hash(payload):
    # 원천은 같은 관련 레시피를 호출마다 다른 순서로 준다(2026-11-13 실수집 123개 중 48개) → 매일 적재 때 가짜 변경
    two = copy.deepcopy(payload)
    item = next(i for i in two["items"] if i["fdmtNm"] == "시금치")
    item["detail"]["connRecipeList"]["recipeInfo"] = [
        {"recipeSn": "1093", "recipeNm": "시금치 프리타타"}, {"recipeSn": "193", "recipeNm": "시금치그린스무디"}]
    flipped = copy.deepcopy(two)
    next(i for i in flipped["items"] if i["fdmtNm"] == "시금치")["detail"]["connRecipeList"]["recipeInfo"].reverse()
    rows, rows_flipped = seasonal_rows(two, RECIPES), seasonal_rows(flipped, RECIPES)
    assert [r["content_sha256"] for r in rows] == [r["content_sha256"] for r in rows_flipped]
    spinach = next(r for r in rows if r["name"] == "시금치")
    assert spinach["official_related_recipes"] == ["시금치그린스무디", "시금치 프리타타"]    # 레시피 번호 193 < 1093
    item["detail"]["connRecipeList"]["recipeInfo"].pop()                                 # 레시피가 빠지면 변경
    assert next(r for r in seasonal_rows(two, RECIPES) if r["name"] == "시금치")["content_sha256"] \
        != spinach["content_sha256"]


def test_one_ingredient_name_cannot_belong_to_two_items_in_a_month(payload):
    twin = copy.deepcopy(payload)
    spinach = next(i for i in twin["items"] if i["fdmtNm"] == "시금치")
    twin["items"].append({**copy.deepcopy(spinach), "row_id": f"m{spinach['month']}-999", "fdmtSn": "999"})
    with pytest.raises(ValueError, match="two items"):
        seasonal_rows(twin, RECIPES)
