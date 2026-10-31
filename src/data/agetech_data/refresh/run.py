"""공공데이터 갱신 실행기.

    uv run python -m agetech_data.refresh                         # 전체 소스 갱신
    uv run python -m agetech_data.refresh --source recipes welfare_local
    uv run python -m agetech_data.refresh --list                  # 소스·현재 판본·상태
    uv run python -m agetech_data.refresh --rollback welfare_local 20261101T031500Z

소스마다: 수집(재시도 포함) → 검증(건수·ID 중복·필수 필드, 급감 방지) → 판본 게시 → 변경 감지.
하나라도 실패하면 그 소스는 마지막 정상 판본을 그대로 두고, 종료 코드 1 을 돌려준다(다른 소스는 계속 진행).
상태는 data/processed/refresh_status.json, 실행 기록은 refresh_log.jsonl 에 남긴다 (키는 남기지 않음).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from agetech_data import paths
from agetech_data.net import CollectError, http_fetch
from agetech_data.refresh.changes import diff, drop_guard
from agetech_data.refresh.snapshot import SnapshotStore, snapshot_id
from agetech_data.refresh.sources import SOURCES, Source
from agetech_data.settings import load_secret_any, redact

STATUS_SCHEMA = 1
DEFAULT_KEEP = 3
DEFAULT_MIN_RATIO = 0.8


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def load_status(path: Path) -> dict:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"schema_version": STATUS_SCHEMA, "sources": {}}


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def refresh_source(src: Source, *, fetch, sleep, log, keep: int, min_ratio: float,
                   now: Callable[[], datetime], secret_loader, options: dict | None = None) -> dict:
    started = now()
    store = SnapshotStore(src.name, src.latest, keep)
    key = secret_loader(*src.key_names)
    result = {"source": src.name, "label": src.label, "attempt_at": _iso(started)}
    try:
        if not key:
            raise CollectError(f"{' 또는 '.join(src.key_names)} 가 비어 있습니다. 레포 루트 .env 를 확인하세요.")
        previous = store.load_latest()
        prev_items = previous.get("items") if previous else None
        payload = src.collect(key, fetch=fetch, sleep=sleep, log=log, **(options or {}))
        items = payload.get("items") or []
        guard = drop_guard(len(prev_items) if prev_items is not None else None, len(items), min_ratio)
        if guard:
            raise CollectError(guard)
        changes = diff(prev_items, items, src.id_of, content_of=src.content_of)
        quality = src.quality(items) if src.quality else None
        pointer = store.publish(payload, snapshot_id(started))
        result.update(status="ok", item_count=len(items), previous_count=len(prev_items) if prev_items is not None else None,
                      changes=changes, quality=quality, snapshot=pointer, error=None,
                      notes=(payload.get("meta") or {}).get("details"))
    except Exception as e:  # noqa: BLE001 — 한 소스의 실패가 다른 소스 갱신을 막지 않게 한다
        expected = isinstance(e, CollectError) or type(e).__name__ == "CollectError"
        msg = str(e) if expected else f"{type(e).__name__}: {e}"
        result.update(status="failed", error=redact(msg, key))
    result["duration_sec"] = round((now() - started).total_seconds(), 1)
    return result


def merge_status(status: dict, result: dict) -> dict:
    """소스별 상태 갱신. 실패해도 마지막 정상 판본 정보(last_success_at·serving)는 유지한다."""
    prev = status["sources"].get(result["source"], {})
    entry = {**prev, "label": result["label"], "last_attempt_at": result["attempt_at"],
             "last_status": result["status"], "last_error": result["error"],
             "last_duration_sec": result["duration_sec"]}
    if result["status"] == "ok":
        entry.update(last_success_at=result["attempt_at"], consecutive_failures=0,
                     serving=result["snapshot"], item_count=result["item_count"],
                     previous_count=result["previous_count"], changes=result["changes"], quality=result["quality"],
                     details=result.get("notes"))
    else:
        entry["consecutive_failures"] = prev.get("consecutive_failures", 0) + 1
    status["sources"][result["source"]] = entry
    return status


def run_sources(names: list[str], *, registry: dict[str, Source] = SOURCES, fetch=http_fetch,
                sleep=time.sleep, log=print, keep: int = DEFAULT_KEEP, min_ratio: float = DEFAULT_MIN_RATIO,
                status_path: Path = paths.REFRESH_STATUS, log_path: Path = paths.REFRESH_LOG,
                now: Callable[[], datetime] = _now, secret_loader=load_secret_any,
                options: dict | None = None) -> list[dict]:
    status = load_status(status_path)
    results = []
    for name in names:
        log(f"[{name}] 갱신 시작")
        r = refresh_source(registry[name], fetch=fetch, sleep=sleep, log=log, keep=keep, min_ratio=min_ratio,
                           now=now, secret_loader=secret_loader, options=options)
        results.append(r)
        status = merge_status(status, r)
        status["updated_at"] = _iso(now())
        _write_json(status_path, status)  # 소스마다 바로 기록 (중간에 멈춰도 앞 결과는 남음)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({k: r.get(k) for k in ("source", "attempt_at", "status", "item_count", "error",
                                                      "duration_sec")} | {"changes": {k: (r.get("changes") or {}).get(k)
                                                      for k in ("added", "removed", "changed")}},
                               ensure_ascii=False) + "\n")
        if r["status"] == "ok":
            c, d = r["changes"], r.get("notes")
            log(f"[{name}] 정상: {r['item_count']}건 (추가 {c['added']}, 삭제 {c['removed']}, 변경 {c['changed']}) "
                f"→ 판본 {r['snapshot']['snapshot_id']}")
            if d:
                log(f"[{name}] 상세: {d['counts']} / 이번에 받음 {d['fetched_this_run']} / 다음으로 미룸 {d['remaining']}")
        else:
            log(f"[{name}] 실패: {r['error']} → 마지막 정상 판본 유지")
    return results


def _list(registry: dict[str, Source], status_path: Path, keep: int) -> None:
    status = load_status(status_path)["sources"]
    for name, src in registry.items():
        store = SnapshotStore(name, src.latest, keep)
        p, s = store.pointer(), status.get(name, {})
        print(f"{name:16} {src.label}")
        print(f"  최신본: {src.latest.relative_to(paths.REPO_ROOT).as_posix() if src.latest.is_relative_to(paths.REPO_ROOT) else src.latest}"
              f" {'(있음)' if src.latest.is_file() else '(없음)'}")
        print(f"  현재 판본: {p['snapshot_id'] if p else '-'} / 보관 판본: {', '.join(store.ids()) or '-'}")
        print(f"  마지막 시도: {s.get('last_attempt_at', '-')} {s.get('last_status', '')} / 마지막 성공: {s.get('last_success_at', '-')}")
        if s.get("last_error"):
            print(f"  마지막 오류: {s['last_error']}")


def main(argv: list[str] | None = None, *, registry: dict[str, Source] = SOURCES,
         status_path: Path = paths.REFRESH_STATUS, log_path: Path = paths.REFRESH_LOG, **kwargs) -> int:
    ap = argparse.ArgumentParser(prog="python -m agetech_data.refresh", description="공공데이터 갱신·판본 관리")
    ap.add_argument("--source", nargs="+", choices=list(registry), help="갱신할 소스 (기본: 전체)")
    ap.add_argument("--keep", type=int, default=DEFAULT_KEEP, help="소스별로 남길 판본 수")
    ap.add_argument("--min-ratio", type=float, default=DEFAULT_MIN_RATIO, help="이전 대비 최소 건수 비율 (급감 방지)")
    ap.add_argument("--detail-budget", type=int, default=None,
                    help="복지 상세를 이번 실행에서 최대 몇 건 받을지 (기본: 일일 한도에 닿을 때까지)")
    ap.add_argument("--list", action="store_true", help="소스·현재 판본·상태 보기")
    ap.add_argument("--rollback", nargs=2, metavar=("SOURCE", "SNAPSHOT_ID"), help="남아 있는 판본으로 되돌리기")
    args = ap.parse_args(argv)

    if args.list:
        _list(registry, status_path, args.keep)
        return 0
    if args.rollback:
        name, sid = args.rollback
        if name not in registry:
            ap.error(f"알 수 없는 소스: {name}")
        try:
            pointer = SnapshotStore(name, registry[name].latest, args.keep).rollback(sid)
        except FileNotFoundError as e:
            print(str(e), file=sys.stderr)
            return 1
        status = load_status(status_path)
        entry = status["sources"].setdefault(name, {"label": registry[name].label})
        entry.update(serving=pointer, rolled_back_at=pointer["published_at"])
        _write_json(status_path, status)
        print(f"{name}: 판본 {sid} 으로 되돌림 → 최신본 교체")
        return 0
    options = {"detail_budget": args.detail_budget} if args.detail_budget is not None else None
    results = run_sources(args.source or list(registry), registry=registry, keep=args.keep,
                          min_ratio=args.min_ratio, status_path=status_path, log_path=log_path,
                          options=options, **kwargs)
    failed = [r["source"] for r in results if r["status"] != "ok"]
    print(f"완료: 정상 {len(results) - len(failed)} / 실패 {len(failed)}" + (f" ({', '.join(failed)})" if failed else ""))
    return 1 if failed else 0
