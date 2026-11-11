"""Import a refresh meal-facility snapshot into meal_facilities; default is a file-only dry run.

Input is the data refresh output (agetech_data.collect.meal_facilities via agetech_data.refresh):
data/raw/facilities/free_meal.json. Rows come from agetech_data.facilities.revision, the same
normalizer the facility query sample uses (judgement date = collection date in KST).

Facilities missing from a newer complete snapshot stay in the table but are unpublished.
Manually entered facilities (provider NULL) are never touched.
"""

import argparse
import hashlib
import json
import sys
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from agetech_data import paths
from agetech_data.collect.meal_facilities import SERVICE
from agetech_data.facilities.revision import (
    NORMALIZER_VERSION,
    PROVIDER,
    facility_rows,
)
from agetech_data.snapshot import aware_time
from agetech_data.textutil import sha256_json
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import DataImportRun, MealFacility

IMPORT_LOCK = 6711061156  # shared with the other public-data imports
COORDINATE = Decimal("0.00001")  # meal_facilities.latitude/longitude are Numeric(8, 5)
COLUMNS = (
    "name",
    "sido",
    "sigungu",
    "address",
    "latitude",
    "longitude",
    "eligibility_text",
    "hours_text",
    "contact_text",
    "source_url",
    "reference_date",
    "quality_flags",
    "checked_on",
    "is_published",
    "normalized",
    "content_sha256",
)


def coordinate(value: float | None) -> Decimal | None:
    # Round here (half away from zero, like PostgreSQL) so the stored value is exactly the planned one.
    if value is None:
        return None
    return Decimal(repr(value)).quantize(COORDINATE, rounding=ROUND_HALF_UP)


def column_values(row: dict) -> dict:
    values = {column: row[column] for column in COLUMNS}
    values["latitude"] = coordinate(row["latitude"])
    values["longitude"] = coordinate(row["longitude"])
    return values


@dataclass
class FacilityPlan:
    fingerprint: str
    inputs: dict
    collected_at: datetime
    rows: list[dict]
    counts: dict


def read_snapshot(path: Path) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    snapshot = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("meta"), dict):
        raise ValueError("Complete meal facility collector metadata is required")
    meta, items = snapshot["meta"], snapshot.get("items")
    if (
        not isinstance(items, list)
        or not items
        or not all(isinstance(item, dict) for item in items)
        or meta.get("complete") is not True
        or meta.get("item_count") != len(items)
        or meta.get("total_count") != len(items)
        or meta.get("service") != SERVICE
        or meta.get("items_sha256") != sha256_json(items)
    ):
        raise ValueError(
            "Meal facility snapshot is incomplete or its source/checksum/count is invalid"
        )
    row_ids = [item.get("row_id") for item in items]
    if not all(isinstance(value, str) and value for value in row_ids) or len(
        row_ids
    ) != len(set(row_ids)):
        raise ValueError("Meal facility rows need unique collector row IDs")
    return snapshot, raw


def prepare_import(path: Path = paths.FREE_MEAL_RAW) -> FacilityPlan:
    snapshot, raw = read_snapshot(path)
    collected_at = aware_time(snapshot["meta"]["fetched_at"])
    if collected_at > datetime.now(UTC):
        raise ValueError("Meal facility collection time cannot be in the future")
    rows, skipped = facility_rows(snapshot)
    if not rows:
        raise ValueError(
            "Meal facility snapshot has no usable rows after normalization"
        )
    inputs = {
        "dataset": "meal_facilities",
        "file_sha256": hashlib.sha256(raw).hexdigest(),
        "meta": snapshot["meta"],
        "content_manifest": {row["source_id"]: row["content_sha256"] for row in rows},
        "skipped": skipped,
    }
    published = sum(row["is_published"] for row in rows)
    counts = {
        "source_rows": len(snapshot["items"]),
        "facilities": len(rows),
        "published": published,
        "unpublished": len(rows) - published,
        "skipped": dict(Counter(item["reason"] for item in skipped)),
        "quality_flags": dict(
            sorted(Counter(f for row in rows for f in row["quality_flags"]).items())
        ),
    }
    return FacilityPlan(
        sha256_json({"input": inputs, "normalizer": NORMALIZER_VERSION}),
        inputs,
        collected_at,
        rows,
        counts,
    )


