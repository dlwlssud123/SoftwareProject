"""Keep central service information separate from unverified recruitment periods."""

import re
from datetime import UTC, datetime
from html import unescape
from urllib.parse import parse_qs, urlsplit

from agetech_data.textutil import sha256_json
from agetech_data.welfare.client import SCOPE, parse_xml

NORMALIZER_VERSION = "central-welfare-v1"


def clean_text(value: str | None) -> str:
    value = unescape(unescape(value or ""))
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", "", value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def xml_value(node):
    if not len(node):
        return clean_text(node.text)
    out = {}
    for child in node:
        if child.tag in ("resultCode", "resultMessage", "inqNum"):
            continue
        value = xml_value(child)
        if child.tag.endswith("List"):
            out.setdefault(child.tag, []).append(value)
        elif child.tag in out:
            raise ValueError("Unexpected repeated welfare field")
        else:
            out[child.tag] = value
    return out


def aware_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Welfare timestamps require a timezone")
    return parsed.astimezone(UTC)


def normalize_item(item: dict, collected_at: datetime) -> dict:
    source_id = item["service_id"]
    if not isinstance(source_id, str) or not re.fullmatch(r"WLF[0-9]+", source_id):
        raise ValueError("Invalid welfare source ID")
    listing = parse_xml(item["list_xml"])
    detail = (
        parse_xml(item["detail_xml"]) if item.get("detail_xml") is not None else None
    )
    if (
        listing.findtext("servId") != source_id
        or detail is not None
        and detail.findtext("servId") != source_id
    ):
        raise ValueError("Welfare source ID mismatch")
    if detail is not None and detail.findtext("resultCode") != "0":
        raise ValueError("Welfare detail does not have a success result")
    checked_at = aware_time(item["checked_at"])
    if checked_at > collected_at:
        raise ValueError("Welfare detail check is newer than its snapshot")
    list_fields, detail_fields = (
        xml_value(listing),
        xml_value(detail) if detail is not None else {},
    )
    source_url = list_fields.get("servDtlLink", "")
    link = urlsplit(source_url)
    if (
        link.scheme != "https"
        or link.hostname not in ("www.bokjiro.go.kr", "bokjiro.go.kr")
        or link.username
        or link.password
        or parse_qs(link.query).get("wlfareInfoId") != [source_id]
    ):
        raise ValueError("Welfare source URL must identify the official service")
    normalized = {"scope": SCOPE, "list": list_fields, "detail": detail_fields}
    issues = []
    if detail is None:
        issues.append("detail_pending")
    title = detail_fields.get("servNm") or list_fields.get("servNm") or ""
    target = detail_fields.get("tgtrDtlCn", "")
    benefit = detail_fields.get("alwServCn", "")
    if not title:
        issues.append("missing_title")
    if not target:
        issues.append("missing_target")
    if not benefit:
        issues.append("missing_benefit")
    # sprtCycNm is the benefit payment cycle, not an application window.
    return {
        "source_id": source_id,
        "raw": {"list_xml": item["list_xml"], "detail_xml": item["detail_xml"]},
        "normalized": normalized,
        "content_sha256": sha256_json(normalized),
        "fingerprint": sha256_json(
            {"content": normalized, "normalizer": NORMALIZER_VERSION}
        ),
        "title": title,
        "summary": detail_fields.get("wlfareInfoOutlCn")
        or list_fields.get("servDgst", ""),
        "target_text": target,
        "selection_text": detail_fields.get("slctCritCn", ""),
        "benefit_text": benefit,
        "application": detail_fields.get("applmetList", []),
        "contacts": detail_fields.get("inqplCtadrList", []),
        "source_url": source_url,
        "criteria_year": detail_fields.get("crtrYr") or None,
        "checked_at": checked_at,
        "issues": issues,
        "quality_status": "hold"
        if not title or detail is None
        else ("flagged" if issues else "ok"),
        "detail_state": "pending" if detail is None else "ready",
        "application_status": "unknown",
    }
