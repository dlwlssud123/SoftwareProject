# RAG 검색 인덱스 정의서 (데이터 → DB·AI 도우미 API 인계)

| 항목 | 내용 |
|---|---|
| 작성 | 최재영 (데이터) |
| 대상 | DB 적재·AI 도우미 API(이진녕), 검색 품질·상태 표시(김민찬) |
| 결정·표 | 모델·서버 결정은 `rag_embedding_decision.md`, 표 초안은 `sql/rag_chunk_draft.sql` |
| 입력 | `data/processed/welfare_elderly.json`(복지 정제, `welfare.build`), `data/processed/recipes_api_all.json`(레시피 계약 형식 전체, `recipes.contract --input data/raw/recipes/cookrcp01_all.json`) |
| 설치 | `uv sync --extra embed` — torch CPU 전용판 + sentence-transformers. 모델 `nlpai-lab/KURE-v1`(약 2.3GB)은 첫 실행 때 Hugging Face 캐시로 받음 |

## 1. 명령

| 명령 | 하는 일 |
|---|---|
| `uv run python -m agetech_data.rag.index` | 청크 생성 → **바뀐 청크만** 임베딩 → 인덱스 파일·변경 목록 |
| `uv run python -m agetech_data.rag.index --dry-run` | 모델을 올리지 않고 청크 수·임베딩할 수·변경 건수만 |
| `uv run python -m agetech_data.rag.evaluate` | 평가 질문으로 Hit@k·문턱값 → `docs/data/rag_search_report.md` |
| `uv run python -m agetech_data.rag.export` | 인덱스 → `rag_chunk.csv` + 판본 적재·전환 스크립트 `load_index.sql` |
| `uv run python -m agetech_data.rag.bench` | 서버 실측(모델 로드·메모리·질문 지연·문서 속도) → 서버를 옮길지 판정. 종료 코드 0 = 유지, 2 = 옮김 |
| `uv run python -m agetech_data.rag.samples` | AI 도우미 API 인계용 근거 표본 → `docs/data/samples/rag_context_sample.json` (5.1절) |

갱신 순서(복지 하루 1회): `refresh` → `welfare.build` → `rag.index` → `rag.export` → `psql -f load_index.sql` — 복지 상세가 바뀐 사업의 청크만 다시 임베딩되고, DB에는 판본 단위로 통째로 넣은 뒤 활성 판본만 바꾼다(4절).

## 2. 출력 파일 — `data/processed/rag/` (gitignore)

| 파일 | 내용 |
|---|---|
| `manifest.json` | `index_version`(인덱스 판본, UTC 예 `20261107T072117Z` — 내용이 그대로면 직전 값 유지), `model_id`(revision 포함), `dim`(1024), `count`, `by_source_type`, `sources`(원천별 산출 근거, 아래), `data_versions`, 입력 sha256, 파일 sha256, 변경 건수, `embedded_this_run`, `built_at`. **마지막에 쓰므로 이 파일이 기준** |
| `chunks.jsonl` | 청크 한 줄에 하나. 칸은 `rag_chunk` 표와 같음(아래 3절, `embedding`·`embedding_model`·`embedded_at` 제외) |
| `embeddings.npy` | float32 `(count, 1024)`. i번째 행 = `chunks.jsonl` i번째 줄. 길이 1로 정규화됨 |
| `changes.json` | 직전 인덱스 대비 `added`·`changed`·`removed` chunk_id **전체 목록**, `unchanged` 건수, `first_index`. 변경은 **행 전체** 기준(본문 밖 칸 — 종료일·확인 시각·품질·원본 해시 — 만 바뀌어도 `changed`, 새 판본). 임베딩은 본문이 바뀐 청크만 다시 함 |
| `rag_chunk.csv` | `rag.export` 결과. 표 칸 순서 그대로(첫 칸 `index_version`), 벡터는 `[...]` 문자열 |
| `load_index.sql` | `rag.export` 결과. 임시 표에 `\copy` → 게시 판본 지문 붙이기 → 판본 등록(`loading`) → 행 수·모델 확인 → 활성 전환 (4절) |
| `embed_cache/` | `content_sha256` → 벡터 캐시. 중간에 멈춰도 다음 실행이 이어서 함. 지금 청크에 없는 것은 끝에 정리 |

