"""식품영양성분DB 원본 행 → 정제 식품 레코드.

원칙
- 값은 기준량(basis, 보통 100g 또는 100mL)당 함량 그대로 둔다. g↔mL 환산은 하지 않는다.
- 빈 값은 0이 아니라 None(결측)이다. 천 단위 쉼표("1,670.000")만 정리한다.
- 원본 행 sha256 을 남겨 수집본과 추적한다. 이상값은 고치지 않고 quality_flags 로 표시한다.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field

from agetech_data.nutrition.fields import NUTRIENT_FIELDS, TEXT_FIELDS
from agetech_data.textutil import nfc, sha256_json

# 품질 표시 (모두 '고치지 않고 표시만' 한다)
FOOD_FLAGS: dict[str, str] = {
    "invalid_basis": "영양성분함량기준량이 100g/100mL 형식이 아님",
    "suspicious_name": "식품명이 시험용 값으로 보임(test 등)",
    "unparsed_value": "숫자로 읽을 수 없는 함량 값",
    "missing_energy": "에너지 결측",
    "missing_sodium": "나트륨 결측",
    "proximate_exceeds_basis": "수분·단백질·지방·회분·탄수화물 합이 기준량(g)의 105% 초과",
    "sat_fat_exceeds_fat": "포화지방산 > 지방",
    "sugars_exceeds_carbohydrate": "당류 > 탄수화물",
    "energy_macro_mismatch": "4·4·9 환산 열량과 표기 에너지 차이 35% 초과(참고)",
    "same_name_multiple_rows": "같은 식품명이 여러 행(식품코드 계열·기준량 단위가 다름)",
}

_BASIS = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(g|mL|ml)\s*$")
_WEIGHT = re.compile(r"^\s*([\d,]+(?:\.\d+)?)\s*(g|mL|ml|kg|L)\s*$")


def parse_value(v) -> tuple[float | None, bool]:
    """(값, 읽기 성공). ''·None·'None'·'-' 는 결측(None, True)."""
    if v is None:
        return None, True
    s = str(v).strip()
    if s in ("", "None", "-", "null"):
        return None, True
    try:
        return float(s.replace(",", "")), True
    except ValueError:
        return None, False


def parse_basis(text: str | None) -> tuple[float | None, str | None]:
    m = _BASIS.match(text or "")
    if not m:
        return None, None
    return float(m.group(1)), "mL" if m.group(2).lower() == "ml" else "g"


def parse_weight(text: str | None) -> tuple[float | None, str | None]:
    m = _WEIGHT.match(text or "")
    if not m:
        return None, None
    unit = {"ml": "mL", "kg": "g", "L": "mL"}.get(m.group(2), m.group(2))
    factor = 1000 if m.group(2) in ("kg", "L") else 1
    return float(m.group(1).replace(",", "")) * factor, unit


def _text(v) -> str | None:
    if v is None:
        return None
    s = nfc(str(v)).strip()
    return None if s in ("", "None") else s


@dataclass
class FoodRecord:
    food_code: str
    name: str
    db_group: str | None
    db_class: str | None
    category1: str | None
    ref_name: str | None
    basis_text: str | None
    basis_amount: float | None
    basis_unit: str | None            # "g" | "mL" | None
    food_weight_text: str | None
    food_weight_amount: float | None
    food_weight_unit: str | None
    serving_ref_text: str | None
    source_name: str | None
    create_method: str | None
    research_date: str | None
    update_date: str | None
    nutrients: dict[str, float | None]  # basis 당 함량
    raw_sha256: str
    quality_flags: list[str] = field(default_factory=list)
    dish_serving_text: str | None = None  # 1회분량 참고량 원문 (DISH_ONE_SERVING)

    def to_dict(self) -> dict:
        return asdict(self)


def clean_food(row: dict) -> FoodRecord:
    t = {k: _text(row.get(src)) for k, src in TEXT_FIELDS.items()}
    flags: list[str] = []
    nutrients: dict[str, float | None] = {}
    for key, (src, _label) in NUTRIENT_FIELDS.items():
        value, ok = parse_value(row.get(src))
        nutrients[key] = value
        if not ok and "unparsed_value" not in flags:
            flags.append("unparsed_value")
    basis_amount, basis_unit = parse_basis(t["basis_text"])
    weight_amount, weight_unit = parse_weight(t["food_weight_text"])
    rec = FoodRecord(
        food_code=t["food_code"] or "", name=t["name"] or "",
        db_group=t["db_group"], db_class=t["db_class"], category1=t["category1"], ref_name=t["ref_name"],
        basis_text=t["basis_text"], basis_amount=basis_amount, basis_unit=basis_unit,
        food_weight_text=t["food_weight_text"], food_weight_amount=weight_amount, food_weight_unit=weight_unit,
        serving_ref_text=t["serving_ref_text"], source_name=t["source_name"], create_method=t["create_method"],
        research_date=t["research_date"], update_date=t["update_date"],
        nutrients=nutrients, raw_sha256=sha256_json(row), quality_flags=flags,
        dish_serving_text=t["dish_serving_text"],
    )
    rec.quality_flags += food_flags(rec)
    return rec


def food_flags(r: FoodRecord) -> list[str]:
    n = r.nutrients
    flags = []
    if r.basis_unit is None:
        flags.append("invalid_basis")
    if r.name.strip().lower() in ("test", "테스트", "sample"):
        flags.append("suspicious_name")
    if n["energy_kcal"] is None:
        flags.append("missing_energy")
    if n["sodium_mg"] is None:
        flags.append("missing_sodium")
    prox = [n[k] for k in ("water_g", "protein_g", "fat_g", "ash_g", "carbohydrate_g")]
    if r.basis_unit == "g" and r.basis_amount and all(v is not None for v in prox):
        if sum(prox) > r.basis_amount * 1.05:
            flags.append("proximate_exceeds_basis")
    if n["sat_fat_g"] is not None and n["fat_g"] is not None and n["sat_fat_g"] > n["fat_g"] + 1e-9:
        flags.append("sat_fat_exceeds_fat")
    if (n["sugars_g"] is not None and n["carbohydrate_g"] is not None
            and n["sugars_g"] > n["carbohydrate_g"] + 1e-9):
        flags.append("sugars_exceeds_carbohydrate")
    e, p, f, c = n["energy_kcal"], n["protein_g"], n["fat_g"], n["carbohydrate_g"]
    if e and e >= 20 and None not in (p, f, c):
        if abs(4 * p + 4 * c + 9 * f - e) / e > 0.35:
            flags.append("energy_macro_mismatch")
    return flags


def clean_foods(rows: list[dict]) -> list[FoodRecord]:
    recs = [clean_food(r) for r in rows]
    names = Counter(r.name for r in recs)
    for r in recs:
        if names[r.name] > 1:
            r.quality_flags.append("same_name_multiple_rows")
    return recs
