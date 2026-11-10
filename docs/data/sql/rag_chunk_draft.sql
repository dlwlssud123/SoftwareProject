-- RAG 검색 청크 표 초안 v3 (2026-11-09, v2 최재영 작성 / 롤백·판본 대조 보완)
-- 저장 구조 작업(이진녕, 11/08~11/10)에서 표·칸 이름과 원본 표 연결 방식을 확정한다.
-- 결정 근거·검색 순서는 docs/data/rag_embedding_decision.md
--
-- v1 → v2 (PR #11 리뷰 반영)
--   1. 검색 예에 embedding_model 조건 추가 — 다른 모델 벡터가 섞이면 1위로 나올 수 있음
--   2. 인덱스 판본 표 rag_index_version 추가. 판본 단위로 통째로 적재하고, 건수를 확인한 뒤
--      한 트랜잭션에서 활성 판본만 바꾼다. 검색은 활성 판본만 조회 → 적재 중·실패한 판본은 보이지 않음
--   3. rag_chunk 기본 키 = (index_version, chunk_id)
--   4. 원본 표 게시 상태 연결: 청크에 원본 레코드 해시(source_record_sha256)를 두고, 검색은 원본 표에
--      '지금 게시 중이고 해시가 같은' 레코드의 청크만 쓴다(rag_source_active 뷰 JOIN).
--      원본 표 판본 전환과 RAG 판본 전환은 한 트랜잭션으로 묶지 않는다 — 아래 '원본 표와 맞추기' 참고
--
-- 임베딩 모델: nlpai-lab/KURE-v1 (revision 8b418a58414668e75532ed045c22d9ca018ae2b2)
--   1024차원, CLS pooling, 길이 1로 정규화한 벡터 → 코사인 거리(<=>) 사용
-- 대상: PostgreSQL 16 + pgvector 0.8 (pgvector/pgvector:pg16 이미지)
-- 확인(11/07): pgvector 0.8.7 컨테이너에 이 파일 적용 → 실데이터 2,880 청크를 적재 스크립트로 넣고
--   검색 예 1을 평가 질문 38개로 실행(파이썬 검색과 상위 5개·순서 같음, 1회 약 9ms), 다른 모델 행 섞기·
--   원본 표 게시 중단·원본 해시 변경·판본 적재 중·전환·되돌리기·건수 불일치 실패를 재현해 확인

CREATE EXTENSION IF NOT EXISTS vector;

-- 인덱스 판본: rag.index 1회 실행 결과(manifest.json) 하나 = 한 행
CREATE TABLE rag_index_version (
    index_version     text         PRIMARY KEY,   -- manifest.index_version (UTC, 예: 20261107T070716Z)
    embedding_model   text         NOT NULL,      -- 이 판본 모든 청크의 'nlpai-lab/KURE-v1@<revision>'
    chunk_count       integer      NOT NULL,      -- 실제로 넣은 청크 수(manifest 청크 중 게시 판본 지문이 붙은 것) — 전환·되돌리기 때 실제 행 수와 대조
    manifest_sha256   char(64)     NOT NULL,
    data_versions     jsonb        NOT NULL,      -- 원천 판본 목록 (복지·레시피 원문 sha256 앞 12자리)
    status            text         NOT NULL DEFAULT 'loading'
                      CHECK (status IN ('loading', 'active', 'retired', 'failed')),
    created_at        timestamptz  NOT NULL DEFAULT now(),
    activated_at      timestamptz
);
-- 활성 판본은 언제나 하나 이하
CREATE UNIQUE INDEX rag_index_version_one_active ON rag_index_version ((status)) WHERE status = 'active';

CREATE TABLE rag_chunk (
    index_version     text         NOT NULL REFERENCES rag_index_version (index_version) ON DELETE CASCADE,
    chunk_id          text         NOT NULL,      -- '<source_type>:<source_id>:<section>:<번호>'. 다시 만들어도 같은 값
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
                                                  -- 다음 판본을 기다리지 않고 바로 숨길 때만 retracted
    data_version      text         NOT NULL,      -- 청크를 만든 원천 판본
    source_record_sha256 char(64)  NOT NULL,      -- 게시 DB 판본 fingerprint(원문·보완·정규화/검증 버전 포함)
                                                  -- → rag_source_active.record_sha256 과 같을 때만 검색
    embedding_model   text         NOT NULL,      -- 'nlpai-lab/KURE-v1@<revision>'. 모델이 다르면 섞어 쓰지 않음
    embedding         vector(1024) NOT NULL,
    embedded_at       timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (index_version, chunk_id),
    CHECK (region_scope <> 'district' OR (ctpv IS NOT NULL AND sgg IS NOT NULL)),
    CHECK (region_scope <> 'province' OR (ctpv IS NOT NULL AND sgg IS NULL)),
    CHECK (region_scope NOT IN ('national', 'none') OR (ctpv IS NULL AND sgg IS NULL))
);

CREATE INDEX rag_chunk_source_idx ON rag_chunk (index_version, source_type, source_id);
CREATE INDEX rag_chunk_region_idx ON rag_chunk (index_version, ctpv, sgg) WHERE status = 'active';

-- 되돌릴 판본을 모두 검증한 뒤 전환한다. 예외가 나면 현재 active는 유지된다.
-- 검색 SELECT는 허용하며 적재·정리·동시 롤백의 쓰기를 트랜잭션 종료까지 직렬화한다.
CREATE FUNCTION rag_rollback_index(previous_version text) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    target rag_index_version%ROWTYPE;
    actual_count bigint;
    mixed_models boolean;
BEGIN
    LOCK TABLE rag_index_version, rag_chunk IN EXCLUSIVE MODE;
    SELECT * INTO target FROM rag_index_version WHERE index_version = previous_version;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Rollback index version does not exist: %', previous_version
            USING ERRCODE = '22023';
    END IF;
    IF target.status NOT IN ('active', 'retired') OR target.activated_at IS NULL THEN
        RAISE EXCEPTION 'Rollback requires a previously activated version: %', previous_version
            USING ERRCODE = '22023';
    END IF;
    SELECT count(*), bool_or(embedding_model IS DISTINCT FROM target.embedding_model)
      INTO actual_count, mixed_models
      FROM rag_chunk WHERE index_version = previous_version;
    IF actual_count <> target.chunk_count OR coalesce(mixed_models, false) THEN
        RAISE EXCEPTION 'Rollback index count or model is invalid: %', previous_version
            USING ERRCODE = '23514';
    END IF;
    IF target.status = 'active' THEN
        RETURN;
    END IF;
    UPDATE rag_index_version SET status = 'retired' WHERE status = 'active';
    UPDATE rag_index_version SET status = 'active', activated_at = now()
      WHERE index_version = previous_version;
END;
$$;

-- 벡터 색인은 일부러 만들지 않는다.
--   판본 하나가 청크 약 3천 건이라 색인 없이 전부 비교해도(정확 검색) 약 11ms이고, 지역 조건과 충돌하지 않는다.
--   수만 건을 넘으면 아래 색인을 추가한다. 이때 지역 조건과 함께 쓰면 결과가 LIMIT보다 적게 나올 수 있어
--   검색 세션에서 SET hnsw.iterative_scan = relaxed_order; 를 켠다(pgvector 0.8 이상).
-- CREATE INDEX rag_chunk_embedding_hnsw ON rag_chunk USING hnsw (embedding vector_cosine_ops);


-- ── 판본 적재·전환 ──────────────────────────────────────────────────────
-- 적재: `uv run python -m agetech_data.rag.export` 가 rag_chunk.csv 와 load_index.sql 을 만든다.
--   load_index.sql = ① 임시 표에 \copy → 행 수·모델이 manifest와 같은지 확인(다르면 아무것도 안 남김)
--                    ② 원본 표 활성 판본의 fingerprint 를 source_record_sha256 에 붙이고, 붙은 청크만 새 판본(loading)으로
--                       넣는다(아직 검색 안 됨). 레시피는 recipe_revisions 의 raw_sha256·effective_sha256 이 둘 다 청크
--                       원본 행 해시와 같을 때만. 복지는 맞출 기준이 정해질 때까지 넣지 않는다(rag_index_contract.md 4절)
--                    ③ 넣은 행 수·모델이 맞으면 한 트랜잭션에서 이전 active → retired, 새 판본 → active
--                    ④ 다르면 failed 로 남기고 오류로 끝냄(종료 코드 3) — 이전 판본이 계속 검색됨
--   적재·전환은 rag_rollback_index 와 같은 표 잠금을 잡아 동시 실행을 막는다(검색 SELECT 는 됨).
--   임베딩이 중간에 실패하면 manifest가 만들어지지 않아 적재할 판본 자체가 없다(이전 판본 그대로).
--
-- ── 원본 표와 맞추기 (결정: 한 트랜잭션으로 묶지 않음) ────────────────────
-- 원본 표(복지 하루 1회·레시피 주 1회)와 RAG 판본은 따로 전환한다. 묶으면 임베딩 실패가 복지 정보 갱신까지
-- 막고, 갱신 주기도 다르다. 대신 검색이 원본 표의 '지금 게시 중인 판본 fingerprint'를 대조한다.
-- raw_sha256만 비교하면 원문이 같고 보완·정규화 코드만 바뀐 이전 청크가 남을 수 있다.
-- exporter는 실제 게시 DB 판본의 fingerprint를 청크에 복사한다. 기존 raw 해시 청크는 다시 내보낸다.
--   순서: ① 원본 수집·정제 → ② 원본 표 적재·전환 → ③ rag.index(바뀐 청크만 임베딩) → ④ load_index.sql
--   ②~④ 사이: 원본에서 내려간 사업·내용이 바뀐 사업은 해시가 달라 검색에서 바로 빠진다(틀린 근거 대신 '없음').
--             새로 생긴 사업은 ④ 뒤부터 검색된다. RAG가 실패해도 원본 표 갱신은 그대로 진행된다.
-- rag_source_active 는 원본 표에 맞춰 이진녕이 정의하는 뷰(이름·칸만 지키면 됨). 예:
-- CREATE VIEW rag_source_active (source_type, source_id, record_sha256) AS
--   SELECT 'welfare_central', w.source_id, v.fingerprint
--     FROM welfare_services w JOIN welfare_revisions v ON v.id = w.active_revision_id AND v.service_id = w.id
--    WHERE w.scope = 'central_nationwide' AND w.publication_status = 'published'
--      AND v.detail_state = 'ready' AND v.quality_status <> 'hold'
--   UNION ALL
--   SELECT 'recipe', r.source_id, v.fingerprint
--     FROM recipes r JOIN recipe_revisions v ON v.id = r.active_revision_id AND v.recipe_id = r.id
--    WHERE r.provider = 'foodsafetykorea:COOKRCP01' AND v.quality_status <> 'hold';
-- 지자체 DB 적재와 공고 저장을 연결할 때 해당 원본의 게시·마감·철회 조건도 뷰에 반영한다.
-- 원본 표가 생기기 전 시험용(청크에서 채움):
-- CREATE TABLE rag_source_active (source_type text, source_id text, record_sha256 char(64),
--                                 PRIMARY KEY (source_type, source_id));
--
-- 되돌리기 (:previous = 되돌릴 판본):
-- SELECT rag_rollback_index(:previous);
-- missing/loading/failed/활성화 이력 없음/건수·모델 불일치는 오류로 거부한다.
-- 현재 active를 다시 지정하면 검증 후 같은 상태로 끝나며, 부분 전환은 커밋되지 않는다.
--
-- 정리 (활성 + 바로 전 판본 하나만 남김, 청크는 ON DELETE CASCADE):
-- DELETE FROM rag_index_version
-- WHERE status IN ('retired', 'failed')
--   AND index_version IS DISTINCT FROM (SELECT index_version FROM rag_index_version
--                                       WHERE status = 'retired' ORDER BY activated_at DESC NULLS LAST LIMIT 1);


-- ── 검색 예 1: 복지 (대구광역시 남구 사용자) ─────────────────────────────
-- :q = 질문 임베딩(vector(1024)), :embedding_model = 질문을 임베딩한 모델 ID(인덱스와 같아야 함)
-- :ctpv·:sgg = welfare.query.resolve_region() 결과 (앱 입력 '대구'·'남구' → '대구광역시'·'남구', 옛 광주·전남 → 통합특별시)
-- 활성 판본·원본 표 게시 레코드만 보고, 같은 사업의 청크가 여러 개면 가장 가까운 하나만 남긴다(DISTINCT ON).
-- SELECT chunk_id, source_type, source_id, title, content, source_url, source_checked_at,
--        1 - distance AS similarity
-- FROM (
--   SELECT DISTINCT ON (c.source_type, c.source_id)
--          c.chunk_id, c.source_type, c.source_id, c.title, c.content, c.source_url, c.source_checked_at,
--          c.embedding <=> :q AS distance
--   FROM rag_chunk c
--   JOIN rag_index_version v ON v.index_version = c.index_version AND v.status = 'active'
--   JOIN rag_source_active s ON s.source_type = c.source_type AND s.source_id = c.source_id
--                           AND s.record_sha256 = c.source_record_sha256
--   WHERE c.status = 'active'
--     AND c.embedding_model = :embedding_model
--     AND c.source_type IN ('welfare_central', 'welfare_local')
--     AND (c.region_scope = 'national'
--          OR (c.ctpv = :ctpv AND (c.region_scope = 'province' OR c.sgg = :sgg)))
--     AND (c.period_end IS NULL OR c.period_end >= current_date)
--   ORDER BY c.source_type, c.source_id, c.embedding <=> :q
-- ) best
-- ORDER BY distance
-- LIMIT 5;

-- ── 검색 예 2: 레시피 (사용자 알레르기 거르기) ──────────────────────────
-- :allergies = 사용자 알레르기 text[] (예: '{대두,새우}')
-- SELECT c.chunk_id, c.source_id, c.title, c.content, c.quality_status, 1 - (c.embedding <=> :q) AS similarity
-- FROM rag_chunk c
-- JOIN rag_index_version v ON v.index_version = c.index_version AND v.status = 'active'
-- JOIN rag_source_active s ON s.source_type = c.source_type AND s.source_id = c.source_id
--                         AND s.record_sha256 = c.source_record_sha256
-- WHERE c.status = 'active' AND c.embedding_model = :embedding_model
--   AND c.source_type = 'recipe' AND NOT (c.allergens && :allergies)
-- ORDER BY c.embedding <=> :q
-- LIMIT 5;
