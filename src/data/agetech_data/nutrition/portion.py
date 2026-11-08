"""사용자가 확인한 식품(food_code)·분량 → 영양값. 사진 분석·식사 기록 API용.

    from agetech_data.nutrition.portion import portion_nutrients, meal_total
    p = portion_nutrients(food, 300, "g")      # food = FoodRecord (서버에서 food_code 로 찾은 행)
    meal_total([p, ...])                        # 한 끼 합계

규칙 (docs/data/food_nutrition_contract.md 7절)
- 함량은 기준량(100g 또는 100mL)당 값이다 → 영양값 = 분량 ÷ 기준량 × 기준량당 함량.
- 분량 단위(g·mL)가 기준량 단위와 같으면 그대로 계산한다(computed).
- g ↔ mL 가 다르면 1mL≈1g 으로 근사해 계산하고 표시한다(approx_ml). 밀도 근거는 없다.
- 인분·그릇 등은 원천의 1회분량 참고량(DISH_ONE_SERVING) 또는 1회 섭취참고량(NUTRI_AMOUNT_SERVING)이
  g·mL 로 적혀 있을 때만 환산한다. 없으면 계산하지 않고(unconvertible) g·mL 입력을 받는다.
  식품중량(Z10500)은 1인분 근거로 쓰지 않는다(명세 항목명이 '식품중량'일 뿐이다).
- 개·조각 등 개수 단위는 출처 있는 개당 중량표가 없어 환산하지 않는다(unconvertible).
- 결측 함량은 null 그대로 둔다. 0 으로 채우지 않는다.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Literal

from agetech_data.nutrition.fields import SUM_NUTRIENTS
from agetech_data.nutrition.foods import FoodRecord

PortionStatus = Literal["computed", "approx_ml", "unconvertible", "invalid"]
CALCULATED: tuple[PortionStatus, ...] = ("computed", "approx_ml")

# 입력 단위 → (기준 단위, 배수)
MEASURE_UNITS: dict[str, tuple[str, float]] = {
    "g": ("g", 1.0), "kg": ("g", 1000.0),
    "mL": ("mL", 1.0), "ml": ("mL", 1.0), "cc": ("mL", 1.0), "L": ("mL", 1000.0),
}
SERVING_UNITS = ("인분", "그릇", "공기", "접시", "대접", "회분")
# 1인분 환산 근거로 쓰는 원천 필드 (앞에 있는 것을 먼저 쓴다)
SERVING_FIELDS = (("dish_serving_text", "DISH_ONE_SERVING", "1회분량 참고량"),
                  ("serving_ref_text", "NUTRI_AMOUNT_SERVING", "1회 섭취참고량"))
_SERVING = re.compile(r"^\s*([\d,]+(?:\.\d+)?)\s*(g|kg|mL|ml|L)\s*$")


@dataclass
class Portion:
    status: PortionStatus
    food_code: str | None
    food_name: str | None
    input: dict                                  # {"amount": 300, "unit": "g"} — 사용자가 확인한 값 그대로
    amount: float | None = None                  # g 또는 mL 로 바꾼 분량 (계산 안 했으면 null)
    amount_unit: str | None = None
    serving: dict | None = None                  # 인분 환산에 쓴 원천 필드 {field, label, text}
    basis: dict | None = None                    # {"amount": 100.0, "unit": "g", "text": "100g"}
    factor: float | None = None                  # 분량 ÷ 기준량
    approx_ml: bool = False                      # g↔mL 를 1mL≈1g 으로 근사했는가
    nutrients: dict[str, float | None] | None = None
    missing: list[str] = field(default_factory=list)   # 원천에 값이 없는 성분 (0 아님)
    note: str = ""

    @property
    def calculated(self) -> bool:
        return self.status in CALCULATED

    def to_dict(self) -> dict:
        return asdict(self)


def _number(v) -> float | None:
    if isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x > 0 else None


def serving_reference(food: FoodRecord) -> tuple[float, str, dict] | None:
    """원천에 적힌 1인분 중량 (분량, 단위 g/mL, 근거). 없으면 None."""
    for attr, src, label in SERVING_FIELDS:
        text = getattr(food, attr, None)
        m = _SERVING.match(text or "")
        if m:
            unit, mult = MEASURE_UNITS[m.group(2)]
            return float(m.group(1).replace(",", "")) * mult, unit, {"field": src, "label": label, "text": text}
    return None


def portion_nutrients(food: FoodRecord, amount, unit: str, nutrients: list[str] = SUM_NUTRIENTS) -> Portion:
    """식품 1개 + 분량 → 영양값. 계산할 수 없으면 status 와 note 로 이유를 돌려준다(예외를 던지지 않는다)."""
    unit = (unit or "").strip()
    p = Portion("invalid", food.food_code, food.name, {"amount": amount, "unit": unit})
    if food.basis_unit is None or not food.basis_amount or "invalid_basis" in food.quality_flags:
        p.note = f"식품의 영양성분함량기준량을 읽을 수 없음 ({food.basis_text!r}) → 계산하지 않음"
        return p
    p.basis = {"amount": food.basis_amount, "unit": food.basis_unit, "text": food.basis_text}
    n = _number(amount)
    if n is None:
        p.note = "분량은 0보다 큰 숫자여야 함"
        return p

    if unit in MEASURE_UNITS:
        base_unit, mult = MEASURE_UNITS[unit]
        qty = n * mult
    elif unit in SERVING_UNITS:
        ref = serving_reference(food)
        if ref is None:
            p.status = "unconvertible"
            p.note = (f"'{unit}' 단위의 중량 근거(1회분량 참고량·1회 섭취참고량)가 원천에 없음 → "
                      "g 또는 mL 로 다시 입력")
            return p
        qty, base_unit, p.serving = n * ref[0], ref[1], ref[2]
    else:
        p.status = "unconvertible"
        p.note = (f"'{unit}' 단위는 출처 있는 중량표가 없어 환산하지 않음 → g 또는 mL 로 다시 입력"
                  if unit else "단위가 없음 → g 또는 mL 로 입력")
        return p

    p.amount, p.amount_unit = round(qty, 4), base_unit
    p.factor = round(qty / food.basis_amount, 6)
    p.approx_ml = base_unit != food.basis_unit
    p.status = "approx_ml" if p.approx_ml else "computed"
    p.nutrients = {k: (round(food.nutrients[k] * qty / food.basis_amount, 2)
                       if food.nutrients.get(k) is not None else None) for k in nutrients}
    p.missing = [k for k, v in p.nutrients.items() if v is None]
    notes = []
    if p.serving:
        notes.append(f"{n:g}{unit} × {p.serving['label']} {p.serving['text']}")
    if p.approx_ml:
        notes.append(f"기준량이 {food.basis_text}인 식품을 {base_unit}로 계산 — 1mL≈1g 근사(밀도 미반영)")
    if p.missing:
        notes.append(f"원천에 값이 없는 성분 {len(p.missing)}개는 null(0 아님)")
    p.note = " / ".join(notes)
    return p


def meal_total(portions: list[Portion], nutrients: list[str] = SUM_NUTRIENTS) -> dict:
    """한 끼(여러 음식) 합계. 계산된 음식만 더하고, 빠진 음식·결측 성분 수를 함께 돌려준다."""
    used = [p for p in portions if p.calculated]
    totals: dict[str, float | None] = {}
    missing_items: dict[str, int] = {}
    for k in nutrients:
        vals = [p.nutrients[k] for p in used if p.nutrients and p.nutrients.get(k) is not None]
        totals[k] = round(sum(vals), 2) if vals else None
        miss = len(used) - len(vals)
        if miss:
            missing_items[k] = miss
    return {
        "items": len(portions),
        "items_calculated": len(used),
        "excluded": [{"index": i, "food_code": p.food_code, "status": p.status, "note": p.note}
                     for i, p in enumerate(portions) if not p.calculated],
        "complete": bool(portions) and len(used) == len(portions),
        "approx_ml_items": sum(p.approx_ml for p in used),
        "nutrients": totals,
        "missing_items": missing_items,
    }
