"""판본 스냅샷 저장소.

구조 (소스마다)
  <latest>                         최신 정상본. 다른 단계(정제·매핑·보고서)는 이 파일만 읽는다.
  <latest>.bak                     게시·되돌리기 도중에만 잠깐 있는 이전 최신본 백업
  <latest 폴더>/snapshots/<소스>/<판본ID>.json   게시된 판본들
  <latest 폴더>/snapshots/<소스>/current.json    현재 판본 포인터

원칙
- 게시의 커밋 지점은 포인터(current.json) 기록이다. 포인터가 가리키는 판본과 최신본 내용은 항상 같아야 한다.
  1) 새 판본 파일 저장 → 2) 이전 최신본 백업 → 3) 최신본 교체 → 4) 포인터 기록(커밋) → 5) 백업 삭제·오래된 판본 정리
  4) 전에 실패하면 최신본을 백업으로 되돌리고 새 판본 파일을 지운 뒤 예외를 그대로 올린다(이전 판본 유지).
  5) 의 실패는 이미 커밋된 게시를 무르지 않고 경고(warnings)로만 남긴다.
- 파일 하나를 쓸 때는 임시 파일에 다 쓴 뒤 이름 바꾸기로 교체한다(중간 실패 시 기존 파일 유지).
- 되돌리기(rollback)도 같은 커밋 순서로 남아 있는 판본을 최신본으로 다시 게시한다.
- 복구 중에 또 실패해도 다음 실행의 repair()가 포인터 기준으로 최신본을 다시 맞춘다.
- 오래된 판본은 keep 개만 남기고 지운다. 현재 판본은 지우지 않는다.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

POINTER = "current.json"


class SnapshotError(OSError):
    """게시·되돌리기 실패. 이전 판본 유지 여부를 메시지에 적는다."""


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _atomic_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    shutil.copyfile(src, tmp)
    tmp.replace(dst)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot_id(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")


class SnapshotStore:
    def __init__(self, name: str, latest: Path, keep: int = 3):
        self.name, self.latest, self.keep = name, latest, max(1, keep)
        self.dir = latest.parent / "snapshots" / name
        self.backup = latest.with_suffix(latest.suffix + ".bak")
        self.warnings: list[str] = []   # 마지막 게시·되돌리기에서 커밋 뒤에 난 문제

    # --- 조회 -------------------------------------------------------------
    def pointer(self) -> dict | None:
        p = self.dir / POINTER
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None

    def ids(self) -> list[str]:
        return sorted(p.stem for p in self.dir.glob("*.json") if p.name != POINTER) if self.dir.is_dir() else []

    def load_latest(self) -> dict | None:
        """최신 정상본. 스냅샷 도입 전에 만든 최신본 파일도 그대로 읽는다."""
        return json.loads(self.latest.read_text(encoding="utf-8")) if self.latest.is_file() else None

    # --- 게시 -------------------------------------------------------------
    def _pointer_for(self, sid: str, data: bytes, payload: dict, **extra) -> dict:
        return {"source": self.name, "snapshot_id": sid, "file": f"{sid}.json",
                "sha256": hashlib.sha256(data).hexdigest(), "item_count": len(payload.get("items") or []),
                "fetched_at": (payload.get("meta") or {}).get("fetched_at"),
                "published_at": datetime.now(UTC).isoformat(timespec="seconds"), **extra}

    def _commit(self, data: bytes, pointer: dict) -> None:
        """최신본 교체와 포인터 기록을 한 단위로 처리한다. 포인터 기록이 커밋 지점."""
        had_latest = self.latest.is_file()
        if had_latest:
            _atomic_copy(self.latest, self.backup)
        try:
            _atomic_write_bytes(self.latest, data)
            _atomic_write_bytes(self.dir / POINTER,
                                (json.dumps(pointer, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
        except BaseException as e:
            try:
                if had_latest:
                    self.backup.replace(self.latest)
                else:
                    self.latest.unlink(missing_ok=True)
            except OSError as restore_error:
                raise SnapshotError(
                    f"{self.name}: 게시 실패 후 최신본 복구도 실패({restore_error}). "
                    "다음 실행 때 포인터 기준으로 다시 맞춥니다.") from e
            raise
        try:
            self.backup.unlink(missing_ok=True)
        except OSError as e:
            self.warnings.append(f"이전 최신본 백업 삭제 실패(다음 실행 때 정리): {e}")

    def publish(self, payload: dict, sid: str | None = None) -> dict:
        self.warnings = []
        sid = sid or snapshot_id()
        while (self.dir / f"{sid}.json").exists():  # 같은 초에 두 번 게시
            sid += "_1"
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        snap = self.dir / f"{sid}.json"
        _atomic_write_bytes(snap, data)
        pointer = self._pointer_for(sid, data, payload)
        try:
            self._commit(data, pointer)
        except BaseException:
            with contextlib.suppress(OSError):  # 커밋되지 않은 판본은 남기지 않는다
                snap.unlink(missing_ok=True)
            raise
        try:
            self.prune(current=sid)
        except OSError as e:  # 커밋은 끝났으므로 게시를 무르지 않는다
            self.warnings.append(f"오래된 판본 정리 실패(다음 게시 때 다시 정리): {e}")
        return pointer

    def prune(self, current: str | None = None) -> list[str]:
        ids = self.ids()
        removable = [i for i in ids if i != current]
        drop = removable[: max(0, len(ids) - self.keep)]
        for i in drop:
            (self.dir / f"{i}.json").unlink(missing_ok=True)
        return drop

    def rollback(self, sid: str) -> dict:
        self.warnings = []
        snap = self.dir / f"{sid}.json"
        if not snap.is_file():
            raise FileNotFoundError(f"{self.name} 판본 {sid} 이 없습니다. 남은 판본: {', '.join(self.ids()) or '없음'}")
        data = snap.read_bytes()
        pointer = self._pointer_for(sid, data, json.loads(data), rollback=True)
        self._commit(data, pointer)
        return pointer

    # --- 점검·복구 ---------------------------------------------------------
    def repair(self) -> str | None:
        """최신본을 포인터가 가리키는 판본과 같게 맞춘다. 고친 것이 있으면 설명을, 없으면 None."""
        notes = []
        p = self.pointer()
        snap = self.dir / p["file"] if p else None
        if p and snap.is_file():
            if not self.latest.is_file() or _sha256_file(self.latest) != p["sha256"]:
                _atomic_copy(snap, self.latest)
                notes.append(f"최신본이 현재 판본 {p['snapshot_id']}과 달라 판본 파일로 다시 맞춤")
        elif not p and self.backup.is_file():
            # 포인터가 없는데 백업이 남았다 = 첫 게시가 커밋 전에 실패하고 복구도 못 한 경우 → 백업이 마지막 정상본
            self.backup.replace(self.latest)
            notes.append("첫 게시가 끝나지 않아 게시 전 최신본(백업)으로 되돌림")
        if self.backup.is_file():
            self.backup.unlink()
            notes.append("남은 이전 최신본 백업 삭제")
        return "; ".join(notes) or None
