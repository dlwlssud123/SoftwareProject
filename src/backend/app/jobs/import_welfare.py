"""Import a refresh welfare snapshot (central or local); default is a file-only dry run.

Input is the data refresh output (agetech_data.collect.welfare via agetech_data.refresh):
data/raw/welfare/central_elderly.json and local_elderly.json. Records are normalized with
agetech_data.welfare.normalize, the same records the welfare API sample and RAG chunks use.
"""

import argparse
import hashlib
import json
import sys
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agetech_data import paths
from agetech_data.collect.welfare import LIFE_ELDERLY
from agetech_data.textutil import sha256_json
from agetech_data.welfare.revision import (
    NORMALIZER_VERSION,
    SOURCES,
    aware_time,
    revision_rows,
)
from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import DataImportRun, WelfareNotice, WelfareRevision, WelfareService

DEFAULT_INPUTS = {
    "central": paths.WELFARE_CENTRAL_RAW,
    "local": paths.WELFARE_LOCAL_RAW,
}


@dataclass
class WelfarePlan:
    fingerprint: str
    inputs: dict
    collected_at: datetime
    rows: list[dict]
    counts: dict
    source: str = "central"

    @property
    def provider(self) -> str:
        return SOURCES[self.source]["provider"]

    @property
    def scope(self) -> str:
        return SOURCES[self.source]["scope"]


