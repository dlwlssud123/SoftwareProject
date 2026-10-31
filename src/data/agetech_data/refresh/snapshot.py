"""판본 스냅샷 저장소.

구조 (소스마다)
  <latest>                         최신 정상본. 다른 단계(정제·매핑·보고서)는 이 파일만 읽는다.
  <latest 폴더>/snapshots/<소스>/<판본ID>.json   게시된 판본들
  <latest 폴더>/snapshots/<소스>/current.json    현재 판본 포인터

원칙
- 새 판본은 임시 파일에 다 쓴 뒤 이름 바꾸기로 교체한다(중간 실패 시 기존 파일 유지).
- 오래된 판본은 keep 개만 남기고 지운다. 현재 판본은 지우지 않는다.
- 되돌리기(rollback)는 남아 있는 판본을 최신본으로 다시 게시한다.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

POINTER = "current.json"


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def snapshot_id(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")


class SnapshotStore:
    def __init__(self, name: str, latest: Path, keep: int = 3):
        self.name, self.latest, self.keep = name, latest, max(1, keep)
        self.dir = latest.parent / "snapshots" / name

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
    def publish(self, payload: dict, sid: str | None = None) -> dict:
        sid = sid or snapshot_id()
        while (self.dir / f"{sid}.json").exists():  # 같은 초에 두 번 게시
            sid += "_1"
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        snap = self.dir / f"{sid}.json"
        _atomic_write_bytes(snap, data)
        _atomic_write_bytes(self.latest, data)
        meta = payload.get("meta") or {}
        pointer = {"source": self.name, "snapshot_id": sid, "file": snap.name,
                   "sha256": hashlib.sha256(data).hexdigest(), "item_count": len(payload.get("items") or []),
                   "fetched_at": meta.get("fetched_at"),
                   "published_at": datetime.now(UTC).isoformat(timespec="seconds")}
        _atomic_write_bytes(self.dir / POINTER, (json.dumps(pointer, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
        self.prune(current=sid)
        return pointer

    def prune(self, current: str | None = None) -> list[str]:
        ids = self.ids()
        removable = [i for i in ids if i != current]
        drop = removable[: max(0, len(ids) - self.keep)]
        for i in drop:
            (self.dir / f"{i}.json").unlink(missing_ok=True)
        return drop

    def rollback(self, sid: str) -> dict:
        snap = self.dir / f"{sid}.json"
        if not snap.is_file():
            raise FileNotFoundError(f"{self.name} 판본 {sid} 이 없습니다. 남은 판본: {', '.join(self.ids()) or '없음'}")
        tmp = self.latest.with_suffix(self.latest.suffix + ".tmp")
        self.latest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(snap, tmp)
        tmp.replace(self.latest)
        payload = json.loads(snap.read_text(encoding="utf-8"))
        pointer = {"source": self.name, "snapshot_id": sid, "file": snap.name,
                   "sha256": hashlib.sha256(snap.read_bytes()).hexdigest(),
                   "item_count": len(payload.get("items") or []),
                   "fetched_at": (payload.get("meta") or {}).get("fetched_at"),
                   "published_at": datetime.now(UTC).isoformat(timespec="seconds"), "rollback": True}
        _atomic_write_bytes(self.dir / POINTER, (json.dumps(pointer, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
        return pointer
