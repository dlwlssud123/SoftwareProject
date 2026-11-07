"""무료급식소·경로식당 조회 (기획서 ADD-06): 위치 허용 시 가까운 순, 거부 시 지역(시군구 → 시도) 순.

가깝거나 지역이 같다는 이유로 이용 자격·당일 운영을 확정하지 않는다. 결과마다 확인할 점(cautions)과
자료 기준일을 함께 주고, 화면은 "이용 전 전화로 확인"을 안내한다.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

from agetech_data.facilities.normalize import MealFacility
from agetech_data.welfare.query import RegionQuery, resolve_region

CLOSED_FLAGS = {"operation_ended", "not_operating"}
CAUTIONS = {
    "reference_stale": "자료 기준일이 1년 넘음 — 지금도 운영하는지 전화로 확인",
    "coords_missing": "좌표 없음 — 지도·거리 계산에서 빠짐",
    "coords_invalid": "좌표가 국내 범위 밖 — 지도·거리 계산에서 빠짐",
    "phone_missing": "전화번호 없음 — 운영 기관·제공 지자체로 문의",
    "days_unparsed": "급식 요일을 읽지 못함 — 원문(days_raw) 확인",
    "time_unparsed": "급식 시간을 읽지 못함 — 원문(time_raw) 확인",
    "includes_delivery": "반찬·도시락 배달 포함 — 찾아가는 식당이 아닐 수 있음",
    "not_started": "운영 시작일 전",
    "operation_ended": "운영 종료일이 지남",
    "not_operating": "원천에 '미운영'으로 표시",
    "region_from_provider": "주소가 없어 제공 지자체로 지역을 정함",
}
ALWAYS = "급식 대상·요일·시간은 바뀔 수 있으니 이용 전 시설에 전화로 확인"


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def resolve(records: list[MealFacility], ctpv_input: str | None, sgg_input: str | None = None) -> RegionQuery:
    return resolve_region([SimpleNamespace(ctpv=r.ctpv, sgg=r.sgg) for r in records], ctpv_input, sgg_input)


def _item(r: MealFacility, match: str, dist: float | None) -> dict:
    return {"facility": r, "match": match, "distance_km": None if dist is None else round(dist, 2),
            "cautions": [CAUTIONS[f] for f in r.quality_flags if f in CAUTIONS] + [ALWAYS]}


def facilities_for(records: list[MealFacility], ctpv_input: str | None = None, sgg_input: str | None = None, *,
                   lat: float | None = None, lon: float | None = None, radius_km: float = 5.0,
                   include_closed: bool = False) -> tuple[RegionQuery | None, list[dict]]:
    """(해석한 지역, [{facility, match, distance_km, cautions}]).

    - 위치(lat, lon)가 있으면: 반경 radius_km 안의 좌표 있는 시설을 가까운 순으로(지역 경계와 무관).
      좌표가 없는 같은 시군구 시설은 맨 뒤에 붙인다(match='district_no_coords').
    - 위치가 없으면: 내 시군구(match='district') → 같은 시도의 다른 시군구('province'), 각각 이름순.
    - 운영 종료·미운영은 기본으로 뺀다(include_closed=True면 포함)."""
    region = resolve(records, ctpv_input, sgg_input) if ctpv_input else None
    pool = [r for r in records if include_closed or not CLOSED_FLAGS.intersection(r.quality_flags)]
    if lat is not None and lon is not None:
        near = []
        for r in pool:
            if r.latitude is None or r.longitude is None:
                continue
            d = distance_km(lat, lon, r.latitude, r.longitude)
            if d <= radius_km:
                in_sgg = region is not None and r.ctpv == region.ctpv and r.sgg == region.sgg and region.sgg
                near.append(_item(r, "district" if in_sgg else "nearby", d))
        near.sort(key=lambda x: (x["distance_km"], x["facility"].name))
        tail = []
        if region and region.sgg:
            tail = [_item(r, "district_no_coords", None) for r in pool
                    if r.ctpv == region.ctpv and r.sgg == region.sgg and r.latitude is None]
        return region, near + sorted(tail, key=lambda x: x["facility"].name)
    if region is None or not region.ctpv:
        return region, []
    out = [_item(r, "district" if region.sgg and r.sgg == region.sgg else "province", None)
           for r in pool if r.ctpv == region.ctpv]
    out.sort(key=lambda x: (x["match"] != "district", x["facility"].sgg or "", x["facility"].name))
    return region, out
