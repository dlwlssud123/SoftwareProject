"""갱신 수집본(collect.meal_facilities) → DB meal_facilities 행 (backend app.jobs.import_meal_facilities 의 입력).

    from agetech_data.facilities.revision import facility_rows
    rows, skipped = facility_rows(payload)      # payload = data/raw/facilities/free_meal.json

- 정제는 facilities.normalize 그대로다(docs/data/meal_facility_contract.md 2절). 판단 기준일(as_of)은 실행 날짜가
  아니라 **수집 날짜(KST)** 라서 같은 수집본이면 언제 적재해도 같은 행이 나온다.
- normalized = 정제 레코드에서 실행마다 바뀌는 칸(VOLATILE_FIELDS)을 뺀 것, content_sha256 = 그 해시.
- 표 칸(#18 meal_facilities): checked_on = 수집 날짜(우리가 원천에서 확인한 날), reference_date = 원천 자료 기준일
  (화면의 '자료 기준일'), hours_text = 요일 원문 + 시간 원문, eligibility_text = 대상 원문, contact_text = 전화번호.
- 시도·시군구를 못 정한 시설은 지역 조회에 걸 수 없어서 적재하지 않는다(skipped 로 돌려준다).
- 운영 종료·미운영 시설은 행은 넣되 is_published = False — 기본 조회에서 빼는 규칙(정의서 1절 5)과 같다.
"""

from __future__ import annotations

from datetime import date

from agetech_data.collect.meal_facilities import DOCUMENTATION
from agetech_data.facilities.normalize import normalize_payload
from agetech_data.snapshot import collected_on
from agetech_data.textutil import sha256_json

NORMALIZER_VERSION = "refresh-meal-facilities-v1"
PROVIDER = "data.go.kr:15013107"                # 전국무료급식소표준데이터
SOURCE_URL = DOCUMENTATION
# 정제 레코드에서 비교에 쓰지 않는 칸 — 수집 시각만 바뀐 날은 같은 내용
VOLATILE_FIELDS = ("source_fetched_at",)
# 이 표시가 있으면 게시하지 않음(기본 조회에서 뺌)
HIDDEN_FLAGS = ("operation_ended", "not_operating")


def record_content(record: dict) -> dict:
    return {k: v for k, v in record.items() if k not in VOLATILE_FIELDS}


def hours_text(days_raw: str | None, time_raw: str | None) -> str | None:
    """'수+목' + '중식(11:20-12:20)' → '수+목 / 중식(11:20-12:20)'. 원문을 바꾸지 않고 잇기만 한다."""
    parts = [p for p in (days_raw, time_raw) if p]
    return " / ".join(parts) or None


def facility_rows(payload: dict) -> tuple[list[dict], list[dict]]:
    """수집본 한 파일 → (적재 행, 적재하지 않은 시설 [{source_id, name, reason}]). 순서는 정제 결과 그대로."""
    as_of = collected_on(payload["meta"])
    rows, skipped = [], []
    for rec in normalize_payload(payload, as_of):
        if not rec.name:
            skipped.append({"source_id": rec.facility_id, "name": rec.name, "reason": "name_missing"})
            continue
        if not rec.ctpv or not rec.sgg:
            reason = "sigungu_unknown" if rec.ctpv else "region_unknown"
            skipped.append({"source_id": rec.facility_id, "name": rec.name, "reason": reason})
            continue
        normalized = record_content(rec.to_dict())
        rows.append({
            "source_id": rec.facility_id,
            "name": rec.name,
            "sido": rec.ctpv,
            "sigungu": rec.sgg,
            "address": rec.address_road or rec.address_lot,
            "latitude": rec.latitude,
            "longitude": rec.longitude,
            "eligibility_text": rec.target_raw,
            "hours_text": hours_text(rec.days_raw, rec.time_raw),
            "contact_text": rec.phone,
            "source_url": SOURCE_URL,
            "reference_date": date.fromisoformat(rec.reference_date) if rec.reference_date else None,
            "quality_flags": list(rec.quality_flags),
            "checked_on": as_of,
            "is_published": not set(HIDDEN_FLAGS) & set(rec.quality_flags),
            "normalized": normalized,
            "content_sha256": sha256_json(normalized),
        })
    ids = [r["source_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate meal facility IDs")
    return rows, skipped
