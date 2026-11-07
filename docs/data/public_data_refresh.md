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
- 목록 내용(조회수 `inqNum` 제외)이 그대로인 항목은 캐시를 다시 쓴다.
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
| `details` | 복지만: `{counts, fetched_this_run, remaining, stopped_by_quota, daily_limit, max_age_days}` — `remaining > 0`이면 다음 실행에서 이어 받음 |
| `rolled_back_at` | 되돌리기를 했으면 그 시각 |
| `last_warnings` | 마지막 실행의 경고(게시는 됐지만 오래된 판본 정리·백업 삭제 실패 등). 없으면 `[]` |
| `last_repair` | 실행 시작 점검에서 최신본을 다시 맞췄으면 `{at, note}` |

**관리자 화면 권장 표시**: 소스별 `serving.snapshot_id`·`fetched_at`(원천 확인 시각), `last_status`, `consecutive_failures ≥ 1`이면 경고, `last_warnings`가 있으면 주의, `changes`의 추가·삭제·변경 건수, 레시피 `quality.hold` 건수, 복지 `details.remaining`(상세 미수집 건수).

**2026-11-01 첫 실행 결과**: 레시피 1,156건·영양 8,807건 정상(두 번째 실행 변경 0건). 복지는 상세 한도를 첫 시도에서 소진해 목록만 게시(중앙 130·지자체 1,338건, 상세 `pending`) — 다음 실행부터 상세를 채운다.

## 5. 일정 등록 (worker 담당과 협의)

- 서버 worker에서 하루 1회 `uv run python -m agetech_data.refresh`를 실행하고, 종료 코드 1이면 운영 알림을 보낸다.
- 갱신 뒤 정제·매핑을 다시 만들려면 이어서 `uv run python -m agetech_data.nutrition.build`(영양 매핑)를 실행한다.
- 같은 소스를 동시에 두 번 실행하지 않는다(판본 파일 경합 방지). 잠금은 worker 쪽에서 둔다.

## 6. 알려진 제한

- 판본 파일은 원문 전체라 크다(영양 약 34MB/판본). `--keep`으로 보관 수를 조절한다.
- 복지 정제(지역 정규화·필드 정리)와 검색용 판본(RAG 청크) 갱신은 각각 지자체 복지 작업·RAG 작업에서 이 최신본을 읽어 만든다.
- 원천 API의 하루 호출 한도·응답 지연은 운영 중 실제 값으로 다시 확인한다.
