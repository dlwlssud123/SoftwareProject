"""복지 상세 일일 한도 대응: 캐시·우선순위·pending (개발계정 중앙 상세 100회/일, 지자체 상세 1,000회/일)."""

import json
from urllib.parse import parse_qs, urlsplit

import pytest

from agetech_data.collect.welfare import collect_welfare, fingerprint
from agetech_data.net import CollectError
from agetech_data.refresh.changes import diff

KEY = "k"
QUIET = {"sleep": lambda s: None, "log": lambda m: None}
QUOTA_XML = ("<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR</errMsg>"
             "<returnReasonCode>22</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>")


class Api:
    """목록은 항상 응답, 상세는 quota 회까지만 응답하고 이후 HTTP 429 + 코드 22."""

    def __init__(self, n, quota=10_000, inq="1", names=None, fail_detail_at=None, life="노년, 중장년"):
        self.ids = [f"WLF{i:08d}" for i in range(1, n + 1)]
        self.quota, self.inq, self.names, self.life = quota, inq, names or {}, life
        self.detail_calls, self.fail_detail_at = 0, fail_detail_at

    def __call__(self, url):
        u = urlsplit(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if "detail" in u.path.lower():
            self.detail_calls += 1
            if self.fail_detail_at and self.detail_calls == self.fail_detail_at:
                return 400, "<html>bad</html>"
            if self.detail_calls > self.quota:
                return 429, QUOTA_XML
            sid = q["servId"]
            return 200, (f"<wantedDtl><resultCode>0</resultCode><servId>{sid}</servId>"
                         f"<inqNum>{self.inq}</inqNum><sprtTrgtCn>대상 {self.names.get(sid, '')}</sprtTrgtCn></wantedDtl>")
        body = "".join(f"<servList><servId>{i}</servId><servNm>{self.names.get(i, '서비스')}</servNm>"
                       f"<lifeNmArray>{self.life}</lifeNmArray><inqNum>{self.inq}</inqNum></servList>"
                       for i in self.ids)
        return 200, f"<wantedList><resultCode>0</resultCode><totalCount>{len(self.ids)}</totalCount>{body}</wantedList>"


def _status(out):
    return {i["servId"]: i["detail_status"] for i in out["items"]}


def test_quota_stops_details_and_marks_pending(tmp_path):
    api = Api(5, quota=3)
    out = collect_welfare("central", KEY, fetch=api, cache_path=tmp_path / "c.json", **QUIET)
    st = out["meta"]["details"]
    assert out["meta"]["item_count"] == 5  # 목록은 완전
    assert out["meta"]["complete"] is False   # 상세 대기가 있으면 DB 적재는 명시적으로 허용할 때만
    assert st["counts"] == {"fresh": 3, "pending": 2} and st["remaining"] == 2 and st["stopped_by_quota"]
    assert api.detail_calls == 4  # 한도 초과 응답에서 재시도하지 않음
    assert "pending" in _status(out).values() and "detail" not in out["items"][4]


def test_next_run_reuses_cache_and_fills_pending(tmp_path):
    cache = tmp_path / "c.json"
    collect_welfare("local", KEY, fetch=Api(5, quota=3), cache_path=cache, **QUIET)
    api = Api(5, inq="999")  # 조회수만 바뀜
    out = collect_welfare("local", KEY, fetch=api, cache_path=cache, **QUIET)
    assert api.detail_calls == 2  # 남은 2건만 받음
    assert sorted(_status(out).values()) == ["cached", "cached", "cached", "fresh", "fresh"]


def test_list_change_marks_stale_and_is_refetched_first(tmp_path):
    cache = tmp_path / "c.json"
    collect_welfare("local", KEY, fetch=Api(3), cache_path=cache, **QUIET)
    changed = "WLF00000002"
    out = collect_welfare("local", KEY, fetch=Api(3, quota=0, names={changed: "새 이름"}), cache_path=cache, **QUIET)
    assert _status(out)[changed] == "stale" and out["items"][1]["detail"]  # 이전 상세 유지
    api = Api(3, names={changed: "새 이름"})
    out = collect_welfare("local", KEY, fetch=api, cache_path=cache, **QUIET)
    assert api.detail_calls == 1 and _status(out)[changed] == "fresh"


def test_detail_budget_limits_calls(tmp_path):
    api = Api(10)
    out = collect_welfare("local", KEY, fetch=api, cache_path=tmp_path / "c.json", detail_budget=4, **QUIET)
    assert api.detail_calls == 4 and out["meta"]["details"]["remaining"] == 6


def test_cache_kept_when_run_fails_midway(tmp_path):
    cache = tmp_path / "c.json"
    with pytest.raises(CollectError):
        collect_welfare("local", KEY, fetch=Api(5, fail_detail_at=4), cache_path=cache, **QUIET)
    assert len(json.loads(cache.read_text(encoding="utf-8"))["entries"]) == 3  # 실패 전까지 받은 상세 보존


def test_view_count_is_not_a_change(tmp_path):
    a = collect_welfare("local", KEY, fetch=Api(3, inq="1"), **QUIET)["items"]
    b = collect_welfare("local", KEY, fetch=Api(3, inq="50"), **QUIET)["items"]
    d = diff(a, b, lambda it: it["servId"], content_of=fingerprint)
    assert d["changed"] == 0 and d["unchanged"] == 3
    assert diff(a, b, lambda it: it["servId"])["changed"] == 3  # 조회수를 빼지 않으면 전부 변경으로 잡힘


def test_list_order_only_change_is_not_refetched_or_counted(tmp_path):
    # 원천이 '노년, 중장년' ↔ '중장년, 노년'처럼 쉼표 목록 순서만 바꿔 준다(11/12 지자체 252건) — 상세를 다시 받지 않는다
    cache = tmp_path / "c.json"
    a = collect_welfare("local", KEY, fetch=Api(3, life="노년, 중장년"), cache_path=cache, **QUIET)
    api = Api(3, life="중장년, 노년")
    b = collect_welfare("local", KEY, fetch=api, cache_path=cache, **QUIET)
    assert api.detail_calls == 0 and set(_status(b).values()) == {"cached"}
    assert b["items"][0]["list"]["lifeNmArray"] == "중장년, 노년"  # 수집본은 받은 그대로
    assert diff(a["items"], b["items"], lambda it: it["servId"], content_of=fingerprint)["changed"] == 0
    # 값이 실제로 바뀌면(목록에 생애주기 추가) 여전히 다시 받는다
    api = Api(3, life="중장년, 노년, 청년")
    collect_welfare("local", KEY, fetch=api, cache_path=cache, **QUIET)
    assert api.detail_calls == 3


def test_cache_saved_with_old_signature_is_migrated_without_refetch(tmp_path):
    from agetech_data.collect.welfare import legacy_list_signature, list_signature

    cache = tmp_path / "c.json"
    collect_welfare("local", KEY, fetch=Api(3, life="노년, 중장년"), cache_path=cache, **QUIET)
    saved = json.loads(cache.read_text(encoding="utf-8"))
    row = {"servId": "WLF00000001", "servNm": "서비스", "lifeNmArray": "노년, 중장년", "inqNum": "1"}
    for sid in saved["entries"]:  # 11/13 전 코드가 저장한 모양으로 되돌림
        saved["entries"][sid]["sig"] = legacy_list_signature({**row, "servId": sid})
    cache.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    api = Api(3, life="노년, 중장년")
    out = collect_welfare("local", KEY, fetch=api, cache_path=cache, **QUIET)
    assert api.detail_calls == 0 and set(_status(out).values()) == {"cached"}
    entries = json.loads(cache.read_text(encoding="utf-8"))["entries"]
    assert all(e["sig"] == list_signature({**row, "servId": sid}) for sid, e in entries.items())
