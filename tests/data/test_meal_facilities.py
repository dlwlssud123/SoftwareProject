"""무료급식소 수집·정제·지역 조회 (실제 응답 행 발췌 표본 + 가짜 HTTP)."""

import json
from datetime import date
from pathlib import Path

import pytest

from agetech_data.collect.meal_facilities import add_row_ids, collect_free_meal, parse_page
from agetech_data.facilities.normalize import normalize_payload, parse_days, parse_meals, split_region
from agetech_data.facilities.query import ALWAYS, facilities_for
from agetech_data.net import CollectError, Fatal, Quota, QuotaExceededError
from agetech_data.textutil import sha256_json
from agetech_data.welfare.regions import MERGED, normalize_ctpv

FIXTURE = Path(__file__).parent / "fixtures" / "free_meal_sample.json"
AS_OF = date(2026, 11, 7)


@pytest.fixture(scope="module")
def rows():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["items"]


@pytest.fixture(scope="module")
def records(rows):
    return normalize_payload({"meta": {"fetched_at": "2026-11-07T07:51:46+00:00"}, "items": add_row_ids(rows)}, AS_OF)


def _page(items, total):
    return json.dumps({"header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                       "body": {"items": {"item": items}, "numOfRows": len(items), "pageNo": 1, "totalCount": total}},
                      ensure_ascii=False)


# ── 수집 ────────────────────────────────────────────────────────────────

def test_parse_page_json_nodata_and_gateway_errors():
    assert parse_page(200, _page([{"fcltyNm": "가"}], 1)) == ([{"fcltyNm": "가"}], 1)
    single = json.dumps({"header": {"resultCode": "00"}, "body": {"items": {"item": {"fcltyNm": "가"}}, "totalCount": 1}})
    assert parse_page(200, single) == ([{"fcltyNm": "가"}], 1)
    assert parse_page(200, json.dumps({"header": {"resultCode": "03"}, "body": {}})) == ([], 0)
    gw = "<OpenAPI_ServiceResponse><cmmMsgHeader><returnReasonCode>{}</returnReasonCode>" \
         "<returnAuthMsg>X</returnAuthMsg></cmmMsgHeader></OpenAPI_ServiceResponse>"
    with pytest.raises(Quota):
        parse_page(429, gw.format("22"))
    with pytest.raises(Fatal):
        parse_page(200, gw.format("30"))


def test_collect_pages_row_ids_and_count_check(rows):
    pages = {1: _page(rows[:10], 16), 2: _page(rows[10:], 16)}
    got = collect_free_meal("KEY", fetch=lambda url: (200, pages[int(url.split("pageNo=")[1].split("&")[0])]),
                            sleep=lambda s: None, log=lambda m: None, page_size=10)
    assert got["meta"]["item_count"] == got["meta"]["total_count"] == 16
    assert got["meta"]["complete"] is True                # DB 적재(import_meal_facilities)가 확인
    assert got["meta"]["items_sha256"] == sha256_json(got["items"])
    ids = [r["row_id"] for r in got["items"]]
    assert len(ids) == len(set(ids)) == 16
    twin = add_row_ids([{"a": 1}, {"a": 1}])
    assert twin[1]["row_id"] == twin[0]["row_id"] + "-2"
    with pytest.raises(CollectError):                     # 전체 건수보다 적게 받으면 게시하지 않음
        collect_free_meal("KEY", fetch=lambda url: (200, _page(rows[:3], 16) if "pageNo=1&" in url else _page([], 16)),
                          sleep=lambda s: None, log=lambda m: None, page_size=3)
    gw22 = "<OpenAPI_ServiceResponse><cmmMsgHeader><returnReasonCode>22</returnReasonCode>" \
           "</cmmMsgHeader></OpenAPI_ServiceResponse>"
    with pytest.raises(QuotaExceededError):
        collect_free_meal("KEY", fetch=lambda url: (429, gw22), sleep=lambda s: None, log=lambda m: None)


def test_refresh_source_registered():
    from agetech_data.refresh.sources import SOURCES

    src = SOURCES["meal_facilities"]
    assert src.id_field == "row_id" and src.latest.name == "free_meal.json"
    assert src.quality([{"latitude": "", "phoneNumber": "1", "referenceDate": "2026-07-13"}])["coords_missing"] == 1


# ── 정제 ────────────────────────────────────────────────────────────────

def test_split_region_handles_old_reordered_and_glued_names():
    assert split_region("대구광역시 남구 중앙대로38길 17") == ("대구광역시", "남구")
    assert split_region("광주전남통합특별시 순천시 주암면") == (MERGED, "순천시")
    assert split_region("전라남도 완도군 완도읍") == (MERGED, "완도군")
    assert split_region("충청남도홍성군 홍성읍 문화로") == ("충청남도", "홍성군")
    assert split_region("세종특별자치시 조치원읍 새내로") == ("세종특별자치시", None)
    assert split_region(None) == (None, None)
    assert normalize_ctpv("광주전남통합특별시") == MERGED


@pytest.mark.parametrize("raw,days,closed", [
    ("수+목", ["수", "목"], False), ("월~금", list("월화수목금"), False), ("월+화+수+목+금요일", list("월화수목금"), False),
    ("주 5회(월~금)", list("월화수목금"), False), ("주 2회(화, 목)", ["화", "목"], False),
    ("매주 월~금요일", list("월화수목금"), False), ("월+수+금(공휴일 제외)", ["월", "수", "금"], False),
    ("주1회(6일분) 반찬배달", None, False), ("평일 5회(공휴일 제외)", None, False), ("미운영", None, True),
])
def test_parse_days(raw, days, closed):
    assert parse_days(raw) == (days, closed)


def test_parse_meals():
    assert parse_meals("중식(12:00-13:00)+석식(17:00-18:00)") == [
        {"meal": "중식", "start": "12:00", "end": "13:00"}, {"meal": "석식", "start": "17:00", "end": "18:00"}]
    assert parse_meals("11시30분~12시30분") == [{"meal": None, "start": "11:30", "end": "12:30"}]
    assert parse_meals("11:20 ~ 12:20") == [{"meal": None, "start": "11:20", "end": "12:20"}]
    assert parse_meals("중식(12:00)") == [{"meal": "중식", "start": "12:00", "end": None}]
    assert parse_meals("00:00~00:00") == [] and parse_meals("미정 (배달)") == []


def test_normalize_real_rows(records):
    by = {}
    for r in records:
        by.setdefault(r.name, []).append(r)
    nam = by["남구종합사회복지관"][0]
    assert (nam.ctpv, nam.sgg, nam.days, nam.phone) == ("대구광역시", "남구", ["수", "목"], "053-476-7700")
    assert nam.meals == [{"meal": "중식", "start": "11:20", "end": "12:20"}] and nam.quality_flags == []
    assert nam.targets == ["결식노인", "저소득층", "장애인(회원제)"] and nam.facility_id.startswith("FM")
    [ssang] = by["쌍촌종합사회복지관"]                          # 통합 전·후 지자체가 각각 올린 같은 시설
    assert "duplicate_merged" in ssang.quality_flags and len(ssang.merged_from) == 1 and len(ssang.row_ids) == 2
    assert ssang.provider == MERGED and ssang.merged_from[0]["provider"] == "광주광역시"
    [chil] = by["칠곡사랑의집 무료급식소"]                       # 기준일만 다름 → 최신
    assert chil.reference_date == max(m["reference_date"] for m in chil.merged_from + [{"reference_date": chil.reference_date}])
    nana = by["정나눔터"]                                        # 같은 지자체, 다른 급식 일정 → 둘 다
    assert len(nana) == 2 and {r.facility_id[-2:] == "-2" for r in nana} == {True, False}
    assert "not_operating" in by["영흥면무료급식소"][0].quality_flags
    assert "coords_missing" in by["예사의 집"][0].quality_flags
    assert by["주암댐노인복지관"][0].ctpv == MERGED and by["(사)공감사랑나눔회"][0].sgg == "홍성군"
    assert "includes_delivery" in by["홍은종합사회복지관"][0].quality_flags
    stale = by["대한노인회 완도군지회(완도읍분회)"][0]
    assert {"reference_stale", "days_unparsed", "time_unparsed", "includes_delivery"} <= set(stale.quality_flags)
    assert stale.days_raw == "주1회(6일분) 반찬배달"                # 못 읽어도 원문은 그대로


def test_sigungu_from_same_province_provider_when_address_is_glued(rows):
    base = next(r for r in rows if r["fcltyNm"] == "남구종합사회복지관")
    glued = {**base, "rdnmadr": "전라남도 완도군신지면 신지로 516", "lnmadr": "", "insttNm": "전남광주통합특별시 완도군"}
    [rec] = normalize_payload({"items": add_row_ids([glued])}, AS_OF)
    assert (rec.ctpv, rec.sgg) == (MERGED, "완도군") and "sgg_from_provider" in rec.quality_flags
    other = {**glued, "insttNm": "대구광역시 남구"}            # 다른 시도 지자체의 시군구는 쓰지 않음
    [rec] = normalize_payload({"items": add_row_ids([other])}, AS_OF)
    assert (rec.ctpv, rec.sgg) == (MERGED, None) and "sgg_from_provider" not in rec.quality_flags


def test_operation_ended_flag_relative_to_as_of(rows):
    closed = next(r for r in rows if (r.get("operCloseDate") or "9999") < "2026-01-01")
    [rec] = normalize_payload({"items": add_row_ids([closed])}, AS_OF)
    assert "operation_ended" in rec.quality_flags
    [old] = normalize_payload({"items": add_row_ids([closed])}, date(2020, 1, 1))
    assert "operation_ended" not in old.quality_flags


# ── 조회 ────────────────────────────────────────────────────────────────

def test_region_query_district_first_and_closed_excluded(records):
    region, out = facilities_for(records, "대구", "남구")
    assert (region.ctpv, region.sgg) == ("대구광역시", "남구")
    names = [x["facility"].name for x in out]
    assert names[:2] == ["남구종합사회복지관", "희망의집"] and {x["match"] for x in out[:2]} == {"district"}
    assert {x["match"] for x in out[2:]} == {"province"} and "요셉의집" in names
    assert all(x["facility"].ctpv == "대구광역시" for x in out)
    assert all(x["cautions"][-1] == ALWAYS for x in out)
    _, inc = facilities_for(records, "인천", None, include_closed=True)
    _, exc = facilities_for(records, "인천", None)
    assert len(inc) > len(exc)                                    # 미운영·종료는 기본 제외


def test_location_query_nearest_first_and_no_coords_tail(records):
    nam = next(r for r in records if r.name == "남구종합사회복지관")
    _, out = facilities_for(records, "대구", "남구", lat=nam.latitude, lon=nam.longitude, radius_km=3.0)
    assert out[0]["facility"].name == "남구종합사회복지관" and out[0]["distance_km"] == 0.0
    dists = [x["distance_km"] for x in out if x["distance_km"] is not None]
    assert dists == sorted(dists) and max(dists) <= 3.0
    assert any(x["facility"].sgg == "중구" and x["match"] == "nearby" for x in out)   # 지역 경계와 무관
    _, far = facilities_for(records, None, None, lat=37.5665, lon=126.9780, radius_km=3.0)   # 서울 시청 근처
    assert all(x["facility"].ctpv == "서울특별시" for x in far)


def test_build_main_end_to_end(tmp_path, rows):
    from agetech_data.facilities.build import main

    raw = tmp_path / "free_meal.json"
    raw.write_text(json.dumps({"meta": {"service": "s", "documentation": "d", "fetched_at": "t"},
                               "items": add_row_ids(rows)}, ensure_ascii=False), encoding="utf-8")
    out, rep, smp = tmp_path / "out.json", tmp_path / "rep.md", tmp_path / "smp.json"
    assert main(["--input", str(raw), "--output", str(out), "--report", str(rep), "--sample", str(smp),
                 "--as-of", "2026-11-07"]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["summary"]["rows"] == 16 and data["summary"]["facilities"] == len(data["records"]) == 14
    text = rep.read_text(encoding="utf-8")
    assert "## 4. 시범 지역 — 대구광역시 남구 (2곳)" in text and "남구종합사회복지관" in text
    cases = {c["id"]: c for c in json.loads(smp.read_text(encoding="utf-8"))["cases"]}
    assert cases["region_daegu_namgu"]["results"][0]["match"] == "district"
    assert cases["nearby_3km"]["results"][0]["distance_km"] == 0.0
