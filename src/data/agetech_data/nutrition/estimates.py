"""출처 있는 무게가 없을 때 쓰는 g 추정 — resources/estimated_amounts.json.

공식 자료(식약처 1회 분량, 한국보건산업진흥원 눈대중량 DB → unit_weights.json)가 없을 때만 쓴다.
추정은 g 환산 상태 `estimated` 로 남고, 근거 문장(grams.basis)에 무엇으로 추정했는지 적는다.

- qualitative : '약간·적당량' → 같은 재료를 g으로 적은 레시피 줄의 분포(이 모듈의 usage_table 로 만들어 파일에 고정).
                약간·조금·소량·한꼬집 = 25% 지점과 중앙값의 절반 중 작은 값(늘 같은 양을 쓰는 재료에서 '약간'이
                보통 양과 같아지지 않게), 적당량·적당히·넉넉히·기호에 따라·취향껏 = 중앙값. 줄이 5개 이상일 때만.
- qualitative_by_food : 같은 분포를 매핑한 식품코드로 모은 것 — 이름이 달라 위 표에 없는 '약간'과, 분량 표기가
                아예 없는 줄(중앙값)에 쓴다(build 가 매핑 뒤에 적용).
- count_units : 개수 단위의 1단위 무게 — 수입 과일·채소는 USDA FoodData Central 분량, 그 밖에는 레시피 원문에 함께
                적힌 무게나 근사(근거 문장에 적음)
- frying_oil  : 튀김기름의 먹는 양 — 같은 레시피 재료 무게의 비율(식품영양성분DB 생것↔튀긴것 짝의 지방 증가)

    uv run python -m agetech_data.nutrition.estimates --write   # qualitative 표를 지금 레시피 원본으로 다시 만듦
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ESTIMATES_FILE = Path(__file__).resolve().parents[1] / "resources" / "estimated_amounts.json"
SMALL_WORDS = ("약간", "조금", "소량", "한꼬집")
NORMAL_WORDS = ("적당량", "적당히", "넉넉히", "기호에 따라", "취향껏")
MIN_ROWS = 5


@dataclass(frozen=True)
class Estimates:
    qualitative: dict          # 재료명(공백 없음) → {small, normal, n}
    counts: dict               # (재료명, 단위) → {grams, source, evidence}
    sources: dict
    frying_ratio: float | None
    frying_source: str | None
    by_food: dict = field(default_factory=dict)   # 식품코드 → {name, small, normal, n} (이름이 달라도 같은 식품)


def _compact(name: str | None) -> str:
    return "".join((name or "").split())


@lru_cache
def load_estimates(path: Path = ESTIMATES_FILE) -> Estimates:
    if not path.is_file():
        return Estimates({}, {}, {}, None, None)
    d = json.loads(path.read_text(encoding="utf-8"))
    counts = {(_compact(e["ingredient"]), e["unit"]): e for e in d.get("count_units", [])}
    fry = d.get("frying_oil") or {}
    return Estimates(d.get("qualitative", {}), counts, d.get("sources", {}), fry.get("ratio"), fry.get("source"),
                     d.get("qualitative_by_food", {}))


def qualitative_word(text: str) -> str | None:
    """정성 분량 원문 → 'small'(약간 류) / 'normal'(적당량 류)."""
    if any(w in (text or "") for w in SMALL_WORDS):
        return "small"
    if any(w in (text or "") for w in NORMAL_WORDS):
        return "normal"
    return None


def _round(v: float) -> float:
    return round(v, 2) if v < 1 else round(v, 1)


def _stats(v: list[float]) -> dict:
    v = sorted(v)
    med = statistics.median(v)
    return {"small": _round(min(v[len(v) // 4], med / 2)), "normal": _round(med), "n": len(v)}


def usage_table(recipes: list[dict], min_rows: int = MIN_ROWS) -> tuple[dict, dict]:
    """build_recipe_nutrition 결과 → (재료명별, 식품코드별) 원문 g 분포의 25% 지점·중앙값.

    재료명 표는 정성 분량('약간' 등)이 있는 재료만, 식품코드 표는 정성 분량이거나 분량 표기가 없는 줄의 매핑 식품만
    담는다. 식품코드 표는 이름이 달라 재료명 표에 없는 줄('넛맥가루 약간' → 육두구 가루)에 쓴다."""
    grams, wanted = defaultdict(list), set()
    by_code, wanted_code, names = defaultdict(list), set(), {}
    for r in recipes:
        for i in r["ingredients"]:
            key, g, code = _compact(i["name"]), i["grams"], i["match"].get("food_code")
            if g["status"] in ("direct", "direct_paren") and g["grams"]:
                grams[key].append(g["grams"])
                if code:
                    by_code[code].append(g["grams"])
                    names.setdefault(code, i["match"].get("food_name"))
            vague = g["status"] == "qualitative" or "정성 분량" in (g.get("basis") or "")
            if vague:
                wanted.add(key)
            if code and (vague or g["status"] == "missing"):
                wanted_code.add(code)
    by_name = {k: _stats(grams[k]) for k in sorted(wanted) if len(grams.get(k, [])) >= min_rows}
    by_food = {c: {"name": names[c], **_stats(by_code[c])} for c in sorted(wanted_code)
               if len(by_code.get(c, [])) >= min_rows}
    return by_name, by_food


def main(argv: list[str] | None = None) -> int:
    from agetech_data import paths
    from agetech_data.nutrition.build import build_recipe_nutrition
    from agetech_data.nutrition.foods import clean_foods
    from agetech_data.nutrition.match import load_ingredient_map
    from agetech_data.recipes.correct import apply_corrections
    from agetech_data.recipes.validate import load_rows

    ap = argparse.ArgumentParser(description="정성 분량 추정 표(qualitative)를 레시피 원본으로 다시 만듦")
    ap.add_argument("--recipes", type=Path, default=paths.RECIPES_ALL_RAW)
    ap.add_argument("--write", action="store_true", help="resources/estimated_amounts.json 의 qualitative 를 바꿈")
    args = ap.parse_args(argv)
    foods = clean_foods(json.loads(paths.NUTRITION_RAW.read_bytes())["items"])
    rows, _ = apply_corrections(load_rows(args.recipes), json.loads(paths.RECIPE_CORRECTIONS.read_bytes()))
    load_estimates.cache_clear()
    table, by_food = usage_table(build_recipe_nutrition(rows, foods, load_ingredient_map(),
                                                        estimates=Estimates({}, {}, {}, None, None)))
    print(f"정성 분량 재료 {len(table)}종, 식품 {len(by_food)}종 (원문 g 줄 {MIN_ROWS}개 이상)")
    if args.write:
        d = json.loads(ESTIMATES_FILE.read_text(encoding="utf-8"))
        d["qualitative"] = table
        d["qualitative_by_food"] = by_food
        ESTIMATES_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
