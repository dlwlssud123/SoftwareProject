# 공공데이터 갱신·판본 관리 안내

| 항목 | 내용 |
|---|---|
| 작성 | 최재영 (데이터) |
| 대상 | worker 일정 등록·운영 API(이진녕), 관리자 갱신·품질 화면(김민찬) |
| 기준 | 기획서 CORE-10 "원문·출처·확인 시각 보존, 실패 시 마지막 정상 자료 유지" |
| 명령 | `uv run python -m agetech_data.refresh` (레포 루트, `uv sync` 후) |

## 1. 갱신 대상

| 소스 | 원천 | 범위 (2026-11-01 기준 건수) | 최신본 (gitignore) | 키 |
|---|---|---|---|---|
| `recipes` | 식품안전나라 COOKRCP01 | 전체 1,156건 | `data/raw/recipes/cookrcp01_all.json` | `FOODSAFETY_API_KEY` |
| `nutrition` | 식품영양성분DB 03 판본 | 품목대표 8,807건 | `data/raw/nutrition/foodntr_v03_representative.json` | `DATA_GO_KR_SERVICE_KEY` |
| `welfare_central` | 중앙부처 복지서비스 | 노년층(`lifeArray=006`) 130건 + 상세 | `data/raw/welfare/central_elderly.json` | `DATA_GO_KR_SERVICE_KEY` 또는 `WELFARE_API_KEY` |
| `welfare_local` | 지자체 복지서비스 | 노년층 1,338건 + 상세 | `data/raw/welfare/local_elderly.json` | 〃 |
| `meal_facilities` | 전국무료급식소표준데이터(지자체 제공) | 전국 1,282행 (2026-11-07) | `data/raw/facilities/free_meal.json` | `DATA_GO_KR_SERVICE_KEY` (활용신청 필요) |
| `seasonal_foods` | 농식품 이달의 식재료(국립식량과학원) | 1~12월 123개 + 상세 (2026-11-07) | `data/raw/seasonal/food_month.json` | 〃 (초당 10회 한도 — 호출 간격 0.5초) |

- 앱 번들 자료(`src/frontend/assets/data/*.json`)는 갱신하지 않는다. 앱은 서버 API 연동 후 서버 판본을 쓴다.
- 하루 1회 실행을 권장한다.

### 일일 호출 한도와 복지 상세 나눠 받기

공공데이터포털 개발계정 한도(2026-11-01 응답 헤더 `X-RateLimit-Limit` 기준):

| 오퍼레이션 | 하루 한도 | 필요 호출 |
|---|---|---|
| 중앙부처 복지 상세 | **100** | 노년층 130건 |
| 지자체 복지 상세 | **1,000** | 노년층 1,338건 |
| 지자체 복지 목록 | 1,000 | 3페이지 |

상세를 하루에 전부 받을 수 없으므로 복지 상세는 **캐시에 받는 즉시 저장하고 나눠 받는다.**

- 캐시: `data/raw/welfare/detail_cache_central.json`, `detail_cache_local.json` (gitignore). 실행이 중간에 실패해도 받은 상세는 남는다.
- 목록 내용(조회수 `inqNum` 제외)이 그대로인 항목은 캐시를 다시 쓴다. 쉼표로 이은 목록 칸(생애주기·대상·관심주제 `lifeNmArray` 등)은 **순서를 무시한다** — 원천이 같은 값을 순서만 바꿔 주는 일이 있어서(11/05 → 11/12 지자체 252건, 그때마다 상세를 다시 받고 '변경'으로 셈). 변경 감지(`changes`)도 같은 기준. 11/13 전 서명으로 저장된 캐시는 목록이 그대로면 다시 받지 않고 새 서명으로 옮긴다(첫 실행에서 중앙 118·지자체 735건, 상세 호출 0).
- 받는 순서: 상세가 아직 없는 항목 → 목록이 바뀐 항목 → 30일 넘은 캐시.
- 일일 한도 초과(결과코드 22)를 만나면 **실패가 아니라 중단**하고, 남은 항목은 다음 실행에서 받는다. 목록은 항상 완전해야 게시한다.
- 첫 갱신 기준: 지자체는 2일, 중앙은 2일이면 상세가 모두 채워진다.
- 항목별 `detail_status`: `fresh`(이번에 받음) / `cached`(재사용) / `stale`(목록이 바뀌었는데 아직 다시 못 받아 이전 상세 유지) / `pending`(상세 없음, 목록 필드만).
- 한도를 늘리려면 공공데이터포털에서 운영계정 전환을 신청한다(활용 사례 등록 필요, 사용자 계정 작업).

## 2. 명령

```bash
uv run python -m agetech_data.refresh                                   # 전체
uv run python -m agetech_data.refresh --source welfare_central welfare_local
uv run python -m agetech_data.refresh --list                            # 소스·현재 판본·보관 판본·마지막 상태
uv run python -m agetech_data.refresh --rollback welfare_local 20261101T030000Z
```

