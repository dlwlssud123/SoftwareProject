# ValueFlow 공통 백엔드

Python 3.12·FastAPI 기반이다. 환경설정, DB 세션, 공통 응답·오류, 요청 ID, 상태 확인과 레시피·식품·복지 원천 테이블·적재 CLI를 구현했다. 게스트·카카오 세션, 관리자 권한 확인, 레시피·복지 DB 조회, 식단·복지 후보 추천, 동의 기반 프로필, 하루 식단표·레시피/복지 저장을 제공한다.

API 계약은 [API 명세서](../../docs/설계/API_명세서.md), 자동 생성 스냅샷은 [OpenAPI JSON](../../docs/설계/openapi.json)을 따른다.

장보기는 인증된 `GET /api/v1/shopping-lists/{날짜}`, `PATCH /shopping-lists/{날짜}/items/{item_key}`로 조회·구매 체크를 제공한다. 저장한 식단의 원문 재료를 검증된 단위끼리 모으고 불명확한 분량은 그대로 보존한다. 구성 메뉴나 필요 재료가 바뀌면 다시 체크하도록 `source_hash`를 비교한다. `20261120_02`는 체크 테이블을 추가하며 식단·체크 수정은 같은 사용자 잠금으로 조정한다. 쿠팡 검색에는 공개 재료명만 전달한다.

식품 검색·상세(`GET /api/v1/foods`, `/foods/{food_id}`)와 분량별 영양 미리보기(`POST /api/v1/nutrition/calculate`)를 제공한다. 활성 원천 판본과 데이터팀의 분량 계산 로직을 사용하고, 결측·단위 근사·환산 불가를 응답에 표시한다. 미리보기는 섭취 기록을 저장하지 않는다.

확정 섭취는 인증된 `/api/v1/meals`의 생성·목록·상세·수정·삭제 API로 별도 보관한다. 서버에서 재계산한 영양·원천 판본·환산 근거를 스냅샷으로 유지하며, 생성 재시도는 `Idempotency-Key`, 수정·삭제 경합은 기록 `version`으로 제어한다. 사진 분석 제공자 연동과 앱의 직접 선택·확정 화면 연결은 후속 작업이다. 필요한 DB 이력은 `20261118_01 → 20261119_01 → 20261120_01`이며 PR #58의 선행 복지 메모 스키마를 같은 내용으로 재사용한다.

저장 구조는 [DB 마이그레이션 계획](../../docs/설계/DB_마이그레이션_계획.md)을 따른다. 2026-11-05 로컬 DB에 전체 레시피 1,156건과 식품 품목대표 8,807건을 별도 테이블로 적재했다. 실행·검증 절차와 범위는 [전체 데이터 적재 기록](../../docs/data/public_db_import.md)에 정리했다.

복지는 중앙부처 목록 461건을 저장했고, API 일일 한도로 상세 80건·수집 대기 381건이다. 신청 기간·현재 신청 가능 여부는 미확인으로 유지한다. [복지 적재·재개 절차](../../docs/data/welfare_db_import.md)를 따른다. RAG 임베딩·지자체 자료·자동 주기 실행은 후속 범위다.

## 개발환경 준비

Docker Desktop의 Linux 엔진과 uv를 준비한 뒤 `src/backend`에서 실행한다. Python 버전은 `.python-version`, 패키지는 `uv.lock`을 따른다.

```powershell
uv sync --locked

# .env가 없는 새 체크아웃에서만 복사한다.
Copy-Item .env.example .env
```

`.env`의 `POSTGRES_PASSWORD`를 개발용 비밀번호로 설정하고, `DATABASE_URL`에도 같은 계정·비밀번호·DB 이름을 반영한다. 비밀번호에 URL 예약문자가 있으면 연결 문자열의 비밀번호 부분을 URL 인코딩한다. 실제 `.env`는 커밋하지 않는다.

```text
DATABASE_URL=postgresql+psycopg://<POSTGRES_USER>:<URL인코딩한비밀번호>@127.0.0.1:5432/<POSTGRES_DB>
```

