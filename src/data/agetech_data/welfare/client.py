"""Collect the full central welfare catalog and every detail, preserving XML."""

import argparse
import json
import re
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode
from urllib.request import urlopen
from xml.etree import ElementTree as ET

from agetech_data import paths
from agetech_data.settings import load_secret
from agetech_data.textutil import sha256_json

BASE_URL = "https://apis.data.go.kr/B554287/NationalWelfareInformationsV001"
SCOPE = "central_nationwide"
DOCUMENTATION = "https://www.data.go.kr/data/15090532/openapi.do"
Fetcher = Callable[[str], tuple[int, str]]


class CollectError(RuntimeError):
    pass


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def save_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def http_fetch(url: str) -> tuple[int, str]:
    try:
        with urlopen(url, timeout=30) as response:
            return response.status, response.read().decode("utf-8-sig")
    except HTTPError as error:
        return error.code, error.read().decode("utf-8-sig", errors="replace")


def parse_xml(body: str) -> ET.Element:
    if "<!DOCTYPE" in body.upper() or "<!ENTITY" in body.upper():
        raise ValueError("Unsupported XML declarations")
    return ET.fromstring(body)


def request_xml(
    key: str,
    operation: str,
    parameters: dict,
    fetch: Fetcher = http_fetch,
    sleep: Callable[[float], None] = time.sleep,
) -> ET.Element:
    query = urlencode({"serviceKey": unquote(key), **parameters})
    last_status = None
    for attempt in range(5):
        try:
            status, body = fetch(f"{BASE_URL}/{operation}?{query}")
            last_status = status
            if body:
                try:
                    gateway = parse_xml(body)
                    if gateway.findtext(".//returnReasonCode") == "22":
                        raise CollectError("Daily welfare API quota exceeded (code 22)")
                except ET.ParseError:
                    pass
            if status == 200:
                root = parse_xml(body)
                if root.findtext("resultCode") != "0":
                    raise CollectError(
                        "Welfare API rejected the request; check key, approval and quota"
                    )
                return root
            if 400 <= status < 500 and status != 429:
                raise CollectError(f"Welfare API HTTP {status}; check service approval")
        except (URLError, TimeoutError, OSError, ET.ParseError, ValueError):
            pass
        if attempt < 4:
            sleep(
                min(30 * (attempt + 1), 60) if last_status == 429 else 2 * (attempt + 1)
            )
    raise CollectError(
        f"Welfare API could not be read after retries (HTTP {last_status})"
    )


def collect_catalog(key: str, fetch: Fetcher, sleep: Callable) -> list[str]:
    entries, total, page = [], None, 1
    while total is None or len(entries) < total:
        root = request_xml(
            key,
            "NationalWelfarelistV001",
            {
                "callTp": "L",
                "pageNo": page,
                "numOfRows": 500,
                "srchKeyCode": "001",
                "orderBy": "popular",
            },
            fetch,
            sleep,
        )
        try:
            observed = int(root.findtext("totalCount", "0"))
        except ValueError:
            raise CollectError("Welfare catalog has an invalid total") from None
        if observed <= 0 or total is not None and observed != total:
            raise CollectError("Welfare catalog is empty or changed during collection")
        total = observed
        batch = root.findall("servList")
        if not batch:
            raise CollectError("Welfare catalog ended before the expected total")
        entries.extend(ET.tostring(node, encoding="unicode") for node in batch)
        page += 1
        if page > 1001:
            raise CollectError("Welfare catalog exceeded the page limit")
    ids = [parse_xml(value).findtext("servId", "") for value in entries]
    if (
        len(ids) != total
        or len(set(ids)) != total
        or any(not re.fullmatch(r"WLF[0-9]+", value) for value in ids)
    ):
        raise CollectError("Welfare catalog count or unique IDs failed validation")
    return entries


