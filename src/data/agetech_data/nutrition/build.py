"""식품영양성분 정제 + 레시피 재료 매핑·g 환산·영양 계산 + 보고서.

    uv run python -m agetech_data.nutrition.client   # 1) 원본 수집 (API 키 필요, 최초 1회·갱신 시)
    uv run python -m agetech_data.nutrition.build    # 2) 정제·매핑·보고서 (네트워크 불필요)

출력
- data/processed/foods_v03.json                 정제 식품 (gitignore)
- data/processed/recipe_ingredient_nutrition.json 레시피 재료별 매핑·g·영양 기여 (gitignore)
- docs/data/nutrition_mapping_report.md         보고서 (커밋)

영양 계산 규칙
- 매핑 상태가 reviewed/curated/exact 이고 g 환산이 된 재료만 더한다. candidate·unmapped·개수 단위는 더하지 않는다.
- 기여량 = g ÷ 기준량 × 기준량당 함량. 식품 기준량이 mL 이면 1mL≈1g 근사로 계산하고 표시한다.
- 결측 함량은 0 으로 채우지 않는다. 결측이 섞인 성분은 합계 옆에 결측 재료 수를 함께 남긴다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from agetech_data import paths
from agetech_data.nutrition.fields import NUTRIENT_FIELDS
from agetech_data.nutrition.foods import FoodRecord, clean_foods
from agetech_data.nutrition.match import FoodIndex, load_ingredient_map, match_ingredient, search_dishes
from agetech_data.nutrition.units import CONVERTED, to_grams
from agetech_data.recipes.correct import apply_corrections
from agetech_data.recipes.validate import check_recipe, load_rows

SCHEMA_VERSION = 1
# 레시피 원문 영양값(INFO_*)과 비교할 성분
COMPARE = {"energy_kcal": "INFO_ENG", "protein_g": "INFO_PRO", "fat_g": "INFO_FAT",
           "carbohydrate_g": "INFO_CAR", "sodium_mg": "INFO_NA"}
SUM_NUTRIENTS = ["energy_kcal", "protein_g", "fat_g", "carbohydrate_g", "sugars_g", "fiber_g",
                 "sodium_mg", "potassium_mg", "calcium_mg", "cholesterol_mg", "sat_fat_g"]
DISH_EXAMPLES = ["김치찌개", "된장찌개", "쌀밥", "미역국", "불고기", "비빔밥", "잡채", "계란말이",
                 "고등어구이", "제육볶음", "순두부찌개", "김치찌게"]


def _rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(paths.REPO_ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def contribution(food: FoodRecord, grams: float) -> tuple[dict[str, float | None], bool]:
    """(성분별 기여량, mL 근사 여부)."""
    factor = grams / (food.basis_amount or 100.0)
    out = {k: (round(food.nutrients[k] * factor, 4) if food.nutrients.get(k) is not None else None)
           for k in SUM_NUTRIENTS}
    return out, food.basis_unit == "mL"


def build_recipe_nutrition(rows: list[dict], foods: list[FoodRecord], entries) -> list[dict]:
    index = FoodIndex(foods)
    by_code = {f.food_code: f for f in foods}
    out = []
    for row in rows:
        chk = check_recipe(row)
        items = []
        totals: dict[str, float] = dict.fromkeys(SUM_NUTRIENTS, 0.0)
        missing: Counter = Counter()
        for ing in chk.ingredients.ingredients:
            g = to_grams(ing)
            m = match_ingredient(ing.name, index, ing.paren_texts, entries)
            contrib, ml_approx = None, False
            if m.usable and g.status in CONVERTED:
                contrib, ml_approx = contribution(by_code[m.food_code], g.grams)
                for k, v in contrib.items():
                    if v is None:
                        missing[k] += 1
                    else:
                        totals[k] += v
            items.append({
                "order_no": ing.order_no, "line_no": ing.line_no, "section": ing.section,
                "raw_item": ing.raw_item, "name": ing.name, "amount_text": ing.amount_text,
                "grams": g.to_dict(), "match": m.to_dict(),
                "contribution": contrib, "basis_ml_approx": ml_approx,
            })
        conv = [i for i in items if i["grams"]["status"] in CONVERTED and i["match"]["status"] != "water"]
        g_total = sum(i["grams"]["grams"] for i in conv)
        g_used = sum(i["grams"]["grams"] for i in conv if i["contribution"] is not None)
        non_water = [i for i in items if i["match"]["status"] != "water"]
        complete = bool(non_water) and all(i["contribution"] is not None for i in non_water)
        out.append({
            "source_id": chk.source_id, "name": chk.name, "quality_status": chk.status,
            "raw_sha256": chk.raw_sha256,
            "ingredients": items,
            "computed": {k: round(v, 2) for k, v in totals.items()},
            "computed_missing": dict(missing),
            "coverage": {
                "items": len(items),
                "items_used": sum(i["contribution"] is not None for i in items),
                "grams_converted": round(g_total, 2),
                "grams_used": round(g_used, 2),
                "grams_used_pct": round(100 * g_used / g_total, 1) if g_total else None,
                "complete": complete,
            },
            "source_values": {k: row.get(src) for k, src in COMPARE.items()},
        })
    return out


def summarize(recipes: list[dict], foods: list[FoodRecord], entries) -> dict:
    items = [i for r in recipes for i in r["ingredients"]]
    grams_by_status: Counter = Counter()
    for i in items:
        if i["grams"]["status"] in CONVERTED:
            grams_by_status[i["match"]["status"]] += i["grams"]["grams"]
    review: dict[str, dict] = {}
    for i in items:
        st = i["match"]["status"]
        if st in ("candidate", "unmapped", "curated"):
            key = (st, i["name"])
            d = review.setdefault("|".join(key), {"status": st, "name": i["name"], "count": 0, "grams": 0.0,
                                                  "food_name": i["match"]["food_name"],
                                                  "rationale": i["match"]["rationale"],
                                                  "candidates": i["match"]["candidates"][:3]})
            d["count"] += 1
            d["grams"] += i["grams"]["grams"] or 0
    groups = Counter((f.db_group, f.basis_unit) for f in foods)
    used_codes = {e["food_code"] for e in entries if e.get("food_code")}
    return {
        "recipes": len(recipes),
        "items": len(items),
        "match_items": dict(Counter(i["match"]["status"] for i in items)),
        "match_grams": {k: round(v, 1) for k, v in grams_by_status.items()},
        "gram_status": dict(Counter(i["grams"]["status"] for i in items)),
        "ml_approx_items": sum(i["basis_ml_approx"] for i in items),
        "complete_recipes": sum(r["coverage"]["complete"] for r in recipes),
        "review": sorted(review.values(), key=lambda d: (d["status"], -d["grams"], -d["count"], d["name"])),
        "foods": {
            "count": len(foods),
            "by_group_basis": {f"{g}|{u}": n for (g, u), n in sorted(groups.items(), key=lambda kv: str(kv[0]))},
            "flags": dict(Counter(fl for f in foods for fl in f.quality_flags).most_common()),
            "missing_pct": {k: round(100 * sum(f.nutrients[k] is None for f in foods) / max(len(foods), 1), 1)
                            for k in SUM_NUTRIENTS},
        },
        "manual_map": {"entries": len(entries), "reviewed": sum(bool(e.get("reviewed_by")) for e in entries),
                       "codes": len(used_codes)},
    }


def main(argv: list[str] | None = None) -> int:
    from agetech_data.nutrition.report import render_report

    ap = argparse.ArgumentParser(description="식품영양성분 정제·레시피 재료 매핑·보고서")
    ap.add_argument("--nutrition-raw", type=Path, default=paths.NUTRITION_RAW)
    ap.add_argument("--recipes", type=Path, default=paths.RECIPES_RAW)
    ap.add_argument("--corrections", type=Path, default=paths.RECIPE_CORRECTIONS)
    ap.add_argument("--foods-out", type=Path, default=paths.FOODS_PROCESSED)
    ap.add_argument("--recipes-out", type=Path, default=paths.RECIPE_NUTRITION)
    ap.add_argument("--report", type=Path, default=paths.NUTRITION_MAPPING_REPORT)
    ap.add_argument("--no-report", action="store_true")
    args = ap.parse_args(argv)

    if not args.nutrition_raw.is_file():
        print(f"원본이 없습니다: {_rel(args.nutrition_raw)} — 먼저 `python -m agetech_data.nutrition.client` 실행",
              file=sys.stderr)
        return 1
    raw_bytes = args.nutrition_raw.read_bytes()
    raw = json.loads(raw_bytes)
    foods = clean_foods(raw["items"])
    entries = load_ingredient_map()
    rows = load_rows(args.recipes)
    correction_bytes = args.corrections.read_bytes()
    rows, corrections = apply_corrections(rows, json.loads(correction_bytes))
    recipes = build_recipe_nutrition(rows, foods, entries)
    summary = summarize(recipes, foods, entries)
    dish_index = FoodIndex(foods, ("음식",))
    dishes = {q: search_dishes(q, dish_index, limit=3) for q in DISH_EXAMPLES}

    inputs = {
        "nutrition_raw": {"path": _rel(args.nutrition_raw), "sha256": hashlib.sha256(raw_bytes).hexdigest(),
                          "meta": raw.get("meta")},
        "recipes": {
            "path": _rel(args.recipes),
            "sha256": hashlib.sha256(args.recipes.read_bytes()).hexdigest(),
            "corrections_path": _rel(args.corrections),
            "corrections_sha256": hashlib.sha256(correction_bytes).hexdigest(),
            "correction_count": len(corrections),
        },
    }
    nutrient_spec = {k: {"field": f, "label": label} for k, (f, label) in NUTRIENT_FIELDS.items()}
    _write(args.foods_out, {"schema_version": SCHEMA_VERSION, "input": inputs["nutrition_raw"],
                            "nutrients": nutrient_spec, "foods": [f.to_dict() for f in foods]})
    _write(args.recipes_out, {"schema_version": SCHEMA_VERSION, "input": inputs, "summary": summary,
                              "recipes": recipes})
    if not args.no_report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(render_report(inputs, summary, recipes, dishes), encoding="utf-8", newline="\n")

    mi = summary["match_items"]
    print(f"식품 {len(foods)}건 정제 → {_rel(args.foods_out)}")
    print(f"레시피 {summary['recipes']}건 재료 {summary['items']}개: " +
          ", ".join(f"{k} {mi.get(k, 0)}" for k in ("exact", "curated", "reviewed", "water", "candidate", "unmapped")))
    print(f"모든 재료가 계산된 레시피 {summary['complete_recipes']}건 → {_rel(args.recipes_out)}")
    if not args.no_report:
        print(f"보고서 → {_rel(args.report)}")
    return 0


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


if __name__ == "__main__":
    sys.exit(main())