현재 작업 PC의 비어 있던 `.env`에는 임의 생성한 개발 비밀번호와 연결 주소를 설정했다. 기존 파일을 예시 파일로 덮어쓰지 않는다.

## 실행

```powershell
docker compose up -d --wait db
uv run --locked alembic upgrade head
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# uv가 PATH에 없지만 .venv가 준비된 경우
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

DB는 `pgvector/pgvector:0.8.7-pg16-bookworm` 이미지를 사용하며 로컬 `127.0.0.1:5432`에서 접근한다. 새 DB 볼륨을 처음 초기화할 때 `docker/initdb/001-vector.sql`로 vector 확장을 활성화한다. DB 데이터는 Compose의 `postgres_data` 볼륨에 보관한다. 기존 볼륨의 비밀번호는 `.env` 변경만으로 바뀌지 않는다.

| 경로 | 정상 결과 |
| --- | --- |
| `GET /api/v1/health/live` | 서버가 실행 중이면 200 |
| `GET /api/v1/health/ready` | 실제 DB 조회 성공 시 200, 연결 실패 시 503 |
| `POST /api/v1/auth/guest` | 빈 JSON `{}`로 게스트 사용자·세션 발급, 201 |
| `GET /api/v1/auth/me` | Bearer 세션 검사와 현재 사용자 확인 |
| `POST /api/v1/auth/refresh` | 기존 토큰을 폐기하고 같은 사용자 새 세션 발급 |
| `DELETE /api/v1/auth/session` | 현재 세션 폐기 |
| `GET /api/v1/admin/me` | 관리자 세션이면 200, 일반 사용자이면 403 |
| `POST /api/v1/admin/login` | 운영자가 발급한 전용 아이디·비밀번호로 관리자 세션 발급 |
| `/api/v1/content-topic-requests` | 생활 가이드·영상 주제 접수·본인 조회·취소, 동일 전송 번호 재시도 보호 |
| `/api/v1/admin/content-topic-requests` | 관리자 요청 검토·답변·게시 가이드 연결·감사 조회 |
| `GET /api/v1/recipes` | 활성 레시피 목록, 검색·분류·조리방법·알레르기 제외와 페이지 조회 |
| `GET /api/v1/recipes/{recipe_id}` | 원천 ID로 활성 레시피 상세 조회 |
| `GET/PATCH/DELETE /api/v1/profile` | 본인 프로필 조회·동의 후 저장·철회 또는 삭제 |
| `GET /api/v1/welfare` | 게시된 활성 복지 목록, 검색·지역·중앙/지자체 필터와 페이지 조회 |
| `GET /api/v1/welfare/{service_id}` | 원천 ID로 상세·신청 안내·문의처·판본·확인 시각 조회 |
| `POST /api/v1/welfare/recommendations` | 지역 범위와 연령·독거 관련 원문 단서에 따른 후보 정렬, 자격 확정 아님 |
| `GET /api/v1/saved-welfare` | 본인이 저장한 복지 목록 |
| `GET/PUT/DELETE /api/v1/saved-welfare/{service_id}` | 본인 저장 상태·저장·해제, 반복 요청 시 중복 없음 |
| `/docs` | Swagger UI |
| `GET /api/v1/meal-facilities` | 게시된 급식소 목록, 지역 우선순위·검색·페이지·이용 전 확인 안내 |
| `GET /api/v1/meal-facilities/{facility_id}` | 급식소 UUID 상세, 출처·자료 기준일·원천 확인일 |
| `GET /api/v1/seasonal-foods` | 월별 제철 식재료 요약, 월 생략 시 한국 시간의 현재 월 |
| `GET /api/v1/seasonal-foods/{food_id}` | 제철 식재료 UUID 상세와 외부 쇼핑 검색 링크 |
| `GET /api/v1/seasonal-foods/{food_id}/recipes` | 현재 활성 판본과 일치하는 연결 레시피 목록 |
| `GET /api/v1/life-guides`, `GET /api/v1/life-guides/{slug}` | 게시된 생활 가이드 요약·단계별 상세 |
| `GET /api/v1/admin/data-jobs` | 관리자 전용 공공데이터 갱신 작업 현황, 개인 작업 제외 |
| `/api/v1/admin/life-guides` | 관리자 가이드 목록·초안 작성·버전 확인 수정 |
| `POST /api/v1/admin/life-guides/{guide_id}/actions` | 검수 요청·승인/반려·게시·비공개 처리 |
| `GET /api/v1/admin/life-guides/{guide_id}/audit` | 가이드 변경 감사 메타데이터 조회 |
| `/openapi.json` | OpenAPI 명세 |

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/live | ConvertTo-Json -Depth 10
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/ready | ConvertTo-Json -Depth 10
docker compose exec -T db psql -U valueflow_dev -d valueflow -c "SELECT extversion FROM pg_extension WHERE extname = 'vector';"
```