| 옵션 | 기본 | 설명 |
|---|---|---|
| `--keep` | 3 | 소스별로 남길 판본 수 (현재 판본은 지우지 않음) |
| `--min-ratio` | 0.8 | 이전 정상본 대비 이 비율 미만이면 게시하지 않음 (빈 응답·부분 응답 방어) |
| `--detail-budget` | 없음 | 복지 상세를 이번 실행에서 최대 몇 건 받을지 (기본: 일일 한도에 닿을 때까지). 수동 확인용 호출을 남겨 두고 싶을 때 |

**종료 코드**: `0` 모두 정상 / `1` 하나 이상 실패(실패한 소스는 이전 판본 유지, 나머지는 정상 게시) / `2` 잘못된 옵션

## 3. 동작 순서와 실패 처리

0. 점검: 지난 실행이 게시·복구 도중 멈춰 최신본이 현재 판본(`current.json`)과 다르면 판본 파일로 다시 맞추고, 남은 백업(`<최신본>.bak`)을 지운다 (`last_repair`에 기록)
1. 키 확인 → 없으면 실패 (이전 판본 유지)
2. 수집: 페이지·상세 조회. HTTP 5xx·응답 해석 실패는 최대 5회 재시도(대기 2·4·6·8초). 인증키 미등록 등 결과 코드는 즉시 실패, 일일 한도 초과는 재시도 없이 중단(복지 상세는 위 "나눠 받기")
3. 검증: 받은 건수 = 원천 totalCount, ID 형식·중복, 필수 필드(레시피 메뉴명, 복지 서비스명), 복지 상세 ID 일치, **급감 방지**(`--min-ratio`)
4. 게시 — **커밋 지점은 `current.json` 포인터 기록**이다. 포인터가 가리키는 판본과 최신본 내용은 항상 같다.
   1. 새 판본 파일(`<최신본 폴더>/snapshots/<소스>/<판본ID>.json`, 판본ID는 UTC 시각) 저장
   2. 이전 최신본을 `<최신본>.bak`으로 백업
   3. 최신본 교체 → 4. 포인터 기록(커밋) → 5. 백업 삭제·오래된 판본 정리
   - 4 전에 실패하면 최신본을 백업으로 되돌리고 새 판본 파일을 지운 뒤 **그 소스를 실패로 처리**한다(이전 판본 유지).
   - 5의 실패(정리 권한 등)는 이미 커밋된 게시를 무르지 않고 `last_warnings`에 남긴다. 남은 판본은 다음 게시 때 정리된다.
   - 복구까지 실패하면 오류에 그 사실을 적고, 다음 실행의 0번 점검이 포인터 기준으로 최신본을 맞춘다.
   - 파일 하나를 쓸 때는 임시 파일 → 이름 바꾸기로 교체해 중간 실패에도 기존 파일이 남는다.
5. 변경 감지: 이전 최신본과 ID 기준 추가·삭제·변경 건수와 예시 ID. 복지는 조회수(`inqNum`)를 빼고 비교
6. 상태 기록: 소스마다 바로 `data/processed/refresh_status.json`에 반영, 실행 기록을 `refresh_log.jsonl`에 한 줄씩 추가. `serving`은 실제 포인터를 따르므로, 상태 기록 전에 멈췄어도 다음 실행에서 맞춰진다

**되돌리기**(`--rollback`)도 같은 커밋 순서다. 포인터 기록 전에 실패하면 최신본·현재 판본은 그대로이고 종료 코드 1이다.

키와 키가 들어간 URL은 출력·오류 메시지·상태 파일·판본 파일 어디에도 남기지 않는다.

## 4. 상태 파일 — `data/processed/refresh_status.json`

관리자 화면·운영 API가 읽는 파일이다. 최상위 `schema_version`, `updated_at`, `sources.<소스>`:

