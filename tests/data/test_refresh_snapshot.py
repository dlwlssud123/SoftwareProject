import json

import pytest

from agetech_data.refresh.changes import diff, drop_guard
from agetech_data.refresh.snapshot import SnapshotStore


def _payload(ids, tag="v1"):
    return {"meta": {"fetched_at": "2026-11-01T00:00:00+00:00"}, "items": [{"id": i, "v": tag} for i in ids]}


# --- 스냅샷 ---------------------------------------------------------------
def test_publish_prune_and_rollback(tmp_path):
    latest = tmp_path / "raw" / "x.json"
    store = SnapshotStore("x", latest, keep=2)
    for n, sid in enumerate(["20261101T000000Z", "20261102T000000Z", "20261103T000000Z"]):
        store.publish(_payload(range(n + 1)), sid)
    assert store.ids() == ["20261102T000000Z", "20261103T000000Z"]  # keep=2
    assert store.pointer()["snapshot_id"] == "20261103T000000Z" and store.pointer()["item_count"] == 3
    assert len(json.loads(latest.read_text(encoding="utf-8"))["items"]) == 3
    store.rollback("20261102T000000Z")
    assert len(store.load_latest()["items"]) == 2 and store.pointer()["rollback"] is True
    with pytest.raises(FileNotFoundError):
        store.rollback("20261101T000000Z")


def test_same_second_publish_does_not_overwrite(tmp_path):
    store = SnapshotStore("x", tmp_path / "x.json", keep=5)
    store.publish(_payload([1]), "S")
    store.publish(_payload([1, 2]), "S")
    assert store.ids() == ["S", "S_1"]


# --- 변경 감지 ------------------------------------------------------------
def test_diff_and_drop_guard():
    old = [{"id": 1, "v": "a"}, {"id": 2, "v": "a"}, {"id": 3, "v": "a"}]
    new = [{"id": 2, "v": "a"}, {"id": 3, "v": "b"}, {"id": 4, "v": "a"}]
    d = diff(old, new, lambda it: str(it["id"]))
    assert (d["added"], d["removed"], d["changed"], d["unchanged"]) == (1, 1, 1, 1)
    assert d["samples"]["changed"] == ["3"] and d["first_snapshot"] is False
    assert diff(None, new, lambda it: str(it["id"]))["added"] == 3
    assert drop_guard(100, 79, 0.8) and drop_guard(100, 80, 0.8) is None and drop_guard(None, 0, 0.8) is None
