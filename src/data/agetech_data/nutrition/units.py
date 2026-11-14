"""레시피 재료 분량 → g 환산. 근거가 있을 때만 환산하고, 근거를 함께 남긴다.

입력은 레시피 재료 파서(agetech_data.recipes.ingredients)의 항목(dict 또는 Ingredient)이다.
원문 분량(amount_text)은 바꾸지 않는다.

상태
- direct     : 원문에 g·kg·mg 로 적힘 → 그대로 환산
- direct_paren: 원문 괄호 안에 g 로 적힘 (예: 1개(50g))
- approx_ml  : 원문이 mL·L·cc 또는 계량 단위(큰술·작은술·Ts·ts·컵 → resources/unit_weights.json 의 mL)
               → 1mL≈1g 으로 근사 (밀도 근거 없음, 보고서에 근사로 표시)
- unit_weight: 개수 단위인데 출처 있는 1단위 무게가 환산표에 있음 (예: 달걀 1개 60 g — 식약처, 한국인 영양소 섭취기준)
- estimated  : 출처 있는 무게가 없어 추정 (resources/estimated_amounts.json — 수입 과일 USDA 분량·원문에 함께 적힌
               무게·어림, '약간·적당량'은 같은 재료를 g으로 적은 레시피들의 25% 지점·중앙값, 튀김기름은 build 에서
               레시피 단위로). 근거 문장(basis)에 무엇으로 추정했는지 적는다
- count_unit : 개·장·알·뿌리 등 개수 단위 → 출처 있는 개당 중량이 환산표에 없어 환산하지 않음
- qualitative: 약간·적당량 → 환산하지 않음
- missing    : 분량 표기 없음
- unparsed   : 숫자는 있으나 단위를 읽지 못함
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from agetech_data.nutrition.estimates import Estimates, load_estimates, qualitative_word
from agetech_data.textutil import parse_number

GramStatus = Literal["direct", "direct_paren", "approx_ml", "unit_weight", "estimated", "count_unit", "qualitative",
                     "missing", "unparsed"]
CONVERTED: tuple[GramStatus, ...] = ("direct", "direct_paren", "approx_ml", "unit_weight", "estimated")
UNIT_WEIGHTS_FILE = Path(__file__).resolve().parents[1] / "resources" / "unit_weights.json"

_MASS = {"g": 1.0, "kg": 1000.0, "mg": 0.001}
_VOLUME = {"ml": 1.0, "mL": 1.0, "cc": 1.0, "L": 1000.0}
_PAREN_MASS = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|mg|g)\b")
# 재료 파서가 단위로 읽지 않는 영문 계량 약자 — 숫자 바로 뒤 (예: '(1Ts)', '(0.3Ts)', '1/2ts', '1T')
_SPOON_ABBR = re.compile(r"[\d½¼¾⅓⅔]\s*(Tbsp|tsp|Ts|ts|T|t)(?![A-Za-z])")


@dataclass
class GramAmount:
    grams: float | None
    status: GramStatus
    basis: str            # 환산 근거 (보고서·검토용 문장)

    def to_dict(self) -> dict:
        return asdict(self)


def _get(item, key):
    return item.get(key) if isinstance(item, dict) else getattr(item, key)


def _compact(name: str | None) -> str:
    return re.sub(r"\s+", "", name or "")


@lru_cache
def load_unit_weights(path: Path = UNIT_WEIGHTS_FILE) -> tuple[dict, dict, dict]:
    """(개수 단위 {(재료명, 단위): 항목}, 계량 단위 {단위: 항목}, 출처 {키: 문장})."""
    data = json.loads(path.read_text(encoding="utf-8"))
    counts = {(_compact(e["ingredient"]), e["unit"]): e for e in data["count_units"]}
    volumes = {e["unit"]: e for e in data["volume_units"]}
    return counts, volumes, data["sources"]


def _name(item) -> str:
    """괄호 뺀 재료명(공백 없음). DB parsed·Ingredient 는 name, parse_item 결과는 name_raw 에서."""
    name = item.get("name") if isinstance(item, dict) else getattr(item, "name", None)
    if not name:
        name = re.sub(r"\([^()]*\)?", " ", _get(item, "name_raw") or "")
    return _compact(name)


_ODD_VOLUME = re.compile(r"(\d+(?:\.\d+)?)\s*(㎖|ℓ)")                        # 한 글자 단위 기호
_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*~\s*(\d+(?:\.\d+)?)\s*([가-힣]+)")    # '6~7쪽'
_TEXT_MASS = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|g)(?![A-Za-z])")
_EDIBLE_MASS = re.compile(r"^\s*([가-힣]*살)\s*(?:무게)?\s*(\d+(?:\.\d+)?)\s*g\s*$")   # 괄호 전체가 '○○살 (무게) N g'
COUNT_TEXT = re.compile(r"(\d+(?:\.\d+)?(?:/\d+)?|[½⅓⅔¼¾⅕⅛])\s*([가-힣]+)")


def _estimated_count(item, unit, amount, text, est: Estimates) -> GramAmount | None:
    guess = est.counts.get((_name(item), unit))
    if not guess:
        return None
    source = est.sources.get(guess["source"], guess["source"]).split(" — ")[0].split("(")[0].strip()
    return GramAmount(round(amount * guess["grams"], 4), "estimated",
                      f"원문 {text} → 1{unit}≈{guess['grams']}g 추정({source}: {guess['evidence']})")


def to_grams(item, unit_weights: tuple[dict, dict, dict] | None = None,
             estimates: Estimates | None = None) -> GramAmount:
    """estimates 를 빈 Estimates 로 넘기면 추정 없이(출처 있는 환산만) 계산한다."""
    amount, unit, kind = _get(item, "amount"), _get(item, "unit"), _get(item, "amount_kind")
    text = _get(item, "amount_text") or ""
    counts, volumes, sources = unit_weights or load_unit_weights()
    est = estimates if estimates is not None else load_estimates()
    if kind == "measured" and amount is not None:
        if unit in _MASS:
            g = round(amount * _MASS[unit], 4)
            # "꽃게 70g(꽃게살 30g)"·"토막 낸 닭 170g(닭고기살 무게 90g)": 껍데기·뼈 포함 무게 옆의 먹는 살 무게
            for p in _get(item, "paren_texts") or []:
                m = _EDIBLE_MASS.search(p)
                if m and float(m.group(2)) < g:
                    return GramAmount(float(m.group(2)), "direct_paren",
                                      f"원문 {text} → 괄호의 먹는 살 무게 '{m.group(1)} {m.group(2)}g'(껍데기·뼈 뺀 것)")
            return GramAmount(g, "direct", f"원문 {text} → {unit} 그대로")
        if unit in _VOLUME:
            g = round(amount * _VOLUME[unit], 4)
            return GramAmount(g, "approx_ml", f"원문 {text} → 1mL≈1g 근사(밀도 미반영)")
    # 괄호 안 질량 표기 (예: 1개(50g)) — 원문 근거가 있으므로 환산표보다 먼저
    for p in _get(item, "paren_texts") or []:
        m = _PAREN_MASS.search(p)
        if m:
            g = round(float(m.group(1)) * _MASS[m.group(2)], 4)
            return GramAmount(g, "direct_paren", f"원문 괄호 ({p}) → {m.group(1)}{m.group(2)}")
    if kind == "measured" and amount is not None:
        abbr = _SPOON_ABBR.search(text) if unit is None else None
        measure = abbr.group(1) if abbr else unit
        volume = volumes.get(measure)
        if volume:
            ml = volume["ml"]
            source = sources[volume["source"]].split(" — ")[0]
            return GramAmount(round(amount * ml, 4), "approx_ml",
                              f"원문 {text} → 1{measure}={ml}mL({source}), 1mL≈1g 근사(밀도 미반영)")
        weight = counts.get((_name(item), unit))
        if weight:
            source = sources[weight["source"]].split(",")[0]
            return GramAmount(round(amount * weight["grams"], 4), "unit_weight",
                              f"원문 {text} → 1{unit}={weight['grams']}g({source}: {weight['evidence']})")
        guess = _estimated_count(item, unit, amount, text, est)
        if guess:
            return guess
    # 원문 단위가 한 글자 기호(㎖·ℓ)이거나 범위('6~7쪽')라 재료 파서가 단위를 못 읽은 것
    m = _ODD_VOLUME.search(text)
    if m:
        ml = round(float(m.group(1)) * (1000.0 if m.group(2) == "ℓ" else 1.0), 4)
        return GramAmount(ml, "approx_ml", f"원문 {text} → {m.group(2)} = mL, 1mL≈1g 근사(밀도 미반영)")
    m = _RANGE.search(text)
    if m:
        mid, unit_r = (float(m.group(1)) + float(m.group(2))) / 2, m.group(3)
        weight = counts.get((_name(item), unit_r))
        if weight:
            source = sources[weight["source"]].split(",")[0]
            return GramAmount(round(mid * weight["grams"], 4), "unit_weight",
                              f"원문 {text} → 범위 가운데 {mid:g}{unit_r} × 1{unit_r}={weight['grams']}g({source})")
        guess = _estimated_count(item, unit_r, mid, text, est)
        if guess:
            return guess
    # 단위를 못 읽었지만 원문 안에 g 이 있음 ("1cm 정사각형 7g")
    m = _TEXT_MASS.search(text)
    if m and kind != "qualitative":
        g = round(float(m.group(1)) * _MASS[m.group(2)], 4)
        return GramAmount(g, "direct", f"원문 {text} 안의 {m.group(1)}{m.group(2)}")
    # 단위를 못 읽은 개수 표기 ("(2줄)", "(5×5cm, 2장)") — 추정 표에 그 단위가 있을 때만
    if kind != "qualitative" and unit is None:
        for m in COUNT_TEXT.finditer(text):
            n, unit_t = parse_number(m.group(1)), m.group(2)
            weight = counts.get((_name(item), unit_t)) if n else None
            if weight:
                source = sources[weight["source"]].split(",")[0]
                return GramAmount(round(n * weight["grams"], 4), "unit_weight",
                                  f"원문 {text} → {n:g}{unit_t} × 1{unit_t}={weight['grams']}g({source})")
            guess = _estimated_count(item, unit_t, n, text, est) if n else None
            if guess:
                return guess
    if kind == "qualitative":
        q, word = est.qualitative.get(_name(item)), qualitative_word(text)
        if q and word:
            where = "25% 지점" if word == "small" else "중앙값"
            return GramAmount(q[word], "estimated",
                              f"정성 분량 '{text}' → 같은 재료를 g으로 적은 레시피 {q['n']}줄의 {where} {q[word]}g(추정)")
        return GramAmount(None, "qualitative", f"정성 분량 '{text}' → 환산하지 않음")
    if kind == "none":
        return GramAmount(None, "missing", "분량 표기 없음")
    if unit is None:
        return GramAmount(None, "unparsed", f"단위를 읽지 못함 '{text}'")
    return GramAmount(None, "count_unit", f"개수 단위 '{text}' → 출처 있는 개당 중량이 환산표에 없어 환산하지 않음")