- 읽을 때는 `agetech_data.rag.index.load_index()`를 쓰면 manifest의 sha256과 파일을 대조해, 쓰다가 멈춘 파일을 읽지 않는다.
- 파일은 임시 이름으로 쓴 뒤 바꿔 넣는다(벡터 → 청크 → 변경 목록 → manifest 순).
- 임베딩이 중간에 실패하면 manifest가 바뀌지 않아 새 판본이 생기지 않는다(DB는 이전 판본 그대로).

**청크 산출 근거** (`manifest.sources`, 보고서 첫 표와 같음 — 11/07 판본 `20261107T072117Z`)

| 원천 | 원본 | 제외 | 색인한 원본 | 그중 나뉜 원본 | 청크 |
|---|---:|---|---:|---:|---:|
| 복지(중앙부처) | 130 | — | 130 | 57 | 273 |
| 복지(지자체) | 1,338 | — | 1,338 | 54 | 1,456 |
| 레시피 | 1,156 (ok 902·flagged 247·hold 7) | hold 7 | 1,149 | 2 | 1,151 |
| 합계 | 2,624 | | 2,617 | 113 | 2,880 |

- 청크 수 = 색인한 원본 + 나뉜 원본이 늘린 조각. 레시피 1,149건 중 2건(3470 밀푀유 채소 웰링턴, 3773 고추장카르네와 K-쌈밥)이 1,000자를 넘어 개요·만드는 법 2청크로 나뉘어 1,151개.
- 숫자는 손으로 쓰지 않고 `manifest.sources`에서 보고서가 만든다. 원천이 바뀌면 보고서를 다시 생성한다.

## 3. 청크 칸 (`rag_chunk` 한 행)

| 칸 | 예 | 설명 |
|---|---|---|
| `index_version` | `20261107T072117Z` | 인덱스 판본. 기본 키는 (`index_version`, `chunk_id`) |
| `chunk_id` | `welfare_local:WLF00004828:all:1` | `<source_type>:<source_id>:<section>:<번호>`. 다시 만들어도 같은 값 |
| `source_type` | `welfare_central` / `welfare_local` / `recipe` | |
| `source_id` | `WLF00004828` / `28` | 복지 `serv_id` / 레시피 `recipe_id` |
| `section` | `all` / `overview` / `benefits` / `apply` / `steps` | 나누지 않으면 `all` |
| `chunk_no` | `1` | 같은 원본 안 순서 |
| `title` | `경로우대사업` | |
| `content` | `[복지] 경로우대사업 (대구광역시 남구)\n요약: …` | 임베딩한 글 = 대화 AI 근거 |
| `content_sha256` | | 바뀐 청크 판단 |
| `region_scope`, `ctpv`, `sgg` | `district`, `대구광역시`, `남구` | 전국 사업·레시피는 `ctpv`·`sgg` 없음. 시도 전체 사업은 `sgg` 없음 |
| `source_url` | 복지로 링크 | 레시피는 없음 |
| `source_checked_at` | `2026-11-05T…+00:00` | 복지 상세 확인 시각(없으면 목록), 레시피 수집 시각 |
| `source_modified`, `period_end` | `2026-03-01`, `9999-12-31` | 지자체 복지만 |
| `quality_status`, `quality_flags` | `flagged`, `["ingredient_amount_missing"]` | 레시피 hold는 청크 없음. 복지 미확인 필드는 `unverified:<필드>` |
| `allergens` | `["대두", "알류"]` | 레시피 재료명 추정(법정 19종 이름), 확인 필요 종류 포함 |
| `status` | `active` | 다음 판본을 기다리지 않고 바로 숨길 때만 `retracted`(사라진 원본은 새 판본에 없음) |
| `data_version` | `welfare_local:3f761c00cacb` | 원천 원문 sha256 앞 12자리 |
| `source_record_sha256` | 64자리 | **인덱스 파일**: 청크를 만든 원본 행 해시(복지 `raw_sha256`, 레시피 `source.raw_sha256`) — 파일 검색에서 대조. **DB `rag_chunk`**: 원본 표의 게시 판본 fingerprint — 적재 스크립트가 붙이고, 검색 때 `rag_source_active`와 같아야 씀(4절, SQL 초안 v3) |

