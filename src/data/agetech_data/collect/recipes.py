"""식품안전나라 COOKRCP01(조리식품 레시피 DB) 전체 수집.

- 요청 형식: https://openapi.foodsafetykorea.go.kr/api/{키}/COOKRCP01/json/{시작}/{끝} (한 번에 최대 1000건)
- 2026-10-31 확인: 전체 1,156건 → 2회 호출
- 앱 자산(src/frontend/assets/data/recipes.json)은 건드리지 않는다. 이미지도 받지 않는다.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import quote

from agetech_data.net import CollectError, Fatal, Fetcher, Retry, fetch_with_retry, http_fetch

PROVIDER = "식품의약품안전처 식품안전나라"
SERVICE = "COOKRCP01"
DOCUMENTATION = "https://www.foodsafetykorea.go.kr/api/newDatasetDetail.do?svc_no=COOKRCP01"
URL = "https://openapi.foodsafetykorea.go.kr/api/{key}/COOKRCP01/json/{start}/{end}"
PAGE_SIZE = 1000
# INFO-000 정상, INFO-200 해당 데이터 없음, INFO-100 인증키 오류, INFO-300 호출 한도 초과 등
FATAL_CODES = {"INFO-100", "INFO-200", "INFO-300", "INFO-400", "ERROR-300", "ERROR-310", "ERROR-331",
               "ERROR-332", "ERROR-334", "ERROR-336"}


def _parse(status: int, text: str) -> tuple[list[dict], int]:
    if status != 200:
        raise Fatal(f"HTTP {status}")
    data = json.loads(text)
    svc = data.get("COOKRCP01", data) if isinstance(data, dict) else {}
    code = str((svc.get("RESULT") or {}).get("CODE", ""))
    if code != "INFO-000":
        raise (Fatal if code in FATAL_CODES else Retry)(f"결과 코드 {code or '없음'}")
    rows = svc.get("row") or []
    if not isinstance(rows, list):
        raise Fatal("row 형식 오류")
    return rows, int(svc.get("total_count") or 0)


def collect_recipes(key: str, *, fetch: Fetcher = http_fetch, sleep: Callable[[float], None] = time.sleep,
                    log: Callable[[str], None] = print, page_size: int = PAGE_SIZE) -> dict:
    if not key:
        raise CollectError("FOODSAFETY_API_KEY 가 비어 있습니다. 레포 루트 .env 를 확인하세요 (.env.example 참고).")
    k = quote(key, safe="")
    items: list[dict] = []
    start, total = 1, None
    while total is None or start <= total:
        url = URL.format(key=k, start=start, end=start + page_size - 1)
        rows, t = fetch_with_retry(url, _parse, what=f"레시피 {start}번부터", secrets=(key,), fetch=fetch, sleep=sleep)
        total = t if total is None else total
        items.extend(rows)
        if not rows:
            break
        start += page_size
    log(f"{SERVICE}: 전체 {total}건 중 {len(items)}건 수집")
    ids = [str(r.get("RCP_SEQ", "")) for r in items]
    if len(items) != total:
        raise CollectError(f"받은 건수({len(items)})가 total_count({total})와 다릅니다.")
    if any(not re.fullmatch(r"\d+", i) for i in ids):
        raise CollectError("레시피 ID(RCP_SEQ)가 비었거나 숫자가 아닌 행이 있습니다.")
    if len(set(ids)) != len(ids):
        raise CollectError(f"레시피 ID 가 중복된 행이 {len(ids) - len(set(ids))}건 있습니다.")
    if any(not str(r.get("RCP_NM", "")).strip() for r in items):
        raise CollectError("메뉴명(RCP_NM)이 빈 행이 있습니다.")
    return {
        "meta": {"provider": PROVIDER, "service": SERVICE, "documentation": DOCUMENTATION,
                 "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
                 "total_count": total, "item_count": len(items)},
        "items": items,
    }
