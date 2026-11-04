"""레시피 재료 분량 → g 환산. 근거가 있을 때만 환산하고, 근거를 함께 남긴다.

입력은 레시피 재료 파서(agetech_data.recipes.ingredients)의 항목(dict 또는 Ingredient)이다.
원문 분량(amount_text)은 바꾸지 않는다.

상태
- direct     : 원문에 g·kg·mg 로 적힘 → 그대로 환산
- direct_paren: 원문 괄호 안에 g 로 적힘 (예: 1개(50g))
- approx_ml  : 원문이 mL·L·cc → 1mL≈1g 으로 근사 (밀도 근거 없음, 보고서에 근사로 표시)
- count_unit : 개·장·알·뿌리 등 개수 단위 → 출처 있는 개당 중량표가 없어 환산하지 않음
- qualitative: 약간·적당량 → 환산하지 않음
- missing    : 분량 표기 없음
- unparsed   : 숫자는 있으나 단위를 읽지 못함
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Literal

GramStatus = Literal["direct", "direct_paren", "approx_ml", "count_unit", "qualitative", "missing", "unparsed"]
CONVERTED: tuple[GramStatus, ...] = ("direct", "direct_paren", "approx_ml")

_MASS = {"g": 1.0, "kg": 1000.0, "mg": 0.001}
_VOLUME = {"ml": 1.0, "mL": 1.0, "cc": 1.0, "L": 1000.0}
_PAREN_MASS = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|mg|g)\b")


@dataclass
class GramAmount:
    grams: float | None
    status: GramStatus
    basis: str            # 환산 근거 (보고서·검토용 문장)

    def to_dict(self) -> dict:
        return asdict(self)


def _get(item, key):
    return item.get(key) if isinstance(item, dict) else getattr(item, key)


def to_grams(item) -> GramAmount:
    amount, unit, kind = _get(item, "amount"), _get(item, "unit"), _get(item, "amount_kind")
    text = _get(item, "amount_text") or ""
    if kind == "measured" and amount is not None:
        if unit in _MASS:
            return GramAmount(round(amount * _MASS[unit], 4), "direct", f"원문 {text} → {unit} 그대로")
        if unit in _VOLUME:
            g = round(amount * _VOLUME[unit], 4)
            return GramAmount(g, "approx_ml", f"원문 {text} → 1mL≈1g 근사(밀도 미반영)")
    # 괄호 안 질량 표기 (예: 1개(50g)) — 원문 근거가 있으므로 환산
    for p in _get(item, "paren_texts") or []:
        m = _PAREN_MASS.search(p)
        if m:
            g = round(float(m.group(1)) * _MASS[m.group(2)], 4)
            return GramAmount(g, "direct_paren", f"원문 괄호 ({p}) → {m.group(1)}{m.group(2)}")
    if kind == "qualitative":
        return GramAmount(None, "qualitative", f"정성 분량 '{text}' → 환산하지 않음")
    if kind == "none":
        return GramAmount(None, "missing", "분량 표기 없음")
    if unit is None:
        return GramAmount(None, "unparsed", f"단위를 읽지 못함 '{text}'")
    return GramAmount(None, "count_unit", f"개수 단위 '{text}' → 출처 있는 개당 중량표가 없어 환산하지 않음")
