"""재료명 기반 알레르기 유발물질 추정.

COOKRCP01에는 알레르기 칸이 없다. 규칙(resources/allergen_rules.json)으로 재료명에서 추정하고,
근거 재료·맞은 단어·구분(direct 재료 자체 / usually 보통 원료로 들어가는 가공식품)을 함께 남긴다.
소·돼지를 알 수 없는 '갈비'처럼 정할 수 없는 재료는 needs_check 로 따로 둔다. 임의로 확정하지 않는다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from agetech_data.recipes.ingredients import Ingredient, IngredientResult

RULES_FILE = Path(__file__).resolve().parents[1] / "resources" / "allergen_rules.json"
BASIS = "ingredient_name"
# 비교용: 앱의 현재 규칙 (src/frontend/lib/models/recommendations.dart Recipe.fromPublicData, 2026-11-05).
# 재료 원문 전체에서 단어가 들어 있는지만 본다. 앱 선택지 '달걀'은 법령 표기 '알류'에 해당.
APP_TERMS: dict[str, tuple[str, ...]] = {
    "알류": ("달걀", "계란"), "우유": ("우유", "생크림", "버터", "치즈"), "대두": ("두부", "콩", "된장", "간장"),
    "새우": ("새우",), "밀": ("밀가루", "간장"), "땅콩": ("땅콩",),
}


def app_terms_found(parts_text: str | None, allergen: str) -> list[str]:
    text = parts_text or ""
    return [t for t in APP_TERMS.get(allergen, ()) if t in text]


def app_detect(parts_text: str | None) -> set[str]:
    return {a for a in APP_TERMS if app_terms_found(parts_text, a)}
# 이 이상이 있으면 재료명이 잘렸을 수 있어 추정이 불완전하다
INCOMPLETE_CODES = {"ingredients_none", "ingredients_unparsed", "ingredient_unclosed_paren",
                    "ingredient_unmatched_close_paren"}


@dataclass(frozen=True)
class Rule:
    name: str
    label: str
    direct: tuple[str, ...] = ()
    usually: tuple[str, ...] = ()
    exact: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    determinable: bool = True


@dataclass(frozen=True)
class Ambiguous:
    terms: tuple[str, ...]
    candidates: tuple[str, ...]
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True)
class Rules:
    standard: dict
    allergens: tuple[Rule, ...]
    ambiguous: tuple[Ambiguous, ...]

    @property
    def names(self) -> list[str]:
        return [r.name for r in self.allergens]


def _t(xs) -> tuple[str, ...]:
    return tuple(x.casefold() for x in xs or ())


@lru_cache(maxsize=4)
def load_rules(path: Path = RULES_FILE) -> Rules:
    d = json.loads(path.read_text(encoding="utf-8"))
    allergens = tuple(Rule(a["name"], a.get("label", a["name"]), _t(a.get("direct")), _t(a.get("usually")),
                           _t(a.get("exact")), _t(a.get("exclude")), a.get("determinable", True))
                      for a in d["allergens"])
    ambiguous = tuple(Ambiguous(_t(a["terms"]), tuple(a["candidates"]), _t(a.get("exclude"))) for a in d["ambiguous"])
    return Rules(d["standard"], allergens, ambiguous)


def match_key(name: str) -> str:
    """'크림치즈 > 우유' → '우유', '다진 돼지고기' → '다진돼지고기' (소문자)."""
    return re.sub(r"\s+", "", name.split(">")[-1]).casefold()


def match_name(name: str, rules: Rules | None = None, context: str = "") -> list[tuple[str, str, str]]:
    """재료명 하나 → [(물질, 맞은 단어, direct|usually)] (규칙 순서).
    context: 제외 단어를 함께 볼 원문 (예: '양고기(부채살)'의 '부채살'을 볼 때 '양고기')."""
    rules = rules or load_rules()
    k = match_key(name)
    ctx = re.sub(r"\s+", "", context).casefold()
    out = []
    for r in rules.allergens:
        if not r.determinable or not k or any(x in k or x in ctx for x in r.exclude):
            continue
        hits = ([(t, "direct") for t in r.direct if t in k] + [(t, "usually") for t in r.usually if t in k]
                + [(t, "direct") for t in r.exact if t == k])
        if hits:
            term, kind = max(hits, key=lambda h: (len(h[0]), h[1] == "direct"))
            out.append((r.name, term, kind))
    return out


def ambiguous_of(name: str, rules: Rules | None = None) -> tuple[str, tuple[str, ...]] | None:
    """정할 수 없는 재료면 (맞은 단어, 후보 물질). match_name 이 비었을 때만 쓴다."""
    rules = rules or load_rules()
    k = match_key(name)
    for a in rules.ambiguous:
        if any(x in k for x in a.exclude):
            continue
        term = next((t for t in a.terms if t in k), None)
        if term:
            return term, a.candidates
    return None


@dataclass
class AllergenResult:
    detected: list[dict] = field(default_factory=list)      # [{allergen, kind, evidence: [{ingredient, term, kind}]}]
    needs_check: list[dict] = field(default_factory=list)   # [{ingredient, term, candidates}]
    not_determinable: list[str] = field(default_factory=list)
    complete: bool = True

    @property
    def names(self) -> list[str]:
        return [d["allergen"] for d in self.detected]

    def to_dict(self) -> dict:
        return {"basis": BASIS, "detected": self.detected, "needs_check": self.needs_check,
                "not_determinable": self.not_determinable, "complete": self.complete}


_SEGMENT = re.compile(r"[\[\]()/:：,]")


def _segments(text: str) -> list[str]:
    """괄호·대괄호·구분 기호로 나눈 조각. '(버터크림재료)'처럼 '…재료'로 끝나는 머리말 조각은 뺀다."""
    return [s for s in _SEGMENT.split(text or "") if s.strip() and not re.sub(r"\s+", "", s).endswith("재료")]


def _evidence(ing: Ingredient, rules: Rules) -> tuple[list[tuple[str, dict]], dict | None]:
    """재료명에서 먼저 찾고, 항목 원문(괄호 설명·한 줄에 붙은 다음 재료)에서 더 찾는다.
    예: '흰살생선 100g [흰 살생선 양념] 달걀흰자 15g'(원문 섹션이 줄 중간에 있어 한 항목으로 합쳐짐) → 알류."""
    out = [(a, {"ingredient": ing.name, "term": t, "kind": kind}) for a, t, kind in match_name(ing.name, rules)]
    seen = {a for a, _ in out}
    for seg in _segments(ing.raw_item):
        for a, t, kind in match_name(seg, rules, context=ing.raw_item):
            if a not in seen:
                seen.add(a)
                out.append((a, {"ingredient": ing.name, "term": t, "kind": kind, "from": "item_text"}))
    if out:
        return out, None
    amb = ambiguous_of(ing.name, rules)
    return [], ({"ingredient": ing.name, "term": amb[0], "candidates": list(amb[1])} if amb else None)


def detect(ingredients: IngredientResult, rules: Rules | None = None) -> AllergenResult:
    rules = rules or load_rules()
    by_allergen: dict[str, list[dict]] = {}
    needs: list[dict] = []
    for ing in ingredients.ingredients:
        ev, amb = _evidence(ing, rules)
        for a, e in ev:
            by_allergen.setdefault(a, []).append(e)
        if amb:
            needs.append(amb)
    # 섹션 제목으로만 남은 재료 (예: '고명 : 파마산치즈'가 제목 줄로 읽힌 경우)
    for sec in ingredients.sections:
        for seg in _segments(sec.title):
            for a, t, kind in match_name(seg, rules):
                if a not in by_allergen:
                    by_allergen[a] = [{"ingredient": sec.title, "term": t, "kind": kind, "from": "section_title"}]
    detected = [{"allergen": a, "kind": "direct" if any(e["kind"] == "direct" for e in by_allergen[a]) else "usually",
                 "evidence": by_allergen[a]} for a in rules.names if a in by_allergen]
    return AllergenResult(
        detected=detected,
        needs_check=needs,
        not_determinable=[r.name for r in rules.allergens if not r.determinable],
        complete=not any(i.code in INCOMPLETE_CODES for i in ingredients.issues),
    )
