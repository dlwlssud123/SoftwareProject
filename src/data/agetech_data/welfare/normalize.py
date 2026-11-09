"""복지 원문(갱신 최신본) → 통합 레코드.

입력: data/raw/welfare/{central,local}_elderly.json 의 items[] = {servId, list, detail?, detail_xml?, detail_status}
원칙
- 원문은 raw 파일에 그대로 있다. 여기서는 HTML 엔티티·<br>·태그만 정리하고 내용을 바꾸지 않는다.
- 상세를 아직 못 받은 항목(pending)도 목록 정보로 레코드를 만들고, 확인 못 한 필드는 unverified_fields 로 표시한다.
- 수급 자격을 판정하지 않는다. 대상·기준 문장은 원문 그대로 안내용으로만 둔다.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import date
from html import unescape

from agetech_data.textutil import nfc, sha256_json
from agetech_data.welfare.regions import normalize_ctpv, normalize_sgg

# 통합 필드 → (중앙 태그 후보, 지자체 태그 후보). 목록·상세 어디서든 처음 값이 있는 것을 쓴다.
TEXT_FIELDS: dict[str, tuple[str, ...]] = {
    "name": ("servNm",),
    "summary": ("servDgst",),
    "target_detail": ("tgtrDtlCn", "sprtTrgtCn"),        # 지원 대상
    "selection_criteria": ("slctCritCn",),               # 선정 기준
    "benefits": ("alwServCn",),                          # 지원 내용
    "apply_detail": ("aplyMtdCn",),                      # 신청 방법 설명
    "support_cycle": ("sprtCycNm",),
    "department": ("bizChrDeptNm",),
    "ministry": ("jurMnofNm",),
    "ministry_office": ("jurOrgNm",),
    "main_contact": ("rprsCtadr",),
    "detail_url": ("servDtlLink",),
    "criteria_year": ("crtrYr",),
}
LIST_FIELDS: dict[str, tuple[str, ...]] = {
    "life_stages": ("lifeArray", "lifeNmArray"),
    "target_groups": ("trgterIndvdlArray", "trgterIndvdlNmArray"),
    "themes": ("intrsThemaArray", "intrsThemaNmArray"),
    "provision_types": ("srvPvsnNm",),
    "apply_methods": ("aplyMtdNm",),
}
DATE_FIELDS: dict[str, tuple[str, ...]] = {
    "last_modified": ("lastModYmd",),
    "first_registered": ("svcfrstRegTs",),
    "period_start": ("enfcBgngYmd",),
    "period_end": ("enfcEndYmd",),
}
# 상세 XML 안의 목록형 요소
GROUPS = {"contacts": "inqplCtadrList", "homepages": "inqplHmpgReldList", "apply_guides": "applmetList",
          "laws": "baslawList", "forms": "basfrmList"}
# 목록형 요소의 하위 태그 → 공통 키 (중앙 servSe…, 지자체 wlfareInfo…)
ENTRY_NAME_TAGS = ("servSeDetailNm", "wlfareInfoReldNm")
ENTRY_VALUE_TAGS = ("servSeDetailLink", "wlfareInfoReldCn")
# 값이 주소여야 하는 목록 — url·link_status 를 붙인다
LINK_GROUPS = ("homepages", "forms")
# 안내 카드에 필요한데 상세에서만 오는 필드 — 없으면 '미확인'으로 표시
DETAIL_KEY_FIELDS = ("target_detail", "selection_criteria", "benefits")

_TAG = re.compile(r"<[^>]+>")
_BR = re.compile(r"<br\s*/?>", re.I)
_URL = re.compile(r"^https?://\S+$", re.I)
_DOMAIN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}(/\S*)?$", re.I)
# '첨부파일없음.hwp'처럼 첨부가 없다는 자리 표시 파일 — 내려받을 서식이 아니다 (11/06 수집본 88건)
_PLACEHOLDER_FORM = re.compile(r"^(첨부\s*파일\s*)?없음\.(hwpx?|pdf|docx?)$", re.I)


def is_placeholder_form(entry: dict) -> bool:
    return bool(_PLACEHOLDER_FORM.match((entry.get("name") or "").strip()))


def clean_text(v: str | None) -> str | None:
    if v is None:
        return None
    s = unescape(unescape(nfc(v)))
    s = _BR.sub("\n", s)
    s = _TAG.sub("", s)
    s = s.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s)
    s = "\n".join(line.strip() for line in s.split("\n")).strip()
    return s or None


def split_list(v: str | None) -> list[str]:
    return [p.strip() for p in re.split(r"[,，]", clean_text(v) or "") if p.strip()]


def parse_ymd(v: str | None) -> tuple[str | None, bool]:
    """'20261028' → ('2026-10-28', True). 빈 값 (None, True), 형식 오류 (None, False)."""
    s = re.sub(r"\D", "", v or "")
    if not s:
        return None, True
    if len(s) == 8:
        try:
            return date(int(s[:4]), int(s[4:6]), int(s[6:])).isoformat(), True
        except ValueError:
            return None, False
    return None, False


def link_of(v: str | None) -> tuple[str | None, str]:
    """원문 값 → (열 수 있는 주소, 상태).
    ok: 원문이 http(s) 주소 / scheme_added: 도메인만 있어 https:// 를 붙임 / not_url: 주소가 아님(예: '목포시청')."""
    if v and _URL.match(v):
        return v, "ok"
    if v and _DOMAIN.match(v):
        return "https://" + v, "scheme_added"
    return None, "not_url"


