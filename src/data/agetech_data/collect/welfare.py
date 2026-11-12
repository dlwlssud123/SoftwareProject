"""한국사회보장정보원 복지서비스 수집 (공공데이터포털) — 중앙부처·지자체, 노년층.

- 중앙부처: NationalWelfareInformationsV001 (목록 callTp=L, 상세 callTp=D)
- 지자체:   LocalGovernmentWelfareInformations (LcgvWelfarelist / LcgvWelfaredetailed)
- 노년층: lifeArray=006. 2026-11-01 확인: 중앙 130건, 지자체 1,338건. 목록은 500건씩.
- 원문 보존: 목록 필드(태그→원문 텍스트)와 상세 응답 XML 전체를 그대로 저장한다. 정제·지역 정규화는 별도 단계.

일일 호출 한도 (개발계정, 2026-11-01 응답 헤더 X-RateLimit-Limit 기준)
- 중앙 상세 100회/일, 지자체 상세 1,000회/일, 지자체 목록 1,000회/일 → 상세를 매일 전부 받을 수 없다.
- 그래서 상세는 캐시(detail_cache_<kind>.json)에 받는 즉시 저장하고, 목록 내용이 그대로면 캐시를 다시 쓴다.
- 받는 순서: 상세 없음(pending) → 목록이 바뀜(stale) → 오래된 캐시(max_age_days 초과). 한도에 닿으면 멈추고
  나머지는 다음 실행에서 받는다. 목록은 항상 완전해야 게시한다.

항목의 detail_status
- fresh  : 이번 실행에서 받은 상세
- cached : 목록이 그대로라 캐시 상세를 재사용
- stale  : 목록이 바뀌었지만 아직 다시 받지 못해 이전 상세를 유지
- pending: 상세를 아직 한 번도 받지 못함 (목록 필드만 있음)
"""

from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode

from agetech_data.net import CollectError, Fatal, Fetcher, Quota, QuotaExceededError, Retry, fetch_with_retry, http_fetch
from agetech_data.textutil import sha256_json

Kind = Literal["central", "local"]
PROVIDER = "한국사회보장정보원 (공공데이터포털)"
LIFE_ELDERLY = "006"
PAGE_SIZE = 500
MAX_AGE_DAYS = 30
VOLATILE_FIELDS = ("inqNum",)  # 조회수 — 매일 바뀌므로 변경 판단에서 뺀다
# 쉼표로 이은 목록 칸 — 원천이 같은 값을 호출마다 다른 순서로 준다(11/05 → 11/12 지자체 252건이 순서만 다름).
# 변경 판단·상세 캐시 서명에서만 순서를 빼고, 수집본에는 받은 그대로 둔다.
UNORDERED_FIELDS = ("lifeArray", "lifeNmArray", "trgterIndvdlArray", "trgterIndvdlNmArray",
                    "intrsThemaArray", "intrsThemaNmArray")
API = {
    "central": {
        "service": "중앙부처 복지서비스 (NationalWelfareInformationsV001)",
        "documentation": "https://www.data.go.kr/data/15090532/openapi.do",
        "list": "https://apis.data.go.kr/B554287/NationalWelfareInformationsV001/NationalWelfarelistV001",
        "detail": "https://apis.data.go.kr/B554287/NationalWelfareInformationsV001/NationalWelfaredetailedV001",
        "list_params": {"callTp": "L", "srchKeyCode": "001"},
        "detail_params": {"callTp": "D"},
        "daily_detail_limit": 100,
    },
    "local": {
        "service": "지자체 복지서비스 (LocalGovernmentWelfareInformations)",
        "documentation": "https://www.data.go.kr/data/15108347/openapi.do",
        "list": "https://apis.data.go.kr/B554287/LocalGovernmentWelfareInformations/LcgvWelfarelist",
        "detail": "https://apis.data.go.kr/B554287/LocalGovernmentWelfareInformations/LcgvWelfaredetailed",
        "list_params": {},
        "detail_params": {},
        "daily_detail_limit": 1000,
    },
}
# 게이트웨이 결과코드: 22 일일 한도 초과 / 20·30·31·32·33 권한·키 문제 (재시도해도 같음)
QUOTA_CODES = {"22"}
FATAL_GATEWAY = {"20", "30", "31", "32", "33"}
_SERV_ID = re.compile(r"WLF\d+")
_INQ = re.compile(r"<inqNum>[^<]*</inqNum>")


