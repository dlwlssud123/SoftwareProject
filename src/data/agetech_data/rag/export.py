"""인덱스 → DB 적재 파일 (docs/data/sql/rag_chunk_draft.sql 표 구조).

    uv run python -m agetech_data.rag.export     # data/processed/rag/rag_chunk.csv + load_index.sql
    cd data/processed/rag && psql -v ON_ERROR_STOP=1 -f load_index.sql

판본 전환(이진녕 확정 전 제안): 인덱스 판본(index_version) 단위로 통째로 넣고, 건수를 확인한 뒤
한 트랜잭션에서 활성 판본만 바꾼다. 적재 중·실패한 판본은 검색되지 않고(검색은 활성 판본만 조회),
되돌리기는 이전 판본을 다시 활성으로 바꾸면 된다.

CSV: 빈 칸(따옴표 없는 빈 값)은 NULL, 배열은 '{...}', 벡터는 '[...]' 문자열.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from agetech_data import paths

COLUMNS = [
    "index_version", "chunk_id", "source_type", "source_id", "section", "chunk_no", "title", "content",
    "content_sha256", "region_scope", "ctpv", "sgg", "source_url", "source_checked_at", "source_modified",
    "period_end", "quality_status", "quality_flags", "allergens", "status", "data_version", "embedding_model",
    "embedding", "embedded_at",
]


def pg_array(items: list[str]) -> str:
    def q(s: str) -> str:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return "{" + ",".join(q(x) for x in items) + "}"


def pg_vector(v) -> str:
    return "[" + ",".join(f"{float(x):.7g}" for x in v) + "]"


def _sql_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def write_csv(manifest: dict, chunks: list[dict], vectors, out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for c, v in zip(chunks, vectors):
            row = {**c, "index_version": manifest["index_version"],
                   "quality_flags": pg_array(c["quality_flags"]), "allergens": pg_array(c["allergens"]),
                   "embedding_model": manifest["model_id"], "embedding": pg_vector(v),
                   "embedded_at": manifest["built_at"]}
            w.writerow(["" if row[k] is None else row[k] for k in COLUMNS])
    return len(chunks)


def load_script(manifest: dict, manifest_sha256: str, csv_name: str = "rag_chunk.csv") -> str:
    """psql 적재·전환 스크립트. 같은 판본이 이미 있으면 아무것도 하지 않는다."""
    v, n, model = _sql_str(manifest["index_version"]), int(manifest["count"]), _sql_str(manifest["model_id"])
    versions = _sql_str(json.dumps(manifest["data_versions"], ensure_ascii=False))
    return f"""-- 생성: agetech_data.rag.export — 판본 {manifest['index_version']}, 청크 {n}, 모델 {manifest['model_id']}
-- 실행: 이 파일이 있는 폴더에서  psql -v ON_ERROR_STOP=1 -f load_index.sql
\\set ON_ERROR_STOP on

SELECT EXISTS (SELECT 1 FROM rag_index_version WHERE index_version = {v}) AS already \\gset
\\if :already
  \\echo '판본 {manifest['index_version']} 이미 있음 — 적재·전환하지 않음'
  \\quit
\\endif

-- 1) 새 판본을 loading 으로 등록하고 청크를 넣는다 (아직 검색되지 않음)
BEGIN;
INSERT INTO rag_index_version (index_version, embedding_model, chunk_count, manifest_sha256, data_versions, status)
VALUES ({v}, {model}, {n}, '{manifest_sha256}', {versions}::jsonb, 'loading');
\\copy rag_chunk ({', '.join(COLUMNS)}) FROM '{csv_name}' WITH (FORMAT csv, HEADER true)
COMMIT;

-- 2) 건수·모델이 맞으면 한 트랜잭션에서 활성 판본을 바꾼다. 안 맞으면 failed 로 남기고 이전 판본 유지
SELECT count(*) = {n} AND coalesce(bool_and(embedding_model = {model}), false) AS ok
FROM rag_chunk WHERE index_version = {v} \\gset
\\if :ok
  BEGIN;
  UPDATE rag_index_version SET status = 'retired' WHERE status = 'active';
  UPDATE rag_index_version SET status = 'active', activated_at = now() WHERE index_version = {v};
  COMMIT;
  \\echo '판본 {manifest['index_version']} 활성'
\\else
  UPDATE rag_index_version SET status = 'failed' WHERE index_version = {v};
  DO $$ BEGIN RAISE EXCEPTION '청크 수·모델이 manifest와 다름 — 전환하지 않음 (이전 판본 그대로)'; END $$;
\\endif
"""


def main(argv: list[str] | None = None) -> int:
    from agetech_data.rag.index import _sha256_file, load_index

    ap = argparse.ArgumentParser(description="RAG 인덱스 → DB 적재 CSV·psql 스크립트")
    ap.add_argument("--index", type=Path, default=paths.RAG_INDEX_DIR)
    ap.add_argument("--out", type=Path, default=None, help="CSV 경로 (기본: <index>/rag_chunk.csv)")
    args = ap.parse_args(argv)
    manifest, chunks, vectors = load_index(args.index)
    out = args.out or args.index / "rag_chunk.csv"
    n = write_csv(manifest, chunks, vectors, out)
    script = out.with_name("load_index.sql")
    script.write_text(load_script(manifest, _sha256_file(args.index / "manifest.json"), out.name),
                      encoding="utf-8", newline="\n")
    print(f"판본 {manifest['index_version']}: {n}행 → {out}")
    print(f"적재·전환: cd {out.parent} && psql -v ON_ERROR_STOP=1 -f {script.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
