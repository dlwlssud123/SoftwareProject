"""갱신 수집본(collect.welfare) → DB 복지 판본 행 (backend app.jobs.import_welfare 의 입력).

    from agetech_data.welfare.revision import SOURCES, revision_rows
    rows = revision_rows(payload, "local")      # payload = data/raw/welfare/local_elderly.json

- 정제는 welfare.normalize 그대로다(docs/data/welfare_contract.md 2절). 중앙·지자체 모두 같은 형식.
- DB 판본의 normalized = 정제 레코드에서 실행마다 바뀌는 칸(VOLATILE_FIELDS: 상세 상태·확인 시각·원문 해시)을
  뺀 것이다. 그래서 조회수·확인 시각만 바뀌면 같은 판본이고, 내용·품질 표시가 바뀌면 새 판본이다.
- content_sha256 = normalized 의 해시. RAG 청크도 같은 함수(content_sha256)로 레코드 해시를 만들어
  DB 활성 판본과 맞춘다.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from urllib.parse import parse_qs, urlsplit

from agetech_data.textutil import sha256_json
from agetech_data.welfare.normalize import normalize_payload

NORMALIZER_VERSION = "refresh-welfare-v1"
# 정제 레코드에서 판본 비교에 쓰지 않는 칸 — 실행마다 바뀌거나(확인 시각) 조회수가 섞인 원문 해시
VOLATILE_FIELDS = ("detail_status", "detail_fetched_at", "source_fetched_at", "raw_sha256")

# 수집 종류(collect.welfare kind) → DB welfare_services 의 provider·scope, 수집본 meta.service 에 들어 있는 코드
SOURCES: dict[str, dict[str, str]] = {
    "central": {"provider": "ssis:NationalWelfareInformationsV001", "scope": "central_nationwide",
                "service": "NationalWelfareInformationsV001"},
    "local": {"provider": "ssis:LocalGovernmentWelfareInformations", "scope": "local",
              "service": "LocalGovernmentWelfareInformations"},
}
_BOKJIRO = ("www.bokjiro.go.kr", "bokjiro.go.kr")


def record_content(record: dict) -> dict:
    """정제 레코드(WelfareRecord.to_dict()) → 판본 비교용 내용."""
    return {k: v for k, v in record.items() if k not in VOLATILE_FIELDS}


def content_sha256(record: dict) -> str:
    return sha256_json(record_content(record))


def aware_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Welfare timestamps require a timezone")
    return parsed.astimezone(UTC)


def official_url(url: str | None, serv_id: str) -> bool:
    """복지로 상세 링크이고 그 사업 ID 를 가리키는지."""
    if not url:
        return False
    link = urlsplit(url)
    return (link.scheme == "https" and link.hostname in _BOKJIRO and not link.username and not link.password
            and parse_qs(link.query).get("wlfareInfoId") == [serv_id])


def revision_rows(payload: dict, source: str, as_of: date | None = None) -> list[dict]:
    """수집본 한 파일 → 판본 행 목록 (항목 순서 그대로).

    행: source_id, raw(수집 항목 그대로), normalized, content_sha256, fingerprint, 구조화 칸(title … application_status),
    checked_at(상세 확인 시각, 상세가 없으면 수집 시각).
    """
    if source not in SOURCES:
        raise ValueError(f"Unknown welfare source: {source}")
    # meta.fetched_at 은 목록 확인(실행 시작) 시각이다. 상세는 실행 중에 받으므로 이보다 늦을 수 있다.
    collected_at = aware_time(payload["meta"]["fetched_at"])
    now = datetime.now(UTC)
    items = payload["items"]
    rows = []
    for item, rec in zip(items, normalize_payload(payload, source, as_of), strict=True):
        if not isinstance(rec.serv_id, str) or not re.fullmatch(r"WLF[0-9]+", rec.serv_id):
            raise ValueError("Invalid welfare source ID")
        normalized = record_content(rec.to_dict())
        ready = rec.detail_status != "pending"
        checked_at = aware_time(rec.detail_fetched_at) if ready and rec.detail_fetched_at else collected_at
        if checked_at > now:
            raise ValueError("Welfare check time cannot be in the future")
        issues = sorted(set(rec.quality_flags) | {f"unverified:{f}" for f in rec.unverified_fields})
        title, linked = rec.name or "", official_url(rec.detail_url, rec.serv_id)
        if not linked:
            issues = sorted(set(issues) | {"no_official_link"})
        rows.append({
            "source_id": rec.serv_id,
            "raw": item,
            "normalized": normalized,
            "content_sha256": sha256_json(normalized),
            "fingerprint": sha256_json({"content": normalized, "normalizer": NORMALIZER_VERSION}),
            "title": title,
            "summary": rec.summary or "",
            "target_text": rec.target_detail or "",
            "selection_text": rec.selection_criteria or "",
            "benefit_text": rec.benefits or "",
            "application": rec.apply_guides,
            "contacts": rec.contacts,
            "source_url": rec.detail_url or "",
            "criteria_year": rec.criteria_year,
            "checked_at": checked_at,
            "issues": issues,
            # 이름·상세·공식 링크가 없으면 게시하지 않는다(hold). 표시할 문제가 있으면 flagged 로 게시
            "quality_status": "hold" if not title or not ready or not linked else ("flagged" if issues else "ok"),
            "detail_state": "ready" if ready else "pending",
            "application_status": "unknown",
        })
    return rows
