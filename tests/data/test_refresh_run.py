import json
from datetime import UTC, datetime, timedelta

from agetech_data.net import CollectError
from agetech_data.refresh.run import main, run_sources
from agetech_data.refresh.snapshot import SnapshotStore
from agetech_data.refresh.sources import Source


def _payload(ids, tag="v1"):
    return {"meta": {"fetched_at": "2026-11-01T00:00:00+00:00"}, "items": [{"id": i, "v": tag} for i in ids]}


# --- 실행기 ---------------------------------------------------------------
class Clock:
    def __init__(self):
        self.t = datetime(2026, 11, 1, tzinfo=UTC)

    def __call__(self):
        self.t += timedelta(seconds=1)
        return self.t


def _registry(tmp_path, behaviors):
    """behaviors[name] = 호출마다 꺼내 쓰는 결과 목록 (payload 또는 예외)."""
    def make(name):
        def collect(key, *, fetch, sleep, log):
            nxt = behaviors[name].pop(0)
            if isinstance(nxt, Exception):
                raise nxt
            return nxt
        return Source(name, f"시험 {name}", tmp_path / "raw" / f"{name}.json", ("K",), "id", collect)
    return {n: make(n) for n in behaviors}


def _run(tmp_path, registry, names=None, **kw):
    return run_sources(names or list(registry), registry=registry, fetch=None, sleep=lambda s: None,
                       log=lambda m: None, status_path=tmp_path / "status.json", log_path=tmp_path / "log.jsonl",
                       now=kw.pop("now", Clock()), secret_loader=kw.pop("secret_loader", lambda *n: "k"), **kw)


def test_failure_keeps_last_good_and_other_sources_continue(tmp_path):
    reg = _registry(tmp_path, {
        "a": [_payload([1, 2, 3]), CollectError("HTTP 500 (5회 시도)")],
        "b": [_payload([1]), _payload([1, 2], "v2")],
    })
    clock = Clock()
    _run(tmp_path, reg, now=clock)
    results = _run(tmp_path, reg, now=clock)
    assert [r["status"] for r in results] == ["failed", "ok"]
    # a: 실패했지만 최신본·현재 판본·마지막 성공 시각 유지
    assert len(json.loads((tmp_path / "raw" / "a.json").read_text(encoding="utf-8"))["items"]) == 3
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))["sources"]
    assert status["a"]["last_status"] == "failed" and status["a"]["consecutive_failures"] == 1
    assert status["a"]["last_success_at"] < status["a"]["last_attempt_at"]
    assert status["a"]["serving"]["item_count"] == 3
    # b: 두 번째 판본, 변경 감지
    assert status["b"]["changes"]["added"] == 1 and status["b"]["changes"]["changed"] == 1
    assert len((tmp_path / "log.jsonl").read_text(encoding="utf-8").splitlines()) == 4


def test_drop_guard_blocks_publish(tmp_path):
    reg = _registry(tmp_path, {"a": [_payload(range(10)), _payload(range(5))]})
    _run(tmp_path, reg)
    [r] = _run(tmp_path, reg)
    assert r["status"] == "failed" and "건수 급감" in r["error"]
    assert len(json.loads((tmp_path / "raw" / "a.json").read_text(encoding="utf-8"))["items"]) == 10


def test_missing_key_and_secret_redaction(tmp_path):
    reg = _registry(tmp_path, {"a": [_payload([1])], "b": [RuntimeError("url?serviceKey=TOPSECRET 실패")]})
    results = _run(tmp_path, reg, secret_loader=lambda *names: "TOPSECRET")
    assert results[0]["status"] == "ok"
    assert results[1]["status"] == "failed" and "TOPSECRET" not in results[1]["error"]
    assert "TOPSECRET" not in (tmp_path / "status.json").read_text(encoding="utf-8")
    reg2 = _registry(tmp_path / "2", {"a": [_payload([1])]})
    [r] = _run(tmp_path / "2", reg2, secret_loader=lambda *n: "")
    assert r["status"] == "failed" and "비어 있습니다" in r["error"]


def test_cli_exit_codes_list_and_rollback(tmp_path, capsys):
    reg = _registry(tmp_path, {"a": [_payload([1, 2]), _payload([1, 2, 3])], "b": [CollectError("x")]})
    common = {"registry": reg, "status_path": tmp_path / "status.json", "log_path": tmp_path / "log.jsonl",
              "sleep": lambda s: None, "log": lambda m: None, "secret_loader": lambda *n: "k"}
    clock = Clock()
    assert main([], now=clock, **common) == 1               # b 실패 → 종료 코드 1
    assert main(["--source", "a"], now=clock, **common) == 0
    store = SnapshotStore("a", reg["a"].latest)
    first = store.ids()[0]
    assert main(["--rollback", "a", first], **{k: common[k] for k in ("registry", "status_path", "log_path")}) == 0
    assert len(store.load_latest()["items"]) == 2
    assert main(["--list"], **{k: common[k] for k in ("registry", "status_path", "log_path")}) == 0
    assert "현재 판본" in capsys.readouterr().out


