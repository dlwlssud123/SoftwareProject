"""인덱스 → DB 적재 파일 (docs/data/sql/rag_chunk_draft.sql v3 표 구조).

    uv run python -m agetech_data.rag.export     # data/processed/rag/rag_chunk.csv + load_index.sql
    cd data/processed/rag && psql -v ON_ERROR_STOP=1 -f load_index.sql

판본 전환: 인덱스 판본(index_version)의 적재·건수 확인·활성 전환을 한 트랜잭션에서 처리한다.
커밋하기 전까지 이전 활성 판본을 검색한다. 되돌리기는 SQL 초안의
rag_rollback_index(판본) 함수.

게시 판본 지문(v3): rag_chunk.source_record_sha256 은 원본 표의 게시 판본 fingerprint 다. 인덱스 파일에는
청크를 만든 원본 행 해시만 있으므로(CSV 의 source_row_sha256), load_index.sql 이 적재할 때 원본 표의
활성 판본과 맞춰 fingerprint 를 붙이고, 맞는 판본이 없는 청크는 넣지 않는다.
  - 레시피: recipes·recipe_revisions 의 활성 판본에서 effective_sha256(보완 후 행 해시, 보완이 없으면 원문 행 해시와
    같음)이 청크 원본 행 해시와 같을 때만. 보완표로 고친 레시피는 계약 파일을 `recipes.contract --corrections` 로
    만들었을 때만 들어간다(아니면 청크가 원문 내용이라 DB 게시 내용과 달라 빠짐).
  - 복지: welfare_services·welfare_revisions 의 활성 판본에서 content_sha256(정제 레코드 내용 해시,
    welfare.revision.content_sha256) 이 청크의 원본 해시와 같을 때만. DB 적재와 청크가 같은 갱신 수집본·같은 정제를 쓴다.
  - 이달의 식재료: seasonal_foods 의 게시 행에서 content_sha256(seasonal.revision.content_sha256)이 청크의 원본 해시와
    같을 때만. 이 표에는 판본 fingerprint 가 없으므로 content_sha256 을 그대로 지문으로 쓴다.

CSV: 빈 칸(따옴표 없는 빈 값)은 NULL, 배열은 '{...}', 벡터는 '[...]' 문자열.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from agetech_data import paths
from agetech_data.welfare.revision import SOURCES as WELFARE_SOURCES

# rag_chunk 표 칸 (DB)
COLUMNS = [
    "index_version", "chunk_id", "source_type", "source_id", "section", "chunk_no", "title", "content",
    "content_sha256", "region_scope", "ctpv", "sgg", "source_url", "source_checked_at", "source_modified",
    "period_end", "quality_status", "quality_flags", "allergens", "status", "data_version",
    "source_record_sha256", "embedding_model", "embedding", "embedded_at",
]
# CSV 칸: 게시 판본 지문 대신 청크를 만든 원본 행 해시를 싣는다 — 적재 때 지문으로 바꾼다
CSV_COLUMNS = ["source_row_sha256" if c == "source_record_sha256" else c for c in COLUMNS]
RECIPE_PROVIDER = "foodsafetykorea:COOKRCP01"   # 백엔드 recipes.provider (import_public_data.RECIPE_PROVIDER)
SEASONAL_PROVIDER = "data.go.kr:15168024"         # 백엔드 seasonal_foods.provider (seasonal.revision.PROVIDER)


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
        w.writerow(CSV_COLUMNS)
        for c, v in zip(chunks, vectors):
            row = {**c, "index_version": manifest["index_version"],
                   "quality_flags": pg_array(c["quality_flags"]), "allergens": pg_array(c["allergens"]),
                   "source_row_sha256": c["source_record_sha256"],   # 인덱스 파일 = 원본 행 해시
                   "embedding_model": manifest["model_id"], "embedding": pg_vector(v),
                   "embedded_at": manifest["built_at"]}
            w.writerow(["" if row[k] is None else row[k] for k in CSV_COLUMNS])
    return len(chunks)


def load_script(manifest: dict, manifest_sha256: str, csv_name: str = "rag_chunk.csv") -> str:
    """psql 적재·전환 스크립트. 이미 활성화한 적이 있는 판본은 건너뛴다.

    백엔드 마이그레이션의 원본 표(recipes·recipe_revisions)와 SQL 초안 v3 표가 있는 DB 에서 실행한다.
    """
    name, model_id = manifest["index_version"], manifest["model_id"]
    v, n, model = _sql_str(name), int(manifest["count"]), _sql_str(model_id)
    versions = _sql_str(json.dumps(manifest["data_versions"], ensure_ascii=False))
    cols = ", ".join(COLUMNS)
    # 청크 source_type(welfare_central·welfare_local) ↔ 백엔드 welfare_services 의 provider·scope
    welfare_match = "\n     OR ".join(
        f"(s.source_type = 'welfare_{kind}' AND w.provider = '{src['provider']}' AND w.scope = '{src['scope']}')"
        for kind, src in WELFARE_SOURCES.items())
    return f"""-- 생성: agetech_data.rag.export — 판본 {name}, 청크 {n}, 모델 {model_id}
-- 실행: 이 파일이 있는 폴더에서  psql -v ON_ERROR_STOP=1 -f load_index.sql
-- 필요: SQL 초안 v3 표(rag_index_version·rag_chunk)와 백엔드 원본 표(recipes·recipe_revisions·welfare_services·welfare_revisions)
\\set ON_ERROR_STOP on

