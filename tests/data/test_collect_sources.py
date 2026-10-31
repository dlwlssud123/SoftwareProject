import json
from urllib.parse import parse_qs, urlsplit

import pytest

from agetech_data.collect.recipes import collect_recipes
from agetech_data.collect.welfare import collect_welfare
from agetech_data.net import CollectError, Fatal, Retry, fetch_with_retry
from agetech_data.settings import load_secret_any

KEY = "abc+/=SECRET키"
NOSLEEP = {"sleep": lambda s: None, "log": lambda m: None}


# --- 공통 재시도 -----------------------------------------------------------
def test_retry_then_success_and_fatal_stops():
    calls = []

    def fetch(url):
        calls.append(url)
        return (500, "") if len(calls) < 3 else (200, "ok")

    assert fetch_with_retry("u", lambda s, t: t, what="시험", fetch=fetch, sleep=lambda s: None) == "ok"
    assert len(calls) == 3

    def fatal(status, text):
        raise Fatal(f"키 {KEY} 미등록")

    calls.clear()
    with pytest.raises(CollectError) as e:
        fetch_with_retry("u", fatal, what="시험", secrets=(KEY,), fetch=lambda u: (calls.append(u), (200, ""))[1],
                         sleep=lambda s: None)
    assert len(calls) == 1 and "SECRET" not in str(e.value)


def test_retry_exhausted_message():
    def parse(status, text):
        raise Retry("결과 코드 X")

    with pytest.raises(CollectError, match="3회 시도"):
        fetch_with_retry("u", parse, what="시험", fetch=lambda u: (200, ""), retries=3, sleep=lambda s: None)


def test_load_secret_any_falls_back(tmp_path, monkeypatch):
    monkeypatch.delenv("DATA_GO_KR_SERVICE_KEY", raising=False)
    monkeypatch.delenv("WELFARE_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("WELFARE_API_KEY='w-key'\n", encoding="utf-8")
    assert load_secret_any("DATA_GO_KR_SERVICE_KEY", "WELFARE_API_KEY", env_file=env) == "w-key"


# --- 레시피 ---------------------------------------------------------------
def _recipe_api(total, dup=False, code="INFO-000"):
    def fetch(url):
        parts = urlsplit(url).path.split("/")
        start, end = int(parts[-2]), int(parts[-1])
        rows = [{"RCP_SEQ": "1" if dup else str(i), "RCP_NM": f"메뉴{i}"} for i in range(start, min(end, total) + 1)]
        return 200, json.dumps({"COOKRCP01": {"RESULT": {"CODE": code, "MSG": ""}, "total_count": str(total), "row": rows}})
    return fetch


def test_collect_recipes_pages_and_meta():
    out = collect_recipes(KEY, fetch=_recipe_api(1156), **NOSLEEP)
    assert out["meta"]["item_count"] == 1156 and len({r["RCP_SEQ"] for r in out["items"]}) == 1156
    assert KEY not in json.dumps(out, ensure_ascii=False)


def test_collect_recipes_rejects_duplicates_and_fatal_codes():
    with pytest.raises(CollectError, match="중복"):
        collect_recipes(KEY, fetch=_recipe_api(5, dup=True), **NOSLEEP)
    with pytest.raises(CollectError, match="INFO-100") as e:
        collect_recipes(KEY, fetch=_recipe_api(5, code="INFO-100"), **NOSLEEP)
    assert "SECRET" not in str(e.value) and "abc" not in str(e.value)


# --- 복지 -----------------------------------------------------------------
def _welfare_api(total, *, gateway=None, mismatch=False, ids=None):
    ids = ids or [f"WLF{i:08d}" for i in range(1, total + 1)]

    def fetch(url):
        u = urlsplit(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if gateway:
            return 200, ("<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</errMsg>"
                         f"<returnReasonCode>{gateway}</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>")
        if "detail" in u.path.lower():
            sid = "WLF99999999" if mismatch else q["servId"]
            return 200, (f"<wantedDtl><resultCode>0</resultCode><servId>{sid}</servId><servNm>이름</servNm>"
                         "<sprtTrgtCn>65세 이상</sprtTrgtCn><inqplCtadrList><servSeDetailNm>문의</servSeDetailNm>"
                         "</inqplCtadrList></wantedDtl>")
        assert q["lifeArray"] == "006"
        page, size = int(q["pageNo"]), int(q["numOfRows"])
        chunk = ids[(page - 1) * size: page * size]
        body = "".join(f"<servList><servId>{i}</servId><servNm>서비스 {i}</servNm><ctpvNm>경상북도</ctpvNm></servList>"
                       for i in chunk)
        return 200, f"<wantedList><resultCode>0</resultCode><totalCount>{total}</totalCount>{body}</wantedList>"
    return fetch


@pytest.mark.parametrize("kind", ["central", "local"])
def test_collect_welfare_list_and_detail(kind):
    out = collect_welfare(kind, KEY, fetch=_welfare_api(7), page_size=3, **NOSLEEP)
    assert out["meta"]["item_count"] == 7 and out["meta"]["params"]["lifeArray"] == "006"
    item = out["items"][0]
    assert item["list"]["ctpvNm"] == "경상북도"
    assert item["detail"]["sprtTrgtCn"] == "65세 이상" and "<inqplCtadrList>" in item["detail_xml"]  # 원문 XML 보존
    assert "inqplCtadrList" not in item["detail"]  # 목록형 요소는 평탄화하지 않음


def test_collect_welfare_errors():
    with pytest.raises(CollectError, match="게이트웨이 30"):
        collect_welfare("local", KEY, fetch=_welfare_api(3, gateway="30"), **NOSLEEP)
    with pytest.raises(CollectError, match="상세 ID 불일치"):
        collect_welfare("local", KEY, fetch=_welfare_api(2, mismatch=True), **NOSLEEP)
    with pytest.raises(CollectError, match="중복"):
        collect_welfare("central", KEY, fetch=_welfare_api(2, ids=["WLF00000001", "WLF00000001"]), details=False,
                        **NOSLEEP)
    with pytest.raises(CollectError, match="비어"):
        collect_welfare("central", "", **NOSLEEP)
