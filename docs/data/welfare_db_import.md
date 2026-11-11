# 복지 원천 DB 적재·재개 절차

> **2026-11-11부터 DB 적재 입력은 데이터 갱신 수집본(중앙·지자체 노년층)이다.** 아래 "현재 기준"을 따른다. 맨 아래 "11/05 기록"은 이전 방식(`agetech_data.welfare.client` 수집본 `central_all.json`)이며 지금은 적재에 쓰지 않는다.

## 현재 기준 (11/11~) — 갱신 수집본 → DB

복지 API·RAG·DB가 같은 수집본과 같은 정제 레코드를 쓰게 한다. 그래서 RAG 청크를 DB의 게시 판본과 맞출 수 있고(`rag_source_active`), 지자체 사업(시범 지역 대구 남구 사업 전부)도 같은 방식으로 들어간다.

| 항목 | 내용 |
| --- | --- |
| 입력 | `data/raw/welfare/central_elderly.json`·`local_elderly.json` — `agetech_data.refresh --source welfare_central welfare_local` 결과 |
| 정제 | `agetech_data.welfare.normalize` (`welfare_contract.md` 2절). 복지 API 표본·RAG 청크와 같은 레코드 |
| 판본 행 변환 | `agetech_data.welfare.revision.revision_rows` |
| 출처 구분 | 중앙: provider `ssis:NationalWelfareInformationsV001`, scope `central_nationwide` / 지자체: provider `ssis:LocalGovernmentWelfareInformations`, scope `local`. 누락 판정은 출처별 |
| 판본 기준 | `normalized` = 정제 레코드에서 실행마다 바뀌는 칸(`detail_status`·`detail_fetched_at`·`source_fetched_at`·`raw_sha256`)을 뺀 것. `content_sha256` = 그 해시(RAG가 같은 함수 `content_sha256`로 맞춤), `fingerprint` = 내용 + 정제 버전 `refresh-welfare-v1`. **조회수·확인 시각·캐시 상태만 바뀌면 새 판본을 만들지 않는다.** `raw`는 수집 항목 그대로(조회수 포함) |
| 구조화 칸 | `title`=`name`, `summary`, `target_text`=`target_detail`, `selection_text`=`selection_criteria`, `benefit_text`=`benefits`, `application`=`apply_guides`, `contacts`, `source_url`=`detail_url`, `criteria_year`. 나머지 칸(신청 방법 설명·서식·법령·기간 등)은 `normalized`에 있다 |
| 품질 | `hold`: 이름·상세·공식 링크(복지로 상세 + 같은 사업 ID) 중 하나라도 없음 → 게시하지 않음. `flagged`: 품질 표시나 미확인 필드(`unverified:<필드>`)가 있음 → 게시. 나머지 `ok` |
| 지역 | 표 칸은 없다. `normalized`의 `scope`(`national`/`province`/`district`)·`ctpv`·`sgg`. 복지 API 조회에 칸이 필요하면 그때 추가한다 |
| 완전성 | 수집본 meta의 `complete`(상세 대기 없음)·`items_sha256`·건수·`kind`·`service`를 확인한다. 상세 대기가 있으면 `--allow-partial-details`로만 적재하고 누락 판정에 쓰지 않는다 |

저장소 루트에서 실행한다(DB 연결은 backend `.env`).

```powershell
uv run python -m agetech_data.refresh --source welfare_central welfare_local   # 복지 하루 1회

Set-Location src/backend
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m app.jobs.import_welfare --dry-run   # 기본 --source all = 중앙·지자체
.venv/Scripts/python.exe -m app.jobs.import_welfare --apply     # 두 출처를 한 트랜잭션으로
.venv/Scripts/python.exe -m app.jobs.import_welfare --verify
# 한 출처만: --source central|local, 다른 파일: --input <경로> (한 출처일 때만)
```

- 11/11 이전에 받은 수집본은 meta에 `complete`·`items_sha256`이 없어 거부된다 → 갱신을 한 번 돌린 뒤 적재한다.
- 이전 방식으로 넣은 중앙 사업(전 생애주기 461건)은 갱신 수집본(노년층 130건)에 없는 사업이 완전한 두 번의 적재 뒤 `missing`이 된다. 노년층 사업은 정제 버전이 바뀌어 새 판본 하나씩 생긴다.
- 레시피 갱신 수집본(`cookrcp01_all.json`)도 meta에 `complete`·`items_sha256`을 써서 `app.jobs.import_public_data --dataset recipes`가 그대로 받는다.
- `agetech_data.welfare.client`·`central_snapshot.py`는 지우지 않았다. API 계약 표본(`export_api_contract --welfare-snapshot`)이 아직 이 형식을 쓴다. 예정 API 계약(`app/schemas/catalog.py` `WelfareRecord`)은 `scope=local`과 `region_scope`·`ctpv`·`sgg`를 받는다(`normalized`의 `scope`·`ctpv`·`sgg` 그대로).

