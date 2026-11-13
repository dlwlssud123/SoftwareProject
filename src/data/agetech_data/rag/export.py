"""인덱스 → DB 적재용 CSV (표: 백엔드 Alembic 20261114_03 의 rag_chunk).

    uv run python -m agetech_data.rag.export     # data/processed/rag/rag_chunk.csv
    cd src/backend && uv run python -m app.jobs.load_rag_index --apply

적재·전환은 백엔드 작업 app.jobs.load_rag_index 가 한다(psql 필요 없음, 이 CSV 와 manifest.json 만 읽음).
한 트랜잭션에서 임시 표 COPY → 게시 판본 지문 붙이기 → 판본 등록 → 건수·모델 확인 → 활성 전환. 커밋 전까지
이전 활성 판본을 검색한다. 되돌리기는 같은 작업의 --rollback(= DB 함수 rag_rollback_index).

게시 판본 지문: rag_chunk.source_record_sha256 은 원본 표의 게시 판본 fingerprint 다. 인덱스 파일에는 청크를
만든 원본 행 해시만 있으므로(CSV 의 source_row_sha256), 적재 작업이 DB 뷰 rag_source_active 의 row_sha256 과
맞춰 record_sha256(fingerprint)을 붙이고, 맞는 게시 행이 없는 청크는 넣지 않는다. 원본 행 해시는
레시피 = recipe_revisions.effective_sha256(보완 후 행 — 계약 파일을 `recipes.contract --corrections` 로 만들어야
보완 레시피도 맞음), 복지 = welfare_revisions.content_sha256(정제 레코드 내용), 이달의 식재료 =
seasonal_foods.content_sha256(이 표엔 판본 fingerprint 가 없어 이 값이 지문). 게시 조건은 뷰 한 곳에만 있다.

CSV: 빈 칸(따옴표 없는 빈 값)은 NULL, 배열은 '{...}', 벡터는 '[...]' 문자열. 첫 줄은 칸 이름(CSV_COLUMNS).
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from agetech_data import paths

# rag_chunk 표 칸 (DB)
COLUMNS = [
    "index_version", "chunk_id", "source_type", "source_id", "section", "chunk_no", "title", "content",
    "content_sha256", "region_scope", "ctpv", "sgg", "source_url", "source_checked_at", "source_modified",
    "period_end", "quality_status", "quality_flags", "allergens", "status", "data_version",
    "source_record_sha256", "embedding_model", "embedding", "embedded_at",
]
# CSV 칸: 게시 판본 지문 대신 청크를 만든 원본 행 해시를 싣는다 — 적재 때 지문으로 바꾼다
CSV_COLUMNS = ["source_row_sha256" if c == "source_record_sha256" else c for c in COLUMNS]


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
        w.writerow(CSV_COLUMNS)
        for c, v in zip(chunks, vectors):
            row = {**c, "index_version": manifest["index_version"],
                   "quality_flags": pg_array(c["quality_flags"]), "allergens": pg_array(c["allergens"]),
                   "source_row_sha256": c["source_record_sha256"],   # 인덱스 파일 = 원본 행 해시
                   "embedding_model": manifest["model_id"], "embedding": pg_vector(v),
                   "embedded_at": manifest["built_at"]}
            w.writerow(["" if row[k] is None else row[k] for k in CSV_COLUMNS])
    return len(chunks)


def main(argv: list[str] | None = None) -> int:
    from agetech_data.rag.index import load_index

    ap = argparse.ArgumentParser(description="RAG 인덱스 → DB 적재 CSV")
    ap.add_argument("--index", type=Path, default=paths.RAG_INDEX_DIR)
    ap.add_argument("--out", type=Path, default=None, help="CSV 경로 (기본: <index>/rag_chunk.csv)")
    args = ap.parse_args(argv)
    manifest, chunks, vectors = load_index(args.index)
    out = args.out or args.index / "rag_chunk.csv"
    n = write_csv(manifest, chunks, vectors, out)
    # 예전 psql 적재 스크립트가 남아 있으면 지운다 — 이 판본과 안 맞는 파일을 실행하지 않게
    out.with_name("load_index.sql").unlink(missing_ok=True)
    print(f"판본 {manifest['index_version']}: {n}행 → {out}")
    print("적재·전환: cd src/backend && uv run python -m app.jobs.load_rag_index --apply"
          " (원본 표 게시 판본과 맞는 청크만 들어감)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