def apply_import(session: Session, plan: FacilityPlan) -> dict:
    """Caller owns the transaction; never commit a partially applied snapshot."""
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": IMPORT_LOCK})
    previous = session.scalar(
        select(DataImportRun).where(DataImportRun.fingerprint == plan.fingerprint)
    )
    if previous:
        return {
            "run_id": str(previous.id),
            "already_imported": True,
            **previous.counts,
            "new_facilities": 0,
            "changed_facilities": 0,
            "newly_unpublished": 0,
        }
    existing = session.scalars(
        select(MealFacility).where(MealFacility.provider == PROVIDER)
    ).all()
    if any(facility.last_seen_at > plan.collected_at for facility in existing):
        raise ValueError(
            "An older meal facility snapshot cannot replace the latest successful scan"
        )
    by_source = {facility.source_id: facility for facility in existing}
    run = DataImportRun(
        id=uuid.uuid4(),
        fingerprint=plan.fingerprint,
        parser_version=NORMALIZER_VERSION,
        inputs=plan.inputs,
        counts=plan.counts,
    )
    session.add(run)
    session.flush()
    new = changed = newly_unpublished = 0
    for row in plan.rows:
        values = column_values(row)
        facility = by_source.get(row["source_id"])
        if facility is None:
            facility = MealFacility(
                id=uuid.uuid4(), provider=PROVIDER, source_id=row["source_id"]
            )
            session.add(facility)
            new += 1
        elif any(
            getattr(facility, column) != value for column, value in values.items()
        ):
            changed += 1
        for column, value in values.items():
            setattr(facility, column, value)
        facility.last_seen_at, facility.last_seen_run_id = plan.collected_at, run.id
    seen = {row["source_id"] for row in plan.rows}
    for source_id, facility in by_source.items():
        if source_id not in seen and facility.is_published:
            facility.is_published = False
            newly_unpublished += 1
    result = {
        **plan.counts,
        "new_facilities": new,
        "changed_facilities": changed,
        "newly_unpublished": newly_unpublished,
    }
    run.counts, run.completed_at = result, datetime.now(UTC)
    session.flush()
    return {"run_id": str(run.id), "already_imported": False, **result}


def verify_import(session: Session, plan: FacilityPlan) -> dict:
    """Read-only: every planned row matches the table, and nothing else imported is published."""
    stored = {
        facility.source_id: facility
        for facility in session.scalars(
            select(MealFacility).where(MealFacility.provider == PROVIDER)
        )
    }
    for row in plan.rows:
        facility = stored.get(row["source_id"])
        if facility is None:
            raise ValueError("Meal facilities are missing")
        for column, value in column_values(row).items():
            if getattr(facility, column) != value:
                raise ValueError("Meal facility fields differ from the snapshot")
    planned = {row["source_id"] for row in plan.rows}
    if any(
        facility.is_published and source_id not in planned
        for source_id, facility in stored.items()
    ):
        raise ValueError("A facility missing from the snapshot is still published")
    return {
        "verified": True,
        "facilities": len(plan.rows),
        "published": plan.counts["published"],
        "fingerprint": plan.fingerprint,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=paths.FREE_MEAL_RAW)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        plan = prepare_import(args.input)
        if args.apply or args.verify:
            from app.core.database import SessionLocal

            with SessionLocal.begin() as session:
                result = (
                    apply_import(session, plan)
                    if args.apply
                    else verify_import(session, plan)
                )
        else:
            result = {"dry_run": True, "fingerprint": plan.fingerprint, **plan.counts}
    except (OSError, ValueError, KeyError, TypeError, SQLAlchemyError):
        # Driver messages can include connection details; never print exception strings.
        print(
            "Meal facility import failed. Check the complete refresh snapshot, timestamps and database schema. Transaction was not committed.",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
