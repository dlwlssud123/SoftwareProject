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
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

from agetech_data import paths
from agetech_data.nutrition.dish_eval import evaluate as evaluate_dish_search
from agetech_data.nutrition.fields import NUTRIENT_FIELDS, SUM_NUTRIENTS
from agetech_data.nutrition.estimates import Estimates, load_estimates, qualitative_word
from agetech_data.nutrition.foods import FoodRecord, clean_foods
from agetech_data.nutrition.match import (
    NOT_COUNTED,
    USABLE,
    FoodIndex,
    MatchResult,
    load_ingredient_map,
    manual_entry,
    match_ingredient,
)
from agetech_data.nutrition.units import COUNT_TEXT, CONVERTED, GramAmount, load_unit_weights, to_grams
from agetech_data.recipes.correct import apply_corrections
from agetech_data.recipes.validate import check_recipe, load_rows
from agetech_data.textutil import parse_number

SCHEMA_VERSION = 1
# 레시피 원문 영양값(INFO_*)과 비교할 성분
COMPARE = {"energy_kcal": "INFO_ENG", "protein_g": "INFO_PRO", "fat_g": "INFO_FAT",
           "carbohydrate_g": "INFO_CAR", "sodium_mg": "INFO_NA"}


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


def _get(item, key):
    return item.get(key) if isinstance(item, dict) else getattr(item, key)


_BARE_NUMBER = re.compile(r"^\(?\s*\d+(?:\.\d+)?\s*\)?(?:\s*\([^()]*\))?$")      # '50', '(50)', '200(갈비살 70)'
_EDIBLE_PAREN = re.compile(r"\(\s*([가-힣]*살)\s*(\d+(?:\.\d+)?)\s*\)")
_GLUED_MASS = re.compile(r"(?<=[가-힣])\s*(\d+(?:\.\d+)?)\s*g$")
OIL_GROUP = "R114-"     # 식품영양성분DB 원재료성 유지류(콩기름·올리브유·들기름 …)
FRYING_MIN_G = 100      # 이보다 적은 기름은 볶음·무침에 다 먹는 양으로 본다
FRYING_EXCESS = 2       # 기름이 '다른 재료 × 튀김 흡유 비율'의 이 배수를 넘으면 튀김용 (9% → 18%)
FRYING_METHOD = "튀기기"  # 레시피 조리방법(COOKRCP01 RCP_WAY2)
# 튀김에 쓰는 식용유류(식품영양성분DB 이름) — 조리방법이 튀기기면 양이 적어도 튀김기름으로 본다
FRYING_OIL_NAMES = frozenset({"콩기름", "옥수수기름", "유채씨기름", "해바라기유", "혼합식물성유", "포도씨유", "면실유",
                              "쌀겨기름(미강유)", "팜유", "땅콩기름", "잇꽃씨기름"})
BARE_NUMBER_MIN = 3   # 레시피 하나에 단위 없는 숫자 재료가 이만큼 있으면 그 레시피는 g을 숫자로만 적은 것으로 본다
# 이름 자리에 양만 있는 항목 — 원문 '포도씨유, 12g' 처럼 쉼표 때문에 앞 재료의 양이 떨어져 나온 것
_AMOUNT_ONLY_NAME = re.compile(r"^(?P<n>\d+(?:\.\d+)?)\s*g$")


def _split_amounts(rows: list[list]) -> None:
    """양만 떨어져 나온 항목을 바로 앞 재료(양을 모르는)의 양으로 붙이고, 그 항목은 '이미 계산됨'으로 뺀다."""
    for prev, cur in zip(rows, rows[1:]):
        name = (_get(cur[0], "name") or "").strip()
        m = _AMOUNT_ONLY_NAME.match(name)
        if not m or prev[1].status in CONVERTED or prev[2].status in NOT_COUNTED:
            continue
        prev[1] = GramAmount(float(m.group("n")), "estimated",
                             f"원문 '{_get(prev[0], 'name')}, {name}' — 쉼표로 떨어진 뒤 항목 '{name}'을 이 재료의 양으로 봄")
        cur[2] = MatchResult("excluded", rule="split_amount:counted_elsewhere",
                             rationale=f"앞 재료 '{_get(prev[0], 'name')}'의 양이 쉼표로 떨어져 나온 항목 — 그 재료에 붙여 계산")


