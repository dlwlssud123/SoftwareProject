from datetime import date, timedelta
from types import SimpleNamespace

from agetech_data.facilities.normalize import STALE_DAYS
from agetech_data.facilities.query import ALWAYS, CAUTIONS, CLOSED_FLAGS, facilities_for
from agetech_data.welfare.regions import normalize_ctpv, normalize_sgg

from app.schemas.content import (
    FacilityNearbyQuery,
    FacilityQuery,
    FacilityRecord,
    NearbyFacilityRecord,
)


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
                latitude=float(row.latitude) if row.latitude is not None else None,
                longitude=float(row.longitude) if row.longitude is not None else None,
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


def nearby_facilities(rows, query: FacilityNearbyQuery, as_of: date):
    candidates = facility_candidates(rows, as_of)
    region, matches = facilities_for(
        candidates,
        query.region,
        query.district,
        lat=query.latitude,
        lon=query.longitude,
        radius_km=query.radius_km,
    )
    notes = list(region.notes) if region is not None else []
    notes.append("거리는 직선거리 기준이며 실제 이동 거리와 다를 수 있어요.")
    if any(match["distance_km"] is None for match in matches):
        notes.append(
            "좌표가 없는 같은 시·군·구 시설은 거리 비교 없이 목록 뒤에 표시해요."
        )
    # Stable ties keep pagination deterministic even for duplicate names/coordinates.
    matches.sort(
        key=lambda item: (
            item["distance_km"] is None,
            item["distance_km"] or 0,
            item["facility"].name,
            str(item["facility"].row.id),
        )
    )
    return notes, [
        NearbyFacilityRecord(
            **facility_record(item["facility"], item["cautions"]).model_dump(),
            match=item["match"],
            distance_km=item["distance_km"],
        )
        for item in matches
    ]
