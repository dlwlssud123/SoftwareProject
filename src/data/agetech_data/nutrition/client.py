"""식약처 식품영양성분DB OpenAPI 수집 (공공데이터포털 FoodNtrCpntDbInfo03).

    uv run python -m agetech_data.nutrition.client              # 품목대표 전체 → data/raw/nutrition/
    uv run python -m agetech_data.nutrition.client --max-pages 1 # 시험용

확인된 API 특성 (2026-10-31)
- 활용신청이 승인된 판본은 03. 02 판본은 같은 키로 SERVICE_KEY_IS_NOT_REGISTERED_ERROR.
- DB_CLASS_NM=품목대표 → 음식·원재료성 대표 식품 약 8.8천 건. 전체는 34만 건(대부분 가공식품).
- numOfRows 500까지 정상. DB_GRP_NM 조건은 무시된다.
- 같은 요청이 간헐적으로 HTTP 500 → 재시도한다.

원칙
- 키와 키가 들어간 URL은 출력·예외 메시지·저장 파일 어디에도 남기지 않는다.
- 모든 페이지를 받고 건수·중복을 확인한 뒤에만 원본 파일을 교체한다. 실패하면 기존 파일을 유지한다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from agetech_data import paths
from agetech_data.settings import load_secret, redact

PROVIDER = "식품의약품안전처 (공공데이터포털)"
SERVICE = "식품의약품안전처_식품영양성분DB정보"
API_VERSION = "03"
ENDPOINT = "https://apis.data.go.kr/1471000/FoodNtrCpntDbInfo03/getFoodNtrCpntDbInq03"
DOCUMENTATION = "https://www.data.go.kr/data/15127578/openapi.do"
KEY_NAME = "DATA_GO_KR_SERVICE_KEY"
DEFAULT_CLASS = "품목대표"
PAGE_SIZE = 500
RETRIES = 5
BACKOFF_SECONDS = 2.0

# (url) -> (HTTP 상태, 본문 문자열). 테스트에서 가짜로 바꿔 끼운다.
Fetcher = Callable[[str], tuple[int, str]]


class CollectError(RuntimeError):
    """수집 실패. 메시지에는 키가 들어가지 않는다."""


def http_fetch(url: str) -> tuple[int, str]:
    req = Request(url, headers={"User-Agent": "ValueFlow-data-import/1.0"})
    try:
        with urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def parse_body(text: str) -> tuple[str, str, list[dict], int | None]:
    """(resultCode, resultMsg, items, totalCount). data.go.kr 응답 형태 차이를 흡수한다."""
    data = json.loads(text)
    if "OpenAPI_ServiceResponse" in data:  # 게이트웨이 인증 오류 형식
        h = data["OpenAPI_ServiceResponse"].get("cmmMsgHeader", {})
        return str(h.get("returnReasonCode")), str(h.get("errMsg")), [], None
    root = data.get("response", data)
    header, body = root.get("header", {}), root.get("body", {})
    items = body.get("items") or []
    if isinstance(items, dict):
        items = items.get("item") or []
    if isinstance(items, dict):
        items = [items]
    total = body.get("totalCount")
    return str(header.get("resultCode")), str(header.get("resultMsg")), items, int(total) if total else None


def fetch_page(key: str, page: int, rows: int, db_class: str, fetch: Fetcher = http_fetch,
               retries: int = RETRIES, backoff: float = BACKOFF_SECONDS,
               sleep: Callable[[float], None] = time.sleep) -> tuple[list[dict], int]:
    query = urlencode({"serviceKey": key, "pageNo": page, "numOfRows": rows, "type": "json",
                       "DB_CLASS_NM": db_class})
    last = ""
    for attempt in range(1, retries + 1):
        try:
            status, text = fetch(f"{ENDPOINT}?{query}")
            if status == 200:
                code, msg, items, total = parse_body(text)
                if code in ("00", "0") and total is not None:
                    return items, total
                last = f"resultCode={code} {msg}"
                if code in ("30", "31", "32", "20", "22"):  # 키 미등록·기한 만료·권한 등: 재시도해도 같음
                    break
            else:
                last = f"HTTP {status}"
        except (URLError, TimeoutError, OSError) as e:
            last = f"네트워크 오류 {type(e).__name__}"
        except ValueError:
            last = "응답 JSON 해석 실패"
        if attempt < retries:
            sleep(backoff * attempt)
    raise CollectError(redact(f"{page}페이지 수집 실패 ({last})", key))


def collect(key: str, db_class: str = DEFAULT_CLASS, rows: int = PAGE_SIZE, max_pages: int | None = None,
            fetch: Fetcher = http_fetch, sleep: Callable[[float], None] = time.sleep,
            log: Callable[[str], None] = print) -> dict:
    if not key:
        raise CollectError(f"{KEY_NAME} 가 비어 있습니다. 레포 루트 .env 를 확인하세요 (.env.example 참고).")
    items, total = fetch_page(key, 1, rows, db_class, fetch, sleep=sleep)
    pages = -(-total // rows)
    limit = min(pages, max_pages) if max_pages else pages
    log(f"{SERVICE} {db_class}: 전체 {total}건, {pages}페이지 중 {limit}페이지 수집")
    for page in range(2, limit + 1):
        page_items, _ = fetch_page(key, page, rows, db_class, fetch, sleep=sleep)
        items.extend(page_items)
    complete = limit == pages
    codes = [it.get("FOOD_CD") for it in items]
    dup = len(codes) - len(set(codes))
    if complete and len(items) != total:
        raise CollectError(f"받은 건수({len(items)})가 totalCount({total})와 다릅니다. 기존 파일을 유지합니다.")
    if dup:
        raise CollectError(f"식품코드가 중복된 행이 {dup}건 있습니다. 기존 파일을 유지합니다.")
    return {
        "meta": {
            "provider": PROVIDER, "service": SERVICE, "api_version": API_VERSION,
            "endpoint": ENDPOINT, "documentation": DOCUMENTATION,
            "params": {"DB_CLASS_NM": db_class, "numOfRows": rows, "type": "json"},
            "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "total_count": total, "item_count": len(items), "complete": complete,
            "items_sha256": hashlib.sha256(
                json.dumps(items, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
        },
        "items": items,
    }


def save_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="식약처 식품영양성분DB(03) 수집")
    ap.add_argument("--db-class", default=DEFAULT_CLASS, help="DB_CLASS_NM (품목대표/상용제품)")
    ap.add_argument("--output", type=Path, default=paths.NUTRITION_RAW)
    ap.add_argument("--max-pages", type=int, default=None, help="시험용 페이지 상한 (원본 파일을 덮지 않음)")
    args = ap.parse_args(argv)
    try:
        result = collect(load_secret(KEY_NAME), args.db_class, max_pages=args.max_pages)
    except CollectError as e:
        print(f"수집 실패: {e} 기존 원본 파일은 그대로 둡니다.", file=sys.stderr)
        return 1
    out = args.output
    if not result["meta"]["complete"] and out == paths.NUTRITION_RAW:
        out = out.with_name(out.stem + ".partial.json")
    save_atomic(out, result)
    m = result["meta"]
    print(f"{m['item_count']}/{m['total_count']}건 저장 → {out.relative_to(paths.REPO_ROOT).as_posix()}"
          if out.is_relative_to(paths.REPO_ROOT) else f"{m['item_count']}건 저장 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
