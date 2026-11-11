"""갱신 수집본 → DB 복지 판본 행 (welfare.revision) — 백엔드 import_welfare 의 입력."""

import copy
import json
from datetime import UTC, datetime, timedelta

import pytest

from agetech_data import paths
from agetech_data.welfare.normalize import normalize_payload
from agetech_data.welfare.revision import SOURCES, VOLATILE_FIELDS, content_sha256, revision_rows

FETCHED = "2026-11-05T15:20:06+00:00"


def _item(sid, *, local=False, views="10", benefit="월 10만원", status="fresh", link=None):
    lst = {"servId": sid, "servNm": "사업", "inqNum": views,
           "servDtlLink": link or f"https://www.bokjiro.go.kr/ssis-tbu/x.do?wlfareInfoId={sid}&wlfareInfoReldBztpCd=02"}
    if local:
        lst.update(ctpvNm="대구광역시", sggNm="남구")
    if status == "pending":
        return {"servId": sid, "list": lst, "detail_status": "pending"}
    det = {"servId": sid, "servNm": "사업", "sprtTrgtCn": "65세 이상", "alwServCn": benefit, "inqNum": views}
    xml = f"<wantedDtl><resultCode>0</resultCode><servId>{sid}</servId><inqNum>{views}</inqNum></wantedDtl>"
    return {"servId": sid, "list": lst, "detail": det, "detail_xml": xml, "detail_status": status,
            "detail_fetched_at": "2026-11-05T15:30:00+00:00"}


def _payload(*items, fetched=FETCHED):
    return {"meta": {"fetched_at": fetched}, "items": list(items)}


def test_rows_keep_structured_fields_and_drop_run_specific_values():
    payload = _payload(_item("WLF00000001", local=True))
    row = revision_rows(payload, "local")[0]
    assert row["source_id"] == "WLF00000001" and row["raw"] == payload["items"][0]
    assert (row["normalized"]["ctpv"], row["normalized"]["sgg"], row["normalized"]["scope"]) == ("대구광역시", "남구", "district")
    assert not set(VOLATILE_FIELDS) & set(row["normalized"])
    assert row["benefit_text"] == "월 10만원" and row["target_text"] == "65세 이상" and row["detail_state"] == "ready"
    assert row["checked_at"] == datetime(2026, 11, 5, 15, 30, tzinfo=UTC)   # 상세 확인 시각(수집 시작보다 늦어도 됨)
    assert row["application_status"] == "unknown" and row["quality_status"] in ("ok", "flagged")
    # RAG 연결 키: 같은 정제 레코드의 내용 해시
    rec = normalize_payload(payload, "local")[0]
    assert row["content_sha256"] == content_sha256(rec.to_dict())
    assert SOURCES["local"]["scope"] == "local" and SOURCES["central"]["scope"] == "central_nationwide"


def test_fingerprint_ignores_view_count_check_time_and_cache_status():
    base = revision_rows(_payload(_item("WLF00000001")), "central")[0]
    later = revision_rows(_payload(_item("WLF00000001", views="999", status="cached"), fetched="2026-11-06T00:00:00+00:00"),
                          "central")[0]
    changed = revision_rows(_payload(_item("WLF00000001", benefit="월 20만원")), "central")[0]
    assert later["fingerprint"] == base["fingerprint"] and later["content_sha256"] == base["content_sha256"]
    assert later["raw"] != base["raw"]                     # 원문(조회수 포함)은 그대로 보존
    assert changed["fingerprint"] != base["fingerprint"]


def test_pending_detail_and_unofficial_link_are_not_published():
    pending = revision_rows(_payload(_item("WLF00000002", status="pending")), "central")[0]
    assert pending["detail_state"] == "pending" and pending["quality_status"] == "hold"
    assert pending["checked_at"] == datetime.fromisoformat(FETCHED)
    other = revision_rows(_payload(_item("WLF00000003", link="https://www.bokjiro.go.kr/x.do?wlfareInfoId=WLF00000009")),
                          "central")[0]
    assert other["quality_status"] == "hold" and "no_official_link" in other["issues"]


def test_invalid_input_rejected():
    bad_id = _item("WLF00000001")
    bad_id["servId"] = "X1"
    with pytest.raises(ValueError):
        revision_rows(_payload(bad_id), "central")
    future = _item("WLF00000001")
    future["detail_fetched_at"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    with pytest.raises(ValueError):
        revision_rows(_payload(future), "central")
    with pytest.raises(ValueError):
        revision_rows(_payload(_item("WLF00000001")), "unknown")
    with pytest.raises(ValueError):
        revision_rows({"meta": {"fetched_at": "2026-11-05T15:20:06"}, "items": [_item("WLF00000001")]}, "central")


@pytest.mark.skipif(not (paths.WELFARE_CENTRAL_RAW.is_file() and paths.WELFARE_LOCAL_RAW.is_file()),
                    reason="복지 수집 원본 없음 (refresh 실행 필요)")
def test_real_snapshots_all_publishable_and_stable():
    for source, path in (("central", paths.WELFARE_CENTRAL_RAW), ("local", paths.WELFARE_LOCAL_RAW)):
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = revision_rows(payload, source)
        assert len(rows) == len(payload["items"]) == len({r["fingerprint"] for r in rows})
        assert not any("no_official_link" in r["issues"] for r in rows)
        again = copy.deepcopy(payload)
        for it in again["items"]:
            it["list"]["inqNum"] = "0"
        assert [r["fingerprint"] for r in revision_rows(again, source)] == [r["fingerprint"] for r in rows]