| 필드 | 설명 |
|---|---|
| `label` | 소스 표시 이름 |
| `last_attempt_at`, `last_status`, `last_error`, `last_duration_sec` | 마지막 시도 시각(UTC)·`ok`/`failed`·오류 문장(키 없음)·소요 초 |
| `last_success_at`, `consecutive_failures` | 마지막 성공 시각, 연속 실패 횟수 (성공 시 0) |
| `serving` | **지금 쓰고 있는 판본** `{snapshot_id, file, sha256, item_count, fetched_at, published_at, rollback?}` — 실제 포인터(`current.json`)와 같음. 실패하면 이전 판본 그대로 |
| `item_count`, `previous_count` | 마지막 성공 판본 건수, 그 이전 건수 |
| `changes` | `{first_snapshot, added, removed, changed, unchanged, samples:{added, removed, changed}}` (예시 ID 최대 20개) |
| `quality` | 소스별 품질 요약. 레시피는 레시피 품질 검증 판정 건수 `{ok, flagged, hold}`, 복지는 `{detail_status: {fresh, cached, stale, pending}}`, 무료급식소는 `{rows, coords_missing, phone_missing, reference_years}`, 이달의 식재료는 `{by_month, detail_status}` |
| `details` | 수집본 meta의 상세 요약(소스마다 모양이 다름, 없으면 `null`). 복지: `{counts, fetched_this_run, remaining, stopped_by_quota, daily_limit, max_age_days}` — `remaining > 0`이면 다음 실행에서 이어 받음. 이달의 식재료: `{requested, failed}` — `failed > 0`이면 수집본 `complete: false`(DB 적재는 `--allow-partial-details`일 때만) |
| `rolled_back_at` | 되돌리기를 했으면 그 시각 |
| `last_warnings` | 마지막 실행의 경고(게시는 됐지만 오래된 판본 정리·백업 삭제 실패 등). 없으면 `[]` |
| `last_repair` | 실행 시작 점검에서 최신본을 다시 맞췄으면 `{at, note}` |

**관리자 화면 권장 표시**: 소스별 `serving.snapshot_id`·`fetched_at`(원천 확인 시각), `last_status`, `consecutive_failures ≥ 1`이면 경고, `last_warnings`가 있으면 주의, `changes`의 추가·삭제·변경 건수, 레시피 `quality.hold` 건수, 복지 `details.remaining`(상세 미수집 건수), 이달의 식재료 `details.failed`(상세 받기 실패 건수).

**2026-11-01 첫 실행 결과**: 레시피 1,156건·영양 8,807건 정상(두 번째 실행 변경 0건). 복지는 상세 한도를 첫 시도에서 소진해 목록만 게시(중앙 130·지자체 1,338건, 상세 `pending`) — 다음 실행부터 상세를 채운다.

## 5. 매일 한 번에 돌리기 — `app.jobs.daily_refresh`

수집부터 DB 적재·재료 매핑·RAG 인덱스 적재까지 하루 한 번 이 명령 하나로 돌린다. 실행 기록은 `job_runs`(`kind = 'public_data_daily'`)에 남는다.

```bash
cd src/backend
uv run python -m app.jobs.daily_refresh                  # 전체
uv run python -m app.jobs.daily_refresh --dry-run        # 단계·명령만 보기 (DB 안 씀)
uv run python -m app.jobs.daily_refresh --skip-refresh   # 수집 없이 지금 수집본으로 다시 적재 (재시도)
RAG_PYTHON=<embed extra가 깔린 python> uv run python -m app.jobs.daily_refresh   # RAG 단계용 (아래)
```

| 순서 | 단계 | 명령 (각각 별도 프로세스) | 건너뛰는 경우 |
|---|---|---|---|
| 1 | `refresh` | `agetech_data.refresh` (전체 소스, `--source`로 줄일 수 있음) | `--skip-refresh` |
| 2 | `import_welfare` | `app.jobs.import_welfare --apply` (중앙·지자체 한 트랜잭션) | 수집본이 아직 미완성(복지 상세가 하루 한도로 남음) |
| 3 | `import_public_data` | `app.jobs.import_public_data --apply` (레시피·식품) | 〃 |
| 4 | `import_meal_facilities` | `app.jobs.import_meal_facilities --apply` | 〃 |
| 5 | `import_seasonal` | `app.jobs.import_seasonal --apply` (DB 활성 레시피 기준 연결) | 〃 (제철 상세 실패) |
| 6 | `map_recipe_foods` | `app.jobs.map_recipe_foods --apply` | — |
| 7 | `welfare_build` | `agetech_data.welfare.build --no-report` (커밋 대상 보고서는 안 건드림) | `--no-rag` |
| 8 | `recipes_contract` | `agetech_data.recipes.contract --input data/raw/recipes/cookrcp01_all.json --no-sample --output-json data/processed/recipes_api_all.json` | `--no-rag` |
| 9 | `rag_index` | `agetech_data.rag.index` — RAG 파이썬 | 이번 실행에서 2·3·7·8 중 하나라도 정상이 아님 / 임베딩 환경 없음 |
| 10 | `rag_export` | `agetech_data.rag.export` — RAG 파이썬 | 9가 정상이 아님 |
| 11 | `rag_load` | `psql -X -v ON_ERROR_STOP=1 -f load_index.sql` (`data/processed/rag`에서) | 10이 정상이 아님 / psql 없음 / RAG 표(`rag_index_version`·`rag_chunk`) 없음 |

