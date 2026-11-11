"""무료급식소 원천 행 → 시설 레코드 (docs/data/meal_facility_contract.md).

- 원문은 바꾸지 않고(`*_raw`) 읽을 수 있는 것만 따로 푼다: 요일 → days, 시간 → meals, 대상 → targets.
- 시도·시군구는 주소에서 정한다(옛 광주·전남·강원 이름, 어순 바뀐 '광주전남통합특별시', 띄어쓰기 빠진
  '충청남도홍성군'도 맞춤). 주소가 없으면 제공 지자체(insttNm)로.
- 같은 시설을 여러 지자체·기준일로 중복 등록한 행은 최신 기준일 하나로 합치고 merged_from 에 남긴다.
  같은 지자체가 한 장소의 다른 급식 일정을 올린 행은 서로 다른 시설 레코드로 둔다.
- 이용 자격·당일 운영을 확정하지 않는다. 기준일·운영 기간·누락을 표시해 화면이 '전화로 확인'을 안내하게 한다.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from agetech_data.welfare.regions import CTPV, CTPV_ALIASES, normalize_ctpv

DAYS = "월화수목금토일"
STALE_DAYS = 365          # 기준일이 이보다 오래되면 reference_stale
_DAY_RANGE = re.compile(rf"([{DAYS}])\s*[~\-]\s*([{DAYS}])")
_TIME = re.compile(r"(조식|중식|석식|아침|점심|저녁)?\s*\(?\s*(\d{1,2})\s*(?:[:시.]\s*(\d{1,2})\s*분?)?\s*[-~]\s*"
                   r"(\d{1,2})\s*(?:[:시.]\s*(\d{1,2})\s*분?)?")
_MEAL = {"아침": "조식", "점심": "중식", "저녁": "석식"}
_CTPV_PREFIXES = sorted(set(CTPV) | set(CTPV_ALIASES), key=len, reverse=True)


@dataclass
class MealFacility:
    facility_id: str
    name: str
    operator: str | None
    ctpv: str | None
    sgg: str | None
    address_road: str | None
    address_lot: str | None
    phone: str | None
    place: str | None
    targets: list[str]
    target_raw: str | None
    days: list[str] | None            # 월~일 순서. 못 읽으면 None (원문은 days_raw)
    days_raw: str | None
    meals: list[dict]                 # [{"meal": "중식", "start": "11:20", "end": "12:20"}]
    time_raw: str | None
    open_date: str | None
    close_date: str | None
    latitude: float | None
    longitude: float | None
    reference_date: str | None        # 원천 데이터 기준일
    provider: str | None              # 제공 지자체 insttNm
    provider_code: str | None
    source_fetched_at: str | None
    raw_sha256: str
    row_ids: list[str] = field(default_factory=list)
    merged_from: list[dict] = field(default_factory=list)
    quality_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _s(v) -> str | None:
    v = (v or "").strip() if isinstance(v, str) else v
    return v or None


def split_region(address: str | None) -> tuple[str | None, str | None]:
    """주소 앞부분 → (정규화 시도, 시군구). 시군구는 '…시/군/구'로 끝나는 둘째 토막(세종은 없음)."""
    tokens = (address or "").split()
    if not tokens:
        return None, None
    first, rest = tokens[0], tokens[1:]
    ctpv = normalize_ctpv(first)
    if ctpv is None:                                  # '충청남도홍성군'처럼 붙어 있으면 앞에서 떼어 냄
        for name in _CTPV_PREFIXES:
            if first.startswith(name) and len(first) > len(name):
                ctpv, rest = normalize_ctpv(name), [first[len(name):]] + rest
                break
    sgg = rest[0] if rest and re.search(r"[시군구]$", rest[0]) else None
    return ctpv, sgg


def parse_days(raw: str | None) -> tuple[list[str] | None, bool]:
    """('월+화+수' 등) → (요일 목록, 미운영 여부). 못 읽으면 (None, False)."""
    s = (raw or "").replace("요일", "").replace(" ", "")
    if not s:
        return None, False
    if "미운영" in s:
        return None, True
    if s in ("매일", "연중무휴", "월~일"):
        return list(DAYS), False
    s = re.sub(r"^매주", "", s)
    days = _days_only(re.sub(r"\(.*?\)", "", s))     # '월+수+금(공휴일 제외)' 괄호 설명은 뺌
    if days is None:                                  # '주 5회(월~금)', '주 2회(화, 목)' → 괄호 안 요일
        inner = [d for part in re.findall(r"\((.*?)\)", s) if (d := _days_only(part))]
        if len(inner) == 1 and re.fullmatch(r"주\d+[회일]", re.sub(r"\(.*?\)", "", s)):
            days = inner[0]
    return days, False


def _days_only(s: str) -> list[str] | None:
    """요일 글자와 구분자로만 된 글 → 요일 목록. 다른 글자가 섞이면 None."""
    s = _DAY_RANGE.sub(lambda m: DAYS[DAYS.index(m.group(1)):DAYS.index(m.group(2)) + 1], s)
    found: set[str] = set()
    for tok in re.split(r"[+,·/、ㆍ]+", s):
        if not tok:
            continue
        if not all(c in DAYS for c in tok):
            return None
        found.update(tok)
    return [d for d in DAYS if d in found] or None


_START_ONLY = re.compile(r"(조식|중식|석식|아침|점심|저녁)?\s*\(?\s*(\d{1,2})\s*(?:[:시]\s*(\d{1,2})?\s*분?)\s*~?\s*\)?\s*$")


def parse_meals(raw: str | None) -> list[dict]:
    """('중식(11:20-12:20)+석식(17:00-18:00)', '11시30분~12시30분') → [{meal, start, end}].
    시작 시각만 있으면('중식(12:00)', '11:30', '12시', '중식(11:00~)') end 는 None."""
    out = []
    for m in _TIME.finditer(raw or ""):
        meal, h1, m1, h2, m2 = m.groups()
        h1, h2, m1, m2 = int(h1), int(h2), int(m1 or 0), int(m2 or 0)
        if not (0 <= h1 <= 23 and 0 <= h2 <= 23 and m1 < 60 and m2 < 60) or (h2, m2) <= (h1, m1):
            continue
        out.append({"meal": _MEAL.get(meal, meal), "start": f"{h1:02d}:{m1:02d}", "end": f"{h2:02d}:{m2:02d}"})
    if not out:
        m = _START_ONLY.fullmatch((raw or "").strip())
        if m and 0 < int(m.group(2)) <= 23 and int(m.group(3) or 0) < 60:
            out.append({"meal": _MEAL.get(m.group(1), m.group(1)),
                        "start": f"{int(m.group(2)):02d}:{int(m.group(3) or 0):02d}", "end": None})
    return out


def _date(v: str | None, flags: list[str], name: str) -> str | None:
    v = _s(v)
    if not v:
        return None
    if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        try:
            return date.fromisoformat(v).isoformat()
        except ValueError:
            pass
    flags.append(f"invalid_date:{name}")
    return None


def _coord(lat: str | None, lon: str | None) -> tuple[float | None, float | None, bool]:
    try:
        la, lo = float(lat), float(lon)
    except (TypeError, ValueError):
        return None, None, False
    if 33.0 <= la <= 39.0 and 124.0 <= lo <= 132.0:
        return la, lo, True
    return None, None, False


def _key(name: str | None, address: str | None) -> tuple[str, str]:
    return (re.sub(r"\s+", "", name or ""), re.sub(r"\s+", "", address or ""))


def normalize_row(row: dict, fetched_at: str | None, as_of: date) -> MealFacility:
    flags: list[str] = []
    road, lot = _s(row.get("rdnmadr")), _s(row.get("lnmadr"))
    ctpv, sgg = split_region(road or lot)
    provider = _s(row.get("insttNm"))
    if not (road or lot):
        flags.append("address_missing")
    if ctpv is None and provider:
        ctpv, sgg = split_region(provider)
        if ctpv:
            flags.append("region_from_provider")
    if ctpv is None:
        flags.append("region_unknown")
    elif sgg is None and provider:                    # '완도군신지면'처럼 시군구가 뒤 글자와 붙어 못 읽음
        p_ctpv, p_sgg = split_region(provider)       # → 같은 시도의 제공 지자체(시군구 단위)로
        if p_ctpv == ctpv and p_sgg:
            sgg = p_sgg
            flags.append("sgg_from_provider")
    lat, lon, ok = _coord(row.get("latitude"), row.get("longitude"))
    if not ok:
        flags.append("coords_missing" if not (_s(row.get("latitude")) and _s(row.get("longitude"))) else "coords_invalid")
    phone = _s(row.get("phoneNumber"))
    if not phone:
        flags.append("phone_missing")
    days, closed_flag = parse_days(row.get("mlsvDate"))
    if closed_flag:
        flags.append("not_operating")
    elif days is None:
        flags.append("days_unparsed")
    meals = parse_meals(row.get("mlsvTime"))
    if not meals:
        flags.append("time_unparsed")
    if any("배달" in (row.get(k) or "") for k in ("mlsvDate", "mlsvTime", "mlsvPlace")):
        flags.append("includes_delivery")             # 찾아가는 식당이 아니라 반찬·도시락 배달(일부·전부)
    ref = _date(row.get("referenceDate"), flags, "referenceDate")
    open_d = _date(row.get("operOpenDate"), flags, "operOpenDate")
    close_d = _date(row.get("operCloseDate"), flags, "operCloseDate")
    if ref and date.fromisoformat(ref) < as_of - timedelta(days=STALE_DAYS):
        flags.append("reference_stale")
    if close_d and date.fromisoformat(close_d) < as_of:
        flags.append("operation_ended")
    if open_d and date.fromisoformat(open_d) > as_of:
        flags.append("not_started")
    target_raw = _s(row.get("mlsvTrget"))
    targets = [t.strip() for t in re.split(r"[+,·/ㆍ]", target_raw or "") if t.strip()]
    raw = {k: v for k, v in row.items() if k != "row_id"}
    return MealFacility(
        facility_id="", name=_s(row.get("fcltyNm")) or "", operator=_s(row.get("operInstitutionNm")),
        ctpv=ctpv, sgg=sgg, address_road=road, address_lot=lot, phone=phone, place=_s(row.get("mlsvPlace")),
        targets=targets, target_raw=target_raw, days=days, days_raw=_s(row.get("mlsvDate")), meals=meals,
        time_raw=_s(row.get("mlsvTime")), open_date=open_d, close_date=close_d, latitude=lat, longitude=lon,
        reference_date=ref, provider=provider, provider_code=_s(row.get("insttCode")), source_fetched_at=fetched_at,
        raw_sha256=hashlib.sha256(repr(sorted(raw.items())).encode("utf-8")).hexdigest(),
        row_ids=[row["row_id"]] if row.get("row_id") else [], quality_flags=flags,
    )


def _current_name(provider: str | None) -> bool:
    first = (provider or "").split()[:1]
    return bool(first) and normalize_ctpv(first[0]) == first[0]


def merge_duplicates(records: list[MealFacility]) -> list[MealFacility]:
    """같은 (시설명, 주소)끼리 묶는다.
    - 제공 지자체가 다르거나 기준일만 다름 → 같은 시설 중복 등록: 기준일 최신(같으면 현재 시도명 지자체) 하나
    - 제공 지자체가 같고 급식 요일·시간이 다름 → 다른 급식 일정: 모두 남김
    facility_id = 'FM' + (시도|시설명|주소) 해시 앞 10자리. 같은 곳의 다른 일정은 -2, -3."""
    groups: dict[tuple[str, str], list[MealFacility]] = {}
    for r in records:
        groups.setdefault(_key(r.name, r.address_road or r.address_lot), []).append(r)
    out: list[MealFacility] = []
    for (name_key, addr_key), rs in groups.items():
        same_provider = len({r.provider_code for r in rs}) == 1
        schedules = {(r.days_raw, r.time_raw) for r in rs}
        if len(rs) > 1 and same_provider and len(schedules) > 1:
            keep = sorted(rs, key=lambda r: (r.days_raw or "", r.time_raw or ""))
        else:
            best = max(rs, key=lambda r: (r.reference_date or "", _current_name(r.provider), r.provider_code or ""))
            others = [r for r in rs if r is not best]
            if others:
                best.merged_from = [{"provider": o.provider, "provider_code": o.provider_code,
                                     "reference_date": o.reference_date, "row_ids": o.row_ids} for o in others]
                best.row_ids = best.row_ids + [i for o in others for i in o.row_ids]
                best.quality_flags.append("duplicate_merged")
            keep = [best]
        base = "FM" + hashlib.sha256(f"{keep[0].ctpv}|{name_key}|{addr_key}".encode("utf-8")).hexdigest()[:10]
        for i, r in enumerate(keep, start=1):
            r.facility_id = base if i == 1 else f"{base}-{i}"
            out.append(r)
    out.sort(key=lambda r: (r.ctpv or "~", r.sgg or "~", r.name, r.facility_id))
    return out


def normalize_payload(payload: dict, as_of: date | None = None) -> list[MealFacility]:
    as_of = as_of or date.today()
    fetched = (payload.get("meta") or {}).get("fetched_at")
    return merge_duplicates([normalize_row(r, fetched, as_of) for r in payload.get("items") or []])
