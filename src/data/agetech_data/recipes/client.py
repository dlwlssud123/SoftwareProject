"""Collect the complete official COOKRCP01 dataset without replacing app assets."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from agetech_data import paths
from agetech_data.settings import load_secret
from agetech_data.textutil import sha256_json

KEY_NAME = "FOODSAFETY_API_KEY"
DOCUMENTATION = (
    "https://www.foodsafetykorea.go.kr/api/newDatasetDetail.do?svc_no=COOKRCP01"
)
Fetcher = Callable[[str], tuple[int, str]]


class CollectError(RuntimeError):
    """A public collection error that never contains credential-bearing URLs."""


def http_fetch(url: str) -> tuple[int, str]:
    request = Request(url, headers={"User-Agent": "ValueFlow-data-import/1.0"})
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8-sig")
    except HTTPError as error:
        return error.code, ""


def fetch_page(
    key: str,
    start: int,
    end: int,
    fetch: Fetcher = http_fetch,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[dict], int]:
    url = f"https://openapi.foodsafetykorea.go.kr/api/{quote(key, safe='')}/COOKRCP01/json/{start}/{end}"
    for attempt in range(3):
        try:
            status, body = fetch(url)
            if status == 200:
                root = json.loads(body)["COOKRCP01"]
                if root.get("RESULT", {}).get("CODE") != "INFO-000":
                    raise CollectError(
                        "COOKRCP01 rejected the request; check credentials and quota"
                    )
                rows, total = root.get("row"), int(root["total_count"])
                if not isinstance(rows, list) or not all(
                    isinstance(row, dict) for row in rows
                ):
                    raise CollectError("COOKRCP01 returned an invalid row list")
                if total <= 0 or not rows:
                    raise CollectError("COOKRCP01 returned an empty dataset")
                return rows, total
            if 400 <= status < 500 and status != 429:
                raise CollectError(f"COOKRCP01 HTTP {status}; check access permissions")
        except (URLError, TimeoutError, OSError, ValueError, KeyError, TypeError):
            pass
        if attempt < 2:
            sleep(2 * (attempt + 1))
    raise CollectError(f"COOKRCP01 rows {start}-{end} could not be collected")


def collect(
    key: str,
    page_size: int = 500,
    fetch: Fetcher = http_fetch,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> dict:
    if not key:
        raise CollectError(f"{KEY_NAME} is not configured")
    if not 1 <= page_size <= 1000:
        raise CollectError("Page size must be between 1 and 1000")
    items, total = fetch_page(key, 1, page_size, fetch, sleep)
    log(f"COOKRCP01: expected {total} recipes")
    for start in range(page_size + 1, total + 1, page_size):
        page, observed_total = fetch_page(
            key, start, min(start + page_size - 1, total), fetch, sleep
        )
        if observed_total != total:
            raise CollectError(
                "COOKRCP01 total changed during collection; rerun to obtain a consistent snapshot"
            )
        items.extend(page)
        log(f"COOKRCP01: {len(items)}/{total} recipes collected")
    ids = [str(row.get("RCP_SEQ", "")) for row in items]
    if (
        len(items) != total
        or len(set(ids)) != len(ids)
        or any(not key.isdigit() for key in ids)
    ):
        raise CollectError(
            "COOKRCP01 count or recipe IDs failed validation; previous snapshot is preserved"
        )
    return {
        "meta": {
            "provider": "Food Safety Korea",
            "service": "COOKRCP01",
            "documentation": DOCUMENTATION,
            "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "total_count": total,
            "item_count": len(items),
            "complete": True,
            "items_sha256": sha256_json(items),
        },
        "items": items,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=paths.RECIPES_ALL_RAW)
    parser.add_argument("--page-size", type=int, default=500)
    args = parser.parse_args(argv)
    try:
        result = collect(load_secret(KEY_NAME), args.page_size)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(
            json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        temporary.replace(args.output)
    except (CollectError, OSError) as error:
        message = (
            str(error)
            if isinstance(error, CollectError)
            else "Snapshot could not be written"
        )
        print(
            f"Collection failed: {message}; previous snapshot is preserved",
            file=sys.stderr,
        )
        return 1
    print(f"Saved {len(result['items'])} recipes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