def _recipe_level_grams(rows: list[list], entries, est: Estimates, cooking_method: str | None = None) -> None:
    """레시피 단위로 봐야 하는 g 추정 (rows = [[재료, GramAmount, MatchResult], …] 를 고친다).

    - 단위 없는 숫자: 숫자만 적은 재료가 BARE_NUMBER_MIN 개 이상이면 g으로 본다('콩비지 50, 다진 마늘 2' 처럼 쓴 레시피)
    - 튀김기름(매핑표 frying_oil, 또는 유지류 100g 이상·조리방법 '튀기기'의 식용유류 중 튀김용으로 보이는 것):
      원문은 튀길 때 쓰는 기름 전체라, 먹는 양 = 같은 레시피에서 g을 아는 다른 재료(물·먹지 않는 재료 빼고)
      무게 × estimated_amounts.json frying_oil.ratio. 레시피당 한 번만 — 튀김기름이 여럿이면 원문 양 비율로 나누고,
      어느 것도 원문 양을 넘지 않음
    """
    _split_amounts(rows)
    for r in rows:   # "강력분60g"·"버터10g": 분량이 이름에 붙어 재료 파서가 분량 없음으로 읽은 것
        m = _GLUED_MASS.search((_get(r[0], "name") or "").strip())
        if m and r[1].status == "missing":
            r[1] = GramAmount(float(m.group(1)), "direct", f"이름에 붙은 분량 '{m.group(0).strip()}'")
    bare = [r for r in rows if r[1].status == "unparsed" and _get(r[0], "amount") is not None
            and _get(r[0], "unit") is None and _BARE_NUMBER.match(_get(r[0], "amount_text") or "")]
    in_grams = sum(r[1].status == "direct" for r in rows)
    measured = sum(r[1].status in CONVERTED or r[1].status in ("count_unit", "unparsed") for r in rows)
    # 숫자만 적은 줄이 여럿이거나, 나머지 줄 대부분(절반 이상, 3줄 이상)이 g 이면 숫자만 적은 줄도 g 으로 본다
    if bare and (len(bare) >= BARE_NUMBER_MIN or (in_grams >= BARE_NUMBER_MIN and in_grams * 2 >= measured)):
        why = (f"숫자만 적은 재료가 {len(bare)}개" if len(bare) >= BARE_NUMBER_MIN
               else f"다른 재료 {measured}줄 중 {in_grams}줄이 g")
        official = load_unit_weights()[0]
        for r in bare:
            text = _get(r[0], "amount_text") or ""
            key = ("".join((_get(r[0], "name") or "").split()), "개")
            each = official.get(key) or est.counts.get(key)
            # 나머지가 g 인 레시피의 '달걀 2' 는 2g 이 아니라 2개 (숫자만 적은 레시피의 '계란 5' 는 5g)
            if each and len(bare) < BARE_NUMBER_MIN and float(_get(r[0], "amount")).is_integer():
                r[1] = GramAmount(round(float(_get(r[0], "amount")) * each["grams"], 4), "estimated",
                                  f"단위 없는 숫자 '{text}' → 개수로 봄, 1개={each['grams']}g(추정)")
                continue
            edible = _EDIBLE_PAREN.search(text)   # "돼지등갈비 200(갈비살 70)" → 먹는 살 70
            g, note = (float(edible.group(2)), f" — 괄호의 '{edible.group(1)} {edible.group(2)}'(먹는 살)") if edible else (
                float(_get(r[0], "amount")), "")
            r[1] = GramAmount(g, "estimated", f"단위 없는 숫자 '{text}' → 이 레시피는 {why}라 g으로 봄(추정){note}")
    if not est.frying_ratio:
        return
    oils = [r for r in rows if r[2].usable and r[1].status in CONVERTED and r[1].grams]
    named = [r for r in oils
             if (manual_entry(_get(r[0], "name"), _get(r[0], "paren_texts") or [], entries) or {}).get("frying_oil")]
    deep = cooking_method == FRYING_METHOD
    # 튀김용일 수 있는 기름: 유지류 100g 이상, 또는 조리방법이 튀기기인 레시피의 식용유류(양 상관없이 —
    # 참기름·들기름·올리브유는 양념·볶음용일 수 있어 뺌)
    oils = [r for r in oils if r not in named and (r[2].food_code or "").startswith(OIL_GROUP)
            and (r[1].grams >= FRYING_MIN_G or (deep and r[2].food_name in FRYING_OIL_NAMES))]
    # 튀기는 재료 무게 — 물·먹지 않는 재료와 기름(양념용 참기름 등 포함)은 빼고
    other = sum(r[1].grams for r in rows if r not in named and r[1].status in CONVERTED and r[1].grams
                and r[2].status not in NOT_COUNTED and not (r[2].food_code or "").startswith(OIL_GROUP))
    # 매핑표 튀김기름은 늘, 나머지는 조리방법이 튀기기이거나 기름이 다른 재료가 튀김에서 먹을 양의
    # FRYING_EXCESS 배를 넘을 때 튀김용으로 본다
    fry = named + [r for r in oils if deep or r[1].grams > other * est.frying_ratio * FRYING_EXCESS]
    if not fry:
        return
    source = (est.sources.get(est.frying_source) or "").split(":")[0]
    absorbed = other * est.frying_ratio            # 레시피 전체가 튀김에서 먹는 기름 (기름이 여럿이어도 한 번)
    listed_total = sum(r[1].grams for r in fry)
    share = min(1.0, absorbed / listed_total) if listed_total else 0.0
    for r in fry:
        listed = r[1].grams
        eaten = round(listed * share, 1)            # 기름 하나면 min(원문 양, 다른 재료 × 비율)
        why = ("튀김기름" if r in named else "조리방법 '튀기기' 의 기름" if deep
               else f"기름 {listed:g}g 이 다른 재료 무게에 비해 많아 튀김용으로 봄 —")
        split = f", 튀김기름 {len(fry)}개 합 {listed_total:g}g 에 나눔" if len(fry) > 1 else ""
        r[1] = GramAmount(eaten, "estimated",
                          f"{why} 원문 {listed:g}g은 튀길 때 쓰는 양 → 먹는 양 ≈ 다른 재료 {other:g}g × "
                          f"{est.frying_ratio:g}{split}, 원문 양을 넘지 않음 = {eaten:g}g"
                          f"(추정 — {source}, 소스 재료까지 들어가 조금 높게 잡힐 수 있음)")