def prepare_import(
    path: Path, allow_partial_details: bool = False, source: str = "central"
) -> WelfarePlan:
    if source not in SOURCES:
        raise ValueError("Unknown welfare source")
    raw = path.read_bytes()
    snapshot = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("meta"), dict):
        raise ValueError("Complete welfare collector metadata is required")
    meta, items = snapshot["meta"], snapshot.get("items")
    params = meta.get("params")
    if (
        not isinstance(items, list)
        or not items
        or not all(isinstance(item, dict) for item in items)
        or (meta.get("complete") is not True and not allow_partial_details)
        or meta.get("item_count") != len(items)
        or meta.get("total_count") != len(items)
        or meta.get("kind") != source
        or not isinstance(params, dict)
        or params.get("lifeArray") != LIFE_ELDERLY
        or SOURCES[source]["service"] not in str(meta.get("service", ""))
        or meta.get("items_sha256") != sha256_json(items)
    ):
        raise ValueError(
            "Welfare snapshot is incomplete or its source/checksum/count is invalid"
        )
    collected_at = aware_time(meta["fetched_at"])
    if collected_at > datetime.now(UTC):
        raise ValueError("Welfare collection time cannot be in the future")
    rows = revision_rows(snapshot, source)
    pending = sum(row["detail_state"] == "pending" for row in rows)
    if (pending and meta.get("complete") is True) or (
        pending and not allow_partial_details
    ):
        raise ValueError(
            "Missing details require an explicitly partial snapshot and opt-in"
        )
    ids = [row["source_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate welfare source IDs")
    inputs = {
        "dataset": f"welfare_{source}",
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "meta": meta,
        "revision_manifest": {
            row["source_id"]: {
                "fingerprint": row["fingerprint"],
                "checked_at": row["checked_at"].isoformat(),
            }
            for row in rows
        },
    }
    return WelfarePlan(
        sha256_json({"input": inputs, "normalizer": NORMALIZER_VERSION}),
        inputs,
        collected_at,
        rows,
        {
            "source": source,
            "services": len(rows),
            "quality": dict(Counter(row["quality_status"] for row in rows)),
            "application_unknown": len(rows),
            "ready_details": len(rows) - pending,
            "pending_details": pending,
            "verified_notices": 0,
        },
        source,
    )


def open_notice_condition(as_of: datetime):
    """Use this predicate in future retrieval even before the expiry worker runs."""
    if as_of.tzinfo is None:
        raise ValueError("An aware query time is required")
    return and_(
        WelfareService.publication_status == "published",
        WelfareNotice.source_revision_id == WelfareService.active_revision_id,
        WelfareNotice.status == "open",
        or_(
            WelfareNotice.period_type == "ongoing",
            and_(
                WelfareNotice.period_type == "fixed",
                WelfareNotice.deadline_at > as_of,
                or_(
                    WelfareNotice.starts_at.is_(None), WelfareNotice.starts_at <= as_of
                ),
            ),
        ),
    )


def expire_notices(session: Session, as_of: datetime) -> int:
    if as_of.tzinfo is None:
        raise ValueError("An aware expiry time is required")
    result = session.execute(
        update(WelfareNotice)
        .where(
            WelfareNotice.period_type == "fixed",
            WelfareNotice.deadline_at <= as_of,
            WelfareNotice.status.in_(("open", "scheduled")),
        )
        .values(status="closed")
    )
    return result.rowcount


def apply_import(session: Session, plan: WelfarePlan) -> dict:
    session.execute(text("SELECT pg_advisory_xact_lock(6711061156)"))
    previous = session.scalar(
        select(DataImportRun).where(DataImportRun.fingerprint == plan.fingerprint)
    )
    if previous:
        return {
            "run_id": str(previous.id),
            "already_imported": True,
            **previous.counts,
            "new_services": 0,
            "new_revisions": 0,
            "newly_missing": 0,
            "expired_notices": 0,
        }
    existing = session.scalars(
        select(WelfareService).where(
            WelfareService.provider == plan.provider,
            WelfareService.scope == plan.scope,
        )
    ).all()
    if any(service.last_seen_at >= plan.collected_at for service in existing):
        raise ValueError(
            "An older welfare snapshot cannot replace the latest successful scan"
        )
    by_source = {service.source_id: service for service in existing}
    run = DataImportRun(
        id=uuid.uuid4(),
        fingerprint=plan.fingerprint,
        parser_version=NORMALIZER_VERSION,
        inputs=plan.inputs,
        counts=plan.counts,
    )
    session.add(run)
    session.flush()
    new_services = new_revisions = newly_missing = 0
    seen = set()
    for row in plan.rows:
        source_id = row["source_id"]
        seen.add(source_id)
        service = by_source.get(source_id)
        if service is None:
            service = WelfareService(
                id=uuid.uuid4(),
                provider=plan.provider,
                source_id=source_id,
                scope=plan.scope,
                publication_status="hold",
                last_checked_at=row["checked_at"],
                last_detail_checked_at=row["checked_at"]
                if row["detail_state"] == "ready"
                else None,
                last_seen_at=plan.collected_at,
                last_seen_run_id=run.id,
                missing_scans=0,
            )
            session.add(service)
            session.flush()
            new_services += 1
        revision = session.scalar(
            select(WelfareRevision).where(
                WelfareRevision.service_id == service.id,
                WelfareRevision.fingerprint == row["fingerprint"],
            )
        )
        if (
            row["checked_at"]
            < (service.last_detail_checked_at or service.last_checked_at)
            and row["detail_state"] == "ready"
            and service.active_revision_id != (revision.id if revision else None)
        ):
            raise ValueError(
                "Stale detail checkpoint conflicts with a newer active revision; recollect details"
            )
        if revision is None:
            revision = WelfareRevision(
                id=uuid.uuid4(),
                service_id=service.id,
                import_run_id=run.id,
                fingerprint=row["fingerprint"],
                normalizer_version=NORMALIZER_VERSION,
                raw=row["raw"],
                raw_sha256=sha256_json(row["raw"]),
                normalized=row["normalized"],
                content_sha256=row["content_sha256"],
                **{
                    field: row[field]
                    for field in (
                        "title",
                        "summary",
                        "target_text",
                        "selection_text",
                        "benefit_text",
                        "application",
                        "contacts",
                        "source_url",
                        "criteria_year",
                        "quality_status",
                        "detail_state",
                        "issues",
                        "application_status",
                    )
                },
            )
            session.add(revision)
            session.flush()
            new_revisions += 1
        if service.publication_status != "withdrawn" and not (
            row["detail_state"] == "pending" and service.active_revision_id is not None
        ):
            service.active_revision_id = (
                revision.id if row["quality_status"] != "hold" else None
            )
            service.publication_status = (
                "published" if service.active_revision_id else "hold"
            )
        service.last_checked_at = max(service.last_checked_at, row["checked_at"])
        if row["detail_state"] == "ready":
            service.last_detail_checked_at = max(
                service.last_detail_checked_at or row["checked_at"], row["checked_at"]
            )
        service.last_seen_at, service.last_seen_run_id, service.missing_scans = (
            plan.collected_at,
            run.id,
            0,
        )
    for source_id, service in by_source.items():
        if source_id not in seen and plan.inputs["meta"]["complete"] is True:
            service.missing_scans += 1
            if service.missing_scans >= 2 and service.publication_status == "published":
                service.publication_status = "missing"
                newly_missing += 1
    result = {
        **plan.counts,
        "new_services": new_services,
        "new_revisions": new_revisions,
        "newly_missing": newly_missing,
        "expired_notices": expire_notices(session, datetime.now(UTC)),
    }
    run.counts, run.completed_at = result, datetime.now(UTC)
    session.flush()
    return {"run_id": str(run.id), "already_imported": False, **result}


def verify_import(session: Session, plan: WelfarePlan) -> dict:
    revisions = session.scalars(
        select(WelfareRevision).where(
            WelfareRevision.fingerprint.in_([row["fingerprint"] for row in plan.rows])
        )
    ).all()
    by_fingerprint = {revision.fingerprint: revision for revision in revisions}
    if len(revisions) != len(plan.rows):
        raise ValueError("Welfare revisions are missing")
    for row in plan.rows:
        revision = by_fingerprint[row["fingerprint"]]
        # Re-normalize the stored raw item with the same normalizer and this plan's metadata.
        source = revision_rows(
            {"meta": plan.inputs["meta"], "items": [revision.raw]}, plan.source
        )[0]
        if (
            revision.raw_sha256 != sha256_json(revision.raw)
            or revision.normalized != row["normalized"]
            or source["normalized"] != row["normalized"]
            or revision.content_sha256 != row["content_sha256"]
            or revision.application_status != "unknown"
        ):
            raise ValueError("Welfare raw source or normalized content differs")
        for field in (
            "title",
            "summary",
            "target_text",
            "selection_text",
            "benefit_text",
            "application",
            "contacts",
            "source_url",
            "criteria_year",
            "quality_status",
            "detail_state",
            "issues",
        ):
            if getattr(revision, field) != row[field]:
                raise ValueError("Welfare structured fields differ")
    return {
        "verified": True,
        "service_revisions": len(revisions),
        "fingerprint": plan.fingerprint,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", choices=(*SOURCES, "all"), default="all", help="default: all"
    )
    parser.add_argument(
        "--input", type=Path, help="snapshot path (only with one --source)"
    )
    parser.add_argument("--allow-partial-details", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    sources = list(SOURCES) if args.source == "all" else [args.source]
    if args.input and len(sources) != 1:
        parser.error("--input requires a single --source")
    try:
        plans = [
            prepare_import(
                args.input or DEFAULT_INPUTS[source], args.allow_partial_details, source
            )
            for source in sources
        ]
        if args.apply or args.verify:
            from app.core.database import SessionLocal

            # One transaction: either every source is imported or none is.
            with SessionLocal.begin() as session:
                result = {
                    plan.source: apply_import(session, plan)
                    if args.apply
                    else verify_import(session, plan)
                    for plan in plans
                }
        else:
            result = {
                plan.source: {
                    "dry_run": True,
                    "fingerprint": plan.fingerprint,
                    **plan.counts,
                }
                for plan in plans
            }
    except (OSError, ValueError, KeyError, TypeError, SQLAlchemyError):
        print(
            "Welfare import failed. Check complete snapshot, timestamps, official source IDs/URLs and database schema. Transaction was not committed.",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
