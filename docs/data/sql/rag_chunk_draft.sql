-- RAG 검색 청크 표 초안 (2026-11-07, 최재영)
-- 저장 구조 작업(이진녕, 11/08~11/10)에서 표·칸 이름과 원본 표 연결 방식을 확정한다.
-- 결정 근거·검색 순서는 docs/data/rag_embedding_decision.md
--
-- 임베딩 모델: nlpai-lab/KURE-v1 (revision 8b418a58414668e75532ed045c22d9ca018ae2b2)
--   1024차원, CLS pooling, 길이 1로 정규화한 벡터 → 코사인 거리(<=>) 사용
-- 대상: PostgreSQL 16 + pgvector 0.8 (pgvector/pgvector:pg16 이미지)
-- 확인(11/07): pgvector 0.8.7 컨테이너에 이 파일 적용 → 아래 예 1·2를 표본 8행으로 실행
--   (부산 남구·끝난 사업 제외, 알레르기 거르기, 지역 칸 제약·1024차원 외 거부 확인)

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE rag_chunk (
    chunk_id          text         PRIMARY KEY,   -- '<source_type>:<source_id>:<section>:<번호>'. 다시 만들어도 같은 값
    source_type       text         NOT NULL
                      CHECK (source_type IN ('welfare_central', 'welfare_local', 'recipe')),
                                                  -- 종류가 늘면(예: 기관 자체 안내) 값만 추가
    source_id         text         NOT NULL,      -- 복지 serv_id(WLF…) / 레시피 recipe_id → 원본 표와 연결하는 키
    section           text         NOT NULL,      -- 'all'(나누지 않음) | 'overview' | 'benefits' | 'apply' | 'steps'
    chunk_no          smallint     NOT NULL,      -- 같은 원본 안에서의 순서(1부터)
    title             text         NOT NULL,      -- 사업명·레시피명 (답변에서 인용)
    content           text         NOT NULL,      -- 임베딩한 글 그대로 = 대화 AI에 근거로 넣는 글
    content_sha256    char(64)     NOT NULL,      -- 바뀐 청크만 다시 임베딩
    region_scope      text         NOT NULL
                      CHECK (region_scope IN ('national', 'province', 'district', 'none')),
                                                  -- 전국 / 시도 전체 / 시군구 / 지역 없음(레시피)
    ctpv              text,                       -- 정규화한 시도 (전국 사업·레시피는 NULL)
    sgg               text,                       -- 정규화한 시군구 (시도 전체 사업은 NULL)
    source_url        text,                       -- 공식 안내 링크 (복지로 등)
    source_checked_at timestamptz,                -- 원천 확인 시각 (상세 확인 시각, 없으면 목록 확인 시각)
    source_modified   date,                       -- 원천 최종 수정일 (지자체 복지)
    period_end        date,                       -- 시행 종료일 (끝난 사업 거르기)
    quality_status    text         NOT NULL DEFAULT 'ok'
                      CHECK (quality_status IN ('ok', 'flagged')),
                                                  -- 레시피 hold는 청크를 만들지 않음
    quality_flags     text[]       NOT NULL DEFAULT '{}',
    allergens         text[]       NOT NULL DEFAULT '{}',
                                                  -- 레시피 재료명으로 추정한 알레르기(법정 19종 이름).
                                                  -- direct·usually·needs_check 모두 넣음 → 거를 때 보수적으로
    status            text         NOT NULL DEFAULT 'active'
                      CHECK (status IN ('active', 'retracted')),
                                                  -- 원천에서 사라지면 retracted (검색에서 뺌)
    data_version      text         NOT NULL,      -- 청크를 만든 원천 판본 (갱신 상태 파일의 serving.snapshot_id)
    embedding_model   text         NOT NULL,      -- 'nlpai-lab/KURE-v1@<revision>'. 모델이 다르면 섞어 쓰지 않음
    embedding         vector(1024) NOT NULL,
    embedded_at       timestamptz  NOT NULL DEFAULT now(),
    CHECK (region_scope <> 'district' OR (ctpv IS NOT NULL AND sgg IS NOT NULL)),
    CHECK (region_scope <> 'province' OR (ctpv IS NOT NULL AND sgg IS NULL)),
    CHECK (region_scope NOT IN ('national', 'none') OR (ctpv IS NULL AND sgg IS NULL))
);

CREATE INDEX rag_chunk_source_idx ON rag_chunk (source_type, source_id);
CREATE INDEX rag_chunk_region_idx ON rag_chunk (ctpv, sgg) WHERE status = 'active';

-- 벡터 색인은 일부러 만들지 않는다.
--   청크 약 3천 건은 색인 없이 전부 비교해도(정확 검색) 수 ms이고, 지역 조건과 충돌하지 않는다.
--   수만 건을 넘으면 아래 색인을 추가한다. 이때 지역 조건과 함께 쓰면 결과가 LIMIT보다 적게 나올 수 있어
--   검색 세션에서 SET hnsw.iterative_scan = relaxed_order; 를 켠다(pgvector 0.8 이상).
-- CREATE INDEX rag_chunk_embedding_hnsw ON rag_chunk USING hnsw (embedding vector_cosine_ops);


-- ── 검색 예 1: 복지 (대구광역시 남구 사용자) ─────────────────────────────
-- :q = 질문 임베딩(vector(1024)), :ctpv·:sgg = welfare.query.resolve_region() 결과
--      (앱 입력 '대구'·'남구' → '대구광역시'·'남구', 옛 광주·전남 → 통합특별시)
-- 같은 사업의 청크가 여러 개면 가장 가까운 하나만 남긴다(DISTINCT ON).
-- 확인(11/07): 실데이터 2,880 청크를 \copy로 넣고 평가 질문 38개를 이 형태로 검색 →
--   파이썬 검색(agetech_data.rag.search)과 상위 5개·순서·유사도가 모두 같음. 색인 없이 1회 약 11ms
-- SELECT chunk_id, source_type, source_id, title, content, source_url, source_checked_at,
--        1 - distance AS similarity
-- FROM (
--   SELECT DISTINCT ON (source_type, source_id)
--          chunk_id, source_type, source_id, title, content, source_url, source_checked_at,
--          embedding <=> :q AS distance
--   FROM rag_chunk
--   WHERE status = 'active'
--     AND source_type IN ('welfare_central', 'welfare_local')
--     AND (region_scope = 'national'
--          OR (ctpv = :ctpv AND (region_scope = 'province' OR sgg = :sgg)))
--     AND (period_end IS NULL OR period_end >= current_date)
--   ORDER BY source_type, source_id, embedding <=> :q
-- ) best
-- ORDER BY distance
-- LIMIT 5;

-- ── 검색 예 2: 레시피 (사용자 알레르기 거르기) ──────────────────────────
-- :allergies = 사용자 알레르기 text[] (예: '{대두,새우}')
-- SELECT chunk_id, source_id, title, content, quality_status, 1 - (embedding <=> :q) AS similarity
-- FROM rag_chunk
-- WHERE status = 'active' AND source_type = 'recipe' AND NOT (allergens && :allergies)
-- ORDER BY embedding <=> :q
-- LIMIT 5;
