import json
from datetime import UTC, datetime, timedelta
from xml.etree import ElementTree as ET

import pytest
from agetech_data.textutil import sha256_json
from agetech_data.welfare.normalize import normalize_payload
from agetech_data.welfare.revision import content_sha256
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.jobs.import_welfare import (
    apply_import,
    expire_notices,
    open_notice_condition,
    prepare_import,
    verify_import,
)
from app.models import DataImportRun, WelfareNotice, WelfareRevision, WelfareService

START = datetime(2026, 1, 1, tzinfo=UTC)
SERVICES = {
    "central": "중앙부처 복지서비스 (NationalWelfareInformationsV001)",
    "local": "지자체 복지서비스 (LocalGovernmentWelfareInformations)",
}


def node(tag, fields):
    root = ET.Element(tag)
    for key, value in fields.items():
        ET.SubElement(root, key).text = value
    return ET.tostring(root, encoding="unicode")


def snapshot(
    tmp_path,
    day=0,
    ids=("WLF1", "WLF2"),
    changed=False,
    view_count="1",
    source="central",
):
    """Refresh collector output (agetech_data.collect.welfare) for one source."""
    checked = (START + timedelta(days=day)).isoformat()
    rows = []
    for key in ids:
        listing = {
            "servId": key,
            "servNm": "사업",
            "inqNum": view_count,
            "servDtlLink": f"https://www.bokjiro.go.kr/ssis?wlfareInfoId={key}",
        }
        if source == "local":
            listing.update(ctpvNm="대구광역시", sggNm="남구")
        detail = {
            "servId": key,
            "servNm": "사업",
            "tgtrDtlCn": "대상 안내",
            "alwServCn": "변경된 지원" if changed and key == "WLF1" else "지원 안내",
            "sprtCycNm": "수시",
        }
        rows.append(
            {
                "servId": key,
                "list": listing,
                "detail": detail,
                "detail_xml": node(
                    "wantedDtl", {**detail, "resultCode": "0", "inqNum": view_count}
                ),
                "detail_status": "fresh",
                "detail_fetched_at": checked,
            }
        )
    data = {
        "meta": {
            "provider": "한국사회보장정보원",
            "service": SERVICES[source],
            "kind": source,
            "complete": True,
            "total_count": len(rows),
            "item_count": len(rows),
            "fetched_at": checked,
            "items_sha256": sha256_json(rows),
        },
        "items": rows,
    }
    path = tmp_path / f"welfare_{source}_{day}.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def partial_snapshot(tmp_path, day=1, ids=("WLF1", "WLF2")):
    path = snapshot(tmp_path, day=day, ids=ids)
    data = json.loads(path.read_text(encoding="utf-8"))
    first = data["items"][0]
    for key in ("detail", "detail_xml", "detail_fetched_at"):
        first.pop(key)
    first["detail_status"] = "pending"
    data["meta"].update(complete=False, items_sha256=sha256_json(data["items"]))
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_partial_input_requires_opt_in_and_cannot_claim_complete(tmp_path):
    path = partial_snapshot(tmp_path)
    with pytest.raises(ValueError):
        prepare_import(path)
    assert (
        prepare_import(path, allow_partial_details=True).counts["pending_details"] == 1
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    data["meta"]["complete"] = True
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        prepare_import(path, allow_partial_details=True)


def test_postgres_partial_import_keeps_good_revision_and_does_not_count_missing(
    tmp_path, pg_connection
):
    with Session(pg_connection) as session:
        with session.begin():
            apply_import(session, prepare_import(snapshot(tmp_path)))
            good_id = session.scalar(
                select(WelfareService.active_revision_id).where(
                    WelfareService.source_id == "WLF1"
                )
            )
        with session.begin():
            plan = prepare_import(
                partial_snapshot(tmp_path, ids=("WLF1",)), allow_partial_details=True
            )
            apply_import(session, plan)
            first = session.scalar(
                select(WelfareService).where(WelfareService.source_id == "WLF1")
            )
            second = session.scalar(
                select(WelfareService).where(WelfareService.source_id == "WLF2")
            )
            assert (
                first.active_revision_id == good_id
                and first.publication_status == "published"
            )
            assert (
                second.missing_scans == 0 and second.publication_status == "published"
            )
            assert verify_import(session, plan)["service_revisions"] == 1


@pytest.mark.parametrize(
    "change",
    [
        {"complete": False},
        {"total_count": 99},
        {"kind": "local"},
        {"service": SERVICES["local"]},
        {"items_sha256": "wrong"},
    ],
)
def test_incomplete_or_wrong_scope_rejected(tmp_path, change):
    path = snapshot(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["meta"].update(change)
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        prepare_import(path)


def test_source_must_match_snapshot_kind(tmp_path):
    with pytest.raises(ValueError):
        prepare_import(snapshot(tmp_path), source="local")
    with pytest.raises(ValueError):
        prepare_import(snapshot(tmp_path, source="local"), source="central")
    with pytest.raises(ValueError):
        prepare_import(snapshot(tmp_path), source="unknown")


def test_view_count_and_check_time_do_not_change_fingerprint(tmp_path):
    first = prepare_import(snapshot(tmp_path))
    later = prepare_import(snapshot(tmp_path, day=1, view_count="999"))
    changed = prepare_import(snapshot(tmp_path, day=2, changed=True))
    fingerprints = [
        [row["fingerprint"] for row in plan.rows] for plan in (first, later, changed)
    ]
    assert fingerprints[0] == fingerprints[1]
    assert (
        fingerprints[2][0] != fingerprints[0][0]
        and fingerprints[2][1] == fingerprints[0][1]
    )


def test_postgres_local_source_is_separate_scope_with_region(tmp_path, pg_connection):
    local_path = snapshot(tmp_path, ids=("WLF3",), source="local")
    with Session(pg_connection) as session:
        with session.begin():
            apply_import(session, prepare_import(snapshot(tmp_path)))
            local = prepare_import(local_path, source="local")
            assert apply_import(session, local)["new_services"] == 1
            service = session.scalar(
                select(WelfareService).where(WelfareService.source_id == "WLF3")
            )
            assert (service.provider, service.scope) == (
                "ssis:LocalGovernmentWelfareInformations",
                "local",
            )
            revision = session.get(WelfareRevision, service.active_revision_id)
            assert (revision.normalized["ctpv"], revision.normalized["sgg"]) == (
                "대구광역시",
                "남구",
            )
            # RAG chunks bind to this value: the content hash of the same normalized record.
            record = normalize_payload(
                json.loads(local_path.read_text(encoding="utf-8")), "local"
            )[0]
            assert revision.content_sha256 == content_sha256(record.to_dict())
        # Complete local scans without central IDs never mark central services missing.
        for day in (1, 2):
            with session.begin():
                apply_import(
                    session,
                    prepare_import(
                        snapshot(tmp_path, day=day, ids=("WLF3",), source="local"),
                        source="local",
                    ),
                )
        with session.begin():
            assert set(session.scalars(select(WelfareService.publication_status))) == {
                "published"
            }
            assert verify_import(session, local)["service_revisions"] == 1


def test_postgres_welfare_idempotency_and_semantic_revisions(tmp_path, pg_connection):
    first = prepare_import(snapshot(tmp_path))
    with Session(pg_connection) as session:
        with session.begin():
            result = apply_import(session, first)
            assert result["new_services"] == result["new_revisions"] == 2
        with session.begin():
            assert apply_import(session, first)["new_revisions"] == 0
            assert verify_import(session, first)["service_revisions"] == 2
            assert count(session, WelfareNotice) == 0
            assert all(
                row.application_status == "unknown"
                for row in session.scalars(select(WelfareRevision))
            )
        second = prepare_import(snapshot(tmp_path, day=1, view_count="999"))
        with session.begin():
            assert apply_import(session, second)["new_revisions"] == 0
        third = prepare_import(snapshot(tmp_path, day=2, changed=True))
        with session.begin():
            assert apply_import(session, third)["new_revisions"] == 1
            assert count(session, WelfareRevision) == 3
            assert count(session, WelfareService) == 2
        fourth = prepare_import(snapshot(tmp_path, day=3))
        with pytest.raises(RuntimeError), session.begin():
            apply_import(session, fourth)
            raise RuntimeError("before commit")
        with session.begin():
            assert count(session, DataImportRun) == 3
            assert verify_import(session, third)["service_revisions"] == 2


def test_postgres_missing_requires_distinct_complete_scans_and_can_return(
    tmp_path, pg_connection
):
    with Session(pg_connection) as session:
        with session.begin():
            apply_import(session, prepare_import(snapshot(tmp_path)))
        first_missing = prepare_import(snapshot(tmp_path, day=1, ids=("WLF1",)))
        with session.begin():
            apply_import(session, first_missing)
            apply_import(session, first_missing)
            missing = session.scalar(
                select(WelfareService).where(WelfareService.source_id == "WLF2")
            )
            assert missing.publication_status == "published"
            assert missing.missing_scans == 1
        with session.begin():
            result = apply_import(
                session, prepare_import(snapshot(tmp_path, day=2, ids=("WLF1",)))
            )
            assert result["newly_missing"] == 1
            assert (
                session.scalar(
                    select(WelfareService.publication_status).where(
                        WelfareService.source_id == "WLF2"
                    )
                )
                == "missing"
            )
            assert count(session, WelfareRevision) == 2
        with session.begin():
            apply_import(session, prepare_import(snapshot(tmp_path, day=3)))
            restored = session.scalar(
                select(WelfareService).where(WelfareService.source_id == "WLF2")
            )
            assert (
                restored.publication_status == "published"
                and restored.missing_scans == 0
            )
        with pytest.raises(ValueError, match="older"), session.begin():
            apply_import(
                session, prepare_import(snapshot(tmp_path, day=1, changed=True))
            )


def test_postgres_notice_expiry_query_boundary_and_constraints(tmp_path, pg_connection):
    as_of = START + timedelta(days=10)
    with Session(pg_connection) as session:
        with session.begin():
            apply_import(session, prepare_import(snapshot(tmp_path)))
            services = session.scalars(
                select(WelfareService).order_by(WelfareService.source_id)
            ).all()
            first_id, second_id = services[0].id, services[1].id
            first_revision, second_revision = (
                services[0].active_revision_id,
                services[1].active_revision_id,
            )
            for key, period_type, status, starts, deadline in [
                ("ends_now", "fixed", "open", None, as_of),
                ("ongoing", "ongoing", "open", None, None),
                (
                    "future_start",
                    "fixed",
                    "open",
                    as_of + timedelta(hours=1),
                    as_of + timedelta(days=1),
                ),
                ("unknown", "unknown", "unknown", None, None),
            ]:
                session.add(
                    WelfareNotice(
                        service_id=first_id,
                        source_revision_id=first_revision,
                        source_notice_id=key,
                        source_url="https://www.bokjiro.go.kr/",
                        period_text="공식 원문",
                        period_type=period_type,
                        status=status,
                        starts_at=starts,
                        deadline_at=deadline,
                        checked_at=START,
                    )
                )
        with session.begin():
            found = session.scalars(
                select(WelfareNotice.source_notice_id)
                .join(WelfareService, WelfareNotice.service_id == WelfareService.id)
                .where(open_notice_condition(as_of))
            ).all()
            assert found == ["ongoing"]
            assert expire_notices(session, as_of) == 1
            assert expire_notices(session, as_of) == 0
            assert count(session, WelfareNotice) == 4
        with pytest.raises(IntegrityError), session.begin():
            session.get(WelfareService, second_id).active_revision_id = first_revision
            session.flush()
        with pytest.raises(IntegrityError), session.begin():
            session.add(
                WelfareNotice(
                    service_id=second_id,
                    source_revision_id=second_revision,
                    source_notice_id="invalid_open",
                    source_url="https://www.bokjiro.go.kr/",
                    period_text="",
                    period_type="unknown",
                    status="open",
                    checked_at=START,
                )
            )
            session.flush()


def test_postgres_withdrawn_service_stays_excluded(tmp_path, pg_connection):
    with Session(pg_connection) as session:
        with session.begin():
            apply_import(session, prepare_import(snapshot(tmp_path)))
            service = session.scalar(
                select(WelfareService).where(WelfareService.source_id == "WLF1")
            )
            service.publication_status = "withdrawn"
        with session.begin():
            apply_import(
                session, prepare_import(snapshot(tmp_path, day=1, changed=True))
            )
            assert (
                session.scalar(
                    select(WelfareService.publication_status).where(
                        WelfareService.source_id == "WLF1"
                    )
                )
                == "withdrawn"
            )
