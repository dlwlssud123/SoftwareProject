"""이달의 식재료 정제 실행: 수집 원본 + 레시피 계약 형식 → 제철 재료 레코드·보고서·표본.

    uv run python -m agetech_data.refresh --source seasonal_foods     # 수집(판본·실패 시 이전 판본 유지)
    uv run python -m agetech_data.seasonal.build                      # 정제·레시피 연결·보고서·표본

출력
- data/processed/seasonal_foods.json          제철 재료 레코드 + 레시피별 제철 월 (gitignore)
- docs/data/seasonal_report.md                보고서 (커밋, 생성물)
- docs/data/samples/seasonal_sample.json      11·12월 표본 (커밋, 생성물)
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from agetech_data import paths
from agetech_data.seasonal.normalize import RULES_PATH, build_records, load_rules

SCHEMA_VERSION = 1
SAMPLE_MONTHS = (11, 12)       # 지금(11월)과 최종 발표 달(12월)
TOP = 3


def _rel(p: Path) -> str:
    p = p.resolve()
    return p.relative_to(paths.REPO_ROOT).as_posix() if p.is_relative_to(paths.REPO_ROOT) else p.as_posix()


def _info(p: Path) -> dict:
    return {"path": _rel(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}


def recipe_months(records: list[dict]) -> dict[str, list[int]]:
    out: dict[str, set[int]] = {}
    for r in records:
        for rec in r["recipes"]:
            out.setdefault(rec["recipe_id"], set()).add(r["month"])
    return {k: sorted(v) for k, v in sorted(out.items(), key=lambda kv: (len(kv[0]), kv[0]))}


def summarize(records: list[dict]) -> dict:
    by_month = {}
    for m in range(1, 13):
        rs = [r for r in records if r["month"] == m]
        by_month[m] = {"items": len(rs), "linked": sum(1 for r in rs if r["recipe_count"]),
                       "recipes": len({x["recipe_id"] for r in rs for x in r["recipes"]})}
    kinds = Counter(i["kind"] for r in records for i in r["matched_ingredients"])
    return {"items": len(records), "linked_items": sum(1 for r in records if r["recipe_count"]),
            "details_ok": sum(1 for r in records if r["detail_status"] == "ok"),
            "recipes_with_seasonal": len(recipe_months(records)),
            "ingredient_name_matches": dict(kinds), "by_month": by_month}


def _top(r: dict, n: int = TOP) -> str:
    def one(x):
        share = f" {round(x['share'] * 100)}%" if x["share"] is not None else ""
        return f"{x['name']}{share}"
    return ", ".join(one(x) for x in r["recipes"][:n]) or "—"


def render_report(raw_info: dict, meta: dict, recipe_info: dict, summary: dict, records: list[dict], rules: dict,
                  ingredient_names: set[str] | None = None) -> str:
    ingredient_names = ingredient_names or set()
    L = [
        "# 이달의 식재료 ↔ 레시피 연결 보고서 (농촌진흥청 국립식량과학원)",
        "",
        "> 이 파일은 `uv run python -m agetech_data.seasonal.build`로 생성됩니다. 직접 고치지 마세요.",
        "",
        "| 항목 | 값 |",
        "|---|---|",
        f"| 원천 | {meta.get('service')} — [공공데이터포털]({meta.get('documentation')}), 이용허락범위 제한 없음 |",
        f"| 원문 파일 (gitignore) | `{raw_info['path']}` (sha256 `{raw_info['sha256'][:12]}…`), 수집 {meta.get('fetched_at')} |",
        f"| 레시피 | `{recipe_info['path']}` (sha256 `{recipe_info['sha256'][:12]}…`) — hold 제외 |",
        f"| 연결 규칙 | `{_rel(RULES_PATH)}` — 별칭 {len(rules.get('aliases', {}))}개, 제외어 {len(rules.get('excludes', {}))}개 |",
        "",
        "## 1. 요약",
        "",
        f"- 12개월 제철 식재료 **{summary['items']}개**(상세 {summary['details_ok']}개), 그중 레시피와 연결된 식재료 "
        f"**{summary['linked_items']}개**, 제철 재료가 하나라도 들어간 레시피 **{summary['recipes_with_seasonal']}개**",
        "- 연결 방식: 공식 이름이 재료명에 들어 있음(`official`), 같은 식재료의 다른 이름(`alias`) — "
        + ", ".join(f"{k} {v}건" for k, v in summary["ingredient_name_matches"].items()),
        "- '비중' = 그 레시피 재료 무게(g으로 적힌 것) 중 제철 재료가 차지하는 비율. 주재료인지 고명인지 가르는 데 쓴다.",
        "- 쇼핑은 재료명 검색 링크(`shopping_search_url`)만 둔다. 가격·재고·최저가는 수집하지 않는다.",
        "",
        "| 월 | 식재료 | 레시피 연결 | 연결 레시피 |",
        "|---:|---:|---:|---:|",
    ]
    for m, s in summary["by_month"].items():
        L.append(f"| {m} | {s['items']} | {s['linked']} | {s['recipes']} |")
    L += ["", "## 2. 월별 식재료와 대표 레시피 (비중 높은 순 3개)", ""]
    for m in range(1, 13):
        L += [f"### {m}월", "", "| 식재료 | 레시피 | 맞은 재료명 | 대표 레시피 |", "|---|---:|---|---|"]
        for r in [x for x in records if x["month"] == m]:
            names = ", ".join(i["name"] for i in r["matched_ingredients"][:4]) or "—"
            L.append(f"| {r['name']} | {r['recipe_count']} | {names} | {_top(r)} |")
        L.append("")
    unlinked = [r for r in records if not r["recipe_count"]]
    L += ["## 3. 레시피와 연결되지 않은 식재료", "",
          "같은 이름(또는 별칭)으로 레시피 재료에 나오지 않는다. 제철 안내·AI 설명에는 그대로 쓰되 레시피 추천에는 나오지 않는다. "
          "공식 이름에서 마지막 글자를 뺀 이름(머위순 → 머위)이 들어간 재료명이 있으면 참고로 적었다(다른 부위·가공품일 수 있어 **연결하지 않음** — 사람이 보고 별칭에 넣을지 정함).",
          "", "| 월 | 식재료 | 비슷한 재료명(참고, 연결 안 함) |", "|---:|---|---|"]
    for r in unlinked:
        hints = sorted({n for n in ingredient_names if any(len(t) >= 3 and t[:-1] in n.replace(" ", "") for t in r["terms"])})
        L.append(f"| {r['month']} | {r['name']} | {', '.join(hints[:4]) or '—'} |")
    L += ["",
          "## 4. 연결 규칙", "",
          "- 공식 이름의 `/`는 둘로 나누고(풋콩/껍질콩), 괄호는 설명으로 본다(돼지고기(수제 소시지) → 돼지고기).",
          "- **한 글자 이름**(무·배·감·쌀·잣·팥·조·쑥·밤·귤)은 재료명이 정확히 같거나 별칭일 때만 — 무염버터·배추·감자·조개·쑥갓이 걸리지 않게.",
          "- **겹치는 이름은 긴 쪽이 이긴다**: 단호박 → 8월 단호박(10월 호박 아님), 방울토마토 → 3월, 옥수수 → 8월(9월 수수 아님). "
          "겹치지 않으면 둘 다(깻잎장아찌 → 2월 깻잎·1월 장아찌).",
          "- **제외어**: " + "; ".join(f"{k} — {', '.join(v['words'])}" for k, v in rules.get("excludes", {}).items()),
          "- **별칭**: " + "; ".join(f"{k} — {', '.join(v['terms'])}" for k, v in rules.get("aliases", {}).items()),
          ""]
    return "\n".join(L)


def build_sample(records: list[dict]) -> dict:
    out = []
    for m in SAMPLE_MONTHS:
        for r in [x for x in records if x["month"] == m]:
            d = r["detail"]
            out.append({
                "month": m, "name": r["name"], "id": r["id"], "image_url": r["image_url"],
                "intake": d.get("intake"), "efficacy": d.get("efficacy"), "purchase_tip": d.get("purchase_tip"),
                "shopping_search_url": r["shopping_search_url"],
                "recipe_count": r["recipe_count"],
                "top_recipes": [{k: x[k] for k in ("recipe_id", "name", "category", "quality_status", "ingredients",
                                                   "share")} for x in r["recipes"][:TOP]],
            })
    return {"schema_version": 1,
            "description": "이달의 식재료 표본(11월·12월) — 식재료 설명 + 비중 높은 레시피 3개 + 재료명 검색 링크. "
                           "`python -m agetech_data.seasonal.build`로 생성 — 직접 고치지 마세요.",
            "items": out}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="이달의 식재료 정제·레시피 연결·보고서·표본")
    ap.add_argument("--input", type=Path, default=paths.SEASONAL_RAW)
    ap.add_argument("--recipes", type=Path, default=paths.RECIPES_API_ALL)
    ap.add_argument("--output", type=Path, default=paths.SEASONAL_PROCESSED)
    ap.add_argument("--report", type=Path, default=paths.SEASONAL_REPORT)
    ap.add_argument("--sample", type=Path, default=paths.SEASONAL_SAMPLE)
    args = ap.parse_args(argv)
    for p, how in ((args.input, "python -m agetech_data.refresh --source seasonal_foods"),
                   (args.recipes, "python -m agetech_data.recipes.contract --input data/raw/recipes/cookrcp01_all.json "
                                  "--no-sample --output-json data/processed/recipes_api_all.json")):
        if not p.exists():
            print(f"{p} 없음 — 먼저 `{how}`")
            return 1
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    recipes = json.loads(args.recipes.read_text(encoding="utf-8"))["records"]
    rules = load_rules()
    records, _ = build_records(payload, recipes, rules)
    summary = summarize(records)
    raw_info, recipe_info = _info(args.input), _info(args.recipes)
    meta = payload.get("meta") or {}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"schema_version": SCHEMA_VERSION, "input": {"seasonal": {**raw_info, "meta": meta},
                                                                                   "recipes": recipe_info},
                                       "summary": summary, "records": records,
                                       "recipe_months": recipe_months(records)}, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    names = {i["name"] for r in recipes if (r.get("quality") or {}).get("status") != "hold"
             for i in r.get("ingredients") or []}
    args.report.write_text(render_report(raw_info, meta, recipe_info, summary, records, rules, names),
                           encoding="utf-8", newline="\n")
    args.sample.parent.mkdir(parents=True, exist_ok=True)
    args.sample.write_text(json.dumps(build_sample(records), ensure_ascii=False, indent=1) + "\n", encoding="utf-8",
                           newline="\n")
    print(f"제철 식재료 {summary['items']}개, 레시피 연결 {summary['linked_items']}개, "
          f"제철 재료가 든 레시피 {summary['recipes_with_seasonal']}개")
    print(f"→ {args.output}\n→ {args.report}\n→ {args.sample}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