### 11/11 실데이터 확인 (로컬 PostgreSQL 16, `alembic upgrade head`)

| 구분 | 결과 |
| --- | --- |
| 중앙 | 130건 적재, `ok` 130, 상세 대기 0 |
| 지자체 | 1,338건 적재, `ok` 1,006·`flagged` 332, `hold` 0, 상세 대기 0 |
| verify | 1,468건 원문 재정제·구조화 칸 대조 통과 |
| 재실행 | 같은 파일 → 같은 run 재사용(추가 0) / 조회수만 바뀐 다음 날 파일 → 새 판본 0 |
| 시범 지역 | 대구 남구 사업 4건·대구시 전체 10건 활성 |
| RAG 연결 키 | DB 활성 판본 `content_sha256` = `welfare_elderly.json` 레코드 해시 1,468/1,468 |
| 레시피 | 갱신 수집본 그대로 1,156건 적재 |

## 11/05 기록 — `agetech_data.welfare.client` 수집본 기준 (지금은 적재에 쓰지 않음)


2026-11-05 로컬 PostgreSQL에 중앙부처 복지서비스 목록 461건을 적재했다. 상세 API가 HTTP 429 및 공식 오류 코드 22(일일 요청 허용 횟수 초과)를 반환하여 **상세 80건만 확보했고 381건은 상세 수집 대기**다. 전체 상세 수집 완료 상태가 아니다.

### 적재 결과

| 구분 | 결과 |
| --- | --- |
| 출처 | 한국사회보장정보원 / 복지로 중앙부처복지서비스 API V001 |
| 목록·원문 판본 | 461건 / 461건 |
| 상세 확보 | 80건, `detail_state=ready`, `publication_status=published` |
| 상세 대기 | 381건, `detail_state=pending`, `publication_status=hold`, 활성 판본 null |
| 신청 상태 | 461건 모두 `unknown`. ‘상세 확보’는 ‘현재 신청 가능’이라는 뜻이 아님 |
| 검증된 모집 공고·회차 | 0건. 원천에 없는 회차·기간은 생성하지 않음 |
| 재실행 | 서비스·판본 추가 0건, 같은 run 재사용 |
| 전수 대조 | 461건 저장 원문 XML·정규화 해시·구조화 필드 대조 통과 |
| DB 리비전 | `20261105_02`, metadata 비교 시 추가 변경 없음 |

적재 run은 `6454a9b7-de7a-41ee-aee0-8855d26a9181`, 입력 지문은 `ac1fca0db2d89969a4bd463dcc98257fc0cb0d51a272aa8bf2e3965c4a786d37`이다. 기존 레시피 1,156건·식품 8,807건도 유지됨을 확인했다.

원천 API는 사업 안내다. 지원주기 `sprtCycNm=수시`를 상시 접수로 해석하지 않는다. 대상·선정 기준·지원 내용·신청 절차·문의처의 반복 XML 항목을 보존하며, 정형 신청 기간이 없으므로 `open` 공고를 임의 생성하지 않는다.

### 저장 구조

- `welfare_services`: provider + 원천 ID 유일성, 전국 범위, 게시 상태, 활성 판본, 목록 확인/상세 확인 시각, 마지막 성공 수집 run, 연속 누락 횟수.
- `welfare_revisions`: 원문 목록·상세 XML, 정규화 내용, 해시·파서 버전, 제목·대상·선정 기준·지원·신청·문의·출처, 상세 준비·품질 상태. 조회수와 확인 시각만 달라지면 본문 판본은 추가하지 않는다.
- `welfare_notices`: 향후 공식 모집 회차 ID·기간 원문·기간 유형·시작·마감·접수 상태를 저장한다. 사업과 회차를 분리하고, 다른 사업의 판본은 복합 FK로 참조하지 못하게 한다. 현재 실제 행은 0건이다.
- `data_import_runs`: 기존 공통 run을 재사용한다. 스냅샷 메타·파일 해시와 사업별 판본/확인 시각 manifest를 기록한다.

임베딩·벡터·청크·임베딩 작업 큐와 RAG API는 이번 범위에서 생성하지 않았다. 기업 서버에도 적용하지 않았다.

### 수집·적재·검증

루트 `.env`의 기존 `WELFARE_API_KEY`를 사용한다. DB 연결은 backend `.env`를 사용한다. 키·키가 포함된 요청 URL은 로그·스냅샷·Git에 저장하지 않는다.

저장소 루트에서 실행한다.

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src/data'

# 기본은 전체 상세 수집. 실패 시 기존 정상 전체 파일을 교체하지 않는다.
src/backend/.venv/Scripts/python.exe -m agetech_data.welfare.client

