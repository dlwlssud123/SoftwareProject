"""음식명 검색 정답 표본 평가 (resources/dish_search_gold.json).

1순위 일치: 첫 후보의 식품명이 정답 패턴에 맞고, 정답에 기준량 단위(basis)·찾은 방식(match)이 있으면 그것도 같다.
3순위 안: 상위 3개 후보 중 하나가 같은 조건을 만족한다.
정답(accept)이 빈 목록이면 후보가 하나도 없어야 일치로 센다.
"""

from __future__ import annotations

import json
from fnmatch import fnmatchcase
from pathlib import Path

from agetech_data.nutrition.match import RESOURCES, FoodIndex, search_dishes

GOLD_FILE = RESOURCES / "dish_search_gold.json"


def load_gold(path: Path = GOLD_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def meal_search_indexes(foods) -> tuple[FoodIndex, FoodIndex]:
    """(음식 DB군 색인, 원재료성 색인) — 사진 분석 음식명 검색에 쓴다."""
    return FoodIndex(foods, ("음식",)), FoodIndex(foods, ("원재료성",))


def _ok(cand: dict, entry: dict) -> bool:
    if not any(fnmatchcase(cand["name"], pat) for pat in entry["accept"]):
        return False
    if entry.get("match") and cand["match"] != entry["match"]:
        return False
    return entry.get("basis") is None or cand["basis_unit"] == entry["basis"]


def evaluate(foods, gold: dict | None = None, top: int = 3) -> dict:
    gold = load_gold() if gold is None else gold
    dish_index, raw_index = meal_search_indexes(foods)
    rows = []
    for e in gold["entries"]:
        cands = search_dishes(e["query"], dish_index, limit=top, raw_index=raw_index)
        expect_none = not e["accept"]   # 빈 목록 = 후보가 없어야 정답 (DB에 없는 음식·인식 실패 문구)
        rows.append({
            "query": e["query"], "accept": e["accept"], "basis": e.get("basis"), "note": e.get("note"),
            "known_miss": e.get("known_miss"),
            "top1": not cands if expect_none else bool(cands) and _ok(cands[0], e),
            "top3": not cands if expect_none else any(_ok(c, e) for c in cands[:top]),
            "candidates": cands,
        })
    return {
        "checked_by": gold.get("checked_by"), "checked_at": gold.get("checked_at"),
        "total": len(rows), "top1": sum(r["top1"] for r in rows), "top3": sum(r["top3"] for r in rows),
        "known_miss": sum(bool(r["known_miss"]) for r in rows),
        # 알려진 미해결이 아닌데 1순위가 틀린 항목 (회귀)
        "unexpected": [r["query"] for r in rows if not r["top1"] and not r["known_miss"]],
        "rows": rows,
    }
