"""복지 API 표본(시범 지역 대구광역시 남구) — 실제 수집본이 있을 때만 확인한다."""

import hashlib
import json
from datetime import date, datetime

import pytest

from agetech_data import paths
from agetech_data.welfare import query
from agetech_data.welfare.regions import MERGED
from agetech_data.welfare.sample import NATIONAL_CASES, PILOT, REGION_CASES, SAMPLE_PATH, build, sample_date

needs_raw = pytest.mark.skipif(not (paths.WELFARE_CENTRAL_RAW.is_file() and paths.WELFARE_LOCAL_RAW.is_file()),
                               reason="복지 수집 원본 없음 (refresh 실행 필요)")


def test_case_labels_unique():
    labels = [c[0] for c in REGION_CASES] + [c[0] for c in NATIONAL_CASES]
    assert len(labels) == len(set(labels))


def test_sample_date_is_latest_fetch_day():
    a = {"meta": {"fetched_at": "2026-11-05T15:20:06+00:00"}}
    b = {"meta": {"fetched_at": "2026-11-06T00:19:00+00:00"}}
    assert sample_date(a, b) == date(2026, 11, 6)
    assert sample_date(a, {"meta": {}}, {}) == date(2026, 11, 5)
    assert sample_date({}, {"meta": None}) is None


@needs_raw
def test_sample_does_not_depend_on_run_date(monkeypatch):
    base = build(paths.WELFARE_CENTRAL_RAW, paths.WELFARE_LOCAL_RAW)

    class Later(datetime):   # 조회 함수의 '오늘'을 2030년으로 옮겨도 표본은 같아야 한다
        @classmethod
        def now(cls, tz=None):
            return datetime(2030, 1, 1, tzinfo=tz)

    monkeypatch.setattr(query, "datetime", Later)
    assert build(paths.WELFARE_CENTRAL_RAW, paths.WELFARE_LOCAL_RAW) == base
    assert base["as_of"] == sample_date(json.loads(paths.WELFARE_CENTRAL_RAW.read_text(encoding="utf-8")),
                                        json.loads(paths.WELFARE_LOCAL_RAW.read_text(encoding="utf-8"))).isoformat()
    # 기준일을 직접 늦추면 그때까지 끝난 사업은 빠진다(남구·대구시 사업 수가 늘지 않음)
    later = build(paths.WELFARE_CENTRAL_RAW, paths.WELFARE_LOCAL_RAW, date(2030, 1, 1))
    assert later["as_of"] == "2030-01-01"
    assert later["pilot"]["counts"]["district"] <= base["pilot"]["counts"]["district"]
    assert later["pilot"]["counts"]["province"] <= base["pilot"]["counts"]["province"]


@needs_raw
def test_sample_is_stable_and_complete():
    a = build(paths.WELFARE_CENTRAL_RAW, paths.WELFARE_LOCAL_RAW)
    assert a == build(paths.WELFARE_CENTRAL_RAW, paths.WELFARE_LOCAL_RAW)
    assert a["cases_not_found"] == [] and len(a["regions"]) == len(REGION_CASES)
    p = a["pilot"]
    assert p["resolved"] == {"ctpv": PILOT[0], "sgg": PILOT[1], "notes": []}
    assert p["counts"]["district"] >= 1 and p["counts"]["national"] >= 100
    # 지역 사업은 전부 싣고, 남구 사업이 대구시 전체 사업보다 앞에 온다
    assert [i["match"] for i in p["items"]] == sorted((i["match"] for i in p["items"]), key=["district", "province"].index)
    assert len(p["items"]) == p["counts"]["district"] + p["counts"]["province"]
    assert all(i["record"]["ctpv"] == PILOT[0] for i in p["items"])
    assert all(i["record"]["sgg"] == PILOT[1] for i in p["items"] if i["match"] == "district")
    assert p["national_omitted"] + len(p["national_examples"]) == p["counts"]["national"]
    # 출처·확인일이 모든 표본 레코드에 있다
    for rec in [i["record"] for i in p["items"]] + [e["record"] for e in p["national_examples"]]:
        assert rec["detail_url"].startswith("https://") and rec["source_fetched_at"]
        assert not any(f["name"].endswith("없음.hwp") for f in rec["forms"])   # 자리 표시 서식 없음
    by = {r["cases"][0]: r for r in a["regions"]}
    assert by["2026-07-01 통합 전 옛 이름"]["resolved"]["ctpv"] == MERGED
    assert by["알 수 없는 시도 → 전국만"]["counts"]["province"] == 0
    # 같은 '남구'라도 시도가 다르면 다른 사업
    busan = by["같은 이름 시군구가 다른 시도에도 있음(부산 남구)"]["local_examples"]
    assert busan and all(x.startswith("부산광역시") for x in busan)


@needs_raw
def test_committed_sample_matches_when_same_input():
    if not SAMPLE_PATH.is_file():
        pytest.skip("표본 파일 없음")
    committed = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    same = all(committed["input"][k]["sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()
               for k, p in (("central", paths.WELFARE_CENTRAL_RAW), ("local", paths.WELFARE_LOCAL_RAW)))
    if same:
        assert committed == build(paths.WELFARE_CENTRAL_RAW, paths.WELFARE_LOCAL_RAW)
