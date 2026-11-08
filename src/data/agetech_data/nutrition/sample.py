"""사진·영양 API 입력 표본 생성 (데이터 → 사진 분석·영양 계산 백엔드).

    uv run python -m agetech_data.nutrition.sample     # 원본 수집본 → docs/data/samples/nutrition_api_sample.json

흐름: 사진 분석이 돌려준 음식명 → search_dishes() 후보 → 사용자가 음식·분량 확인 → portion_nutrients() → meal_total()
같은 입력(수집본)이면 같은 출력이다. 필드 정의는 docs/data/food_nutrition_contract.md 7절.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from agetech_data import paths
from agetech_data.nutrition.dish_eval import meal_search_indexes
from agetech_data.nutrition.fields import NUTRIENT_FIELDS, SUM_NUTRIENTS
from agetech_data.nutrition.foods import FoodRecord, clean_foods
from agetech_data.nutrition.match import dish_choice_question, normalize_dish_query, search_dishes
from agetech_data.nutrition.portion import meal_total, portion_nutrients
from agetech_data.recipes.validate import _rel, write_json

SCHEMA_VERSION = 1
CANDIDATES = 5
FOOD_FIELDS = ("food_code", "name", "db_group", "category1", "basis_text", "basis_amount", "basis_unit",
               "create_method", "source_name", "research_date", "update_date",
               "food_weight_text", "dish_serving_text", "serving_ref_text", "quality_flags")


def _first(cands, by_code):
    return cands[0] if cands else None


def _first_ml(cands, by_code):
    return next((c for c in cands if c["basis_unit"] == "mL"), None)


def _first_missing(cands, by_code):
    return next((c for c in cands if any(by_code[c["food_code"]].nutrients[k] is None for k in SUM_NUTRIENTS)), None)


PICKS = {"first": (_first, "첫 후보"), "first_ml": (_first_ml, "100mL 기준 첫 후보"),
         "first_missing": (_first_missing, "성분 결측이 있는 첫 후보")}


def _pick(spec: str):
    """'first' 등 PICKS 이름, 또는 'name=인절미'(그 이름의 후보를 사용자가 고름)."""
    if spec.startswith("name="):
        name = spec[5:]
        return (lambda cands, by_code: next((c for c in cands if c["name"] == name), None)), f"'{name}' 선택"
    return PICKS[spec]

# (사례, 사진 분석 음식명, 사용자가 고르는 후보, 분량, 단위)
SINGLE_CASES: list[tuple[str, str, str, float, str]] = [
    ("정상 · 100g 기준 행 · g 입력 → computed", "김치찌개", "first", 300, "g"),
    ("별칭(공깃밥 → 쌀밥) · g 입력", "공깃밥", "first", 210, "g"),
    ("'계란' → '달걀' 치환 · g 입력", "계란말이", "first", 60, "g"),
    ("100mL 기준 행만 있음 · g 입력 → approx_ml(1mL≈1g 근사)", "고등어구이", "first", 100, "g"),
    ("100mL 기준 행을 골라 mL 입력 → computed", "미역국", "first_ml", 250, "mL"),
    ("대표 음식명만 일치(family) · 세부 종류 확인 필요", "순두부찌개", "first", 300, "g"),
    ("음식 DB군에 없는 반찬 · 별칭이 원재료성 식품 지정(alias_code)", "배추김치", "first", 40, "g"),
    ("원재료성 후보(ingredient) · 성분 결측은 null", "귤", "first_missing", 100, "g"),
    ("부분 일치(partial) · 사용자 확인 필요", "불고기", "first", 150, "g"),
    ("인분 입력 · 1인분 중량 근거 없음 → unconvertible", "김치찌개", "first", 1, "인분"),
    ("개수 단위 입력 → unconvertible", "계란말이", "first", 2, "개"),
    ("넓은 이름 → 종류 고르기(category) · 사용자가 인절미 선택", "떡", "name=인절미", 50, "g"),
    ("별칭 → 이름이 다른 DB 행(보쌈 → 제육(돼지고기 수육)) · g 입력 → approx_ml", "보쌈", "first", 150, "g"),
    ("음료 · 별칭이 원재료성 '물에 탄것' 지정 · mL 입력 → approx_ml", "믹스커피", "first", 100, "mL"),
    ("대구 지역 음식 · 별칭(찜갈비 → 갈비찜_고춧가루) · g 입력", "찜갈비", "first", 200, "g"),
    ("후보 없음(DB에 없는 지역 음식) → 음식명 직접 수정", "뭉티기", "first", 150, "g"),
]

# (사례, [(사진 분석 음식명, 고르는 후보, 분량, 단위), ...])
MEAL_CASES: list[tuple[str, list[tuple[str, str, float, str]]]] = [
    ("한 끼 합계 · 모든 음식 계산됨", [("쌀밥", "first", 210, "g"), ("김치찌개", "first", 300, "g"),
                                   ("계란말이", "first", 60, "g"), ("배추김치", "first", 40, "g")]),
    ("한 끼 합계 · 일부 음식 제외(공기 입력) · mL 근사 · 성분 결측 포함", [("쌀밥", "first", 1, "공기"),
                                                         ("고등어구이", "first", 100, "g"),
                                                         ("시금치나물", "first", 50, "g"),
                                                         ("귤", "first_missing", 100, "g")]),
]


def _food_view(f: FoodRecord) -> dict:
    d = f.to_dict()
    return {k: d[k] for k in FOOD_FIELDS}


class SampleBuilder:
    def __init__(self, foods: list[FoodRecord]):
        self.by_code = {f.food_code: f for f in foods}
        self.dish_index, self.raw_index = meal_search_indexes(foods)

    def search(self, name: str) -> dict:
        q, code = normalize_dish_query(name)
        ask = dish_choice_question(name)
        cands = search_dishes(name, self.dish_index, limit=CANDIDATES, raw_index=self.raw_index)
        for c in cands:
            f = self.by_code[c["food_code"]]
            c.update(basis_text=f.basis_text, create_method=f.create_method, food_weight_text=f.food_weight_text,
                     quality_flags=f.quality_flags)
        return {"query": name, "normalized": q, "alias_food_code": code, "ask": ask, "candidates": cands}

    def one(self, name: str, pick: str, amount: float, unit: str) -> tuple[dict, object | None]:
        search = self.search(name)
        fn, label = _pick(pick)
        chosen = fn(search["candidates"], self.by_code)
        rec = {"recognized_name": name, "search": search, "confirm": None, "food": None, "result": None}
        if chosen is None:
            return rec, None
        food = self.by_code[chosen["food_code"]]
        rank = search["candidates"].index(chosen) + 1
        rec["confirm"] = {"food_code": food.food_code, "amount": amount, "unit": unit,
                          "picked": f"후보 {rank}순위" + ("" if pick == "first" else f" ({label})")}
        rec["food"] = _food_view(food)
        p = portion_nutrients(food, amount, unit)
        rec["result"] = p.to_dict()
        return rec, p


def build(raw_path: Path) -> dict:
    raw_bytes = raw_path.read_bytes()
    raw = json.loads(raw_bytes)
    foods = clean_foods(raw["items"])
    b = SampleBuilder(foods)
    samples, missing = [], []
    for label, name, pick, amount, unit in SINGLE_CASES:
        rec, _ = b.one(name, pick, amount, unit)
        expect_none = label.startswith("후보 없음")
        if (rec["confirm"] is None) != expect_none:
            missing.append(label)
            continue
        samples.append({"cases": [label], **rec})
    meals = []
    for label, items in MEAL_CASES:
        recs, portions = [], []
        for name, pick, amount, unit in items:
            rec, p = b.one(name, pick, amount, unit)
            if p is None:
                break
            recs.append({"recognized_name": name, "confirm": rec["confirm"],
                         "food": {k: rec["food"][k] for k in ("food_code", "name", "basis_text")},
                         "result": rec["result"]})
            portions.append(p)
        else:
            meals.append({"cases": [label], "items": recs, "total": meal_total(portions)})
            continue
        missing.append(label)
    meta = raw.get("meta") or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "description": "사진·영양 API 입력 표본 (데이터 → 사진 분석·영양 계산 백엔드). 실제 수집본으로 만든 대표 사례. "
                       "필드 정의는 contract 문서 7절.",
        "contract": "docs/data/food_nutrition_contract.md",
        "input": {"path": _rel(raw_path), "sha256": hashlib.sha256(raw_bytes).hexdigest(),
                  "api_version": meta.get("api_version"), "db_class": (meta.get("params") or {}).get("DB_CLASS_NM"),
                  "fetched_at": meta.get("fetched_at"), "item_count": meta.get("item_count")},
        "flow": [
            "1. 사진 분석(모델)이 음식명 문자열을 돌려준다 → recognized_name",
            "2. 서버가 search_dishes()로 식품 후보를 찾는다 → search.candidates (확정 아님). "
            "넓은 이름(떡·전 등)이면 search.ask 질문과 종류 후보(match=category)를 보여 준다",
            "3. 사용자가 음식(후보 중 하나)과 분량(숫자+단위)을 확인·수정한다 → confirm",
            "4. 서버가 food_code 로 식품 행을 찾아 portion_nutrients()로 계산한다 → result",
            "5. 한 끼 합계는 meal_total() → total (계산된 음식만 더하고 빠진 음식·결측 성분 수를 함께 둔다)",
        ],
        "nutrients": {k: {"label": NUTRIENT_FIELDS[k][1], "field": NUTRIENT_FIELDS[k][0]} for k in SUM_NUTRIENTS},
        "samples": samples,
        "meals": meals,
        "cases_not_found": missing,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="사진·영양 API 입력 표본 생성")
    ap.add_argument("--nutrition-raw", type=Path, default=paths.NUTRITION_RAW)
    ap.add_argument("--sample", type=Path, default=paths.NUTRITION_API_SAMPLE, help="표본 JSON (커밋)")
    args = ap.parse_args(argv)
    if not args.nutrition_raw.is_file():
        print(f"원본이 없습니다: {_rel(args.nutrition_raw)} — 먼저 `python -m agetech_data.nutrition.client` 실행",
              file=sys.stderr)
        return 1
    payload = build(args.nutrition_raw)
    write_json(args.sample, payload)
    print(f"표본 {len(payload['samples'])}건·한 끼 {len(payload['meals'])}건 → {_rel(args.sample)}"
          + (f" (없는 사례: {', '.join(payload['cases_not_found'])})" if payload["cases_not_found"] else ""))
    return 1 if payload["cases_not_found"] else 0


if __name__ == "__main__":
    sys.exit(main())
