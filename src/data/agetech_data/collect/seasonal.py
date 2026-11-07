"""농식품 이달의 식재료 수집 (공공데이터포털 15168024, 농촌진흥청 국립식량과학원).

    uv run python -m agetech_data.refresh --source seasonal_foods

API: https://apis.data.go.kr/1390803/allbaroFoodMonth (format=json)
- /foodList?srchMonth=1~12   → 그달 식재료 목록 {fdmtSn, fdmtNm, fdmtImgUrl}
- /foodCont?srchFdmtSn=N     → 상세 {stdInfo: 유래·구입 요령·손질법·기타, ntkInfo: 섭취 방법·영양 성분 효능·관련 연구·소비량,
                                connRecipeList: 관련 레시피}
- 기능 경로는 포털 페이지에 묻힌 Swagger 명세에서 확인(2026-11-07). 레시피·상차림 기능(/recipeList 등)은 쓰지 않음
- 정상 결과코드는 "200"(다른 포털 API의 "00"과 다름). 게이트웨이 오류는 JSON/XML의 OpenAPI_ServiceResponse
- 한도: 하루 10,000회, **초당 10회**(넘으면 HTTP 429·코드 23, 잠시 막힘) → 호출 사이를 띄우고 23은 오래 쉬고 다시
"""

from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urlencode

from agetech_data.net import (
    CollectError,
    Fatal,
    Fetcher,
    Quota,
    QuotaExceededError,
    Retry,
    fetch_with_retry,
    http_fetch,
)

API_BASE = "https://apis.data.go.kr/1390803/allbaroFoodMonth"
PROVIDER = "농촌진흥청 국립식량과학원 (공공데이터포털)"
SERVICE = "농식품 이달의 식재료 목록정보 (allbaroFoodMonth)"
DOCUMENTATION = "https://www.data.go.kr/data/15168024/openapi.do"
OK_CODES = {"200", "00"}
QUOTA_CODES = {"22"}                 # 하루 한도
THROTTLE_CODES = {"23"}              # 초당 한도 — 쉬었다가 다시
FATAL_CODES = {"12", "20", "30", "31", "32", "33"}
MIN_INTERVAL = 0.5                   # 호출 사이 최소 간격(초). 초당 10회 한도 안쪽
RETRY_BACKOFF = 15.0                 # 코드 23이면 15·30·45…초 쉬고 다시


def _gateway(code: str, msg: str):
    if code in QUOTA_CODES:
        raise Quota(f"게이트웨이 {code} {msg}")
    if code in THROTTLE_CODES:
        raise Retry(f"초당 한도 {code}")
    raise (Fatal if code in FATAL_CODES else Retry)(f"게이트웨이 {code or '?'} {msg}")


def parse(status: int, text: str) -> dict:
    """응답 → body(dict). 게이트웨이 오류는 JSON·XML 둘 다 온다."""
    t = text.lstrip()
    if t.startswith("<"):
        try:
            root = ET.fromstring(t)
        except ET.ParseError:
            raise Retry("XML 해석 실패") from None
        _gateway((root.findtext(".//returnReasonCode") or "").strip(),
                 (root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg") or "").strip())
    data = json.loads(t)                                  # 깨진 JSON → ValueError → 다시 시도
    if "OpenAPI_ServiceResponse" in data:
        h = data["OpenAPI_ServiceResponse"].get("cmmMsgHeader") or {}
        _gateway(str(h.get("returnReasonCode", "")).strip(), str(h.get("returnAuthMsg") or h.get("errMsg") or ""))
    if status != 200:
        raise Fatal(f"HTTP {status}")
    resp = data.get("response") or data
    head, body = resp.get("header") or {}, resp.get("body") or {}
    code = str(head.get("resultCode", "")).strip()
    if code not in OK_CODES:
        raise Fatal(f"resultCode={code or '없음'} {head.get('resultMsg', '')}".strip())
    return body


def list_items(body: dict) -> list[dict]:
    items = body.get("items") or {}
    rows = items.get("item") if isinstance(items, dict) else items
    if isinstance(rows, dict):
        rows = [rows]
    return [dict(r) for r in rows or []]


class _Caller:
    def __init__(self, key: str, fetch: Fetcher, sleep, min_interval: float):
        self.key, self.fetch, self.sleep, self.min_interval = key, fetch, sleep, min_interval
        self.calls = 0

    def __call__(self, path: str, what: str, **params) -> dict:
        if self.calls:
            self.sleep(self.min_interval)
        self.calls += 1
        url = f"{API_BASE}{path}?" + urlencode({"serviceKey": self.key, "format": "json", **params})
        return fetch_with_retry(url, parse, what=what, secrets=(self.key,), fetch=self.fetch, sleep=self.sleep,
                                backoff=RETRY_BACKOFF)


def collect_seasonal(key: str, *, fetch: Fetcher = http_fetch, sleep=time.sleep, log=print, details: bool = True,
                     min_interval: float = MIN_INTERVAL) -> dict:
    """1~12월 목록 + 식재료 상세 → {"meta", "items"}. 항목 = (월, 식재료) 한 줄, row_id = 'm{월}-{fdmtSn}'.
    목록이 한 달이라도 비면 실패(부분 게시 방지). 상세 하나가 실패하면 그 항목만 detail_status='failed'."""
    call = _Caller(key, fetch, sleep, min_interval)
    items: list[dict] = []
    for month in range(1, 13):
        rows = list_items(call("/foodList", f"이달의 식재료 {month}월 목록", srchMonth=month))
        if not rows:
            raise CollectError(f"이달의 식재료 {month}월 목록이 비어 있음 — 게시하지 않음")
        for r in rows:
            items.append({"row_id": f"m{month}-{r.get('fdmtSn')}", "month": month, **r})
        log(f"이달의 식재료 {month}월 {len(rows)}개")
    failed = 0
    if details:
        cache: dict[str, dict | None] = {}
        for it in items:
            sn = str(it.get("fdmtSn"))
            if sn not in cache:
                try:
                    body = call("/foodCont", f"이달의 식재료 상세 {sn}", srchFdmtSn=sn)
                    cache[sn] = {k: body.get(k) for k in ("stdInfo", "ntkInfo", "connRecipeList")}
                except QuotaExceededError:              # 하루 한도 → 이번 수집은 실패(이전 판본 유지)
                    raise
                except CollectError as e:
                    cache[sn] = None
                    failed += 1
                    log(f"상세 실패 {sn}: {e}")
            it["detail"] = cache[sn]
            it["detail_status"] = "ok" if cache[sn] is not None else "failed"
        log(f"이달의 식재료 상세 {len(cache) - failed}/{len(cache)}개")
    meta = {"provider": PROVIDER, "service": SERVICE, "documentation": DOCUMENTATION,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "item_count": len(items), "months": 12, "api_calls": call.calls,
            "details": {"requested": details, "failed": failed}}
    return {"meta": meta, "items": items}
