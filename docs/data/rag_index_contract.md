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
| `uv run python -m agetech_data.rag.export` | 인덱스 → `rag_chunk` 적재용 CSV(`\copy`로 바로 넣기) |
| `uv run python -m agetech_data.rag.bench` | 서버 실측(모델 로드·메모리·질문 지연·문서 속도) → 서버를 옮길지 판정. 종료 코드 0 = 유지, 2 = 옮김 |

갱신 순서(복지 하루 1회): `refresh` → `welfare.build` → `rag.index` → (DB 적재) — 복지 상세가 바뀐 사업의 청크만 다시 임베딩된다.

## 2. 출력 파일 — `data/processed/rag/` (gitignore)

| 파일 | 내용 |
|---|---|
| `manifest.json` | `model_id`(revision 포함), `dim`(1024), `count`, `by_source_type`, `data_versions`, 입력 sha256, 파일 sha256, 변경 건수, `embedded_this_run`, `built_at`. **마지막에 쓰므로 이 파일이 기준** |
| `chunks.jsonl` | 청크 한 줄에 하나. 칸은 `rag_chunk` 표와 같음(아래 3절, `embedding`·`embedding_model`·`embedded_at` 제외) |
| `embeddings.npy` | float32 `(count, 1024)`. i번째 행 = `chunks.jsonl` i번째 줄. 길이 1로 정규화됨 |
| `changes.json` | 직전 인덱스 대비 `added`·`changed`·`removed` chunk_id **전체 목록**, `unchanged` 건수, `first_index` |
| `rag_chunk.csv` | `rag.export` 결과. 표 칸 순서 그대로, 벡터는 `[...]` 문자열 |
| `embed_cache/` | `content_sha256` → 벡터 캐시. 중간에 멈춰도 다음 실행이 이어서 함. 지금 청크에 없는 것은 끝에 정리 |

- 읽을 때는 `agetech_data.rag.index.load_index()`를 쓰면 manifest의 sha256과 파일을 대조해, 쓰다가 멈춘 파일을 읽지 않는다.
- 파일은 임시 이름으로 쓴 뒤 바꿔 넣는다(벡터 → 청크 → 변경 목록 → manifest 순).

## 3. 청크 칸 (`rag_chunk` 한 행)

| 칸 | 예 | 설명 |
|---|---|---|
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
| `status` | `active` | 사라진 원본은 적재 때 `retracted`로 |
| `data_version` | `welfare_local:3f761c00cacb` | 원천 원문 sha256 앞 12자리 |

청크 본문 규칙:
- 복지: 머리말 `[복지] 사업명 (전국 | 시도 전체 | 시도 시군구)` 다음에 요약·지원 대상·선정 기준·지원 내용·지원 주기·제공 방식·신청 방법·신청 안내(중앙)·문의처(최대 5개)·담당을 원문 그대로 넣음. 1,000자를 넘으면 개요 / 지원 내용 / 신청 항목 경계로 나누고, 조각마다 같은 머리말을 붙인다.
- 레시피: 머리말 `[레시피] 이름` 다음에 분류·조리법·해시태그·재료(분량 원문)·저염 팁·영양 원문 값·만드는 법. 영양값 이상 의심(`nutrition.suspect`) 레시피는 영양 줄을 빼고 `nutrition_suspect` 표시.

## 4. DB 적재 (제안 — 판본 전환 방식은 이진녕 결정)

1. `manifest.json`의 `model_id`가 DB에 있는 벡터의 `embedding_model`과 다르면 전부 다시 넣는다(섞지 않음).
2. `changes.json`의 `added`·`changed` → upsert, `removed` → `status='retracted'`(또는 삭제).
3. 처음 넣을 때는 `rag.export`의 CSV를 `\copy`로 넣으면 된다.

```sql
\copy rag_chunk (chunk_id, source_type, source_id, section, chunk_no, title, content, content_sha256, region_scope, ctpv, sgg, source_url, source_checked_at, source_modified, period_end, quality_status, quality_flags, allergens, status, data_version, embedding_model, embedding, embedded_at) FROM 'rag_chunk.csv' WITH (FORMAT csv, HEADER true)
```

## 5. 검색 (AI 도우미 API)

파이썬(인덱스 파일로, DB 전 확인용):

```python
from agetech_data.rag.embedder import KureEmbedder
from agetech_data.rag.index import load_index
from agetech_data.rag.search import WELFARE_TYPES, IndexSearcher, format_context

manifest, chunks, vectors = load_index()
searcher = IndexSearcher(chunks, vectors, KureEmbedder())        # 모델은 프로세스에 한 번만
hits = searcher.search("혼자 사는데 안부 확인해 주는 거 있어요?", ctpv="대구", sgg="남구",
                       source_types=WELFARE_TYPES, k=5)
context = format_context(hits)      # [1] 청크 본문 (출처: 링크, 확인 날짜) …
```

SQL(같은 조건, 같은 원본은 가장 가까운 청크 하나만):

```sql
SELECT * FROM (
  SELECT DISTINCT ON (source_type, source_id)
         chunk_id, source_type, source_id, title, content, source_url, source_checked_at,
         embedding <=> :q AS distance
  FROM rag_chunk
  WHERE status = 'active'
    AND (region_scope IN ('national', 'none')
         OR (ctpv = :ctpv AND (region_scope = 'province' OR sgg = :sgg)))
    AND (period_end IS NULL OR period_end >= current_date)
    AND NOT (allergens && :allergies)
  ORDER BY source_type, source_id, embedding <=> :q
) best
ORDER BY distance
LIMIT 5;
```

- 지역은 `welfare.query.resolve_region()`으로 먼저 정규화한다(앱 입력 `대구`·`남구` → `대구광역시`·`남구`).
- 같은 사업이 긴 문서라 청크가 여러 개면 근거가 한 사업으로 채워질 수 있어, 원본 단위로 하나만 남긴다.
- **'근거 없음' 판단**(`rag_search_report.md` 2절): KURE-v1 유사도는 0.4~0.7에 몰려 있어 문턱값 하나로는 정답 질문과 정답 없는 질문을 완전히 가르지 못한다(11/07 평가: 정답 1위 질문의 1위 유사도 최소 0.413, 정답 없는 질문 최대 0.520). 그래서
  - 1위 유사도 < 0.40 → 근거 없음(정답 질문 최소값 0.413보다 조금 낮게 잡음). 대화 AI에 근거를 주지 않고 "확인되지 않는다 + 공식 문의처(보건복지상담센터 129, 주민센터)" 안내
  - 0.40 이상 → 상위 5개를 근거로 주되, 프롬프트에 "근거가 질문과 맞지 않으면 모른다고 하고 문의처를 안내하라, 근거에 없는 사업·금액·전화번호를 만들지 말라"를 넣는다
  - 보고서의 제안 문턱값(0.534)은 정답 없는 질문을 모두 거르지만 정답 질문 4개도 거르므로 참고값으로만 쓴다
- 모델은 처음 받은 뒤 `HF_HUB_OFFLINE=1`로 실행한다. 이 값이 없으면 모델을 올릴 때마다 Hugging Face에 접속해 확인하므로, 시연장 인터넷이 불안하면 시작이 늦거나 실패할 수 있다.

## 6. 서버 실측 (`rag.bench`)

기업 서버(Python 3.10) — Docker의 Python 3.12에서:

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
- 판정 기준: 질문 임베딩 p95 ≤ 0.5초, 모델을 올린 뒤 남은 메모리 ≥ 1GB, 측정 중 스왑 증가 ≤ 100MB. 하나라도 넘으면 `move`.
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