청크 본문 규칙:
- 복지: 머리말 `[복지] 사업명 (전국 | 시도 전체 | 시도 시군구)` 다음에 요약·지원 대상·선정 기준·지원 내용·지원 주기·제공 방식·신청 방법·신청 안내(중앙)·문의처(최대 5개)·담당을 원문 그대로 넣음. 1,000자를 넘으면 개요 / 지원 내용 / 신청 항목 경계로 나누고, 조각마다 같은 머리말을 붙인다.
- 레시피: 머리말 `[레시피] 이름` 다음에 분류·조리법·해시태그·재료(분량 원문)·저염 팁·영양 원문 값·만드는 법. 영양값 이상 의심(`nutrition.suspect`) 레시피는 영양 줄을 빼고 `nutrition_suspect` 표시.

## 4. DB 적재와 판본 전환

표는 `sql/rag_chunk_draft.sql` v3: 인덱스 판본 표 `rag_index_version`(상태 `loading`/`active`/`retired`/`failed`, 활성은 하나만) + `rag_chunk`(기본 키 `index_version`, `chunk_id`) + 되돌리기 함수 `rag_rollback_index()`.

1. `rag.export` → `cd data/processed/rag && psql -v ON_ERROR_STOP=1 -f load_index.sql` (DB에 백엔드 원본 표 `recipes`·`recipe_revisions`가 있어야 함)
2. 스크립트가 하는 일 (판본·청크 표는 `rag_rollback_index`와 같은 잠금으로 쓰기를 막고, 검색 SELECT는 그대로 됨):
   1. 같은 판본이 이미 있으면 아무것도 안 함
   2. CSV를 임시 표에 받고 행 수·모델이 manifest와 같은지 확인 → 다르면 아무것도 남기지 않고 종료 코드 3
   3. **게시 판본 지문 붙이기(v3)**: CSV의 `source_row_sha256`(청크를 만든 원본 행 해시)로 원본 표의 활성 판본을 찾아 그 `fingerprint`를 `source_record_sha256`에 넣는다. 맞는 판본이 없는 청크는 넣지 않는다(검색에 틀린 근거 대신 '없음').
      - 레시피: `recipes`(`provider = 'foodsafetykorea:COOKRCP01'`, `source_id`) → 활성 `recipe_revisions`의 `raw_sha256`과 `effective_sha256`(보완표 적용 후 행)이 **둘 다** 원본 행 해시와 같을 때만. 보완표로 고친 레시피(11/10 기준 4건: 33·36·642·276)는 DB 내용이 청크 원문과 달라서 빠진다 — 청크를 보완 후 행으로 만들면 들어간다(후속).
      - 복지: **아직 넣지 않는다.** DB의 중앙 복지(`welfare_revisions`)는 백엔드 수집본(`central_all.json`, XML 원문)에서, 청크는 갱신 수집본(`central_elderly.json`·`local_elderly.json`)에서 만들어 원본 행 해시를 맞출 수 없다. 지자체 복지는 DB 적재 전이다. 어느 수집본을 기준으로 할지 정해지면 같은 방식으로 붙인다.
      - 판본별 넣은 건수를 `source_type`별로 출력한다. 하나도 안 맞으면 아무것도 남기지 않고 종료 코드 3
   4. 넣은 청크로 새 판본을 `loading` 등록(`chunk_count` = 실제로 넣은 수)
   5. 넣은 행 수·모델이 맞으면 **한 트랜잭션에서** 이전 `active` → `retired`, 새 판본 → `active` → 아니면 `failed`로 남기고 종료 코드 3(이전 판본이 계속 검색됨)
