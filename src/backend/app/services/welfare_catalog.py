"""Serve published welfare revisions using the data team's regional matching rules."""

import re
from datetime import date
from types import SimpleNamespace

from agetech_data.welfare.query import SCOPE_ORDER, services_for
from agetech_data.welfare.revision import SOURCES
from sqlalchemy import and_, or_, select

from app.models import WelfareRevision, WelfareService
from app.schemas.catalog import WelfareRecord

RULES_VERSION = "welfare-candidates-v1"
_MIN_AGE = re.compile(r"(?:만\s*)?(\d{1,3})\s*세\s*이상")
_ALONE = re.compile(r"독거|홀로|1\s*인\s*가구|일인\s*가구")


def welfare_sources():
    return or_(
        *(
            and_(
                WelfareService.provider == source["provider"],
                WelfareService.scope == source["scope"],
            )
            for source in SOURCES.values()
        )
    )


def active_welfare():
    return (
        select(WelfareService, WelfareRevision)
        .join(
            WelfareRevision,
            (WelfareRevision.id == WelfareService.active_revision_id)
            & (WelfareRevision.service_id == WelfareService.id),
        )
        .where(
            welfare_sources(),
            WelfareService.publication_status == "published",
            WelfareRevision.quality_status != "hold",
            WelfareRevision.detail_state == "ready",
        )
    )


def welfare_record(service: WelfareService, revision: WelfareRevision) -> WelfareRecord:
    normalized = revision.normalized
    return WelfareRecord(
        service_id=service.source_id,
        scope=service.scope,
        region_scope=region_scope(service, revision),
        ctpv=normalized.get("ctpv"),
        sgg=normalized.get("sgg"),
        title=revision.title,
        summary=revision.summary,
        target_text=revision.target_text,
        selection_text=revision.selection_text,
        benefit_text=revision.benefit_text,
        application=[
            {"method": entry.get("name") or "", "description": entry.get("value") or ""}
            for entry in revision.application
        ],
        contacts=[
            {"name": entry.get("name") or "", "contact": entry.get("value") or ""}
            for entry in revision.contacts
        ],
        criteria_year=revision.criteria_year,
        application_status="unknown",
        detail_state=revision.detail_state,
        quality_status=revision.quality_status,
        issues=revision.issues,
        source={
            "provider": service.provider,
            "source_id": service.source_id,
            "source_url": revision.source_url,
            "checked_at": service.last_checked_at,
            "detail_checked_at": service.last_detail_checked_at,
            "raw_sha256": revision.raw_sha256,
            "revision_id": revision.id,
        },
    )


def region_scope(service: WelfareService, revision: WelfareRevision) -> str:
    # Earlier central imports stored "central_nationwide" in normalized.scope.
    if service.scope == "central_nationwide":
        return "national"
    return revision.normalized["scope"]


def matching_services(rows, region: str | None, district: str | None, as_of: date):
    # Project the stored revision, rather than normalize its raw data again under
    # possibly newer rules. services_for only reads these regional/period fields.
    candidates = [
        SimpleNamespace(
            row=row,
            serv_id=service.source_id,
            name=revision.title,
            ctpv=revision.normalized.get("ctpv"),
            sgg=revision.normalized.get("sgg"),
            scope=region_scope(service, revision),
            period_end=revision.normalized.get("period_end"),
            quality_flags=revision.normalized.get("quality_flags", []),
            detail_status=revision.detail_state,
        )
        for row in rows
        for service, revision in [row]
    ]
    if region is not None:
        query, matches = services_for(candidates, region, district, as_of=as_of)
        return query.notes, [
            (match["record"].row, match["reason"], match["match"]) for match in matches
        ]
    # Without a regional filter the catalog includes all regions, but never
    # promotes a service whose recorded end date has already passed.
    today = as_of.isoformat()
    current = [
        candidate
        for candidate in candidates
        if not (
            candidate.period_end < today
            if candidate.period_end
            else "period_ended" in candidate.quality_flags
        )
    ]
    current.sort(key=lambda candidate: (candidate.name, candidate.serv_id))
    return [], [(candidate.row, "", candidate.scope) for candidate in current]


def recommend_services(matches, age: int, lives_alone: bool | None):
    ranked = []
    for row, region_reason, region_scope in matches:
        _, revision = row
        reasons = [region_reason]
        score = 0
        # These are ranking cues quoted from source text, not eligibility rules.
        # Income, disability, household and application conditions still need review.
        age_cue = next(
            (
                match.group(0)
                for match in _MIN_AGE.finditer(revision.target_text)
                if age >= int(match.group(1))
            ),
            None,
        )
        if age_cue:
            reasons.append(
                f"지원 대상 원문에 ‘{age_cue}’ 안내가 있어요. 세부 조건을 확인해 주세요."
            )
            score += 1
        if lives_alone is True and _ALONE.search(
            f"{revision.title} {revision.target_text}"
        ):
            reasons.append(
                "독거·1인 가구 관련 안내가 있어요. 세부 조건을 확인해 주세요."
            )
            score += 1
        ranked.append((SCOPE_ORDER[region_scope], -score, row, reasons))
    ranked.sort(
        key=lambda item: (item[0], item[1], item[2][1].title, item[2][0].source_id)
    )
    return [(row, reasons) for _, _, row, reasons in ranked]
