"""이달의 식재료 정제와 레시피 재료 연결 (docs/data/seasonal_contract.md).

연결 규칙 (resources/seasonal_terms.json)
- 공식 이름의 '/'는 둘로 나누고(풋콩/껍질콩), 괄호는 설명으로 본다(돼지고기(수제 소시지) → 돼지고기).
- 한 글자 이름(무·배·감·쌀·잣·팥·조·쑥·밤·귤)은 재료명이 정확히 같을 때만 — 무염버터·배추·감자·조개·쑥갓이 걸리지 않게.
- 두 글자 이상은 재료명에 들어 있으면 맞추되, 이름별 제외어(고추장·토마토케첩·감자전분…)가 있으면 뺀다.
- 겹치는 이름은 긴 쪽이 이긴다(단호박 → 8월 단호박만, 10월 호박 아님). 겹치지 않으면 둘 다(깻잎장아찌 → 깻잎·장아찌).
- 같은 식재료의 다른 이름(계란·쇠고기·키위 …)은 근거와 함께 aliases 로.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

RULES_PATH = Path(__file__).resolve().parents[1] / "resources" / "seasonal_terms.json"
SHOPPING_SEARCH = "https://www.coupang.com/np/search?q="     # 재료명 외부 검색 링크만 (가격·재고 수집 안 함)
DETAIL_FIELDS = {
    ("stdInfo", "ctvtIndcDtl"): "origin", ("stdInfo", "prchCheatDtl"): "purchase_tip",
    ("stdInfo", "cstdyMthDtl"): "storage_prep", ("stdInfo", "etcInfoDtl"): "etc",
    ("ntkInfo", "ntkMthDtl"): "intake", ("ntkInfo", "ntrIrdntEfcyDtl"): "efficacy",
    ("ntkInfo", "rltRsrchInfoDtl"): "research", ("ntkInfo", "cnsmpqyDtl"): "consumption",
}
_QTY = re.compile(r"[\d.]+\s*(g|kg|ml|mL|개|큰술|작은술|컵|장|쪽|줌)?$")


def compact(s: str | None) -> str:
    return re.sub(r"\s+", "", s or "")


def official_terms(name: str) -> list[str]:
    """'풋콩/껍질콩' → ['풋콩', '껍질콩'], '돼지고기(수제 소시지)' → ['돼지고기'], '늙은 호박' → ['늙은호박']."""
    base = re.sub(r"\(.*?\)", "", name or "")
    return [t for t in (compact(p) for p in base.split("/")) if t]


def clean_ingredient(name: str | None) -> str:
    """레시피 재료명 → 비교용: [추가 재료]·괄호·끝 분량('호두10g')·공백 제거."""
    s = re.sub(r"\[.*?\]", "", name or "")
    s = re.sub(r"\(.*?\)", "", s).strip()
    return compact(_QTY.sub("", s))


def load_rules(path: Path = RULES_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class Matcher:
    """재료명 → [(식재료 키, 맞은 이름, 'official'|'alias')]. 식재료 키 = row_id(m{월}-{fdmtSn})."""

    def __init__(self, items: list[dict], rules: dict):
        self.terms: list[tuple[str, str, str, list[str]]] = []
        for it in items:
            name = it["fdmtNm"].strip()
            excl = [compact(w) for t in official_terms(name)
                    for w in (rules.get("excludes", {}).get(t) or {}).get("words", [])]
            for t in official_terms(name):
                self.terms.append((t, it["row_id"], "official", excl))
            for a in (rules.get("aliases", {}).get(name) or {}).get("terms", []):
                self.terms.append((compact(a), it["row_id"], "alias", excl))

    def match(self, ingredient: str | None) -> list[tuple[str, str, str]]:
        s = clean_ingredient(ingredient)
        if not s:
            return []
        found = []                                         # (key, term, kind, 시작, 끝, 제외됨)
        for term, key, kind, excl in self.terms:
            if len(term) == 1:
                if s == term:
                    found.append((key, term, kind, 0, 1, False))
                continue
            i = s.find(term)
            if i >= 0:
                found.append((key, term, kind, i, i + len(term), any(w in s for w in excl)))
        keep, seen = [], set()
        for f in sorted(found, key=lambda f: -(f[4] - f[3])):
            if f[5]:
                continue                                   # 제외어(고추장·옥수수전분 …)
            if any(g[3] <= f[3] and f[4] <= g[4] and (g[4] - g[3]) > (f[4] - f[3]) for g in found):
                continue                                   # 더 긴 이름 안에 든 짧은 이름(단호박 안의 호박) —
                                                           # 긴 쪽이 제외됐어도 짧은 쪽은 살리지 않음(옥수수전분 안의 수수)
            if f[0] not in seen:
                seen.add(f[0])
                keep.append(f[:3])
        return keep


_WATER = {"물", "찬물", "더운물", "뜨거운물", "끓는물", "미지근한물", "생수", "정수", "얼음물", "쌀뜨물"}


def _grams(ing: dict) -> float | None:
    """g으로 적힌 분량. 물·육수는 비중 계산에서 뺀다(팥죽의 물처럼 무게만 크고 재료 비중을 흐림)."""
    name = clean_ingredient(ing.get("name"))
    if name in _WATER or name.endswith("육수"):
        return None
    if ing.get("amount_kind") == "measured" and (ing.get("unit") or "").lower() == "g" and ing.get("amount"):
        return float(ing["amount"])
    return None


def link_recipes(items: list[dict], recipes: list[dict], rules: dict) -> tuple[dict, dict]:
    """(식재료 키 → {matched_ingredients, recipes}, 레시피 ID → [식재료 키]). hold 레시피는 빼고 연결."""
    m = Matcher(items, rules)
    by_item: dict[str, dict] = {it["row_id"]: {"ingredients": {}, "recipes": {}} for it in items}
    by_recipe: dict[str, list[str]] = {}
    for rec in recipes:
        if (rec.get("quality") or {}).get("status") == "hold":
            continue
        rid = str(rec["recipe_id"])
        ings = rec.get("ingredients") or []
        total_g = sum(g for g in (_grams(i) for i in ings) if g)
        for ing in ings:
            for key, term, kind in m.match(ing.get("name")):
                slot = by_item[key]
                mi = slot["ingredients"].setdefault(ing["name"], {"name": ing["name"], "term": term, "kind": kind,
                                                                   "recipes": 0})
                r = slot["recipes"].setdefault(rid, {"recipe_id": rid, "name": rec.get("name"),
                                                     "category": rec.get("category"),
                                                     "quality_status": (rec.get("quality") or {}).get("status"),
                                                     "ingredients": [], "weight_g": 0.0, "_w": False})
                if ing["name"] not in r["ingredients"]:
                    r["ingredients"].append(ing["name"])
                    mi["recipes"] += 1
                    g = _grams(ing)
                    if g:
                        r["weight_g"] += g
                        r["_w"] = True
                by_recipe.setdefault(rid, [])
                if key not in by_recipe[rid]:
                    by_recipe[rid].append(key)
        for key in by_recipe.get(rid, []):
            r = by_item[key]["recipes"][rid]
            r["share"] = round(r["weight_g"] / total_g, 3) if r.pop("_w") and total_g else None
            r["weight_g"] = round(r["weight_g"], 1) if r["share"] is not None else None
    for slot in by_item.values():
        slot["ingredients"] = sorted(slot["ingredients"].values(), key=lambda x: (-x["recipes"], x["name"]))
        slot["recipes"] = sorted(slot["recipes"].values(),
                                 key=lambda r: (r["share"] is None, -(r["share"] or 0), r["quality_status"] != "ok",
                                                r["name"] or ""))
    return by_item, by_recipe


def _text(v) -> str | None:
    v = (v or "").strip() if isinstance(v, str) else v
    return v or None


def seasonal_record(it: dict, link: dict) -> dict:
    det = it.get("detail") or {}
    detail = {name: _text((det.get(sec) or {}).get(field)) for (sec, field), name in DETAIL_FIELDS.items()}
    related = ((det.get("connRecipeList") or {}).get("recipeInfo")) or []
    related = [related] if isinstance(related, dict) else related
    plain = re.sub(r"\(.*?\)", "", it["fdmtNm"]).strip()
    return {
        "id": it["row_id"], "month": it["month"], "fdmt_sn": str(it.get("fdmtSn")), "name": it["fdmtNm"].strip(),
        "terms": official_terms(it["fdmtNm"]), "image_url": it.get("fdmtImgUrl"),
        "detail_status": it.get("detail_status"), "detail": detail,
        "official_related_recipes": [r.get("recipeNm") for r in related if r.get("recipeNm")],
        "shopping_search_url": SHOPPING_SEARCH + quote(plain),
        "matched_ingredients": link["ingredients"], "recipe_count": len(link["recipes"]), "recipes": link["recipes"],
    }


def build_records(payload: dict, recipes: list[dict], rules: dict | None = None) -> tuple[list[dict], dict]:
    rules = rules or load_rules()
    items = payload.get("items") or []
    by_item, by_recipe = link_recipes(items, recipes, rules)
    records = [seasonal_record(it, by_item[it["row_id"]]) for it in items]
    records.sort(key=lambda r: (r["month"], r["name"]))
    return records, by_recipe
