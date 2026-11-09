import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree as ET

import pytest
from agetech_data.welfare import client
from agetech_data.welfare.central_snapshot import normalize_item


def xml_node(tag, values):
    root = ET.Element(tag)
    for key, value in values.items():
        ET.SubElement(root, key).text = value
    return ET.tostring(root, encoding="unicode")


def item(source_id="WLF1", count="1"):
    listing = xml_node(
        "servList",
        {
            "servId": source_id,
            "servNm": "복지 사업",
            "inqNum": count,
            "servDtlLink": f"https://www.bokjiro.go.kr/ssis?wlfareInfoId={source_id}",
        },
    )
    detail = xml_node(
        "wantedDtl",
        {
            "servId": source_id,
            "servNm": "복지 사업",
            "resultCode": "0",
            "sprtCycNm": "수시",
            "tgtrDtlCn": "만 65세 이상",
            "alwServCn": "지원 내용",
            "crtrYr": "2026",
        },
    )
    return {
        "service_id": source_id,
        "list_xml": listing,
        "detail_xml": detail,
        "checked_at": "2026-01-01T00:00:00+00:00",
    }


class FakeAPI:
    def __init__(self, fail_id=None):
        self.fail_id, self.detail_calls = fail_id, []

    def __call__(self, url):
        query = parse_qs(urlsplit(url).query)
        if "NationalWelfarelist" in url:
            root = ET.Element("wantedList")
            ET.SubElement(root, "resultCode").text = "0"
            ET.SubElement(root, "totalCount").text = "3"
            for key in ("WLF1", "WLF2", "WLF3"):
                root.append(ET.fromstring(item(key)["list_xml"]))
            return 200, ET.tostring(root, encoding="unicode")
        key = query["servId"][0]
        self.detail_calls.append(key)
        return (503, "") if key == self.fail_id else (200, item(key)["detail_xml"])


def test_full_collection_preserves_repeated_application_sections(tmp_path):
    api = FakeAPI()
    result = client.collect(
        "secret",
        tmp_path / "checkpoint.json",
        fetch=api,
        sleep=lambda _: None,
        log=lambda _: None,
    )
    assert result["meta"]["complete"] is True
    assert result["meta"]["item_count"] == 3
    assert len(api.detail_calls) == 3
    assert "secret" not in json.dumps(result)
    first = result["items"][0]
    first["detail_xml"] = first["detail_xml"].replace(
        "</wantedDtl>",
        "<applmetList><servSeDetailLink>방문</servSeDetailLink></applmetList>"
        "<applmetList><servSeDetailLink>상담</servSeDetailLink></applmetList></wantedDtl>",
    )
    normalized = normalize_item(first, datetime.now(UTC))
    assert len(normalized["application"]) == 2
    assert normalized["application_status"] == "unknown"


def test_resume_failed_detail_without_repeating_successes(tmp_path):
    path = tmp_path / "checkpoint.json"
    with pytest.raises(client.CollectError):
        client.collect(
            "key",
            path,
            fetch=FakeAPI(fail_id="WLF3"),
            sleep=lambda _: None,
            log=lambda _: None,
        )
    assert len(json.loads(path.read_text(encoding="utf-8"))["items"]) == 2
    api = FakeAPI()
    result = client.collect(
        "key", path, fetch=api, sleep=lambda _: None, log=lambda _: None
    )
    assert result["meta"]["complete"]
    assert api.detail_calls == ["WLF3"]


def test_rate_limit_uses_longer_backoff_and_does_not_expose_key():
    waits = []
    with pytest.raises(client.CollectError) as error:
        client.request_xml(
            "SECRET", "detail", {}, fetch=lambda _: (429, ""), sleep=waits.append
        )
    assert waits == [30, 60, 60, 60]
    assert "SECRET" not in str(error.value)


def test_view_count_does_not_create_semantic_revision():
    first, second = item(count="1"), item(count="999")
    left = normalize_item(first, datetime.now(UTC))
    right = normalize_item(second, datetime.now(UTC))
    assert left["raw"] != right["raw"]
    assert left["fingerprint"] == right["fingerprint"]
    assert left["application_status"] == "unknown"


@pytest.mark.parametrize(
    "field,value",
    [
        ("service_id", "OTHER"),
        ("detail_xml", "<invalid>"),
        ("checked_at", "2026-01-01"),
    ],
)
def test_invalid_source_rejected(field, value):
    row = item()
    row[field] = value
    with pytest.raises((ValueError, ET.ParseError)):
        normalize_item(row, datetime.now(UTC))


def test_failure_keeps_previous_complete_file(tmp_path, monkeypatch):
    output = tmp_path / "snapshot.json"
    output.write_text("previous")
    monkeypatch.setattr(client, "load_secret", lambda _: "")
    assert client.main(["--output", str(output)]) == 1
    assert output.read_text() == "previous"


def test_daily_quota_stops_without_retry():
    calls = []

    def fetch(url):
        calls.append(url)
        return (
            429,
            "<OpenAPI_ServiceResponse><cmmMsgHeader><returnReasonCode>22</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>",
        )

    with pytest.raises(client.CollectError, match="code 22"):
        client.request_xml("SECRET", "detail", {}, fetch=fetch, sleep=lambda _: None)
    assert len(calls) == 1


def test_explicit_partial_collection_retains_catalog_and_marks_pending(tmp_path):
    api = FakeAPI(fail_id="WLF2")
    result = client.collect(
        "key",
        tmp_path / "cp.json",
        fetch=api,
        sleep=lambda _: None,
        log=lambda _: None,
        allow_partial_details=True,
    )
    assert result["meta"]["catalog_complete"] is True
    assert result["meta"]["complete"] is False
    assert result["meta"]["detail_count"] == 1
    assert len(result["items"]) == 3
    assert "WLF3" not in api.detail_calls
    pending = normalize_item(result["items"][1], datetime.now(UTC))
    assert pending["detail_state"] == "pending" and pending["quality_status"] == "hold"
