# ValueFlow 공통 백엔드

Python 3.12·FastAPI 기반이다. 환경설정, DB 세션, 공통 응답·오류, 요청 ID, 상태 확인과 레시피·식품·복지 원천 테이블·적재 CLI를 구현했다. 게스트 세션 발급·갱신·폐기, 관리자 권한 확인, 레시피 DB 목록·상세 조회와 동의 기반 개인 프로필을 제공한다. 복지 조회와 추천 API는 DTO와 표본을 제공한다.

API 계약은 [API 명세서](../../docs/설계/API_명세서.md), 자동 생성 스냅샷은 [OpenAPI JSON](../../docs/설계/openapi.json)을 따른다.

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
| `GET /api/v1/recipes` | 활성 레시피 목록, 검색·분류·조리방법·알레르기 제외와 페이지 조회 |
| `GET /api/v1/recipes/{recipe_id}` | 원천 ID로 활성 레시피 상세 조회 |
| `GET/PATCH/DELETE /api/v1/profile` | 본인 프로필 조회·동의 후 저장·철회 또는 삭제 |
| `/docs` | Swagger UI |
| `/openapi.json` | OpenAPI 명세 |

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/live | ConvertTo-Json -Depth 10
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/ready | ConvertTo-Json -Depth 10
docker compose exec -T db psql -U valueflow_dev -d valueflow -c "SELECT extversion FROM pg_extension WHERE extname = 'vector';"
```

DB 사용자·이름을 바꿨으면 마지막 명령의 인자도 바꾼다. 서버 종료는 실행 터미널에서 `Ctrl+C`, DB 종료는 `docker compose stop db`를 사용한다. 데이터 볼륨은 유지한다.

세션 기본 만료는 7일이며 `.env`의 `SESSION_TTL_SECONDS`로 조정한다. 토큰은 발급·갱신 응답에서만 반환하고 DB에는 해시만 저장한다. 앱의 보안 저장소에 보관하고 로그에 출력하지 않는다. 관리자는 기본 생성하지 않으며 운영자가 `python -m app.jobs.set_user_role <사용자-UUID> --role admin`으로 지정한다. `--role user`로 해제한다. 카카오 로그인·만료 사용자 복구·관리자 운영 기능은 후속이다.

## API 계약 인계

[API 명세서 8~9절](../../docs/설계/API_명세서.md)에 세션·권한·DTO 규칙을 정리했다. [catalog.openapi.json](../../docs/설계/catalog.openapi.json)은 미구현 카탈로그 경로의 별도 계약이고 [api_examples.json](../../docs/설계/api_examples.json)은 실제 공개 원천을 검증한 표본이다. 실행 `/openapi.json`에는 구현된 경로만 포함한다.

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

## 기업 서버 배포 경계

현재 Compose는 로컬 DB 개발용이다. 기업 서버 배포용 API 이미지·worker·운영 설정은 아직 구성하지 않았다. API도 Compose 서비스로 실행할 때 DB 주소는 `127.0.0.1` 대신 서비스 이름 `db`를 사용한다. 로컬 개발 DB 볼륨과 기업 서버 DB는 별개이며, 서버에서도 Alembic upgrade 후 같은 입력 스냅샷으로 적재·대조 검증한다.

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
- 구현된 HTTP 경로 7개와 별도 예정 계약 6개를 구분한다. 앱/관리자 실제 연결·카카오·운영 인증 절차·업무별 API와 RAG는 후속이다.

2026-11-09 레시피 조회·프로필 검증

- PostgreSQL 임시 스키마를 사용한 백엔드 테스트 102개와 데이터 테스트 222개 통과. Ruff 정적·포맷 검사 통과.
- 실제 Uvicorn HTTP로 활성 레시피 1,151건을 페이지 조회하고 전체 응답·출처 판본·보류 제외를 확인. 상세 조회 200, 인증 없는 프로필 조회 401.
- 로컬 DB를 `20261109_01`로 업그레이드하고 `alembic check`에서 차이 없음 확인. 기존 레시피 1,156건·식품 8,807건·복지 461건 유지. 검증 임시 스키마 잔여 0건.
- 프로필 최초 동의·부분 변경·사용자 분리·철회와 재동의 요구를 검증. 실제 앱 동의 화면·프로필 입력 화면·보안 저장소 연동은 프런트 작업에서 연결한다.
- 데이터 패키지 `agetech`를 로컬 editable 의존성으로 설치하므로 `uv sync --locked` 후 일반 Uvicorn 진입점에서 계약 모듈을 불러온다. 이미지 빌드 시 저장소 루트와 `src/data`도 포함한다.
