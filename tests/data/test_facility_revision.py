"""갱신 수집본 → DB 급식소 행 (facilities.revision) — 백엔드 import_meal_facilities 의 입력."""

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from agetech_data.collect.meal_facilities import add_row_ids
from agetech_data.facilities.revision import (
    PROVIDER,
    SOURCE_URL,
    VOLATILE_FIELDS,
    facility_rows,
    hours_text,
)
from agetech_data.snapshot import collected_on

FIXTURE = Path(__file__).parent / "fixtures" / "free_meal_sample.json"


@pytest.fixture(scope="module")
def items():
    return add_row_ids(json.loads(FIXTURE.read_text(encoding="utf-8"))["items"])


def _payload(items, fetched="2026-11-07T07:51:46+00:00"):
    return {"meta": {"fetched_at": fetched}, "items": copy.deepcopy(items)}


def test_rows_map_contract_fields_to_storage_columns(items):
    rows, skipped = facility_rows(_payload(items))
    nam = next(r for r in rows if r["name"] == "남구종합사회복지관")
    assert (nam["sido"], nam["sigungu"], nam["address"]) == ("대구광역시", "남구", "대구광역시 남구 중앙대로38길 17")
    assert nam["hours_text"] == "수+목 / 중식(11:20-12:20)"               # 요일 원문 + 시간 원문
    assert nam["eligibility_text"] == "결식노인+저소득층+장애인(회원제)" and nam["contact_text"] == "053-476-7700"
    assert nam["reference_date"] == date(2026, 7, 13) and nam["checked_on"] == date(2026, 11, 7)
    assert nam["source_url"] == SOURCE_URL and nam["is_published"] and nam["quality_flags"] == []
    assert nam["source_id"] == nam["normalized"]["facility_id"] and nam["normalized"]["days"] == ["수", "목"]
    assert not set(VOLATILE_FIELDS) & set(nam["normalized"])
    assert PROVIDER == "data.go.kr:15013107" and skipped == []


def test_closed_or_not_operating_rows_are_kept_but_unpublished(items):
    rows, _ = facility_rows(_payload(items))
    hidden = {r["name"]: r for r in rows if not r["is_published"]}
    assert "not_operating" in hidden["영흥면무료급식소"]["quality_flags"]
    assert all({"operation_ended", "not_operating"} & set(r["quality_flags"]) for r in hidden.values())
    assert all(r["is_published"] for r in rows if not {"operation_ended", "not_operating"} & set(r["quality_flags"]))


def test_judgement_date_is_collection_date_in_kst(items):
    late_utc = facility_rows(_payload(items, "2026-11-06T16:30:00+00:00"))[0]      # KST 11/07 01:30
    assert {r["checked_on"] for r in late_utc} == {date(2026, 11, 7)}
    assert collected_on({"fetched_at": "2026-11-06T14:59:59+00:00"}) == date(2026, 11, 6)
    stale = next(r for r in late_utc if r["name"] == "대한노인회 완도군지회(완도읍분회)")
    assert "reference_stale" in stale["quality_flags"]
    long_ago = facility_rows(_payload(items, "2020-01-01T00:00:00+00:00"))[0]     # 그때 기준이면 오래되지 않음
    assert "reference_stale" not in next(r for r in long_ago if r["source_id"] == stale["source_id"])["quality_flags"]
    with pytest.raises(ValueError):
        facility_rows(_payload(items, "2026-11-07T07:51:46"))                     # 시간대 없는 수집 시각


def test_same_content_same_hash_and_changed_text_new_hash(items):
    first = {r["source_id"]: r for r in facility_rows(_payload(items))[0]}
    again = {r["source_id"]: r for r in facility_rows(_payload(items, "2026-11-07T09:00:00+00:00"))[0]}
    assert {k: r["content_sha256"] for k, r in first.items()} == {k: r["content_sha256"] for k, r in again.items()}
    changed = copy.deepcopy(items)
    target = next(i for i in changed if i["fcltyNm"] == "남구종합사회복지관")
    target["phoneNumber"] = "053-000-0000"
    rows = {r["source_id"]: r for r in facility_rows(_payload(changed))[0]}
    diff = [k for k in first if first[k]["content_sha256"] != rows[k]["content_sha256"]]
    assert len(diff) == 1 and rows[diff[0]]["contact_text"] == "053-000-0000"


def test_rows_without_region_or_name_are_skipped(items):
    base = next(i for i in items if i["fcltyNm"] == "남구종합사회복지관")
    nowhere = {**base, "fcltyNm": "어딘가 급식소", "rdnmadr": "", "lnmadr": "", "insttNm": "모름", "row_id": "x1"}
    unnamed = {**base, "fcltyNm": "", "rdnmadr": "대구광역시 중구 어딘가 1", "row_id": "x2"}
    rows, skipped = facility_rows(_payload([base, nowhere, unnamed]))
    assert [r["name"] for r in rows] == ["남구종합사회복지관"]
    assert sorted(s["reason"] for s in skipped) == ["name_missing", "region_unknown"]


def test_hours_text_keeps_raw_parts():
    assert hours_text("월~금", "중식 11:30~13:00") == "월~금 / 중식 11:30~13:00"
    assert hours_text(None, "12:00") == "12:00" and hours_text(None, None) is None
