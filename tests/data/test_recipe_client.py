import json
from urllib.error import URLError

import pytest
from agetech_data.recipes import client
from agetech_data.recipes.validate import load_rows
from agetech_data.textutil import sha256_json


def response(ids, total=3):
    return 200, json.dumps(
        {
            "COOKRCP01": {
                "RESULT": {"CODE": "INFO-000"},
                "total_count": str(total),
                "row": [{"RCP_SEQ": str(value)} for value in ids],
            }
        }
    )


def test_complete_paging_and_loader(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url.rsplit("/", 2)[-2:])
        return response([1, 2] if len(calls) == 1 else [3])

    data = client.collect("test-key", page_size=2, fetch=fetch, log=lambda _: None)
    assert calls == [["1", "2"], ["3", "3"]]
    assert data["meta"]["complete"] is True
    assert data["meta"]["items_sha256"] == sha256_json(data["items"])
    assert "test-key" not in json.dumps(data)
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(data))
    assert load_rows(path) == data["items"]


@pytest.mark.parametrize(
    "second", [response([2]), response([3], total=4), response([])]
)
def test_reject_inconsistent_pages(second):
    responses = iter([response([1, 2]), second])
    with pytest.raises(client.CollectError):
        client.collect(
            "key", page_size=2, fetch=lambda _: next(responses), log=lambda _: None
        )


def test_network_error_is_retried_without_leaking_key():
    calls = []

    def fetch(url):
        calls.append(url)
        raise URLError(url)

    with pytest.raises(client.CollectError) as error:
        client.collect("secret-key", fetch=fetch, sleep=lambda _: None)
    assert len(calls) == 3
    assert "secret-key" not in str(error.value)


def test_failure_preserves_previous_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "snapshot.json"
    path.write_text("previous")
    monkeypatch.setattr(client, "load_secret", lambda _: "key")

    def fail(*args):
        raise client.CollectError("unavailable")

    monkeypatch.setattr(client, "collect", fail)
    assert client.main(["--output", str(path)]) == 1
    assert path.read_text() == "previous"