def _food_factor(ing, m, entries, cache: dict | None) -> float:
    """매핑표 food_factor — 재료 1g 이 매핑한 식품 몇 g 에 해당하는가 (기본 1).
    대응 식품이 수분만 다를 때 쓴다: '말린 토마토' → '토마토, 생것' × 14, '녹말물' → '전분' × 0.5.
    근거(수분 함량·배합)는 그 항목의 rationale 에 적는다."""
    if not (m.rule or "").endswith("manual"):
        return 1.0
    key = ("food_factor", _get(ing, "name"), tuple(_get(ing, "paren_texts") or ()))
    if cache is not None and key in cache:
        return cache[key]
    e = manual_entry(key[1], list(key[2]), entries) or {}
    f = float(e.get("food_factor") or 1.0)
    if f <= 0:
        raise ValueError(f"매핑표 food_factor 가 0 이하: {e.get('ingredient')}")
    if cache is not None:
        cache[key] = f
    return f


def _counts_by_food(index: FoodIndex, entries, est: Estimates) -> dict:
    """(식품코드, 단위) → 개수 단위 무게 항목. 환산표·추정표의 재료명을 매핑해 같은 식품끼리 쓰게 한다
    ('생표고버섯 5개' → '표고버섯' 1개 무게). 출처 있는 환산표가 먼저."""
    memo = index.__dict__.setdefault("_counts_by_food", {})
    key = (id(entries), id(est))
    if key not in memo:
        out: dict = {}
        tables = [(e, "unit_weight") for e in load_unit_weights()[0].values()]
        tables += [(e, "estimated") for e in est.counts.values()]
        for e, status in tables:
            m = match_ingredient(e["ingredient"], index, [], entries)
            if m.usable:
                out.setdefault((m.food_code, e["unit"]), (e, status))
        memo[key] = out
    return memo[key]