- **다시 돌려도 안전하다.** 적재는 모두 같은 수집본이면 `already_imported`, RAG는 같은 판본이면 적재·전환하지 않는다.
- **기다림은 실패가 아니다.** 미완성 수집본·임베딩 환경 없음·psql/RAG 표 없음은 `skipped`(이유 코드 `incomplete_snapshot`·`needs_not_ok`·`no_embed_env`·`no_psql`·`no_rag_tables`)로 남고 실행은 성공이다. 미완성 수집본은 적재하지 않고 DB를 마지막 완성본 상태로 둔다 — 복지 상세는 다음 실행에서 이어 받은 뒤 적재된다.
- **실패해도 뒤 단계는 계속한다.** 한 소스 수집이 실패하면 그 소스는 마지막 정상 판본으로 적재된다(같은 판본이면 건너뜀). 다만 RAG는 이번 실행에서 복지·레시피 적재가 정상이었을 때만 만든다 — 새 인덱스 판본이 늘 DB 게시 판본과 맞게.
- 실행 결과: 하나라도 `failed`면 실패, `job_runs.error_code` = 처음 실패한 단계 이름. 종료 코드 0 성공 / 1 실패 / 2 `--job-id`가 맞지 않음 / 3 다른 실행이 진행 중.
- **동시 실행 막기**: 세션 advisory lock(키 `6711061157`)으로 하루 실행은 하나만. 강제 종료로 `running`에 남은 같은 종류 행은 다음 실행이 `failed`·`interrupted`로 정리한다. 적재마다 잡는 잠금(`6711061156`)은 그대로다.
- **worker와 연결**: worker가 `queued` 행(재시도면 `failed` 행)을 만들고 `--job-id <id>`로 넘기면 그 행을 `running` → `succeeded`/`failed`로 바꾸고 `attempts`를 1 올린다. 없으면 행을 새로 만든다. 재시도 간격(`next_run_at`)은 worker가 정한다.
- **RAG 파이썬**: `rag.index`·`rag.export`는 numpy·sentence-transformers가 필요하다(백엔드 가상환경에는 없음). `--rag-python` 또는 `RAG_PYTHON`에 `uv sync --extra embed`로 만든 루트 가상환경의 python을 준다. 바뀐 청크가 없으면 모델을 올리지 않는다(0.4초). 바뀐 청크가 있으면 그 단계 동안만 모델(약 2.5GB)을 올린다 — 같은 서버에서 AI 도우미 API가 모델을 올려 두고 있으면 메모리를 함께 본다.
- **psql**: `load_index.sql`은 psql 전용 명령(`\gset`·`\if`·`\copy`)을 쓴다. 서버에 psql(postgresql-client)이 없거나 RAG 표가 아직 없으면(SQL 초안 v3, Alembic 반영 전) `rag_load`만 건너뛴다. 접속 정보는 `DATABASE_URL`에서 `PGHOST`·`PGPORT`·`PGUSER`·`PGPASSWORD`·`PGDATABASE` 환경변수로 넘긴다(명령줄에 비밀번호 안 남김).
- **기록 파일** (gitignore): `data/processed/daily_refresh_status.json` — 마지막 실행 `{job_run_id, status, started_at, finished_at, error_code, planned, steps[]}`, 단계마다 `{name, status, started_at, duration_sec, exit_code, summary, error | reason·detail}`(진행 중에도 단계마다 갱신). `summary`는 적재 결과 JSON(긴 목록은 10개까지), 수집은 소스별 `{status, items, changes, error}`. `daily_refresh_log.jsonl` — 실행마다 한 줄. `data/processed/daily_refresh/<단계>.log` — 단계별 마지막 출력 전체. 출력에 섞일 수 있는 DB 주소·비밀번호·공공데이터 API 키는 `***`로 가린다.
- **일정**: 서버에서 하루 1회(예: 새벽 3시 KST — 복지 상세 한도가 00시에 초기화됨) cron/systemd timer 또는 worker가 실행하고, 종료 코드 1이면 운영 알림. 실데이터 실행(이 PC, 2026-11-13, 빈 DB + RAG 표): 전체 465초 — 수집 368초(영양 DB 응답이 느려 249초, 제철 상세 135회 81초), 적재 합계 58초, 재료 매핑 31초, RAG 5단계 8초(다시 임베딩 0, 활성 2,878청크). 수집 없이 다시 돌리면(`--skip-refresh`) 적재는 모두 `already_imported`, 약 33초.

## 6. 알려진 제한

- 판본 파일은 원문 전체라 크다(영양 약 34MB/판본). `--keep`으로 보관 수를 조절한다.
- 복지 정제(지역 정규화·필드 정리)와 검색용 판본(RAG 청크) 갱신은 각각 지자체 복지 작업·RAG 작업에서 이 최신본을 읽어 만든다.
- 원천 API의 하루 호출 한도·응답 지연은 운영 중 실제 값으로 다시 확인한다.