def collect(
    key: str,
    checkpoint: Path,
    fetch: Fetcher = http_fetch,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
    allow_partial_details: bool = False,
) -> dict:
    if not key:
        raise CollectError("WELFARE_API_KEY is not configured")
    catalog = collect_catalog(key, fetch, sleep)
    ids = [parse_xml(value).findtext("servId") for value in catalog]
    cached = {}
    if checkpoint.is_file():
        saved = json.loads(checkpoint.read_text(encoding="utf-8"))
        if saved.get("scope") == SCOPE and set(saved.get("catalog_ids", [])) == set(
            ids
        ):
            for item in saved.get("items", []):
                checked = datetime.fromisoformat(item["checked_at"])
                if (
                    datetime.now(UTC) - timedelta(days=7)
                    <= checked
                    <= datetime.now(UTC)
                ):
                    cached[item["service_id"]] = item
    items = []
    failure = None

    def persist_checkpoint():
        available = {
            **cached,
            **{row["service_id"]: row for row in items if row.get("detail_xml")},
        }
        save_atomic(
            checkpoint,
            {
                "scope": SCOPE,
                "catalog_ids": ids,
                "catalog": catalog,
                "items": list(available.values()),
            },
        )

    for list_xml, service_id in zip(catalog, ids, strict=True):
        if service_id in cached:
            item = {**cached[service_id], "list_xml": list_xml}
        else:
            try:
                if failure:
                    raise CollectError(failure)
                detail = request_xml(
                    key,
                    "NationalWelfaredetailedV001",
                    {"callTp": "D", "servId": service_id},
                    fetch,
                    sleep,
                )
            except CollectError as error:
                first_failure = failure is None
                failure = str(error)
                if first_failure:
                    persist_checkpoint()
                if not allow_partial_details:
                    raise CollectError(f"{service_id}: {error}") from None
                item = {
                    "service_id": service_id,
                    "list_xml": list_xml,
                    "detail_xml": None,
                    "checked_at": utcnow(),
                }
            else:
                if detail.findtext("servId") != service_id:
                    raise CollectError("Welfare detail ID does not match the catalog")
                item = {
                    "service_id": service_id,
                    "list_xml": list_xml,
                    "detail_xml": ET.tostring(detail, encoding="unicode"),
                    "checked_at": utcnow(),
                }
                sleep(0.7)
        items.append(item)
        if len(items) % 20 == 0 or len(items) == len(catalog):
            # Incomplete files never replace the last complete snapshot.
            persist_checkpoint()
            log(f"Welfare entries processed: {len(items)}/{len(catalog)}")
    return {
        "meta": {
            "provider": "한국사회보장정보원 / 복지로",
            "service": "NationalWelfareInformationsV001",
            "scope": SCOPE,
            "endpoint": BASE_URL,
            "documentation": DOCUMENTATION,
            "fetched_at": utcnow(),
            "total_count": len(catalog),
            "item_count": len(items),
            "catalog_complete": True,
            "detail_count": sum(bool(row["detail_xml"]) for row in items),
            "complete": all(row["detail_xml"] is not None for row in items),
            "items_sha256": sha256_json(items),
        },
        "items": items,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=paths.WELFARE_RAW)
    parser.add_argument("--allow-partial-details", action="store_true")
    args = parser.parse_args(argv)
    checkpoint = args.output.with_suffix(".checkpoint.json")
    try:
        result = collect(
            load_secret("WELFARE_API_KEY"),
            checkpoint,
            allow_partial_details=args.allow_partial_details,
        )
        output = (
            args.output
            if result["meta"]["complete"]
            else args.output.with_suffix(".partial.json")
        )
        save_atomic(output, result)
        if result["meta"]["complete"]:
            checkpoint.unlink(missing_ok=True)
    except (CollectError, OSError, ValueError, KeyError, TypeError) as error:
        reason = str(error) if isinstance(error, CollectError) else type(error).__name__
        print(
            f"Welfare collection failed ({reason}); check approval/quota/network or checkpoint. Previous complete snapshot preserved.",
            file=sys.stderr,
        )
        return 1
    print(
        f"Saved {len(result['items'])} catalog rows, {result['meta']['detail_count']} details; complete={result['meta']['complete']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
