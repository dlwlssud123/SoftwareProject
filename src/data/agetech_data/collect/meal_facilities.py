"""전국무료급식소표준데이터 수집 (공공데이터포털 표준데이터 15013107, 지자체 제공).

    uv run python -m agetech_data.refresh --source meal_facilities

API: http://api.data.go.kr/openapi/tn_pubr_public_free_mlsv_api (type=json, 1,000건씩)
응답: {"header": {"resultCode": "00", ...}, "body": {"items": {"item": [...]}, "totalCount": N}}
게이트웨이 오류(키 미등록·한도)는 XML(OpenAPI_ServiceResponse)로 온다.

원천에 행 ID가 없어 수집기가 row_id(원천 행 해시 앞 16자리)를 붙인다 — 갱신 변경 감지용.
정제 단계의 facility_id(시설 단위, 중복 등록을 합친 뒤)와는 다르다.
"""

from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urlencode

from agetech_data.net import CollectError, Fatal, Fetcher, Quota, Retry, fetch_with_retry, http_fetch
from agetech_data.textutil import sha256_json

API_URL = "http://api.data.go.kr/openapi/tn_pubr_public_free_mlsv_api"
PROVIDER = "전국 지자체 (공공데이터포털 전국무료급식소표준데이터)"
SERVICE = "전국무료급식소표준데이터 (tn_pubr_public_free_mlsv_api)"
DOCUMENTATION = "https://www.data.go.kr/data/15013107/standard.do"
PAGE_SIZE = 1000
QUOTA_CODES = {"22"}
FATAL_CODES = {"12", "20", "30", "31", "32", "33"}   # 서비스 없음·권한·키 문제 (재시도해도 같음)
NODATA = "03"


def parse_page(status: int, text: str) -> tuple[list[dict], int]:
    """한 쪽 응답 → (행 목록, 전체 건수). 한도는 Quota, 키·권한은 Fatal, 그 밖의 일시 오류는 Retry."""
    body_text = text.lstrip()
    if body_text.startswith("<"):
        try:
            root = ET.fromstring(body_text)
        except ET.ParseError:
            raise Retry("XML 해석 실패") from None
        code = (root.findtext(".//returnReasonCode") or root.findtext(".//resultCode") or "").strip()
        msg = (root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg")
               or root.findtext(".//resultMsg") or "").strip()
        if code in QUOTA_CODES:
            raise Quota(f"게이트웨이 {code} {msg}")
        raise (Fatal if code in FATAL_CODES else Retry)(f"게이트웨이 {code or '?'} {msg}")
    if status != 200:
        raise Fatal(f"HTTP {status}")
    data = json.loads(body_text)                       # 깨진 JSON → ValueError → 다시 시도
    if "response" in data:                             # 다른 형식으로 바뀌어도 읽게
        data = data["response"]
    head, body = data.get("header") or {}, data.get("body") or {}
    code = str(head.get("resultCode", "")).strip()
    if code == NODATA:
        return [], 0
    if code in QUOTA_CODES:
        raise Quota(f"resultCode={code}")
    if code != "00":
        raise Fatal(f"resultCode={code or '없음'} {head.get('resultMsg', '')}".strip())
    items = body.get("items") or {}
    rows = items.get("item") if isinstance(items, dict) else items
    if isinstance(rows, dict):
        rows = [rows]
    return [dict(r) for r in rows or []], int(body.get("totalCount") or 0)


def add_row_ids(rows: list[dict]) -> list[dict]:
    """원천 행 해시로 row_id를 붙인다. 완전히 같은 행이 둘 이상이면 -2, -3을 붙여 구분."""
    seen: dict[str, int] = {}
    out = []
    for r in rows:
        base = sha256_json({k: v for k, v in r.items() if k != "row_id"})[:16]
        seen[base] = seen.get(base, 0) + 1
        out.append({**r, "row_id": base if seen[base] == 1 else f"{base}-{seen[base]}"})
    return out


def collect_free_meal(key: str, *, fetch: Fetcher = http_fetch, sleep=time.sleep, log=print,
                      page_size: int = PAGE_SIZE) -> dict:
    """전체 쪽을 받아 {"meta", "items"}. 받은 건수가 전체 건수와 다르면 실패(부분 게시 방지)."""
    rows: list[dict] = []
    total: int | None = None
    page = 1
    while True:
        url = API_URL + "?" + urlencode({"serviceKey": key, "pageNo": page, "numOfRows": page_size, "type": "json"})
        part, count = fetch_with_retry(url, parse_page, what=f"무료급식소 {page}쪽", secrets=(key,),
                                       fetch=fetch, sleep=sleep)
        total = count if total is None else total
        rows += part
        log(f"무료급식소 {page}쪽 {len(part)}건 (누적 {len(rows)}/{total})")
        if not part or len(rows) >= total:
            break
        page += 1
    if total and len(rows) != total:
        raise CollectError(f"무료급식소 {len(rows)}/{total}건만 받음 — 게시하지 않음")
    items = add_row_ids(rows)
    meta = {
        "provider": PROVIDER, "service": SERVICE, "documentation": DOCUMENTATION,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total_count": total, "item_count": len(items),
        # DB 적재(backend import_meal_facilities)가 확인하는 값 — 건수가 다르면 위에서 이미 실패
        "complete": True, "items_sha256": sha256_json(items),
        "note": "row_id는 수집기가 붙인 원천 행 해시(원천에는 ID 없음)",
    }
    return {"meta": meta, "items": items}
