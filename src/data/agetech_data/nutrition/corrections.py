"""식품영양성분DB 원천 오류 보정표 적용 (resources/food_corrections.json).

원칙 (docs/data/food_nutrition_contract.md 1절 5번)
- 수집 원본은 고치지 않는다. 정제 단계(clean_foods)에서 보정표를 적용한다.
- 근거가 있는 보정만 넣는다. 항목마다 원래 값(from)·바꾼 값(to)·이유·근거·확인자·확인일을 적는다.
- 원천 내용 해시(source_sha256, NUM 제외)와 원래 값(from)이 둘 다 맞을 때만 적용한다.
  구형 보정표는 원본 행 해시(raw_sha256)로 검증한다. 원천이 바뀌면(식약처 수정·재수집)
  적용하지 않고 레코드에 'correction_stale'을 붙여 다시 확인하게 한다.
- 보정한 레코드는 corrections[]에 원래 값과 함께 기록하고 quality_flags 에 'corrected'를 붙인다.
  품질 표시는 보정한 값으로 다시 계산한다(예: 기준량을 고치면 invalid_basis 등이 다시 판정됨).

지원 필드
- basis_text            영양성분함량기준량 원문 → basis_amount·basis_unit 도 다시 읽는다
- nutrients.<성분 키>    기준량당 함량 (키는 fields.NUTRIENT_FIELDS)
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from agetech_data.nutrition.fields import NUTRIENT_FIELDS

RESOURCES = Path(__file__).resolve().parents[1] / "resources"
CORRECTIONS_FILE = RESOURCES / "food_corrections.json"
REQUIRED = ("food_code", "food_name", "field", "from", "to", "reason", "evidence", "raw_sha256", "by", "at")
RECORD_KEYS = ("field", "from", "to", "reason", "evidence", "by", "at", "source_sha256")


@lru_cache
def load_corrections(path: Path = CORRECTIONS_FILE) -> tuple[dict, ...]:
    if not path.is_file():
        return ()
    entries = tuple(json.loads(path.read_text(encoding="utf-8"))["corrections"])
    for c in entries:
        missing = [k for k in REQUIRED if c.get(k) in (None, "")]
        if missing:
            raise ValueError(f"보정표 항목에 빈 칸: {c.get('food_code')} {missing}")
        check_field(c["field"])
        if "source_sha256" in c and not re.fullmatch(r"[0-9a-f]{64}", str(c["source_sha256"])):
            raise ValueError(f"보정표 원천 내용 해시가 잘못됨: {c.get('food_code')}")
    return entries


def check_field(field: str) -> None:
    if field == "basis_text":
        return
    if field.startswith("nutrients.") and field.split(".", 1)[1] in NUTRIENT_FIELDS:
        return
    raise ValueError(f"보정할 수 없는 필드: {field}")


def current_value(rec, field: str):
    if field == "basis_text":
        return rec.basis_text
    return rec.nutrients.get(field.split(".", 1)[1])


def _set(rec, field: str, value) -> None:
    from agetech_data.nutrition.foods import parse_basis

    if field == "basis_text":
        rec.basis_text = value
        rec.basis_amount, rec.basis_unit = parse_basis(value)
    else:
        rec.nutrients[field.split(".", 1)[1]] = value


def apply_corrections(recs, corrections) -> list[dict]:
    """recs 를 직접 고치고, 보정 항목마다 결과 {food_code, field, status}를 돌려준다.

    status: applied(적용) / stale(원천이 바뀌어 적용 안 함, 다시 확인 필요) / missing(수집본에 그 식품코드가 없음)
    """
    from agetech_data.nutrition.foods import food_flags

    by_code = {r.food_code: r for r in recs}
    results, touched = [], set()
    for c in corrections:
        check_field(c["field"])
        r = by_code.get(c["food_code"])
        if r is None:
            results.append({"food_code": c["food_code"], "field": c["field"], "status": "missing"})
            continue
        same_source = (r.source_sha256 == c["source_sha256"] if c.get("source_sha256")
                       else r.raw_sha256 == c["raw_sha256"])
        if not same_source or current_value(r, c["field"]) != c["from"]:
            if "correction_stale" not in r.quality_flags:
                r.quality_flags.append("correction_stale")
            results.append({"food_code": c["food_code"], "field": c["field"], "status": "stale"})
            continue
        _set(r, c["field"], c["to"])
        r.corrections.append({k: c[k] for k in RECORD_KEYS if k in c})
        touched.add(r.food_code)
        results.append({"food_code": c["food_code"], "field": c["field"], "status": "applied"})
    for code in touched:
        r = by_code[code]
        kept = [f for f in r.quality_flags if f in ("unparsed_value", "correction_stale")]
        r.quality_flags = kept + food_flags(r) + ["corrected"]
    return results