def _entry(key: str, raw: dict) -> dict:
    """원천 하위 태그 → {name, value[, url, link_status], raw}. raw 에 원천 태그를 그대로 남긴다."""
    e = {"name": _first([raw], ENTRY_NAME_TAGS), "value": _first([raw], ENTRY_VALUE_TAGS)}
    if key in LINK_GROUPS:
        e["url"], e["link_status"] = link_of(e["value"])
    e["raw"] = raw
    return e


def _groups(detail_xml: str | None) -> dict[str, list[dict]]:
    """상세 XML 목록형 요소 → 공통 키 항목 배열 (원천 하위 태그는 각 항목의 raw 에 모두 보존)."""
    out: dict[str, list[dict]] = {k: [] for k in GROUPS}
    if not detail_xml:
        return out
    try:
        root = ET.fromstring(detail_xml)
    except ET.ParseError:
        return out
    for key, tag in GROUPS.items():
        for el in root.iter(tag):
            raw = {c.tag: clean_text(c.text) for c in el if len(c) == 0 and clean_text(c.text)}
            e = _entry(key, raw)
            if e["name"] or e["value"]:  # 구분 코드만 있는 빈 항목은 뺀다
                out[key].append(e)
    return out


@dataclass
class WelfareRecord:
    serv_id: str
    source: str                      # central / local
    scope: str                       # national / province / district
    ctpv: str | None                 # 현재 시도명
    sgg: str | None
    ctpv_raw: str | None
    sgg_raw: str | None
    name: str | None
    summary: str | None
    target_detail: str | None
    selection_criteria: str | None
    benefits: str | None
    apply_detail: str | None
    support_cycle: str | None
    department: str | None
    ministry: str | None
    ministry_office: str | None
    main_contact: str | None
    detail_url: str | None
    criteria_year: str | None
    life_stages: list[str]
    target_groups: list[str]
    themes: list[str]
    provision_types: list[str]
    apply_methods: list[str]
    online_apply: bool | None
    last_modified: str | None
    first_registered: str | None
    period_start: str | None
    period_end: str | None
    contacts: list[dict]
    homepages: list[dict]
    apply_guides: list[dict]
    laws: list[dict]
    forms: list[dict]
    detail_status: str               # fresh / cached / stale / pending
    detail_fetched_at: str | None
    source_fetched_at: str | None    # 목록 확인 시각 (갱신 실행 시각)
    raw_sha256: str
    unverified_fields: list[str] = field(default_factory=list)
    quality_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _first(sources: list[dict], tags: tuple[str, ...]) -> str | None:
    for src in sources:
        for t in tags:
            v = src.get(t)
            if v is not None and str(v).strip():
                return v
    return None


