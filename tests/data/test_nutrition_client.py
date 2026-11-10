import json

import pytest

from agetech_data.nutrition import client
from agetech_data.nutrition.client import CollectError, collect, fetch_page, parse_body

KEY = "abc+/=SECRET키"  # URL 인코딩이 필요한 문자를 섞은 가짜 키


def _ok(items, total):
    return 200, json.dumps({"header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                            "body": {"items": items, "totalCount": total}}, ensure_ascii=False)


def _rows(start, n):
    return [{"FOOD_CD": f"R{start + i:05d}", "FOOD_NM_KR": f"식품{start + i}"} for i in range(n)]


class FakeApi:
    """pageNo 별 응답을 흉내 낸다. fail[page] 횟수만큼 먼저 HTTP 500 을 준다."""

    def __init__(self, total, rows=500, fail=None, dup=False):
        self.total, self.rows, self.fail, self.dup = total, rows, dict(fail or {}), dup
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        page = int(url.split("pageNo=")[1].split("&")[0])
        if self.fail.get(page, 0) > 0:
            self.fail[page] -= 1
            return 500, "<html>Internal Server Error</html>"
        start = (page - 1) * self.rows
        n = max(0, min(self.rows, self.total - start))
        items = _rows(0 if self.dup else start, n)
        return _ok(items, self.total)


def test_parse_body_shapes():
    assert parse_body(_ok([{"FOOD_CD": "1"}], 1)[1])[2:] == ([{"FOOD_CD": "1"}], 1)
    wrapped = json.dumps({"response": {"header": {"resultCode": "00"},
                                       "body": {"items": {"item": {"FOOD_CD": "1"}}, "totalCount": "1"}}})
    assert parse_body(wrapped)[2:] == ([{"FOOD_CD": "1"}], 1)
    gw = json.dumps({"OpenAPI_ServiceResponse": {"cmmMsgHeader": {
        "errMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR", "returnReasonCode": "30"}}})
    assert parse_body(gw)[:2] == ("30", "SERVICE_KEY_IS_NOT_REGISTERED_ERROR")


def test_collect_paginates_and_records_meta():
    api = FakeApi(total=1200)
    result = collect(KEY, fetch=api, sleep=lambda s: None, log=lambda m: None)
    assert result["meta"]["item_count"] == 1200 and result["meta"]["complete"]
    assert len(api.urls) == 3 and "DB_CLASS_NM=%ED%92%88%EB%AA%A9%EB%8C%80%ED%91%9C" in api.urls[0]
    assert "serviceKey" not in json.dumps(result["meta"]) and KEY not in json.dumps(result, ensure_ascii=False)


def test_retry_on_server_error_then_success():
    waits = []
    api = FakeApi(total=10, fail={1: 2})
    items, total = fetch_page(KEY, 1, 500, "품목대표", api, sleep=waits.append)
    assert total == 10 and len(items) == 10 and len(waits) == 2


def test_failure_message_never_contains_key():
    api = FakeApi(total=10, fail={1: 99})
    with pytest.raises(CollectError) as e:
        fetch_page(KEY, 1, 500, "품목대표", api, retries=3, sleep=lambda s: None)
    msg = str(e.value)
    assert "HTTP 500" in msg and "SECRET" not in msg and "abc" not in msg


def test_unregistered_key_is_not_retried():
    calls = []

    def fetch(url):
        calls.append(url)
        return 200, json.dumps({"OpenAPI_ServiceResponse": {"cmmMsgHeader": {
            "errMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR", "returnReasonCode": "30"}}})

    with pytest.raises(CollectError, match="30"):
        fetch_page(KEY, 1, 500, "품목대표", fetch, sleep=lambda s: None)
    assert len(calls) == 1


def test_duplicate_codes_rejected():
    with pytest.raises(CollectError, match="중복"):
        collect(KEY, fetch=FakeApi(total=1000, dup=True), sleep=lambda s: None, log=lambda m: None)


def test_changed_total_rejected():
    responses = iter([_ok(_rows(0, 1), 2), _ok(_rows(1, 1), 3)])
    with pytest.raises(CollectError, match="건수가 변경"):
        collect(KEY, rows=1, fetch=lambda _: next(responses), sleep=lambda _: None, log=lambda _: None)


def test_missing_food_code_rejected():
    with pytest.raises(CollectError, match="식품코드가 없는"):
        collect(KEY, fetch=lambda _: _ok([{"FOOD_NM_KR": "이름만"}], 1), log=lambda _: None)


def test_missing_key_keeps_existing_file(tmp_path, monkeypatch, capsys):
    out = tmp_path / "raw.json"
    out.write_text("기존", encoding="utf-8")
    monkeypatch.setattr(client, "load_secret", lambda name: "")
    assert client.main(["--output", str(out)]) == 1
    assert out.read_text(encoding="utf-8") == "기존"
    assert "DATA_GO_KR_SERVICE_KEY" in capsys.readouterr().err