def _root(status: int, text: str) -> ET.Element:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        if status == 200:
            raise Retry("XML 해석 실패") from None
        raise Fatal(f"HTTP {status}") from None
    if root.tag == "OpenAPI_ServiceResponse":
        code = (root.findtext(".//returnReasonCode") or "").strip()
        msg = (root.findtext(".//errMsg") or "").strip()
        if code in QUOTA_CODES:
            raise Quota(f"게이트웨이 {code} {msg}")
        raise (Fatal if code in FATAL_GATEWAY else Retry)(f"게이트웨이 {code} {msg}")
    if status != 200:
        raise Fatal(f"HTTP {status}")
    code = (root.findtext("resultCode") or "").strip()
    if code != "0":
        raise Fatal(f"resultCode={code or '없음'} {(root.findtext('resultMessage') or '').strip()}")
    return root


def _leaf_fields(el: ET.Element) -> dict[str, str]:
    """자식 중 하위 태그가 없는 것만 {태그: 원문 텍스트}. 목록형 하위 요소는 상세 XML 원문에 남는다."""
    return {c.tag: (c.text or "") for c in el if len(c) == 0}


def _parse_list(status: int, text: str) -> tuple[list[dict], int]:
    root = _root(status, text)
    return [_leaf_fields(n) for n in root.findall("servList")], int(root.findtext("totalCount") or 0)


def _parse_detail(status: int, text: str) -> tuple[dict, str]:
    root = _root(status, text)
    return _leaf_fields(root), text


def _comparable(fields: dict) -> dict:
    """비교용: 조회수를 빼고 쉼표 목록 칸은 순서를 무시한다."""
    out = {k: v for k, v in fields.items() if k not in VOLATILE_FIELDS}
    for k in UNORDERED_FIELDS:
        if isinstance(out.get(k), str):
            out[k] = ",".join(sorted(p.strip() for p in out[k].split(",")))
    return out


def list_signature(row: dict) -> str:
    """상세 캐시 서명 — 목록 행이 이 서명과 같으면 캐시한 상세를 그대로 쓴다."""
    return sha256_json(_comparable(row))


def legacy_list_signature(row: dict) -> str:
    """2026-11-13 전 서명(쉼표 목록 순서 포함). 이 서명으로 저장된 캐시를 다시 받지 않고 새 서명으로 옮길 때만 쓴다."""
    return sha256_json({k: v for k, v in row.items() if k not in VOLATILE_FIELDS})


def fingerprint(item: dict) -> dict:
    """변경 감지용 내용 (조회수·쉼표 목록 순서 제외)."""
    return {"list": _comparable(item["list"]),
            "detail": _comparable(item.get("detail") or {}) or None,
            "detail_xml": _INQ.sub("", item["detail_xml"]) if item.get("detail_xml") else None}


class DetailCache:
    """servId → {sig, fetched_at, detail, detail_xml}. 받는 즉시 주기적으로 디스크에 저장한다."""

    def __init__(self, path: Path | None):
        self.path = path
        self.data: dict[str, dict] = {}
        if path and path.is_file():
            self.data = json.loads(path.read_text(encoding="utf-8")).get("entries", {})
        self._dirty = 0

    def get(self, sid: str) -> dict | None:
        return self.data.get(sid)

    def put(self, sid: str, entry: dict) -> None:
        self.data[sid] = entry
        self._dirty += 1
        if self._dirty >= 25:
            self.save()

    def save(self) -> None:
        if not self.path or not self._dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps({"entries": self.data}, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self.path)
        self._dirty = 0


