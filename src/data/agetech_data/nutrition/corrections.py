"""식품영양성분DB 원천 오류 보정표 적용 (resources/food_corrections.json).

원칙 (docs/data/food_nutrition_contract.md 1절 5번)
- 수집 원본은 고치지 않는다. 정제 단계(clean_foods)에서 보정표를 적용한다.
- 근거가 있는 보정만 넣는다. 항목마다 원래 값(from)·바꾼 값(to)·이유·근거·확인자·확인일을 적는다.
- 원천 내용 해시(source_sha256, NUM 제외)와 원래 값(from)이 둘 다 맞을 때만 적용한다.
  구형 보정표는 원본 행 해시(raw_sha256)로 검증한다. 원천이 바뀌면(식약처 수정·재수집)
  적용하지 않고 레코드에 'correction_stale'을 붙여 다시 확인하게 한다.
- 보정한 레코드는 corrections[]에 원래 값과 함께 기록하고 quality_flags 에 'corrected'를 붙인다.
  품질 표시는 보정한 값으로 다시 계산한다(예: 기준량을 고치면 invalid_basis 등이 다시 판정됨).
- 빈 값 채우기(kind = "fill_missing"): 원천에 측정값이 없는 성분(from = null)을 같은 DB의 같은 식품 행에서
  근거를 대고 채운다. 오류 보정이 아니라 추정이라 quality_flags 에 'filled'를 붙여 구분한다. 원천이 나중에
  값을 내면(from 이 null 이 아니게 되면) 적용하지 않고 correction_stale 로 알린다 — 원천 값이 우선.

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
RECORD_KEYS = ("field", "kind", "from", "to", "reason", "evidence", "by", "at", "source_sha256")
FILL = "fill_missing"


@lru_cache
def load_corrections(path: Path = CORRECTIONS_FILE) -> tuple[dict, ...]:
    if not path.is_file():
        return ()
    entries = tuple(json.loads(path.read_text(encoding="utf-8"))["corrections"])
    for c in entries:
        fill = c.get("kind") == FILL
        missing = [k for k in REQUIRED if c.get(k) in (None, "") and not (fill and k == "from")]
        if missing:
            raise ValueError(f"보정표 항목에 빈 칸: {c.get('food_code')} {missing}")
        check_field(c["field"])
        if c.get("kind") not in (None, FILL):
            raise ValueError(f"보정표 항목 종류가 잘못됨: {c.get('food_code')} {c.get('kind')}")
        if fill and (c["from"] is not None or not c["field"].startswith("nutrients.")
                     or not isinstance(c["to"], (int, float)) or c["to"] < 0):
            raise ValueError(f"빈 값 채우기는 원천이 빈(from = null) 성분에 0 이상 숫자만: {c.get('food_code')}")
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
    results, touched, filled = [], set(), set()
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
        (filled if c.get("kind") == FILL else touched).add(r.food_code)
        results.append({"food_code": c["food_code"], "field": c["field"], "status": "applied"})
    for code in touched | filled:
        r = by_code[code]
        kept = [f for f in r.quality_flags if f in ("unparsed_value", "correction_stale")]
        r.quality_flags = (kept + food_flags(r) + (["corrected"] if code in touched else [])
                           + (["filled"] if code in filled else []))
    return results
