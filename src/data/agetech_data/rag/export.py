"""인덱스 → rag_chunk 표 적재용 CSV (docs/data/sql/rag_chunk_draft.sql 칸 순서).

    uv run python -m agetech_data.rag.export            # data/processed/rag/rag_chunk.csv
    psql ... -c "\\copy rag_chunk (<COLUMNS>) FROM 'rag_chunk.csv' WITH (FORMAT csv, HEADER true)"

DB 적재·판본 전환 방식은 이진녕 담당. 이 파일은 바로 넣어 볼 수 있는 기본 형식이다.
빈 칸(따옴표 없는 빈 값)은 NULL, 배열은 '{...}', 벡터는 '[...]' 문자열.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from agetech_data import paths

COLUMNS = [
    "chunk_id", "source_type", "source_id", "section", "chunk_no", "title", "content", "content_sha256",
    "region_scope", "ctpv", "sgg", "source_url", "source_checked_at", "source_modified", "period_end",
    "quality_status", "quality_flags", "allergens", "status", "data_version", "embedding_model",
    "embedding", "embedded_at",
]


def pg_array(items: list[str]) -> str:
    def q(s: str) -> str:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return "{" + ",".join(q(x) for x in items) + "}"


def pg_vector(v) -> str:
    return "[" + ",".join(f"{float(x):.7g}" for x in v) + "]"


def write_csv(manifest: dict, chunks: list[dict], vectors, out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for c, v in zip(chunks, vectors):
            row = {**c, "quality_flags": pg_array(c["quality_flags"]), "allergens": pg_array(c["allergens"]),
                   "embedding_model": manifest["model_id"], "embedding": pg_vector(v),
                   "embedded_at": manifest["built_at"]}
            w.writerow(["" if row[k] is None else row[k] for k in COLUMNS])
    return len(chunks)


def main(argv: list[str] | None = None) -> int:
    from agetech_data.rag.index import load_index

    ap = argparse.ArgumentParser(description="RAG 인덱스 → rag_chunk 적재용 CSV")
    ap.add_argument("--index", type=Path, default=paths.RAG_INDEX_DIR)
    ap.add_argument("--out", type=Path, default=paths.RAG_INDEX_DIR / "rag_chunk.csv")
    args = ap.parse_args(argv)
    manifest, chunks, vectors = load_index(args.index)
    n = write_csv(manifest, chunks, vectors, args.out)
    print(f"{n}행 → {args.out}")
    print(f"\\copy rag_chunk ({', '.join(COLUMNS)}) FROM '{args.out.name}' WITH (FORMAT csv, HEADER true)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