def collect_welfare(kind: Kind, key: str, *, life: str = LIFE_ELDERLY, details: bool = True,
                    cache_path: Path | None = None, detail_budget: int | None = None,
                    max_age_days: int = MAX_AGE_DAYS, fetch: Fetcher = http_fetch,
                    sleep: Callable[[float], None] = time.sleep, log: Callable[[str], None] = print,
                    page_size: int = PAGE_SIZE, now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> dict:
    if not key:
        raise CollectError("DATA_GO_KR_SERVICE_KEY(또는 WELFARE_API_KEY)가 비어 있습니다. 레포 루트 .env 를 확인하세요.")
    api = API[kind]
    rows: list[dict] = []
    page, total = 1, None
    while total is None or len(rows) < total:
        q = urlencode({"serviceKey": key, "pageNo": page, "numOfRows": page_size, "lifeArray": life,
                       **api["list_params"]})
        batch, t = fetch_with_retry(f"{api['list']}?{q}", _parse_list, what=f"{kind} 복지 목록 {page}페이지",
                                    secrets=(key,), fetch=fetch, sleep=sleep)
        total = t if total is None else total
        rows.extend(batch)
        if not batch:
            break
        page += 1
    ids = [r.get("servId", "") for r in rows]
    if len(rows) != total:
        raise CollectError(f"{kind} 복지 목록 건수({len(rows)})가 totalCount({total})와 다릅니다.")
    if any(not _SERV_ID.fullmatch(i) for i in ids):
        raise CollectError(f"{kind} 복지 서비스 ID(servId) 형식이 올바르지 않은 행이 있습니다.")
    if len(set(ids)) != len(ids):
        raise CollectError(f"{kind} 복지 서비스 ID 가 중복된 행이 {len(ids) - len(set(ids))}건 있습니다.")
    if any(not r.get("servNm", "").strip() for r in rows):
        raise CollectError(f"{kind} 복지 서비스명(servNm)이 빈 행이 있습니다.")
    log(f"{kind} 복지 목록: 노년층(lifeArray={life}) {total}건")

    cache = DetailCache(cache_path)
    sigs = {r["servId"]: list_signature(r) for r in rows}
    for r in rows:  # 옛 서명으로 저장된 캐시 중 목록이 그대로인 것은 새 서명으로 옮긴다(다시 받지 않음)
        c = cache.get(r["servId"])
        if c is not None and c["sig"] != sigs[r["servId"]] and c["sig"] == legacy_list_signature(r):
            cache.put(r["servId"], {**c, "sig": sigs[r["servId"]]})
    started = now()
    old_before = (started - timedelta(days=max_age_days)).isoformat(timespec="seconds")

    def priority(row: dict) -> int | None:
        c = cache.get(row["servId"])
        if c is None:
            return 0  # pending
        if c["sig"] != sigs[row["servId"]]:
            return 1  # stale
        if c["fetched_at"] < old_before:
            return 2  # 오래된 캐시
        return None   # 캐시 그대로 사용

    todo = sorted(((p, n) for n, r in enumerate(rows) if (p := priority(r)) is not None)) if details else []
    budget = len(todo) if detail_budget is None else min(detail_budget, len(todo))
    fetched, stopped = set(), None
    try:
        for count, (_p, n) in enumerate(todo[:budget], start=1):
            sid = rows[n]["servId"]
            q = urlencode({"serviceKey": key, "servId": sid, **api["detail_params"]})
            try:
                fields, xml_text = fetch_with_retry(f"{api['detail']}?{q}", _parse_detail,
                                                    what=f"{kind} 복지 상세 {sid}", secrets=(key,),
                                                    fetch=fetch, sleep=sleep)
            except QuotaExceededError as e:
                stopped = str(e)
                log(f"  상세 수집 중단: 일일 호출 한도 — 남은 {len(todo) - len(fetched)}건은 다음 실행에서 받습니다")
                break
            if fields.get("servId") != sid:
                raise CollectError(f"{kind} 복지 상세 ID 불일치: 요청 {sid}")
            cache.put(sid, {"sig": sigs[sid], "fetched_at": now().isoformat(timespec="seconds"),
                            "detail": fields, "detail_xml": xml_text})
            fetched.add(sid)
            if count % 200 == 0:
                log(f"  상세 {count}/{budget}")
    finally:
        cache.save()  # 중간에 실패해도 받은 상세는 남긴다

    items = []
    for r in rows:
        sid, c = r["servId"], cache.get(r["servId"])
        item = {"servId": sid, "list": r}
        if c is None:
            item["detail_status"] = "pending"
        else:
            item["detail_status"] = ("fresh" if sid in fetched else "cached" if c["sig"] == sigs[sid] else "stale")
            item.update(detail=c["detail"], detail_xml=c["detail_xml"], detail_fetched_at=c["fetched_at"])
        items.append(item)
    detail_counts = dict(Counter(i["detail_status"] for i in items))
    return {
        "meta": {"provider": PROVIDER, "service": api["service"], "documentation": api["documentation"],
                 "kind": kind, "params": {"lifeArray": life, **api["list_params"]},
                 "fetched_at": started.isoformat(timespec="seconds"),
                 "total_count": total, "item_count": len(items),
                 # DB 적재(backend import_welfare)가 확인하는 값: 상세 대기(pending)가 없으면 완전, 항목 해시
                 "complete": not detail_counts.get("pending"), "items_sha256": sha256_json(items),
                 "details": {"counts": detail_counts, "fetched_this_run": len(fetched),
                             "remaining": len(todo) - len(fetched), "stopped_by_quota": stopped,
                             "daily_limit": api["daily_detail_limit"], "max_age_days": max_age_days}},
        "items": items,
    }