3. 되돌리기: `SELECT rag_rollback_index('<판본>');` — 없는·적재 중·실패한·한 번도 활성이 아니었던·건수나 모델이 안 맞는 판본은 오류로 거부하고 지금 활성 판본을 그대로 둔다. 정리: 활성 + 바로 전 판본 하나만 남기고 삭제(청크는 함께 지워짐, SQL은 초안 파일)
4. **원본 표와 맞추기 — 한 트랜잭션으로 묶지 않는다(11/07 결정).** 원본 표(복지 하루 1회·레시피 주 1회)와 RAG 판본은 따로 전환한다. 묶으면 임베딩 실패가 복지 정보 갱신까지 막고, 주기도 다르다. 대신 검색이 원본 표의 지금 게시 레코드와 레코드 해시를 대조한다(`rag_source_active` 뷰 JOIN).
   - 순서: ① 원본 수집·정제 → ② 원본 표 적재·전환 → ③ `rag.index`(바뀐 청크만 임베딩) → ④ `load_index.sql`
   - ②~④ 사이: 원본에서 내려간 사업·내용이 바뀐 사업은 해시가 달라 검색에서 바로 빠진다(틀린 근거 대신 '없음'). 새 사업은 ④ 뒤부터 검색된다. RAG가 실패해도 원본 표 갱신은 그대로 진행된다.
   - `rag_source_active (source_type, source_id, record_sha256)`는 원본 표에 맞춰 이진녕이 정의하는 뷰다(예시는 SQL 초안). `record_sha256`은 게시 판본 `fingerprint`이고, 위 2-3의 지문 붙이기와 같은 값이다.

- 판본마다 청크 전부(약 2,880행, CSV 39MB)를 넣는다. 임베딩은 바뀐 청크만 하므로 DB 적재만 통째로 하는 셈이고, 적재는 수 초다.
- `changes.json`은 DB 적재에는 쓰지 않고 관리자 화면·기록용(추가·변경·삭제 건수)으로 남긴다.
- 11/07 실데이터 확인(pgvector 0.8.7): 판본 적재·같은 판본 재실행 건너뜀·적재 중에는 이전 판본만 검색·전환·되돌리기·건수 불일치 `failed`(종료 코드 3)·활성 두 개 거부·정리, 그리고 원본 표에서 사업을 내리거나 원본 해시가 바뀌면 RAG 판본이 그대로여도 그 사업이 바로 검색에서 빠지는 것을 모두 재현했다.

## 5. 검색 (AI 도우미 API)

파이썬(인덱스 파일로, DB 전 확인용):

```python
from agetech_data.rag.embedder import KureEmbedder
from agetech_data.rag.search import WELFARE_TYPES, IndexSearcher, format_context

emb = KureEmbedder()                                   # 모델은 프로세스에 한 번만
searcher = IndexSearcher.from_index(embedder=emb)      # 인덱스 모델 ≠ 질문 모델이면 ValueError
hits = searcher.search("혼자 사는데 안부 확인해 주는 거 있어요?", ctpv="대구", sgg="남구",
                       source_types=WELFARE_TYPES, k=5)
context = format_context(hits)      # [1] 청크 본문 (출처: 링크, 확인 날짜) …
# 원본 표 대조(SQL의 rag_source_active와 같음): search(..., active_sources={(source_type, source_id): 레코드 해시})
```

SQL(같은 조건 — **활성 판본만, 질문과 같은 모델만**, 같은 원본은 가장 가까운 청크 하나만):

```sql
SELECT * FROM (
  SELECT DISTINCT ON (c.source_type, c.source_id)
         c.chunk_id, c.source_type, c.source_id, c.title, c.content, c.source_url, c.source_checked_at,
         c.embedding <=> :q AS distance
  FROM rag_chunk c
  JOIN rag_index_version v ON v.index_version = c.index_version AND v.status = 'active'
  JOIN rag_source_active s ON s.source_type = c.source_type AND s.source_id = c.source_id
                          AND s.record_sha256 = c.source_record_sha256   -- 원본 표에 지금 게시 중인 그 내용만
  WHERE c.status = 'active'
    AND c.embedding_model = :embedding_model          -- KureEmbedder.model_id (= manifest.model_id)
    AND (c.region_scope IN ('national', 'none')
         OR (c.ctpv = :ctpv AND (c.region_scope = 'province' OR c.sgg = :sgg)))
    AND (c.period_end IS NULL OR c.period_end >= current_date)
    AND NOT (c.allergens && :allergies)
  ORDER BY c.source_type, c.source_id, c.embedding <=> :q
) best
ORDER BY distance
LIMIT 5;
```

