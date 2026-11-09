"""지역별 복지 조회: 사용자 시도·시군구 → 해당 지역 사업 + 시도 전체 사업 + 전국 사업.

수급 자격을 판정하지 않는다. 지역이 맞는 사업을 '확인해 볼 만한 사업'으로 안내하고, 근거(지역 일치 범위)를 함께 준다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from agetech_data.welfare.normalize import WelfareRecord
from agetech_data.welfare.regions import FORMER_GWANGJU_DISTRICTS, MERGED, match_sgg, normalize_ctpv

SCOPE_ORDER = {"district": 0, "province": 1, "national": 2}


@dataclass
class RegionQuery:
    ctpv: str | None          # 정규화된 시도
    sgg: str | None           # 정규화된 시군구 (데이터에 있는 이름)
    ctpv_input: str | None
    sgg_input: str | None
    notes: list[str]


def resolve_region(records: list[WelfareRecord], ctpv_input: str | None, sgg_input: str | None = None) -> RegionQuery:
    notes = []
    ctpv = normalize_ctpv(ctpv_input)
    if ctpv_input and ctpv is None:
        notes.append(f"알 수 없는 시도명 '{ctpv_input}' — 전국 사업만 안내")
    elif ctpv and ctpv_input and ctpv != (ctpv_input or "").replace(" ", ""):
        notes.append(f"'{ctpv_input}' → '{ctpv}'로 찾음" + (" (2026-07-01 통합)" if ctpv == MERGED else ""))
    sgg = None
    if ctpv and sgg_input:
        known = {r.sgg for r in records if r.ctpv == ctpv and r.sgg}
        sgg = match_sgg(sgg_input, known)
        if sgg is None:
            notes.append(f"'{ctpv} {sgg_input}' 시군구 사업이 데이터에 없거나 이름을 확인할 수 없음 — 시도 전체·전국 사업만 안내")
    if ctpv == MERGED and (ctpv_input or "").replace(" ", "") in ("광주", "광주시", "광주광역시") and sgg and \
            sgg not in FORMER_GWANGJU_DISTRICTS:
        notes.append(f"'{sgg}'은 옛 광주광역시 자치구가 아님 — 입력 확인 필요")
    return RegionQuery(ctpv, sgg, ctpv_input, sgg_input, notes)


def services_for(records: list[WelfareRecord], ctpv_input: str | None, sgg_input: str | None = None, *,
                 include_national: bool = True, include_ended: bool = False,
                 as_of: date | None = None) -> tuple[RegionQuery, list[dict]]:
    """(해석한 지역, [{record, match, reason}]). 순서: 내 시군구 → 내 시도 전체 → 전국."""
    q = resolve_region(records, ctpv_input, sgg_input)
    if as_of is None:
        as_of = datetime.now(timezone(timedelta(hours=9))).date()
    query_date = as_of.isoformat()
    out = []
    for r in records:
        period_ended = r.period_end < query_date if r.period_end else "period_ended" in r.quality_flags
        if not include_ended and period_ended:
            continue
        if r.scope == "national":
            if include_national:
                out.append({"record": r, "match": "national", "reason": "전국 사업"})
        elif q.ctpv and r.ctpv == q.ctpv:
            if r.scope == "province":
                out.append({"record": r, "match": "province", "reason": f"{r.ctpv} 전체 사업"})
            elif q.sgg and r.sgg == q.sgg:
                out.append({"record": r, "match": "district", "reason": f"{r.ctpv} {r.sgg} 사업"})
    out.sort(key=lambda m: (SCOPE_ORDER[m["match"]], m["record"].detail_status == "pending",
                            m["record"].name or "", m["record"].serv_id))
    return q, out
