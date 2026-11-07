"""RAG 검색 인덱스 생성·갱신: 정제 결과 → 청크 → (바뀐 것만) 임베딩 → 파일 + 변경 목록.

DB 적재·판본 전환은 이진녕 담당이라, 여기서는 적재할 내용을 파일과 함수로 넘긴다.

    uv run python -m agetech_data.rag.index                 # 바뀐 청크만 임베딩
    uv run python -m agetech_data.rag.index --dry-run       # 청크·변경 건수만 (모델 안 올림)

출력(data/processed/rag/, gitignore) — 형식은 docs/data/rag_index_contract.md
    chunks.jsonl     청크(rag_chunk 한 행, embedding 칸 제외) 한 줄에 하나
    embeddings.npy   float32 (청크 수, 1024). i번째 행 = chunks.jsonl i번째 줄
    changes.json     직전 인덱스 대비 added / changed / removed chunk_id 전체 목록
    manifest.json    모델·건수·파일 sha256·변경 건수. **마지막에 쓰므로 manifest가 기준**
    embed_cache/     content_sha256 → 벡터 캐시(중간에 멈춰도 다시 이어서)
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from agetech_data import paths
from agetech_data.rag.chunks import MAX_CHARS, Chunk, build_chunks

log = logging.getLogger(__name__)
SCHEMA_VERSION = 2          # 2: index_version·sources 추가
SAVE_EVERY = 128            # 이만큼 임베딩할 때마다 캐시에 덧붙임


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _slug(model_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", model_id).strip("_")


def _atomic_write(path: Path, write) -> None:
    tmp = path.with_name(path.name + ".tmp")
    write(tmp)
    os.replace(tmp, path)


# ── 벡터 캐시 ───────────────────────────────────────────────────────────

class VectorCache:
    """content_sha256 → 벡터. 모델별 jsonl(한 줄 {sha, v: base64 float32}). 덧붙이기만 하고 끝에 정리."""

    def __init__(self, path: Path, dim: int):
        import numpy as np

        self.path, self.dim, self._np = path, dim, np
        self.vectors: dict[str, object] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                    v = np.frombuffer(base64.b64decode(row["v"]), dtype=np.float32)
                except (ValueError, KeyError):
                    continue          # 쓰다 끊긴 마지막 줄
                if v.shape == (dim,):
                    self.vectors[row["sha"]] = v

    def append(self, items: list[tuple[str, object]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            for sha, v in items:
                arr = self._np.asarray(v, dtype=self._np.float32)
                self.vectors[sha] = arr
                f.write(json.dumps({"sha": sha, "v": base64.b64encode(arr.tobytes()).decode()}) + "\n")

    def prune(self, keep: set[str]) -> None:
        """지금 청크에 없는 벡터를 지워 캐시를 다시 쓴다."""
        self.vectors = {s: v for s, v in self.vectors.items() if s in keep}

        def write(tmp: Path):
            with tmp.open("w", encoding="utf-8") as f:
                for sha, v in self.vectors.items():
                    f.write(json.dumps({"sha": sha, "v": base64.b64encode(v.tobytes()).decode()}) + "\n")
        _atomic_write(self.path, write)


# ── 인덱스 읽기·쓰기 ────────────────────────────────────────────────────

def load_index(index_dir: Path = paths.RAG_INDEX_DIR, verify: bool = True) -> tuple[dict, list[dict], object]:
    """(manifest, chunks, vectors). verify면 manifest의 sha256과 파일을 대조한다."""
    import numpy as np

    manifest = json.loads((index_dir / "manifest.json").read_text(encoding="utf-8"))
    cpath, vpath = index_dir / "chunks.jsonl", index_dir / "embeddings.npy"
    if verify:
        for name, p in (("chunks", cpath), ("embeddings", vpath)):
            if _sha256_file(p) != manifest["files"][name]:
                raise RuntimeError(f"{p.name} 가 manifest.json 과 다름 — 쓰다가 멈췄거나 손으로 바뀜. 다시 생성하세요.")
    chunks = [json.loads(line) for line in cpath.read_text(encoding="utf-8").splitlines() if line.strip()]
    vectors = np.load(vpath)
    if vectors.shape != (len(chunks), manifest["dim"]):
        raise RuntimeError(f"벡터 모양 {vectors.shape} ≠ 청크 {len(chunks)} × {manifest['dim']}")
    return manifest, chunks, vectors


def _previous(index_dir: Path, model_id: str) -> tuple[dict, dict[str, str], dict[str, object]]:
    """직전 인덱스의 (manifest, {chunk_id: sha}, 같은 모델이면 {sha: 벡터})."""
    try:
        manifest, chunks, vectors = load_index(index_dir)
    except (FileNotFoundError, RuntimeError, KeyError, ValueError) as e:
        if not isinstance(e, FileNotFoundError):
            log.warning("직전 인덱스를 쓸 수 없음(%s) — 변경 목록은 전부 추가로 계산", e)
        return {}, {}, {}
    ids = {c["chunk_id"]: row_sha256(c) for c in chunks}
    if manifest.get("model_id") != model_id:
        log.info("직전 인덱스 모델(%s)이 달라 벡터는 다시 만듦", manifest.get("model_id"))
        return manifest, ids, {}
    return manifest, ids, {c["content_sha256"]: vectors[i] for i, c in enumerate(chunks)}


def new_index_version(now: datetime | None = None) -> str:
    """인덱스 판본 ID. 갱신 판본 스냅샷과 같은 UTC 형식(예: 20261107T013730Z)."""
    return (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")


def source_summary(welfare_payload: dict | None, recipe_payload: dict | None, chunks: list[Chunk]) -> dict:
    """원천별 산출 근거: 원본 건수 → 제외(레시피 hold) → 색인한 원본 → 나뉜 원본 → 청크 수."""
    per: dict[str, Counter] = {}
    for c in chunks:
        per.setdefault(c.source_type, Counter())[c.source_id] += 1
    records = Counter()
    excluded: dict[str, dict] = {}
    if welfare_payload:
        records.update(f"welfare_{r['source']}" for r in welfare_payload["records"])
    if recipe_payload:
        records["recipe"] = len(recipe_payload["records"])
        excluded["recipe"] = {"hold": sum(1 for r in recipe_payload["records"]
                                          if (r.get("quality") or {}).get("status") == "hold")}
    out = {}
    for st in sorted(set(records) | set(per), key=["welfare_central", "welfare_local", "recipe"].index):
        counts = per.get(st, Counter())
        out[st] = {
            "records": records.get(st, 0),
            "excluded": excluded.get(st, {}),
            "indexed_records": len(counts),
            "split_records": sum(1 for v in counts.values() if v > 1),
            "chunks": sum(counts.values()),
            "max_chunks_per_record": max(counts.values(), default=0),
        }
    return out


def row_sha256(row: dict) -> str:
    """청크 한 행 전체(본문 + 지역·종료일·확인 시각·품질·원본 해시 등) 해시. 판본 변경 판단용."""
    data = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def diff_chunks(prev: dict[str, str], chunks: list[Chunk]) -> dict:
    """행 전체 기준 변경 목록. 본문이 같아도 다른 칸이 바뀌면 changed(임베딩은 본문이 바뀐 것만 다시 함)."""
    now = {c.chunk_id: row_sha256(c.to_dict()) for c in chunks}
    added = [i for i in now if i not in prev]
    changed = [i for i in now if i in prev and prev[i] != now[i]]
    removed = sorted(i for i in prev if i not in now)
    return {"first_index": not prev, "added": added, "changed": changed, "removed": removed,
            "unchanged": len(now) - len(added) - len(changed)}


def build_index(welfare_payload: dict | None, recipe_payload: dict | None, embedder, *,
                index_dir: Path = paths.RAG_INDEX_DIR, inputs: dict | None = None,
                max_chars: int = MAX_CHARS, dry_run: bool = False, show_progress: bool = False) -> dict:
    """청크를 만들고 필요한 것만 임베딩해 인덱스를 다시 쓴다. manifest(dict)를 돌려준다."""
    import numpy as np

    t0 = time.perf_counter()
    chunks = build_chunks(welfare_payload, recipe_payload, max_chars)
    prev_manifest, prev_ids, prev_vecs = _previous(index_dir, embedder.model_id)
    changes = diff_chunks(prev_ids, chunks)
    unchanged = (prev_vecs and prev_manifest.get("index_version")
                 and not (changes["added"] or changes["changed"] or changes["removed"]))
    # 내용이 그대로면 판본 ID도 그대로 → DB는 이미 활성인 판본이라 다시 넣지 않는다
    index_version = prev_manifest["index_version"] if unchanged else new_index_version()

    cache = VectorCache(index_dir / "embed_cache" / f"{_slug(embedder.model_id)}.jsonl", embedder.dim)
    known = {**prev_vecs, **cache.vectors}
    todo_sha: dict[str, str] = {}
    for c in chunks:
        if c.content_sha256 not in known:
            todo_sha.setdefault(c.content_sha256, c.content)
    summary = {
        "chunks": len(chunks), "to_embed": len(todo_sha),
        "added": len(changes["added"]), "changed": len(changes["changed"]), "removed": len(changes["removed"]),
    }
    if dry_run:
        return {"dry_run": True, **summary}

    todo = list(todo_sha.items())
    for start in range(0, len(todo), SAVE_EVERY):
        part = todo[start:start + SAVE_EVERY]
        vecs = embedder.embed_passages([t for _, t in part], show_progress=show_progress)
        cache.append([(sha, vecs[i]) for i, (sha, _) in enumerate(part)])
        log.info("임베딩 %d / %d", min(start + SAVE_EVERY, len(todo)), len(todo))
    known.update(cache.vectors)

    matrix = np.vstack([known[c.content_sha256] for c in chunks]).astype(np.float32) if chunks \
        else np.zeros((0, embedder.dim), dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1) if len(matrix) else np.zeros(0)
    if len(matrix) and not np.allclose(norms, 1.0, atol=1e-3):
        raise RuntimeError("정규화되지 않은 벡터가 있음 — 임베딩 설정 확인")

    index_dir.mkdir(parents=True, exist_ok=True)

    def write_npy(p: Path):
        with p.open("wb") as f:
            np.save(f, matrix)
    _atomic_write(index_dir / "embeddings.npy", write_npy)

    def write_chunks(p: Path):
        with p.open("w", encoding="utf-8", newline="\n") as f:
            for c in chunks:
                f.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")
    _atomic_write(index_dir / "chunks.jsonl", write_chunks)
    _atomic_write(index_dir / "changes.json",
                  lambda p: p.write_text(json.dumps(changes, ensure_ascii=False, indent=1), encoding="utf-8"))

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "index_version": index_version,
        "built_at": _now(),
        "model_id": embedder.model_id,
        "dim": embedder.dim,
        "max_chars": max_chars,
        "count": len(chunks),
        "by_source_type": dict(Counter(c.source_type for c in chunks)),
        "sources": source_summary(welfare_payload, recipe_payload, chunks),
        "by_section": dict(Counter(c.section for c in chunks)),
        "data_versions": sorted({c.data_version for c in chunks}),
        "inputs": inputs or {},
        "files": {"chunks": _sha256_file(index_dir / "chunks.jsonl"),
                  "embeddings": _sha256_file(index_dir / "embeddings.npy")},
        "changes": {k: (len(v) if isinstance(v, list) else v) for k, v in changes.items()},
        "embedded_this_run": len(todo),
        "duration_sec": round(time.perf_counter() - t0, 1),
    }
    _atomic_write(index_dir / "manifest.json",
                  lambda p: p.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"))
    cache.prune({c.content_sha256 for c in chunks})
    return manifest


def _load_json(p: Path) -> dict | None:
    if not p.exists():
        log.warning("%s 없음 — 이 원천은 건너뜀", p)
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="RAG 검색 인덱스(청크·KURE-v1 벡터) 생성·갱신")
    ap.add_argument("--welfare", type=Path, default=paths.WELFARE_PROCESSED, help="복지 정제 결과")
    ap.add_argument("--recipes", type=Path, default=paths.RECIPES_API_ALL, help="레시피 계약 형식 전체")
    ap.add_argument("--out", type=Path, default=paths.RAG_INDEX_DIR)
    ap.add_argument("--max-chars", type=int, default=MAX_CHARS)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--threads", type=int, default=None, help="torch 스레드 수 (기본: torch 기본값)")
    ap.add_argument("--dry-run", action="store_true", help="청크·변경 건수만 계산 (모델을 올리지 않음)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from agetech_data.rag.embedder import KureEmbedder

    welfare, recipes = _load_json(args.welfare), _load_json(args.recipes)
    if not welfare and not recipes:
        log.error("입력이 하나도 없음")
        return 1
    inputs = {name: {"path": p.resolve().relative_to(paths.REPO_ROOT).as_posix()
                     if p.resolve().is_relative_to(paths.REPO_ROOT) else p.as_posix(),
                     "sha256": _sha256_file(p)}
              for name, p in (("welfare", args.welfare), ("recipes", args.recipes)) if p.exists()}
    emb = KureEmbedder(batch_size=args.batch_size, threads=args.threads)
    result = build_index(welfare, recipes, emb, index_dir=args.out, inputs=inputs, max_chars=args.max_chars,
                         dry_run=args.dry_run, show_progress=True)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