- `embedding_model` 조건이 없으면 다른 모델로 만든 벡터가 섞였을 때 순위가 무의미해진다. 11/07 재현: 다른 모델 행 하나를 섞자 조건 없이는 그 행이 유사도 1.0으로 1위, 조건을 넣으면 정상 결과(경로우대사업 0.458).
- 11/07 확인: 평가 질문 38개 모두 이 SQL 상위 5개가 파이썬 검색과 순서·유사도까지 같음. 1회 약 9ms(색인 없음, 원본 대조 JOIN 포함).

- 지역은 `welfare.query.resolve_region()`으로 먼저 정규화한다(앱 입력 `대구`·`남구` → `대구광역시`·`남구`).
- 같은 사업이 긴 문서라 청크가 여러 개면 근거가 한 사업으로 채워질 수 있어, 원본 단위로 하나만 남긴다.
- **'근거 없음' 판단**(`rag_search_report.md` 2절): KURE-v1 유사도는 0.4~0.7에 몰려 있어 문턱값 하나로는 정답 질문과 정답 없는 질문을 완전히 가르지 못한다(11/07 평가: 정답 1위 질문의 1위 유사도 최소 0.413, 정답 없는 질문 최대 0.520). 그래서
  - 1위 유사도 < 0.40 → 근거 없음(정답 질문 최소값 0.413보다 조금 낮게 잡음). 대화 AI에 근거를 주지 않고 "확인되지 않는다 + 공식 문의처(보건복지상담센터 129, 주민센터)" 안내
  - 0.40 이상 → 상위 5개를 근거로 주되, 프롬프트에 "근거가 질문과 맞지 않으면 모른다고 하고 문의처를 안내하라, 근거에 없는 사업·금액·전화번호를 만들지 말라"를 넣는다
  - 보고서의 제안 문턱값(0.534)은 정답 없는 질문을 모두 거르지만 정답 질문 4개도 거르므로 참고값으로만 쓴다
  - 코드: `search.evidence_status(hits)` → `none`(< 0.40) / `weak`(0.40~0.53, 근거를 주되 AI가 질문과 맞는지 확인) / `ok`(≥ 0.53)
- 모델은 처음 받은 뒤 `HF_HUB_OFFLINE=1`로 실행한다. 이 값이 없으면 모델을 올릴 때마다 Hugging Face에 접속해 확인하므로, 시연장 인터넷이 불안하면 시작이 늦거나 실패할 수 있다.

### 5.1 AI 도우미 API 인계 표본 — `docs/data/samples/rag_context_sample.json`

실제 인덱스로 검색한 결과다(생성물, 직접 고치지 않음). 최상위 `index`(판본·모델), `evidence_rules`, `prompt_rules`(대화 AI 지시 제안 5줄), `samples[]`.
표본마다 `question`, `profile`(앱 입력 → 해석한 시도·시군구·메모), `filters`, `evidence_status`, `top1_similarity`, `hits[]`(순위·유사도·청크 칸·**본문 전체**), `context`(프롬프트에 그대로 넣을 글, `none`이면 빈 글).

| 표본 | 보여 주는 것 | 판정 |
|---|---|---|
| `welfare_district` | 대구 남구 사업(경로우대사업)이 1위 — **정답인데 `weak`** | weak 0.458 |
| `welfare_district_2`, `welfare_province` | 남구 사업(장수축하물품), 대구시 전체 사업(식사배달)이 1위 | ok |
| `welfare_mixed` | 남구 스마트빌리지·전국 안부살핌 등 함께 | weak |
| `welfare_national_rank2` | 정답(기초연금)이 2위 — 상위 5개를 다 넘겨야 하는 이유 | ok |
| `welfare_other_region` | 서울 노원구 사용자에게 대구 남구 사업이 나오지 않음 | weak |
| `welfare_merged_region` | `광주광역시 광산구` 입력 → 전남광주통합특별시로 검색 | ok |
| `recipe`, `recipe_allergy` | 죽 / 대두·알류 알레르기면 두부·달걀 레시피가 모두 빠짐 → AI가 "두부 요리는 뺐다"고 말해야 함 | ok |
| `none_low` | 정답 없음, 유사도 낮음 → 근거 없음 | none |
| `none_weak`, `none_word_overlap` | 정답 없음인데 0.50 안팎(강아지 사료, 날씨의 '대구' ↔ 생선 대구 요리) → **AI가 걸러야 함** | weak |