def _food_level_grams(rows: list[list], index: FoodIndex, entries, est: Estimates) -> None:
    """매핑한 식품으로 g 을 정하는 마지막 단계 (재료명이 환산표·추정표 이름과 달라 못 정한 줄).

    - 개수 단위: 같은 식품으로 매핑되는 환산표·추정표 이름의 1단위 무게
    - '약간'·'적당량'·분량 표기 없음: 같은 식품을 g으로 적은 레시피 줄의 분포(qualitative_by_food) —
      약간 류 = small, 적당량 류·표기 없음 = normal(중앙값)
    """
    counts = None
    for r in rows:
        ing, g, m = r
        if not m.usable or g.status in CONVERTED:
            continue
        text = _get(ing, "amount_text") or ""
        if g.status in ("count_unit", "unparsed"):
            counts = counts if counts is not None else _counts_by_food(index, entries, est)
            cand = []
            if g.status == "count_unit" and _get(ing, "amount") is not None:
                cand.append((float(_get(ing, "amount")), _get(ing, "unit")))
            cand += [(parse_number(x.group(1)), x.group(2)) for x in COUNT_TEXT.finditer(text)]
            for n, unit in cand:
                hit = counts.get((m.food_code, unit)) if n else None
                if hit:
                    e, status = hit
                    r[1] = GramAmount(round(n * e["grams"], 4), "estimated",
                                      f"원문 {text} → 같은 식품 '{e['ingredient']}'의 1{unit}={e['grams']}g"
                                      f"({'환산표' if status == 'unit_weight' else '추정표'}) × {n:g}(추정)")
                    break
            continue
        q = est.by_food.get(m.food_code)
        if not q and g.status in ("qualitative", "missing"):   # 같은 식품 줄이 모자라면 같은 식품군(코드 앞 4자리) 값의 중앙값
            group = [v for c, v in est.by_food.items() if c[:4] == (m.food_code or "")[:4]]
            if len(group) >= 3:
                q = {"name": f"{m.food_code[:4]} 식품군 {len(group)}종", "n": sum(v["n"] for v in group),
                     "small": statistics.median(v["small"] for v in group),
                     "normal": statistics.median(v["normal"] for v in group)}
        if not q:
            continue
        if g.status == "missing":
            word = "normal"
        elif g.status == "qualitative":
            word = qualitative_word(text)
            if not word:
                continue
        else:
            continue
        where = "25% 지점" if word == "small" else "중앙값"
        label = f"정성 분량 '{text}'" if g.status == "qualitative" else "분량 표기 없음"
        r[1] = GramAmount(q[word], "estimated",
                          f"{label} → 같은 식품('{q['name']}')을 g으로 적은 레시피 {q['n']}줄의 {where} {q[word]}g(추정)")


def ingredient_nutrition(ingredients, index: FoodIndex, by_code: dict[str, FoodRecord], entries,
                         cache: dict | None = None, estimates: Estimates | None = None,
                         cooking_method: str | None = None) -> dict:
    """레시피 재료 목록 → {ingredients, computed, computed_missing, coverage}.

    ingredients 는 재료 파서 결과(Ingredient) 또는 그 dict(DB recipe_ingredients.parsed)다.
    파일 산출물(build_recipe_nutrition)과 DB 적재(nutrition.recipe_map)가 같은 계산을 쓴다.
    cache 를 넘기면 같은 (재료명, 괄호 설명)의 매핑을 레시피 사이에서 다시 쓴다(결과는 같고 빠름 —
    매핑은 이름·괄호·식품 목록·매핑표에만 달려 있다).
    """
    items = []
    totals: dict[str, float] = dict.fromkeys(SUM_NUTRIENTS, 0.0)
    missing: Counter = Counter()
    est = estimates if estimates is not None else load_estimates()
    rows = []
    for ing in ingredients:
        g = to_grams(ing, estimates=est)
        key = (_get(ing, "name"), tuple(_get(ing, "paren_texts") or ()))
        m = cache.get(key) if cache is not None else None
        if m is None:
            m = match_ingredient(key[0], index, list(key[1]), entries)
            if cache is not None:
                cache[key] = m
        rows.append([ing, g, m])
    _recipe_level_grams(rows, entries, est, cooking_method)
    _food_level_grams(rows, index, entries, est)
    for ing, g, m in rows:
        contrib, ml_approx = None, False
        if m.usable and g.status in CONVERTED:
            contrib, ml_approx = contribution(by_code[m.food_code], g.grams * _food_factor(ing, m, entries, cache))
            for k, v in contrib.items():
                if v is None:
                    missing[k] += 1
                else:
                    totals[k] += v
        items.append({
            "order_no": _get(ing, "order_no"), "line_no": _get(ing, "line_no"), "section": _get(ing, "section"),
            "raw_item": _get(ing, "raw_item"), "name": _get(ing, "name"), "amount_text": _get(ing, "amount_text"),
            "grams": g.to_dict(), "match": m.to_dict(),
            "contribution": contrib, "basis_ml_approx": ml_approx,
        })
    # 물·먹지 않는 재료(excluded)는 0 으로 취급 — 무게 비율과 완전 판정에서 뺀다
    counted = [i for i in items if i["match"]["status"] not in NOT_COUNTED]
    conv = [i for i in counted if i["grams"]["status"] in CONVERTED]
    g_total = sum(i["grams"]["grams"] for i in conv)
    g_used = sum(i["grams"]["grams"] for i in conv if i["contribution"] is not None)
    complete = bool(counted) and all(i["contribution"] is not None for i in counted)
    # 약간·적당량은 g을 지어내지 않는다. 대신 무엇이 빠졌는지와, 그것만 빠졌는지를 따로 남긴다
    # (complete 는 그대로 엄격 — 소금 '적당량'이 빠지면 나트륨이 실제보다 낮게 잡히므로 화면이 알려야 한다)
    qualitative = [i for i in counted if i["grams"]["status"] == "qualitative"]
    quantified = [i for i in counted if i["grams"]["status"] != "qualitative"]
    complete_except_qualitative = bool(quantified) and all(i["contribution"] is not None for i in quantified)
    return {
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
            "complete_except_qualitative": complete_except_qualitative,
            "qualitative_items": [{"name": i["name"], "amount_text": i["amount_text"],
                                   "food_code": i["match"].get("food_code")} for i in qualitative],
            # 정성 분량 말고 계산에서 빠진 재료 — 화면이 "무엇을 몰라서 뺐는지" 말할 수 있게 이유와 함께
            "missing_items": [_missing(i) for i in quantified if i["contribution"] is None],
            # 출처 있는 무게가 없어 추정한 g으로 계산에 넣은 재료 (화면이 "추정"이라고 알릴 수 있게)
            "estimated_items": [{"name": i["name"], "amount_text": i["amount_text"], "grams": i["grams"]["grams"],
                                 "basis": i["grams"]["basis"]}
                                for i in counted if i["grams"]["status"] == "estimated" and i["contribution"] is not None],
            # 먹지 않거나 이미 계산돼 0 으로 친 재료 (완전 판정에는 영향 없음)
            "excluded_items": [{"name": i["name"], "amount_text": i["amount_text"], "note": i["match"]["rationale"]}
                               for i in items if i["match"]["status"] == "excluded"],
        },
    }


