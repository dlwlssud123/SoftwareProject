import json
from pathlib import Path

import pytest

from agetech_data.refresh import snapshot as snap_mod
from agetech_data.refresh.changes import diff, drop_guard
from agetech_data.refresh.snapshot import SnapshotError, SnapshotStore


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


# --- 게시·되돌리기 실패 시 일관성 (PR #8 리뷰) -------------------------------
def fail_writes(monkeypatch, file_name):
    """이름이 file_name 인 파일 쓰기만 실패시킨다 (예: 포인터 current.json, 최신본 x.json)."""
    real = snap_mod._atomic_write_bytes

    def fake(path, data):
        if path.name == file_name:
            raise OSError(f"{file_name} 쓰기 실패(시험)")
        return real(path, data)
    monkeypatch.setattr(snap_mod, "_atomic_write_bytes", fake)


def _state(store):
    """(최신본 건수, 포인터 판본, 보관 판본, 백업 남음)"""
    latest = store.load_latest()
    return (len(latest["items"]) if latest else None, (store.pointer() or {}).get("snapshot_id"),
            store.ids(), store.backup.exists())


def _consistent(store):
    p = store.pointer()
    return p is not None and snap_mod._sha256_file(store.latest) == p["sha256"]


def test_pointer_write_failure_keeps_previous_snapshot(tmp_path, monkeypatch):
    store = SnapshotStore("x", tmp_path / "x.json", keep=3)
    store.publish(_payload([1]), "OLD")
    fail_writes(monkeypatch, "current.json")
    with pytest.raises(OSError, match="current.json"):
        store.publish(_payload([1, 2]), "NEW")
    # 최신본·포인터 모두 이전 판본, 커밋되지 않은 NEW 판본 파일과 백업은 남지 않음
    assert _state(store) == (1, "OLD", ["OLD"], False) and _consistent(store)
    assert store.repair() is None


def test_latest_write_failure_keeps_previous_snapshot(tmp_path, monkeypatch):
    store = SnapshotStore("x", tmp_path / "x.json", keep=3)
    store.publish(_payload([1]), "OLD")
    fail_writes(monkeypatch, "x.json")
    with pytest.raises(OSError):
        store.publish(_payload([1, 2]), "NEW")
    assert _state(store) == (1, "OLD", ["OLD"], False) and _consistent(store)


def test_first_publish_failure_leaves_nothing_or_legacy_latest(tmp_path, monkeypatch):
    fail_writes(monkeypatch, "current.json")
    empty = SnapshotStore("x", tmp_path / "a" / "x.json")
    with pytest.raises(OSError):
        empty.publish(_payload([1]), "NEW")
    assert _state(empty) == (None, None, [], False)
    # 스냅샷 도입 전에 만든 최신본이 있으면 그대로 되돌린다
    legacy = SnapshotStore("x", tmp_path / "b" / "x.json")
    legacy.latest.parent.mkdir(parents=True)
    legacy.latest.write_text(json.dumps(_payload([9])), encoding="utf-8")
    with pytest.raises(OSError):
        legacy.publish(_payload([1]), "NEW")
    assert legacy.load_latest() == _payload([9]) and _state(legacy)[1:] == (None, [], False)


def test_prune_failure_after_commit_is_only_a_warning(tmp_path, monkeypatch):
    store = SnapshotStore("x", tmp_path / "x.json", keep=1)
    store.publish(_payload([1]), "OLD")

    def broken_prune(current=None):
        raise OSError("삭제 권한 없음(시험)")
    monkeypatch.setattr(store, "prune", broken_prune)
    pointer = store.publish(_payload([1, 2]), "NEW")       # 커밋은 끝났으므로 예외 없음
    assert pointer["snapshot_id"] == "NEW" and _state(store)[:2] == (2, "NEW") and _consistent(store)
    assert len(store.warnings) == 1 and "정리 실패" in store.warnings[0]
    monkeypatch.undo()
    store.publish(_payload([1, 2, 3]), "NEWER")             # 다음 게시 때 정리됨
    assert store.ids() == ["NEWER"] and store.warnings == []


def test_rollback_pointer_failure_keeps_current_snapshot(tmp_path, monkeypatch):
    store = SnapshotStore("x", tmp_path / "x.json", keep=3)
    store.publish(_payload([1]), "A")
    store.publish(_payload([1, 2]), "B")
    fail_writes(monkeypatch, "current.json")
    with pytest.raises(OSError):
        store.rollback("A")
    assert _state(store) == (2, "B", ["A", "B"], False) and _consistent(store)


def test_repair_after_restore_also_failed(tmp_path, monkeypatch):
    """포인터 기록 실패 뒤 최신본 복구까지 실패한 최악의 경우 → 다음 실행의 repair()가 포인터 기준으로 맞춘다."""
    store = SnapshotStore("x", tmp_path / "x.json", keep=3)
    store.publish(_payload([1]), "OLD")
    fail_writes(monkeypatch, "current.json")
    real_replace = Path.replace

    def fake_replace(self, target):
        if self == store.backup:
            raise OSError("백업 복구 실패(시험)")
        return real_replace(self, target)
    monkeypatch.setattr(Path, "replace", fake_replace)
    with pytest.raises(SnapshotError, match="복구도 실패"):
        store.publish(_payload([1, 2]), "NEW")
    monkeypatch.undo()
    assert _state(store) == (2, "OLD", ["OLD"], True) and not _consistent(store)   # 어긋난 상태
    note = store.repair()
    assert "다시 맞춤" in note and "백업 삭제" in note
    assert _state(store) == (1, "OLD", ["OLD"], False) and _consistent(store)


# --- 변경 감지 ------------------------------------------------------------
def test_diff_and_drop_guard():
    old = [{"id": 1, "v": "a"}, {"id": 2, "v": "a"}, {"id": 3, "v": "a"}]
    new = [{"id": 2, "v": "a"}, {"id": 3, "v": "b"}, {"id": 4, "v": "a"}]
    d = diff(old, new, lambda it: str(it["id"]))
    assert (d["added"], d["removed"], d["changed"], d["unchanged"]) == (1, 1, 1, 1)
    assert d["samples"]["changed"] == ["3"] and d["first_snapshot"] is False
    assert diff(None, new, lambda it: str(it["id"]))["added"] == 3
    assert drop_guard(100, 79, 0.8) and drop_guard(100, 80, 0.8) is None and drop_guard(None, 0, 0.8) is None