- `weak`에는 정답 질문(경로우대사업)과 정답 없는 질문(강아지 사료)이 함께 들어 있다. 그래서 `weak`도 근거를 넘기되 `prompt_rules`의 "근거가 질문과 맞지 않으면 확인되지 않는다고 말하기"가 꼭 필요하다.

## 6. 서버 실측 (`rag.bench`)

**절차는 `rag_server_check.md`.** 임베딩 혼자 재는 1단계는 최소 조건이고, 백엔드와 같이 띄운 2단계(`--label with-backend --concurrency 4 --threads 4 --passages 0`)가 실제 판정이다. 백엔드가 이미 모델을 올렸으면 `bench`를 돌리지 말고(모델이 두 개가 됨) API를 동시에 호출해 잰다.

기업 서버(Python 3.10) — Docker의 Python 3.12에서(1단계):

```bash
git clone -b feature/rag-index-pipeline https://github.com/silversky621/AgeTech.git && cd AgeTech
docker run --rm -v "$PWD":/app -w /app -e UV_PROJECT_ENVIRONMENT=/opt/venv \
  -v agetech-uv-cache:/root/.cache/uv -v agetech-hf-cache:/root/.cache/huggingface \
  python:3.12-slim bash -c "pip install -q uv && uv sync --extra embed && uv run python -m agetech_data.rag.bench --json-out bench_company.json"
```

최재영 서버(ARM, Python 3.12, Docker 없음):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone -b feature/rag-index-pipeline https://github.com/silversky621/AgeTech.git && cd AgeTech
uv sync --extra embed && uv run python -m agetech_data.rag.bench --json-out bench_arm.json
```

- 처음 한 번 모델 약 2.3GB, torch CPU판 약 200MB를 받는다(캐시 볼륨에 남음). 두 번째부터는 `-e HF_HUB_OFFLINE=1`을 붙인다.
- 판정 기준: 질문 임베딩 p95 ≤ 0.5초(동시 요청 `--concurrency`면 ≤ 1.0초), 모델을 올린 뒤 남은 메모리 ≥ 1GB, 측정 중 스왑 증가 ≤ 100MB. 하나라도 넘으면 `move`. 측정 직전 메모리를 많이 쓰던 프로그램(이름별 합계)도 결과에 남는다(리눅스).
- 인덱스·정제 데이터 없이 돈다(질문은 평가 질문, 문서는 커밋된 레시피 표본).

**참고 실측 (11/07, 최재영 노트북 — 서버 아님)**: Intel Core Ultra 7 256V 8코어(GPU 안 씀), Windows 11, torch 2.15.0+cpu

| 항목 | 값 |
|---|---|
| 모델 로드 | 8~10초 |
| 프로세스 메모리 | 모델 올린 뒤 2,876MB, 최대 3,352MB |
| 질문 임베딩 (114회) | p50 65ms · p95 105ms · 최대 112ms |
| 문서 임베딩 | 초당 1.6~1.9개 → 전체 2,880 청크 25분(실제 1회 실행 1,502초) |
| 다시 만들기(바뀐 청크 없음) | 0.2초, 임베딩 0건 |
| 판정 | `move` — 노트북 자체 메모리가 모자라 스왑이 433MB 늘었음(시작 때 남은 메모리 3.8GB) |

- 질문 지연은 기준(0.5초)보다 훨씬 작다. 서버에서도 **메모리**가 먼저 걸릴 가능성이 크다(기업 서버 여유 약 5.9GB, 스왑 사용 중).
- 처음 전체 임베딩(25분 안팎)은 서버에서 할 필요가 없다. 만든 인덱스 파일(약 17MB)이나 CSV를 옮겨 넣으면 된다.

## 7. 알려진 제한

- 레시피 영양값은 원문 값이고 기준량(1인분 여부)이 확인되지 않았다(`recipe_contract.md`). 근거 글에도 "기준량 미확인"으로 적는다.
- 알레르기는 재료명 추정이라 완전하지 않다. 검색 전에 거르되, 화면·답변에서 "재료를 직접 확인" 안내를 함께 둔다.
- 평가 질문은 38개(복지 18, 레시피 14, 정답 없음 6)로 적다. 문턱값은 잠정값.