# 한도로 상세를 다 받지 못했을 때 목록/대기를 명시적으로 저장한다.
src/backend/.venv/Scripts/python.exe -m agetech_data.welfare.client --allow-partial-details

Set-Location src/backend
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m alembic check

# 정상 전체 스냅샷: 기본 dry-run → apply → verify
.venv/Scripts/python.exe -m app.jobs.import_welfare --dry-run
.venv/Scripts/python.exe -m app.jobs.import_welfare --apply
.venv/Scripts/python.exe -m app.jobs.import_welfare --verify
```

현재처럼 상세가 일부인 파일은 명시적으로 지정한다. 부분 상세 파일은 기본 명령으로 적재되지 않는다.

```powershell
.venv/Scripts/python.exe -m app.jobs.import_welfare --input ../../data/raw/welfare/central_all.partial.json --allow-partial-details --dry-run
.venv/Scripts/python.exe -m app.jobs.import_welfare --input ../../data/raw/welfare/central_all.partial.json --allow-partial-details --apply
.venv/Scripts/python.exe -m app.jobs.import_welfare --input ../../data/raw/welfare/central_all.partial.json --allow-partial-details --verify
```

### 한도 확보 후 이어받기

1. 공공데이터포털의 **중앙부처복지서비스 상세조회 기능** 일일 한도를 확인·증설한다. 전체 상세 1회 점검만 461회 호출이 필요하며 목록·재시도 여유를 별도로 확보해야 한다.
2. 루트에서 기존 수집 명령을 다시 실행한다. `data/raw/welfare/central_all.checkpoint.json`의 성공 상세부터 이어받는다. 새 목록의 ID 집합이 같고 7일 이내인 체크포인트만 재사용하며 실제 상세 확인 시각은 보존한다.
3. 전체를 받으면 `central_all.json`에 `complete=true`로 저장하고 체크포인트를 제거한다. 정상 완료 후 다음 수집은 새로 점검한다. 부분 파일이 정상 전체 파일을 덮어쓰지 않는다.
4. 전체 파일로 dry-run → apply → verify를 실행한다. 기존 80건은 내용이 같으면 판본을 재사용하고, 대기 자료는 검증된 새 판본으로 전환한다.

체크포인트는 일회 초기 수집을 재개하기 위한 것이다. 마지막 상세 확인이 오래된 자료도 당일 검증된 것으로 표시하지 않는다. 매일 전체 상세 확인 목표는 호출 한도를 확보한 뒤에 적용할 수 있다. 지자체 자료는 해당 API 승인·필드 확인 후 별도 scope로 추가한다.

### 갱신·마감·실패 처리

- 기본은 파일만 검증하는 dry-run이다. apply는 advisory lock 및 단일 트랜잭션으로 전체 자료와 활성 포인터를 처리하며, 실패하면 롤백한다.
- 파일의 완결성·건수·해시·공식 서비스 ID/URL·시간대를 확인한다. 과거 스캔으로 최신 상태를 되돌리지 않는다.
- 상세 실패가 있는 부분 입력은 누락 판정에 사용하지 않는다. 기존 정상 상세도 대기 자료로 교체하지 않는다. 완전한 서로 다른 두 번의 성공 스캔에서 누락된 사업만 `missing`으로 비활성화한다. 동일 파일 재실행은 누락 횟수를 늘리지 않는다.
- 수동 철회 상태를 일반 수집이 다시 게시하지 않는다. 원문과 판본은 물리 삭제하지 않는다.
- 검증된 공고가 생기면 `open_notice_condition(as_of)`로 게시·활성 판본·접수 상태·기간을 함께 검사한다. 마감 시각과 같거나 이후면 검색 대상에서 제외하며, 기간 미확인은 신청 가능 목록에 포함하지 않는다.
- `expire_notices`는 마감된 open/scheduled 공고를 closed로 변경하고 원문을 남긴다. 현재 apply에서 호출된다. **자동 스케줄러와 실제 RAG 검색·답변 캐시는 아직 연결하지 않았다.** 벡터 정리·캐시 무효화는 해당 기능 구현 시 연결해야 한다.

### 실행 검증

- backend 34개 통과: 기존 HTTP·레시피/식품 회귀, 복지 재실행·의미 판본·롤백·완전 스캔 누락·복귀·과거 입력 거절·부분 입력 보존·기간 미확인·마감 경계·소유 판본 FK.
- data 123개 통과: 수집·재개·반복 XML·조회수 제외 해시·일일 한도 즉시 중단·429 backoff·부분 파일 표시·정상 파일 보존 포함.
- 실제 로컬 apply → 재실행 → 전수 verify와 FK/check 제약 확인. Ruff lint·포맷 검사 완료.
- 기존 Starlette TestClient의 httpx 사용 중단 예정 경고 1건은 남아 있다.
