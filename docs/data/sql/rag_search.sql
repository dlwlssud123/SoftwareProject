-- RAG 근거 검색 SQL (AI 도우미 API용) — 2026-11-14, 최재영
--
-- 표·함수·뷰는 백엔드 Alembic 20261114_03 이 만든다(src/backend/alembic/versions/20261114_03_add_rag_index_tables.py).
-- 이 파일은 그 표로 하는 검색과 운영 SQL 이다. 예전 초안(rag_chunk_draft.sql v1~v3, PR #11·#13·#39 리뷰)의 표 정의는
-- 마이그레이션으로 옮겼고, 아래 검색은 백엔드 시험(tests/test_load_rag_index.py)이 이 파일을 그대로 실행해 확인한다.
-- 결정 근거·검색 순서는 docs/data/rag_embedding_decision.md, 칸·적재 규칙은 docs/data/rag_index_contract.md 4·5절.
--
-- 초안 v3 → 마이그레이션에서 바뀐 것
--   1. rag_index_version.index_version = '<manifest index_version>.<지문 묶음 sha256 앞 12자리>'.
--      rag.index 는 청크 행이 그대로면 판본 이름을 유지하는데, 레시피 검증 판본이 올라가 재적재되면 내용은 같아도
--      게시 지문(fingerprint)이 바뀐다. 이름이 manifest 판본만이면 '이미 활성'으로 건너뛰어 그 청크가 모두 검색에서
--      빠졌다 → 붙인 지문 묶음까지 이름에 넣어, 지문이 바뀌면 새 판본으로 다시 적재한다. manifest_version·binding_sha256 칸 추가.
--   2. rag_source_active 뷰를 마이그레이션에 포함(초안 예시 그대로 + provider 조건)하고 row_sha256(청크를 만든 원본 행 해시)
--      칸을 더했다. 적재 작업이 이 뷰로 지문을 붙이므로 '게시 중' 조건이 적재와 검색에 한 곳만 있다.
--   3. 적재는 psql 스크립트(load_index.sql) 대신 백엔드 작업 app.jobs.load_rag_index(psycopg COPY, 같은 잠금·같은 순서).
--
-- 임베딩 모델: nlpai-lab/KURE-v1 (revision 8b418a58414668e75532ed045c22d9ca018ae2b2)
--   1024차원, CLS pooling, 길이 1로 정규화한 벡터 → 코사인 거리(<=>). 대상: PostgreSQL 16 + pgvector 0.8
-- 벡터 색인은 일부러 만들지 않았다(판본 하나 약 3,400청크, 정확 검색 약 10ms, 지역 조건과 충돌 없음).
--   수만 건을 넘으면 HNSW(vector_cosine_ops)를 추가하고 검색 세션에서 SET hnsw.iterative_scan = relaxed_order;

-- ── 검색: 활성 판본 · 게시 중인 원본 · 질문과 같은 모델만, 같은 원본은 가장 가까운 청크 하나 ────────────
-- :q               질문 임베딩 '[0.01,…]' (KureEmbedder.embed_query, 1024개)
-- :embedding_model 질문을 임베딩한 모델 ID = KureEmbedder.model_id (인덱스와 같아야 함 — 다르면 순위가 무의미)
-- :source_types    주제 묶음. 복지 {welfare_central,welfare_local} / 음식 {recipe,seasonal} / 레시피만 {recipe}
--                  (그 외 질문은 검색하지 않음 — 한꺼번에 찾으면 '겨울 난방비'에 제철 글이 섞임, rag_search_report.md)
-- :ctpv, :sgg      welfare.query.resolve_region() 결과 (앱 '대구'·'남구' → '대구광역시'·'남구'). 모르면 NULL — 전국 사업만
-- :allergies       사용자 알레르기 text[] (예: {대두,새우}). 빈 배열이면 거르지 않음. 거를 때는 판정을 끝낸
--                  (allergen_analysis_complete) 청크 중 검출·확인 필요·판정 불가 목록과 겹치지 않는 것만
SELECT chunk_id, source_type, source_id, title, content, source_url, source_checked_at,
       1 - distance AS similarity
FROM (
  SELECT DISTINCT ON (c.source_type, c.source_id)
         c.chunk_id, c.source_type, c.source_id, c.title, c.content, c.source_url, c.source_checked_at,
         c.embedding <=> CAST(:q AS vector) AS distance
  FROM rag_chunk c
  JOIN rag_index_version v ON v.index_version = c.index_version AND v.status = 'active'
  JOIN rag_source_active s ON s.source_type = c.source_type AND s.source_id = c.source_id
                          AND s.record_sha256 = c.source_record_sha256
  WHERE c.status = 'active'
    AND c.embedding_model = :embedding_model
    AND c.source_type = ANY (CAST(:source_types AS text[]))
    AND (c.region_scope IN ('national', 'none')
         OR (c.ctpv = :ctpv AND (c.region_scope = 'province' OR c.sgg = :sgg)))
    AND (c.period_end IS NULL OR c.period_end >= current_date)
    AND (c.source_type NOT IN ('recipe', 'seasonal')
         OR coalesce(cardinality(CAST(:allergies AS text[])), 0) = 0
         OR ('allergen_analysis_complete' = ANY (c.quality_flags)
             AND NOT (c.allergens && CAST(:allergies AS text[]))))
  ORDER BY c.source_type, c.source_id, c.embedding <=> CAST(:q AS vector)
) best
ORDER BY distance
LIMIT 5;
-- 1위 similarity < 0.40 이면 근거 없음(search.evidence_status) — 대화 AI 에 근거를 주지 말고 문의처 안내.

-- ── 운영 (적재·되돌리기는 cd src/backend 에서 app.jobs.load_rag_index) ─────────────────────────────
-- 적재:      uv run python -m app.jobs.load_rag_index --apply     (rag.export 다음, 매일 갱신의 rag_load 단계)
-- 확인:      uv run python -m app.jobs.load_rag_index --verify    (활성 판본 = 이 인덱스를 지금 게시 판본에 붙인 것?)
-- 되돌리기:  uv run python -m app.jobs.load_rag_index --rollback <index_version>
--            = SELECT rag_rollback_index('<index_version>');  없는·적재 중·실패·활성 이력 없음·건수/모델 불일치는 거부
-- 판본 목록: SELECT index_version, status, chunk_count, activated_at FROM rag_index_version ORDER BY created_at DESC;
-- 정리:      적재 작업이 활성화할 때 직전 판본 하나만 남기고 지운다(청크는 ON DELETE CASCADE).
-- 지금 검색되는 청크 수(원본 표 재적재 뒤 지문이 바뀌면 줄어듦 → 다음 --apply 가 다시 붙임):
--   SELECT c.source_type, count(*) FROM rag_chunk c
--     JOIN rag_index_version v ON v.index_version = c.index_version AND v.status = 'active'
--     JOIN rag_source_active s ON s.source_type = c.source_type AND s.source_id = c.source_id
--                             AND s.record_sha256 = c.source_record_sha256
--    GROUP BY c.source_type;
-- 원본 표와 RAG 판본은 한 트랜잭션으로 묶지 않는다(11/07 결정). 원본에서 내려간·바뀐 사업은 지문이 달라 검색에서
-- 바로 빠지고(틀린 근거 대신 '없음'), 새 사업은 다음 적재부터 검색된다. RAG 가 실패해도 원본 표 갱신은 그대로 진행된다.
