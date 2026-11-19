from datetime import date, timedelta
from types import SimpleNamespace

from agetech_data.facilities.normalize import STALE_DAYS
from agetech_data.facilities.query import ALWAYS, CAUTIONS, CLOSED_FLAGS, facilities_for
from agetech_data.welfare.regions import normalize_ctpv, normalize_sgg

from app.schemas.content import FacilityQuery, FacilityRecord


def facility_candidates(rows, as_of: date):
    candidates = []
    for row in rows:
        flags = list(row.quality_flags)
        normalized = row.normalized or {}
        # Re-evaluate time-dependent flags even between weekly source refreshes.
        for field, flag, compare in (
            ("close_date", "operation_ended", lambda value: value < as_of),
            ("open_date", "not_started", lambda value: value > as_of),
        ):
            value = normalized.get(field)
            if value:
                try:
                    current = compare(date.fromisoformat(value))
                except (TypeError, ValueError):
                    continue
                flags = [item for item in flags if item != flag]
                if current:
                    flags.append(flag)
        if CLOSED_FLAGS.intersection(flags):
            continue
        if row.reference_date and row.reference_date < as_of - timedelta(
            days=STALE_DAYS
        ):
            if "reference_stale" not in flags:
                flags.append("reference_stale")
        candidates.append(
            SimpleNamespace(
                row=row,
                name=row.name,
                ctpv=normalize_ctpv(row.sido) or row.sido,
                sgg=normalize_sgg(row.sigungu),
                latitude=row.latitude,
                longitude=row.longitude,
                quality_flags=flags,
            )
        )
    return candidates


def facility_record(candidate, cautions: list[str] | None = None) -> FacilityRecord:
    row = candidate.row
    data = {
        field: getattr(row, field)
        for field in FacilityRecord.model_fields
        if field not in ("quality_flags", "cautions")
    }
    return FacilityRecord(
        **data,
        quality_flags=candidate.quality_flags,
        cautions=cautions
        or [
            *[CAUTIONS[flag] for flag in candidate.quality_flags if flag in CAUTIONS],
            ALWAYS,
        ],
    )


def matching_facilities(rows, query: FacilityQuery, as_of: date):
    candidates = facility_candidates(rows, as_of)
    if query.region is not None:
        region, matches = facilities_for(candidates, query.region, query.district)
        return region.notes, [
            facility_record(match["facility"], match["cautions"]) for match in matches
        ]
    candidates.sort(
        key=lambda item: (item.ctpv, item.sgg or "", item.name, str(item.row.id))
    )
    return [], [facility_record(item) for item in candidates]