DB 사용자·이름을 바꿨으면 마지막 명령의 인자도 바꾼다. 서버 종료는 실행 터미널에서 `Ctrl+C`, DB 종료는 `docker compose stop db`를 사용한다. 데이터 볼륨은 유지한다.

일반 세션 기본 만료는 7일이며 `.env`의 `SESSION_TTL_SECONDS`로 조정한다. 토큰은 발급·갱신 응답에서만 반환하고 DB에는 해시만 저장한다. 앱의 보안 저장소에 보관하고 로그에 출력하지 않는다. 앱은 카카오 로그인·게스트 연결을, 관리자 웹은 별도 전용 아이디·비밀번호 로그인을 사용한다. 기존 운영자용 `set_user_role` CLI도 유지하지만 공개 권한 변경 API는 없다.

## 관리자 전용 계정

`20261120_04`까지 마이그레이션한 DB에서 운영자가 다음 명령을 실행한다. 비밀번호는 명령 인자·환경변수·문서에 넣지 않고 대화형 프롬프트에서 입력한다. 기본 계정은 생성하지 않는다.

```bash
python -m app.jobs.provision_admin operator
python -m app.jobs.provision_admin operator --reset-password
python -m app.jobs.provision_admin operator --disable
```

첫 명령은 별도의 관리자 사용자를 만들고 비밀번호(15~128자)를 두 번 확인한다. 같은 아이디를 덮어쓰려면 `--reset-password`가 필요하다. 재설정·비활성화는 기존 세션을 폐기한다. 비활성 사용자·일반 사용자로 강등된 계정을 자동으로 활성화하거나 승격하지 않는다. Docker Compose에서는 로그인한 서버 터미널의 `docker compose run --rm --no-deps api python -m app.jobs.provision_admin operator`로 같은 프롬프트를 사용할 수 있다. 실제 운영 계정 생성은 운영자가 직접 수행하며 이번 개발에서 실행하지 않았다.

