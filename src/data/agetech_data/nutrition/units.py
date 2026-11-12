"""레시피 재료 분량 → g 환산. 근거가 있을 때만 환산하고, 근거를 함께 남긴다.

입력은 레시피 재료 파서(agetech_data.recipes.ingredients)의 항목(dict 또는 Ingredient)이다.
원문 분량(amount_text)은 바꾸지 않는다.

상태
- direct     : 원문에 g·kg·mg 로 적힘 → 그대로 환산
- direct_paren: 원문 괄호 안에 g 로 적힘 (예: 1개(50g))
- approx_ml  : 원문이 mL·L·cc 또는 계량 단위(큰술·작은술·Ts·ts·컵 → resources/unit_weights.json 의 mL)
               → 1mL≈1g 으로 근사 (밀도 근거 없음, 보고서에 근사로 표시)
- unit_weight: 개수 단위인데 출처 있는 1단위 무게가 환산표에 있음 (예: 달걀 1개 60 g — 식약처, 한국인 영양소 섭취기준)
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

GramStatus = Literal["direct", "direct_paren", "approx_ml", "unit_weight", "count_unit", "qualitative", "missing",
                     "unparsed"]
CONVERTED: tuple[GramStatus, ...] = ("direct", "direct_paren", "approx_ml", "unit_weight")
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


def to_grams(item, unit_weights: tuple[dict, dict, dict] | None = None) -> GramAmount:
    amount, unit, kind = _get(item, "amount"), _get(item, "unit"), _get(item, "amount_kind")
    text = _get(item, "amount_text") or ""
    counts, volumes, sources = unit_weights or load_unit_weights()
    if kind == "measured" and amount is not None:
        if unit in _MASS:
            return GramAmount(round(amount * _MASS[unit], 4), "direct", f"원문 {text} → {unit} 그대로")
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
    if kind == "qualitative":
        return GramAmount(None, "qualitative", f"정성 분량 '{text}' → 환산하지 않음")
    if kind == "none":
        return GramAmount(None, "missing", "분량 표기 없음")
    if unit is None:
        return GramAmount(None, "unparsed", f"단위를 읽지 못함 '{text}'")
    return GramAmount(None, "count_unit", f"개수 단위 '{text}' → 출처 있는 개당 중량이 환산표에 없어 환산하지 않음")