BEGIN;
LOCK TABLE rag_index_version, rag_chunk IN EXCLUSIVE MODE;   -- rag_rollback_index 와 같은 잠금 (검색 SELECT 는 됨)
SELECT EXISTS (
    SELECT 1 FROM rag_index_version
    WHERE index_version = {v} AND status IN ('active', 'retired')
) AS already \\gset
\\if :already
  ROLLBACK;
  \\echo '판본 {name} 이미 활성화 이력이 있음 — 적재·전환하지 않음'
  \\quit
\\endif

-- 1) 인덱스 파일을 임시 표에 받고, 원본 표의 게시 판본 지문을 붙여서 맞는 청크만 loading 판본으로 넣는다
CREATE TEMP TABLE rag_chunk_stage (LIKE rag_chunk INCLUDING DEFAULTS) ON COMMIT DROP;
ALTER TABLE rag_chunk_stage ALTER COLUMN source_record_sha256 DROP NOT NULL,
                            ADD COLUMN source_row_sha256 char(64) NOT NULL;
\\copy rag_chunk_stage ({', '.join(CSV_COLUMNS)}) FROM '{csv_name}' WITH (FORMAT csv, HEADER true)

-- 같은 실행에서 나온 CSV 인지: 행 수·판본 이름·모델이 모두 manifest 와 같아야 한다
SELECT count(*) = {n} AND coalesce(bool_and(index_version = {v} AND embedding_model = {model}), false) AS staged_ok
FROM rag_chunk_stage \\gset
\\if :staged_ok
\\else
  ROLLBACK;
  DO $$ BEGIN RAISE EXCEPTION 'CSV 행 수·판본·모델이 manifest와 다름 — 적재하지 않음 (이전 판본 그대로)'; END $$;
\\endif

-- 레시피: 활성 판본의 보완 후(effective) 해시가 청크 원본 행 해시와 같을 때만 지문을 붙인다(보완 없으면 원문과 같음)
UPDATE rag_chunk_stage s SET source_record_sha256 = v.fingerprint
  FROM recipes r JOIN recipe_revisions v ON v.id = r.active_revision_id AND v.recipe_id = r.id
 WHERE s.source_type = 'recipe' AND r.provider = '{RECIPE_PROVIDER}' AND r.source_id = s.source_id
   AND v.quality_status <> 'hold'
   AND v.effective_sha256 = s.source_row_sha256;
-- 복지: 활성 welfare_revisions 의 content_sha256(정제 레코드 내용 해시)이 청크의 원본 해시와 같을 때만
UPDATE rag_chunk_stage s SET source_record_sha256 = v.fingerprint
  FROM welfare_services w JOIN welfare_revisions v ON v.id = w.active_revision_id AND v.service_id = w.id
 WHERE ({welfare_match})
   AND w.publication_status = 'published' AND v.detail_state = 'ready' AND v.quality_status <> 'hold'
   AND w.source_id = s.source_id AND v.content_sha256 = s.source_row_sha256;
-- 이달의 식재료: 게시 중인 seasonal_foods 행의 content_sha256 이 청크의 원본 해시와 같을 때만(이 값을 지문으로)
UPDATE rag_chunk_stage s SET source_record_sha256 = f.content_sha256
  FROM seasonal_foods f
 WHERE s.source_type = 'seasonal' AND f.provider = '{SEASONAL_PROVIDER}' AND f.source_id = s.source_id
   AND f.is_published AND f.detail_status = 'ok' AND f.content_sha256 = s.source_row_sha256;

SELECT source_type, count(*) AS in_index, count(source_record_sha256) AS loaded
FROM rag_chunk_stage GROUP BY source_type ORDER BY source_type;
SELECT count(source_record_sha256) AS loaded_count, count(source_record_sha256) > 0 AS any_loaded
FROM rag_chunk_stage \\gset
\\if :any_loaded
\\else
  ROLLBACK;
  DO $$ BEGIN RAISE EXCEPTION '게시 판본과 맞는 청크가 없음 — 적재하지 않음 (이전 판본 그대로)'; END $$;
\\endif

-- 이전 적재기에서 중단된 판본이 있으면 같은 판본만 다시 적재한다.
DELETE FROM rag_index_version
WHERE index_version = {v} AND status IN ('loading', 'failed') AND activated_at IS NULL;
INSERT INTO rag_index_version (index_version, embedding_model, chunk_count, manifest_sha256, data_versions, status)
VALUES ({v}, {model}, :loaded_count, '{manifest_sha256}', {versions}::jsonb, 'loading');
INSERT INTO rag_chunk ({cols})
SELECT {cols} FROM rag_chunk_stage WHERE source_record_sha256 IS NOT NULL;
-- 2) 넣은 행 수·모델을 확인하고 같은 트랜잭션에서 활성 판본을 바꾼다.
SELECT count(*) = :loaded_count AND coalesce(bool_and(embedding_model = {model}), false) AS ok
FROM rag_chunk WHERE index_version = {v} \\gset
\\if :ok
  UPDATE rag_index_version SET status = 'retired' WHERE status = 'active';
  UPDATE rag_index_version SET status = 'active', activated_at = now() WHERE index_version = {v};
  COMMIT;
  \\echo '판본 {name} 활성 (청크 ' :loaded_count '개)'
\\else
  ROLLBACK;
  DO $$ BEGIN RAISE EXCEPTION '청크 수·모델이 적재 기록과 다름 — 전환하지 않음 (이전 판본 그대로)'; END $$;
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
    print(f"적재·전환: cd {out.parent} && psql -v ON_ERROR_STOP=1 -f {script.name}"
          " (원본 표 게시 판본과 맞는 청크만 들어감)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