비밀번호는 고유 salt와 Python 표준 scrypt(N=65536, r=8, p=2)로 해시한다. 이는 [OWASP의 64MiB scrypt 설정](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html#scrypt)을 따른다. API 프로세스당 동시 해시 2개, peer별 5분/30회, 계정별 연속 실패 5회 후 15분 잠금을 적용한다. 입력·hash·salt·세션을 로그/일반 오류로 출력하지 않는다. 제한 peer는 ASGI 연결 주소이며 전달 헤더를 직접 신뢰하지 않는다. 프록시를 공유하면 제한도 공유할 수 있다.

새 관리자 로그인의 절대 재인증 기한은 기본 1시간(`ADMIN_SESSION_TTL_SECONDS`, 300~28800초)이고 `/auth/refresh`로 늘릴 수 없다. 기존 일반 세션은 새 nullable 기한이 null이므로 이전 만료 정책을 유지한다. 웹은 로그인 후 `/admin/me`를 확인하고 메모리에만 세션을 두며, 만료·401/403·로그아웃 때 이전 내용을 제거한다. 운영 웹의 HTTPS API 주소·CORS origin·계정 생성·배포는 별도 확인해야 한다. 관리자 웹 코드는 기존 민찬 담당 `src/admin`에 연결했다.

가이드는 `20261120_03` 마이그레이션 뒤 관리자 세션으로 초안을 작성하고 `submit → approve → publish` 순서로 공개한다. 반려에는 이유가 필요하며 수정하면 비공개 초안으로 돌아간다. 수정·검수·게시에는 최신 `expected_version`이 필요하고 감사 메타데이터를 같은 트랜잭션에 기록한다. 내용·검수 의견·토큰은 감사에 복제하지 않는다. 기존 공개 가이드는 마이그레이션 후에도 공개하며 검수자/검수 시각을 임의로 만들지 않는다. 상세 요청·오류·충돌·보관 규칙은 [API 명세서](../../docs/설계/API_명세서.md)를 따른다. 이 구현은 민찬 담당 `src/admin`의 웹 화면 연결·기업 서버 배포 완료를 의미하지 않는다.

## 사용자 기록과 운영 자료 저장 구조

Alembic `20261110_01`은 기존 레시피·식품·복지 판본과 사용자 데이터를 보존하고 아래 저장 구조를 추가한다.

| 영역 | 저장 방식 |
| --- | --- |
| 섭취 기록 | `meal_logs`와 `meal_log_items`에 섭취 시각, 확정한 식품 판본, g 또는 mL 분량, 영양 계산 결과와 버전을 저장한다. |
| 저장 목록·식단표 | 저장 목록은 사용자와 레시피·복지 서비스의 고유 조합이다. 식단표는 사용자·날짜·끼니별로 선택 당시 레시피 판본 하나를 보관한다. |
| 생활 가이드·급식시설·제철 | 출처와 확인일을 기록한다. 새 자료는 기본 미게시다. 제철 자료는 월과 검수한 레시피 재료명 조합으로 구분한다. |
| 작업 | `job_runs`에 종류·상태·시도 횟수·다음 실행 시각·오류 코드를 기록한다. 사용자 소유 작업과 공통 작업을 구분한다. |

Alembic `20261111_01`은 급식시설·제철 자료에 공공데이터 원천 칸(원천 ID·자료 기준일·품질 표시·정제 레코드)을 더하고, 제철 식재료 상세(`seasonal_foods`)와 레시피 연결(`seasonal_recipe_links`)을 추가한다. 원천 칸이 비어 있는 행은 관리자가 직접 넣은 자료로 보고 적재가 건드리지 않는다. 적재는 `python -m app.jobs.import_meal_facilities`·`import_seasonal`(레시피 적재 뒤)이며 칸 대응·규칙은 `docs/data/facility_seasonal_db_import.md`에 있다.

Alembic `20261111_02`는 레시피 재료 → 식품 매핑(`recipe_ingredient_foods`, 재료 하나·계산에 쓴 식품 판본·g 환산·기여량)과 레시피 계산 영양(`recipe_computed_nutrition`, 레시피 판본 하나)을 추가한다. 원천 레시피가 적은 영양(`recipe_revisions.source_*`)과는 따로 둔다. 계산은 `python -m app.jobs.map_recipe_foods`(레시피·식품 적재 뒤)이며 규칙은 `docs/data/recipe_food_map_db.md`에 있다. Alembic `20261113_01`은 g 환산 상태에 `unit_weight`(출처 있는 개당 중량, 예: 달걀 1개 60 g)를 더한다.

Alembic `20261114_03`은 RAG 검색 표를 만든다: `rag_index_version`(적재한 인덱스 판본, 활성은 하나), `rag_chunk`(청크·KURE-v1 1024차원 `vector`), 되돌리기 함수 `rag_rollback_index(판본)`, 검색이 근거로 써도 되는 게시 원본 뷰 `rag_source_active`. pgvector 확장이 필요하다(`docker/initdb`가 만든다). 적재는 `python -m app.jobs.load_rag_index --apply`(psql 필요 없음, 입력은 데이터 쪽 `rag.export`가 만든 `data/processed/rag/rag_chunk.csv`·`manifest.json`), 확인 `--verify`, 되돌리기 `--rollback <판본>`. 표·적재 규칙은 `docs/data/rag_index_contract.md` 4절, 검색 SQL은 `docs/data/sql/rag_search.sql`. 이 표들은 ORM 모델 없이 마이그레이션 SQL로만 관리하므로 autogenerate·`alembic check`는 건너뛴다(`alembic/env.py`의 `include_name`).

전체 갱신은 `python -m app.jobs.daily_refresh --verify`로 실행한다. 복지만 갱신하는 날은 `--welfare-only`를 더한다. 단계마다 기존 명령을 별도 프로세스로 실행하고 `job_runs`(`kind = 'public_data_daily'`)에 실행 상태와 처음 실패한 단계(`error_code`)를 남긴다. worker는 `queued` 행을 만들고 `--job-id`로 넘기면 된다. 단계·RAG 파이썬·기록 파일은 [데이터 갱신 문서](../../docs/data/public_data_refresh.md), crontab 예시는 [서버 예약 실행](../../docs/data/public_data_refresh.md#서버-예약-실행)에 있다.

DB에서 사용자를 삭제하면 세션·프로필·기록·저장·식단표·사용자 작업도 삭제된다. 프로필 동의 철회는 기존 API대로 프로필만 삭제한다. 원천 판본과 공통 작업은 보존된다. 새 저장 구조를 사용하는 기능별 API와 작업 실행기는 별도 작업에서 연결한다.

## API 계약 인계

[API 명세서 8~9절](../../docs/설계/API_명세서.md)에 세션·권한·DTO 규칙을 정리했다. [catalog.openapi.json](../../docs/설계/catalog.openapi.json)은 미구현 카탈로그 경로의 별도 계약이며 복지 경로 구현 후 현재 `paths`는 비어 있다. [api_examples.json](../../docs/설계/api_examples.json)은 실제 공개 원천을 검증한 표본이다. 실행 `/openapi.json`에는 구현된 경로만 포함한다.

```powershell
uv run --locked python -m app.jobs.export_api_contract
```

API 응답·DTO 수정 후 위 명령으로 스냅샷을 갱신한다. 표본 재생성은 `PYTHONPATH=../data`를 설정하고 `--welfare-snapshot <원천 XML 수집 JSON>`을 추가한다. 스냅샷과 DTO 표본의 일치는 테스트로 확인한다.

## 검증

```powershell
uv run --locked pytest -q
uv run --locked ruff check app tests
uv run --locked ruff format --check app tests

# 현재 준비된 가상환경을 직접 사용할 수도 있다.
.venv/Scripts/python.exe -m pytest -q
```

기본 테스트는 실제 개발 DB를 사용하지 않는다. `RUN_DB_TESTS=1`을 설정하면 UUID로 생성한 격리 스키마에서 Alembic과 적재·롤백·제약을 검증하고, 테스트가 생성한 스키마만 제거한다. 기존 업무 테이블과 데이터는 건드리지 않는다. 테스트 전용 HTTP 경로는 테스트 앱에만 등록된다.

```powershell
$env:RUN_DB_TESTS = '1'
.venv/Scripts/python.exe -m pytest -q
Remove-Item Env:RUN_DB_TESTS
```

## 급식소 위치 검색

급식소 지역 조회는 기존 `GET /api/v1/meal-facilities`를 사용한다. 위치 기반 조회는 `POST /api/v1/meal-facilities/nearby`에 좌표와 반경(기본 5km)을 보내며, 기존 데이터 모듈의 거리 계산·지역 대체·시설 주의사항을 재사용한다. 좌표를 저장하지 않고 POST 응답·오류를 캐시하지 않는다. 반경 내 좌표 있는 시설과 같은 시군구의 좌표 없는 시설을 구분한다. 실제 이동 거리·이용 자격은 보장하지 않으며, 앱 위치 권한 연결과 원천의 서버 적재·실사용 검증은 별도다. 자세한 입력·거리·개인정보 경계는 [API 명세](../../docs/설계/API_명세서.md)의 생활지원 안내 부분을 따른다.

## 콘텐츠 주제 요청

`/api/v1/content-topic-requests`는 생활 가이드·영상 주제를 본인 계정으로 접수·조회·취소한다. 새 전송에는 UUID v4 `submission_id`를 만들고 통신 실패 재시도에는 같은 번호와 같은 내용을 사용한다. 동일 번호의 다른 내용은 409다. 최근 24시간 계정당 새 요청 5건까지이며 취소도 건수에 포함된다. 취소는 원문과 답변을 지우되 재전송 방지용 메타데이터를 남긴다.

응답이 불명확할 때는 목록의 `submission_id` 필터로 접수를 확인한다. 접수 전에도 `POST /api/v1/content-topic-requests/withdraw-submission`에 동일 본문을 보내 취소할 수 있다. 이때 원문 없는 취소 기록을 남겨 늦은 POST가 되살리지 못하게 한다. 미접수 취소 기록은 정상 접수와 별도로 하루 20건까지이며, 접수된 요청의 취소는 기존 5건 한도에 포함된다.

관리자는 `/api/v1/admin/content-topic-requests`에서 판본 확인과 답변을 거쳐 검토·완료·보류한다. 생활 가이드 완료는 승인·게시한 가이드 연결이 필요하고, 영상 요청 처리는 자동 영상 제작을 실행하지 않는다. 마이그레이션 `20261120_06`까지 적용해야 한다. Flutter 요청·안내 화면은 이 API를 사용하며 관리자 요청 처리 웹·운영 자료·실제 배포는 별도다. 상세 요청/응답·재시도·보관 경계는 [API 명세](../../docs/설계/API_명세서.md)의 콘텐츠 주제 요청 부분을 따른다.

## 기업 서버 배포 경계

`src/backend/compose.yaml`은 로컬 DB 개발용이고, 기업 서버의 API·DB 이미지는 [deploy 구성](../../deploy/README.md)으로 실행한다. #57 병합 후 GitHub Actions의 검사·이미지 게시·첫 서버 배포를 확인했다. 관련 main 변경은 활성화된 배포 워크플로로 반영한다. 무거운 임베딩 worker와 데이터 정기 적재 예약은 별도다. API 컨테이너의 DB 주소는 서비스 이름 `db`를 사용한다. 로컬 개발 DB 볼륨과 기업 서버 DB는 별개이며, 서버에서도 Alembic upgrade 후 같은 입력 스냅샷으로 적재·대조 검증한다.

복지·시설·제철·가이드 공개 조회와 관리자 수집 현황, 복지 저장·진행 메모는 이번 작업 브랜치의 신규 API다. 메모에는 `20261119_01` 마이그레이션이 필요하다. 사용자별 최대 2,000자 평문 메모이며 저장 해제 시 같이 삭제한다. 상세 계약은 [API 명세](../../docs/설계/API_명세서.md)의 복지 저장 부분을 따른다. 코드·테스트·PR 공유와 기업 서버 실제 자료 적재·앱 화면 연결은 구분한다.

## 실행 검증 기록

2026-11-03 Windows에서 Python 3.12.16, Docker Engine 29.1.3, PostgreSQL 16.15, pgvector 0.8.7로 확인했다.

- pytest 14개 통과. Starlette의 httpx TestClient 사용 중단 예정 경고 1건이 있다.
- Ruff 정적 검사·포맷 검사 통과, OpenAPI 스냅샷과 실행 코드 일치 확인.
- 실제 Uvicorn HTTP 요청으로 liveness·Swagger·OpenAPI 200, 없는 경로 404, 잘못된 메서드 405와 CORS·요청 ID를 확인.
- DB가 없을 때 readiness 503, Docker DB 준비 후 readiness 200을 확인.
- 실제 PostgreSQL의 임시 테이블 저장·조회와 vector 확장 설치를 확인. 검증용 테이블은 트랜잭션 종료 시 제거.
- Docker Desktop의 잔여 `dockerInference`·`engine.sock` 임시 소켓으로 인한 시작 오류를 복구했다. 사용자 요청에 따라 복구용 백업·설치 임시 폴더는 삭제했다.

2026-11-07 API 계약·인증 기반 검증:

- 실제 PostgreSQL의 격리 스키마를 사용한 백엔드 테스트 78개 통과. 사용자 분리·만료/폐기·권한 해제·동시 갱신 단일 성공·저장 실패 롤백·토큰 비노출과 DTO/표본/스냅샷을 포함한다. 기존 Starlette 경고 1건은 유지된다.
- 최신 main의 자동 갱신 작업을 통합한 뒤 데이터 테스트 222개와 백엔드 Ruff 정적·포맷 검사 통과.
- 기존 레시피 원문 보완을 포함한 Flutter analyze에서 문제 없음, Flutter 테스트 33개 통과. 실기기·APK 배포 검증은 이번 실행 범위에 포함하지 않았다.
- 로컬 DB를 `20261107_01`로 올리고 `alembic check`에서 차이 없음 확인. 기존 레시피 1,156건·영양 8,807건의 활성 판본 대조 검증 통과. 운영용 관리자·테스트 사용자는 생성하지 않았다.
- 실제 Uvicorn HTTP에서 health/live·health/ready·docs·openapi 200, 인증 없는 auth/me·admin/me 401, 예정 recipes 경로 404 확인. 테스트 임시 스키마 잔여 0건.
- 실행 중인 HTTP 경로와 별도 예정 계약을 구분한다. 실제 경로는 생성된 OpenAPI를 기준으로 확인한다.

2026-11-09 레시피 조회·프로필 검증

- PostgreSQL 임시 스키마를 사용한 백엔드 테스트 109개와 데이터 테스트 222개 통과. Ruff 정적·포맷 검사 통과.
- 실제 Uvicorn HTTP로 활성 레시피 1,151건을 페이지 조회하고 전체 응답·출처 판본·보류 제외를 확인. 상세 조회 200, 인증 없는 프로필 조회 401.
- 로컬 DB를 `20261109_01`로 업그레이드하고 `alembic check`에서 차이 없음 확인. 기존 레시피 1,156건·식품 8,807건·복지 461건 유지. 검증 임시 스키마 잔여 0건.
- 프로필 최초 동의·부분 변경·사용자 분리·철회와 재동의 요구를 검증. 실제 앱 동의 화면·프로필 입력 화면·보안 저장소 연동은 프런트 작업에서 연결한다.
- 데이터 패키지 `agetech`를 로컬 editable 의존성으로 설치하므로 `uv sync --locked` 후 일반 Uvicorn 진입점에서 계약 모듈을 불러온다. 이미지 빌드 시 저장소 루트와 `src/data`도 포함한다.
- 원천 수집 시각 역행과 시각 있는 이력 뒤의 무시각 입력을 차단한다. 이전 정상 레시피가 최신 보류 판정을 덮는 경우와 식품 판본 후퇴를 실제 DB에서 재현한 뒤 방지 테스트를 추가했다.

### 카카오 계정 연결

백엔드 `.env`의 `KAKAO_APP_ID`는 카카오 개발자 앱의 숫자 ID다. Native 앱 키와 구분한다. `alembic upgrade head`로 `20261118_01`을 적용한 뒤 실행한다. 서버는 카카오 토큰 정보 API에서 앱 ID·사용자 식별자·만료를 검증하고, 카카오 토큰은 저장하지 않는다.

- `POST /api/v1/auth/kakao`에 `{access_token}`을 보내면 같은 카카오 사용자에게 같은 내부 사용자 ID로 서비스 세션을 발급한다.
- `POST /api/v1/auth/kakao/link`는 현재 Bearer 세션에 카카오 계정을 연결한다. 사용자 ID를 유지하므로 프로필·식단표·저장 레시피도 유지한다. 다른 사용자에게 연결된 계정은 409로 거부한다.
- 세션 발급·조회·갱신 응답의 `kakao_linked`로 연결 여부를 확인한다. 로그아웃은 현재 서비스 세션만 폐기한다.