# --- 게시 실패 시 최신본·포인터·상태 일관성 (PR #8 리뷰) -------------------------
def _fail_pointer_writes(monkeypatch):
    from agetech_data.refresh import snapshot as snap_mod
    real = snap_mod._atomic_write_bytes

    def fake(path, data):
        if path.name == "current.json":
            raise OSError("current.json 쓰기 실패(시험)")
        return real(path, data)
    monkeypatch.setattr(snap_mod, "_atomic_write_bytes", fake)


def _status(tmp_path, name):
    return json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))["sources"][name]


def test_pointer_failure_marks_failed_and_keeps_files_and_status_consistent(tmp_path, monkeypatch):
    reg = _registry(tmp_path, {"a": [_payload([1, 2, 3]), _payload([1, 2, 3, 4])]})
    clock = Clock()
    _run(tmp_path, reg, now=clock)
    store = SnapshotStore("a", reg["a"].latest)
    good = store.pointer()
    _fail_pointer_writes(monkeypatch)
    [r] = _run(tmp_path, reg, now=clock)
    assert r["status"] == "failed" and "current.json" in r["error"]
    assert len(store.load_latest()["items"]) == 3 and store.pointer() == good and store.ids() == [good["snapshot_id"]]
    s = _status(tmp_path, "a")
    assert s["serving"] == good and s["last_status"] == "failed" and s["consecutive_failures"] == 1


def test_prune_failure_is_ok_with_warning_and_status_follows_new_snapshot(tmp_path, monkeypatch):
    reg = _registry(tmp_path, {"a": [_payload([1]), _payload([1, 2])]})
    clock = Clock()
    _run(tmp_path, reg, now=clock, keep=1)

    def broken_prune(self, current=None):
        raise OSError("삭제 권한 없음(시험)")
    monkeypatch.setattr(SnapshotStore, "prune", broken_prune)
    [r] = _run(tmp_path, reg, now=clock, keep=1)
    store = SnapshotStore("a", reg["a"].latest, keep=1)
    assert r["status"] == "ok" and any("정리 실패" in w for w in r["warnings"])
    s = _status(tmp_path, "a")
    assert s["serving"] == store.pointer() and s["serving"]["item_count"] == 2 and len(store.load_latest()["items"]) == 2
    assert s["last_warnings"] == r["warnings"]


def test_next_run_repairs_latest_and_reconciles_status(tmp_path):
    """지난 실행이 게시 도중·상태 기록 전에 멈춘 경우: 다음 실행이 최신본을 포인터에 맞추고 상태도 맞춘다."""
    reg = _registry(tmp_path, {"a": [_payload([1, 2]), CollectError("HTTP 500")]})
    clock = Clock()
    _run(tmp_path, reg, now=clock)
    store = SnapshotStore("a", reg["a"].latest)
    good = store.pointer()
    reg["a"].latest.write_text(json.dumps(_payload([7, 8, 9])), encoding="utf-8")   # 최신본만 바뀐 채 멈춤
    st = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    st["sources"]["a"]["serving"] = {"snapshot_id": "ghost"}                          # 상태도 어긋남
    (tmp_path / "status.json").write_text(json.dumps(st), encoding="utf-8")
    [r] = _run(tmp_path, reg, now=clock)
    assert r["status"] == "failed" and "다시 맞춤" in r["repaired"]
    assert store.load_latest() == _payload([1, 2])
    s = _status(tmp_path, "a")
    assert s["serving"] == good and "다시 맞춤" in s["last_repair"]["note"]


def test_cli_rollback_failure_keeps_current(tmp_path, monkeypatch, capsys):
    reg = _registry(tmp_path, {"a": [_payload([1, 2]), _payload([1, 2, 3])]})
    common = {"registry": reg, "status_path": tmp_path / "status.json", "log_path": tmp_path / "log.jsonl"}
    run_kw = {"sleep": lambda s: None, "log": lambda m: None, "secret_loader": lambda *n: "k"}
    clock = Clock()
    main([], now=clock, **common, **run_kw)
    main([], now=clock, **common, **run_kw)
    store = SnapshotStore("a", reg["a"].latest)
    current, first = store.pointer(), store.ids()[0]
    _fail_pointer_writes(monkeypatch)
    assert main(["--rollback", "a", first], **common) == 1
    assert "되돌리기 실패" in capsys.readouterr().err
    assert store.pointer() == current and len(store.load_latest()["items"]) == 3
    assert _status(tmp_path, "a")["serving"] == current