def normalize_item(item: dict, source: str, fetched_at: str | None, as_of: date) -> WelfareRecord:
    lst, det = item.get("list") or {}, item.get("detail") or {}
    status = item.get("detail_status") or ("fresh" if det else "pending")
    # 재수집 대기 중인 상세가 최신 목록의 지역·기간을 되돌리지 않도록 한다.
    srcs = [{**det, **lst}] if status == "stale" else [det, lst]
    flags: list[str] = []
    text = {k: clean_text(_first(srcs, tags)) for k, tags in TEXT_FIELDS.items()}
    lists = {k: split_list(_first(srcs, tags)) for k, tags in LIST_FIELDS.items()}
    dates = {}
    for k, tags in DATE_FIELDS.items():
        dates[k], ok = parse_ymd(_first(srcs, tags))
        if not ok:
            flags.append(f"invalid_date:{k}")
    ctpv_raw = clean_text(_first(srcs, ("ctpvNm",)))
    sgg_raw = clean_text(_first(srcs, ("sggNm",)))
    if source == "central":
        scope, ctpv, sgg = "national", None, None
    else:
        ctpv, sgg = normalize_ctpv(ctpv_raw), normalize_sgg(sgg_raw)
        scope = "district" if sgg else "province"
        if ctpv is None:
            flags.append("unknown_ctpv")
    online = _first(srcs, ("onapPsbltYn",))
    if status == "pending":
        flags.append("detail_pending")
    elif status == "stale":
        flags.append("detail_stale")
    if dates["period_end"] and dates["period_end"] < as_of.isoformat():
        flags.append("period_ended")
    if not text["detail_url"] or not re.match(r"^https://(www\.)?bokjiro\.go\.kr/", text["detail_url"] or ""):
        flags.append("no_official_link")
    groups = _groups(item.get("detail_xml"))
    if any(e["link_status"] == "not_url" for e in groups["homepages"]):
        flags.append("homepage_not_url")
    if any(is_placeholder_form(e) for e in groups["forms"]):
        # 자리 표시 파일은 서식 목록에서 뺀다(원문은 data/raw 에 그대로)
        groups["forms"] = [e for e in groups["forms"] if not is_placeholder_form(e)]
        flags.append("placeholder_form")
    unverified = [k for k in DETAIL_KEY_FIELDS if not text[k]]
    if source == "local" and not text["apply_detail"]:
        unverified.append("apply_detail")
    if not groups["contacts"] and not text["main_contact"]:
        unverified.append("contacts")
    return WelfareRecord(
        serv_id=item["servId"], source=source, scope=scope, ctpv=ctpv, sgg=sgg, ctpv_raw=ctpv_raw, sgg_raw=sgg_raw,
        **text, **lists,
        online_apply={"Y": True, "N": False}.get((online or "").strip().upper()),
        **dates, **groups,
        detail_status=status, detail_fetched_at=item.get("detail_fetched_at"), source_fetched_at=fetched_at,
        raw_sha256=sha256_json(item), unverified_fields=unverified, quality_flags=flags,
    )


def normalize_payload(payload: dict, source: str, as_of: date | None = None) -> list[WelfareRecord]:
    meta = payload.get("meta") or {}
    fetched = meta.get("fetched_at")
    if as_of is None:
        as_of = date.fromisoformat(fetched[:10]) if fetched else date.today()
    return [normalize_item(it, source, fetched, as_of) for it in payload.get("items") or []]
