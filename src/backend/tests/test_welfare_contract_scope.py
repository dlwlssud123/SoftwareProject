from datetime import UTC, datetime

import pytest
from agetech_data.textutil import sha256_json
from agetech_data.welfare.revision import SOURCES, revision_rows
from pydantic import ValidationError

from app.schemas.catalog import WelfareListQuery, WelfareRecord


def local_row():
    sid = "WLF00004828"
    item = {
        "servId": sid,
        "list": {
            "servId": sid,
            "servNm": "경로우대사업",
            "ctpvNm": "대구광역시",
            "sggNm": "남구",
            "servDtlLink": f"https://www.bokjiro.go.kr/ssis-tbu/x.do?wlfareInfoId={sid}",
        },
        "detail": {"servId": sid, "servNm": "경로우대사업", "sprtTrgtCn": "65세 이상"},
        "detail_xml": (
            f"<wantedDtl><servId>{sid}</servId><inqplCtadrList>"
            "<servSeDetailNm>남구청</servSeDetailNm>"
            "<servSeDetailLink>053-664-2538</servSeDetailLink>"
            "</inqplCtadrList></wantedDtl>"
        ),
        "detail_status": "fresh",
        "detail_fetched_at": "2026-11-05T15:30:00+00:00",
    }
    payload = {"meta": {"fetched_at": "2026-11-05T15:20:00+00:00"}, "items": [item]}
    return revision_rows(payload, "local")[0]


def as_record(row, source):
    """Map a data revision row to the planned API DTO (DB lookup does the same)."""
    normalized = row["normalized"]
    return WelfareRecord(
        service_id=row["source_id"],
        scope=SOURCES[source]["scope"],
        region_scope=normalized["scope"],
        ctpv=normalized["ctpv"],
        sgg=normalized["sgg"],
        **{
            key: row[key]
            for key in (
                "title",
                "summary",
                "target_text",
                "selection_text",
                "benefit_text",
                "criteria_year",
                "application_status",
                "detail_state",
                "quality_status",
                "issues",
            )
        },
        application=[
            {"method": item["name"], "description": item["value"]}
            for item in row["application"]
        ],
        contacts=[
            {"name": item["name"], "contact": item["value"]} for item in row["contacts"]
        ],
        source={
            "provider": SOURCES[source]["provider"],
            "source_id": row["source_id"],
            "source_url": row["source_url"],
            "checked_at": row["checked_at"],
            "detail_checked_at": row["checked_at"],
            "raw_sha256": sha256_json(row["raw"]),
        },
    )


def test_local_revision_row_fits_planned_welfare_record():
    record = as_record(local_row(), "local")
    assert (record.scope, record.region_scope, record.ctpv, record.sgg) == (
        "local",
        "district",
        "대구광역시",
        "남구",
    )
    assert record.contacts[0].contact == "053-664-2538"
    assert record.source.checked_at == datetime(2026, 11, 5, 15, 30, tzinfo=UTC)


def test_central_record_defaults_to_national_and_unknown_scope_is_rejected():
    data = as_record(local_row(), "local").model_dump()
    central = WelfareRecord.model_validate(
        {
            **{
                k: v
                for k, v in data.items()
                if k not in ("region_scope", "ctpv", "sgg")
            },
            "scope": "central_nationwide",
        }
    )
    assert (central.region_scope, central.ctpv, central.sgg) == ("national", None, None)
    with pytest.raises(ValidationError):
        WelfareRecord.model_validate({**data, "scope": "local_district"})
    with pytest.raises(ValidationError):
        WelfareRecord.model_validate({**data, "region_scope": "city"})


def test_welfare_list_query_region_filter():
    assert WelfareListQuery().scope is None
    query = WelfareListQuery(scope="local", region="대구", district="남구")
    assert (query.region, query.district) == ("대구", "남구")
    assert WelfareListQuery(scope="central_nationwide").region is None
    with pytest.raises(ValidationError):
        WelfareListQuery(district="남구")
    with pytest.raises(ValidationError):
        WelfareListQuery(scope="national")