def _missing(item: dict) -> dict:
    """빠진 이유: no_food(매핑표에서 '매핑하지 않음' — DB에 없음·먹는 양 모름 등, note = 근거),
    food_undecided(식품을 아직 못 정함 — 후보만 있거나 없음), grams_unknown(식품은 정했지만 g을 모름 — note = 환산 근거)."""
    match, grams = item["match"], item["grams"]
    if match["status"] in USABLE:
        reason, note = "grams_unknown", grams.get("basis")
    elif (match.get("rule") or "").endswith(":no_match"):
        reason, note = "no_food", match.get("rationale")
    else:
        reason, note = "food_undecided", None
    return {"name": item["name"], "amount_text": item["amount_text"], "reason": reason, "note": note}


def build_recipe_nutrition(rows: list[dict], foods: list[FoodRecord], entries,
                           estimates: Estimates | None = None) -> list[dict]:
    index = FoodIndex(foods)
    by_code = {f.food_code: f for f in foods}
    cache: dict = {}
    out = []
    for row in rows:
        chk = check_recipe(row)
        out.append({
            "source_id": chk.source_id, "name": chk.name, "quality_status": chk.status,
            "raw_sha256": chk.raw_sha256,
            **ingredient_nutrition(chk.ingredients.ingredients, index, by_code, entries, cache, estimates,
                                   cooking_method=row.get("RCP_WAY2")),
            "source_values": {k: row.get(src) for k, src in COMPARE.items()},
        })
    return out


def summarize(recipes: list[dict], foods: list[FoodRecord], entries) -> dict:
    from agetech_data.nutrition.corrections import load_corrections

    items = [i for r in recipes for i in r["ingredients"]]
    grams_by_status: Counter = Counter()
    for i in items:
        if i["grams"]["status"] in CONVERTED:
            grams_by_status[i["match"]["status"]] += i["grams"]["grams"]
    review: dict[str, dict] = {}
    for i in items:
        st = i["match"]["status"]
        if st in ("candidate", "unmapped", "curated", "excluded"):
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
            # 원천 오류 보정 (resources/food_corrections.json, clean_foods 에서 적용됨)
            "corrections": [{"food_code": f.food_code, "name": f.name, **c} for f in foods for c in f.corrections],
            "corrections_stale": [{"food_code": f.food_code, "name": f.name} for f in foods
                                  if "correction_stale" in f.quality_flags],
            "corrections_missing": sorted({c["food_code"] for c in load_corrections()}
                                          - {f.food_code for f in foods}),
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
    dishes = evaluate_dish_search(foods)

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
    print(f"음식명 검색 정답 표본 {dishes['total']}건: 1순위 일치 {dishes['top1']}, 3순위 안 {dishes['top3']}")
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
