# ValueFlow 공통 백엔드 API 명세서

## 건강 영상 목록 (2026-11-25 추가)

| 경로 | 인증 | 요청·응답 |
| --- | --- | --- |
| `GET /api/v1/health-videos` | 불필요 | `topic=stretching/hands/healthy_life` 선택, `limit`·`offset`. `data.items/total/limit/offset` 반환 |
| `GET /api/v1/health-videos/{id}` | 불필요 | 게시 중인 영상 메타데이터. 미등록·게시 중단은 `VIDEO_NOT_FOUND` 404 |

각 항목은 `id`, `topic`, `title`, `publisher`, `video_id`, `source_url`, `checked_on`이다. 앱은 검증한 11자리 `video_id`로 YouTube watch 주소를 만들고 사용자가 재생 버튼을 누를 때 외부 앱/브라우저를 연다. 출처 URL은 HTTPS·확인한 기관/플랫폼 도메인만 허용한다. 손상된 목록은 `VIDEO_CATALOG_UNAVAILABLE` 503이며 빈 성공으로 바꾸지 않는다. 서버는 외부 영상이나 메타데이터를 매 요청마다 가져오지 않는다. 원본 삭제·연령/지역 제한은 플랫폼에서 달라질 수 있다.

기존 예정 `/videos` 경로와 구분하며, 실행 계약은 함께 갱신한 `openapi.json`을 따른다. 새 DB 마이그레이션·환경변수·유료 API 키는 필요 없다.

- 작성일: 2026-11-03
- 갱신일: 2026-11-18
- API 경로 버전: `v1` / 애플리케이션 버전: `0.1.0`
- 구현 기준: `src/backend/app`의 실제 등록 경로·Pydantic 모델·예외 처리
- 로컬 주소: `http://127.0.0.1:8000`
- 서비스 API 접두사: `/api/v1`
- 실행 안내: [백엔드 README](../../src/backend/README.md)
- 기계 판독용 명세: [openapi.json](./openapi.json)

상태 확인, 게스트·카카오 인증, 관리자 권한 확인, 레시피·복지 DB 목록·상세, 식단·복지 후보 추천, 프로필 CRUD, 하루 식단표와 레시피·복지 저장을 구현했다. [요청·응답 표본](./api_examples.json)을 제공하며 실행 계약은 `openapi.json`을 따른다. 코드 구현·main 병합·기업 서버 배포 여부는 별도로 확인한다.

## 1. 공통 규칙

| 항목 | 현재 계약 |
| --- | --- |
| 응답 형식 | JSON, `Content-Type: application/json` |
| 인증 | health·게스트 발급은 공개, 사용자·관리자는 `Authorization: Bearer <access_token>` |
| 성공 | `data`와 `meta` |
| 오류 | `error`와 `meta` |
| 요청 추적 | 서버가 요청마다 UUID를 생성해 `meta.request_id`와 `X-Request-ID` 응답 헤더에 전달 |
| 클라이언트 요청 ID | 클라이언트가 보낸 `X-Request-ID`는 서버 요청 ID로 재사용하지 않음 |
| 시각 | health의 `checked_at`은 ISO 8601 UTC 문자열로 반환 |
| 빈 부가 정보 | 현재 `revision`, `checked_at`, `database`는 값이 없으면 `null`로 포함 |

OpenAPI JSON과 Swagger HTML은 별도의 문서 경로이며 `data/meta`로 감싸지 않는다. CORS 사전 요청은 미들웨어가 별도 처리하므로 서비스 API 응답 형식·요청 ID를 적용하지 않는다.

### 1.1 성공 응답

```json
{
  "data": {"status": "ok", "database": null},
  "meta": {
    "request_id": "9d74d56e-21d2-4d7e-9085-e4c0e7f971e0",
    "revision": null,
    "checked_at": null
  }
}
```

| 필드 | 자료형 | 설명 |
| --- | --- | --- |
| `data` | 기능별 객체 | 현재 health API에서는 `HealthData` |
| `meta.request_id` | string | 서버에서 생성한 UUID |
| `meta.revision` | integer 또는 null | 응답 자료 판본. 현재 health에는 판본이 없어 null |
| `meta.checked_at` | string 또는 null | 현재 readiness에서 DB 확인을 완료한 UTC 시각 |

### 1.2 오류 응답

```json
{
  "error": {
    "code": "DATABASE_UNAVAILABLE",
    "message": "데이터베이스 연결을 확인해 주세요.",
    "fields": [],
    "retryable": true
  },
  "meta": {
    "request_id": "9d74d56e-21d2-4d7e-9085-e4c0e7f971e0",
    "revision": null,
    "checked_at": null
  }
}
```

| 필드 | 자료형 | 설명 |
| --- | --- | --- |
| `error.code` | string | 프로그램에서 분기할 오류 코드 |
| `error.message` | string | 사용자에게 표시할 안내 |
| `error.fields` | array | 입력 오류 위치·이유. 관련 필드가 없으면 빈 배열 |
| `error.fields[].field` | string | 예: `body.age`. 검증 위치를 점으로 연결 |
| `error.fields[].reason` | string | 예: `int_parsing`. 검증기의 오류 종류 |
| `error.retryable` | boolean | 조건 회복 후 재시도 가능한지 여부. 자동 재시도 실행을 뜻하지 않음 |

검증 오류에는 원본 입력값·요청 본문을 포함하지 않는다. 예상하지 못한 예외의 상세 메시지도 응답에 포함하지 않는다.

## 2. 서버 생존 확인

`GET /api/v1/health/live`

- 목적: API 프로세스가 HTTP 요청에 응답하는지 확인한다.
- 인증·경로 인자·쿼리·본문: 없음.
- DB 조회: 수행하지 않음.
- 정상 상태: `200 OK`.

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/live | ConvertTo-Json -Depth 10
```

`data.status`는 `"ok"`, `data.database`는 `null`이다. `meta.revision`과 `meta.checked_at`도 `null`이다. 성공 응답은 1.1절 예시와 같다. 이 경로의 성공만으로 DB 연결 성공을 판단하지 않는다.

## 3. DB 준비 상태 확인

`GET /api/v1/health/ready`

- 목적: 요청별 SQLAlchemy 세션으로 PostgreSQL에 `SELECT 1`을 실행한다.
- 인증·경로 인자·쿼리·본문: 없음.
- 정상 상태: `200 OK`.
- DB 연결·조회 오류: `503 Service Unavailable`, `DATABASE_UNAVAILABLE`, `retryable=true`.
- 확인 범위: DB 연결과 간단한 SQL 조회. 업무 테이블·vector 확장·worker 상태까지 검사하지 않음.

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/ready | ConvertTo-Json -Depth 10
```

정상 응답 예시:

```json
{
  "data": {"status": "ok", "database": "ok"},
  "meta": {
    "request_id": "9d74d56e-21d2-4d7e-9085-e4c0e7f971e0",
    "revision": null,
    "checked_at": "2026-11-03T00:00:00Z"
  }
}
```

DB 실패 응답은 1.2절 예시와 같다. DB 연결 제한 시간은 현재 5초, 연결 풀 대기 제한은 5초이며 네트워크 환경에 따라 전체 응답 시간은 달라질 수 있다.

## 4. 공통 오류 코드

| HTTP 상태 | 코드 | 현재 발생 조건 |
| --- | --- | --- |
| 404 | `HTTP_404` | 등록되지 않은 경로 |
| 401 | `AUTH_REQUIRED` | 토큰 없음·위조·만료·폐기·비활성 사용자. `WWW-Authenticate: Bearer` 유지 |
| 403 | `ADMIN_REQUIRED` | 유효한 일반 사용자 세션으로 관리자 경로 접근 |
| 405 | `HTTP_405` | 해당 경로에서 지원하지 않는 메서드. `Allow` 헤더 유지 |
| 422 | `VALIDATION_ERROR` | 요청 모델 검증 실패 시 사용하는 공통 처리. 현재 health에는 필수 입력 모델이 없음 |
| 503 | `DATABASE_UNAVAILABLE` | readiness의 DB 연결·조회 실패 |
| 503 | `AUTH_UNAVAILABLE` | 인증 저장소 조회·저장 실패, `retryable=true` |
| 500 | `INTERNAL_SERVER_ERROR` | 예상하지 못한 처리 오류 |

`AppError`는 기능별 HTTP 상태·오류 코드·공개 안내·재시도 가능 여부를 지정하는 공통 예외다. 현재 배포 경로에 없는 기능별 오류 코드를 구현 완료된 계약으로 해석하지 않는다.

## 5. React 관리자 웹의 CORS

허용 출처는 `.env`의 `CORS_ORIGINS` JSON 배열로 설정한다. 예시는 `http://localhost:5173`이다.

| 항목 | 현재 설정 |
| --- | --- |
| 허용 메서드 | GET, POST, PATCH, DELETE, OPTIONS |
| 명시적 허용 요청 헤더 | Authorization, Content-Type, Idempotency-Key |
| 브라우저에 노출할 응답 헤더 | X-Request-ID |
| 쿠키 등 자격 증명 공유 | 비활성화 (`allow_credentials=false`) |

허용되지 않은 출처에는 `Access-Control-Allow-Origin`을 전달하지 않는다. CORS 설정과 별도로 서버가 세션·관리자 권한을 검사한다. `Idempotency-Key`를 CORS에서 허용하는 것과 멱등성 저장 기능의 구현 여부는 별개다.

## 6. 자동 API 문서

| 경로 | 형식 | 용도 |
| --- | --- | --- |
| `/docs` | HTML | Swagger UI에서 호출 확인 |
| `/redoc` | HTML | ReDoc 문서 |
| `/openapi.json` | JSON | 서버가 생성하는 현재 OpenAPI 명세 |

`openapi.json`은 실행 코드의 `app.openapi()`에서 생성한 스냅샷이다. `catalog.openapi.json`은 미구현 카탈로그 경로의 별도 인계 문서이며, 복지 구현 후 현재 `paths`는 비어 있다. 실행 서버에 예정 경로를 추가하지 않는다. `src/backend`에서 `PYTHONPATH=../data`를 설정하고 `python -m app.jobs.export_api_contract`로 둘을 재생성한다. 표본 갱신은 같은 명령에 `--welfare-snapshot <실제 수집 JSON 경로>`를 전달한다. 실제/예정 스냅샷과 DTO 표본은 테스트에서 대조한다.

### 카카오 로그인과 게스트 연결

`POST /api/v1/auth/kakao`는 `{access_token}`을 받아 서버에서 카카오 앱 ID·사용자 식별자·만료를 검증한 뒤 서비스 세션을 발급한다. 같은 카카오 사용자는 같은 내부 사용자 ID로 로그인한다. `POST /api/v1/auth/kakao/link`는 기존 서비스 Bearer 세션이 필요하며 현재 사용자의 ID와 식단표·저장 레시피를 유지한 채 연결한다. 다른 사용자에게 이미 연결된 카카오 계정은 `KAKAO_ALREADY_LINKED`(409), 현재 사용자에게 다른 카카오 계정이 연결되어 있으면 `USER_ALREADY_LINKED`(409)다. 클라이언트는 자동 병합하지 않고 기존 계정 로그인 선택을 안내한다.

세션 발급·조회·갱신 응답에 `kakao_linked`가 포함된다. 요청에 내부 사용자 ID를 받지 않고 카카오 원본 토큰은 저장하지 않는다. 미설정은 `KAKAO_DISABLED`(503), 다른 앱·만료 토큰은 `KAKAO_TOKEN_INVALID`(401), 제공자 연결 실패는 `KAKAO_UNAVAILABLE`(503)다. 마이그레이션은 `20261118_01`, 백엔드 설정은 `KAKAO_APP_ID`다.

### 하루 식단표와 저장한 레시피

아래 경로는 `/api/v1` 접두사와 Bearer 세션이 필요하다. 사용자 ID는 인증 정보에서 결정하며 사용자별 데이터는 `Cache-Control: no-store`로 반환한다.

| 메서드 | 경로 | 동작 |
| --- | --- | --- |
| GET | `/meal-plans/{date}` | `YYYY-MM-DD` 날짜의 끼니별 메뉴 조회 |
| PUT | `/meal-plans/{date}/{slot}` | 메뉴 담기 또는 교체, `{recipe_id, recipe_revision_id?}` |
| DELETE | `/meal-plans/{date}/{slot}` | 해당 끼니 비우기, 204 |
| DELETE | `/meal-plans/{date}` | 해당 날짜 비우기, 204 |
| GET | `/saved-recipes?limit=20&offset=0` | 최신 저장순 목록과 total |
| GET | `/saved-recipes/{recipe_id}` | `{saved: boolean}` |
| PUT | `/saved-recipes/{recipe_id}` | 레시피 저장, 반복해도 한 건 |
| DELETE | `/saved-recipes/{recipe_id}` | 저장 해제, 반복해도 204 |

`slot`은 `breakfast/lunch/dinner/snack/special`이다. 식단표는 사용자·날짜·끼니마다 한 메뉴를 저장한다. 조회 항목은 `meal_slot`, `recipe_id`, `recipe_revision_id`, `name`, `is_active`를 담는다. 선택 당시 판본을 유지하고 갱신된 메뉴는 `is_active=false`로 안내한다. 저장 요청의 판본이 현재 판본과 다르면 409를 반환한다. 게시 보류·삭제된 메뉴의 신규 저장은 404이며, 기존 저장 목록에서는 이름을 null로 반환해 해제할 수 있다. 기존 `meal_plan_entries/saved_recipes` 테이블을 사용하므로 추가 마이그레이션은 없다.

게스트는 현재 기기의 보관된 세션으로 연결된다. 세션 만료·삭제 후 새 게스트를 만들면 다른 사용자로 취급되므로 장기 보관과 다른 기기 복원에는 세션 만료 전 카카오 계정을 연결한다. 식단표는 섭취 기록이나 하루 영양 적정량 판정을 생성하지 않는다.

### 식단 추천

`POST /api/v1/meal/recommendations`에는 게스트 또는 사용자 Bearer 세션이 필요하다. 현재 공개된 레시피에 요청과 계정의 제외 조건을 먼저 적용하고, 부드러운 음식·간단한 조리를 선택하면 일치한 조리 조건 수가 많은 메뉴를 우선한다. 그 안에서 선호 재료, 시간대, 최근 섭취·추천 이력, 메뉴 유형 다양성 등을 반영한다. `items[].matched_preferences`는 해당 메뉴가 충족한 `soft_food`·`simple_cooking`을 알려 준다. 죽·미음, 일부 찜, 갈거나 으깨서 거른 수프를 부드러운 조리로 분류한다. 간단한 조리는 재료 1~6개와 누락 없는 조리 단계 1~4개를 기준으로 한다. 건강 조건은 재료로 계산한 영양의 분량과 상관없는 값(`computed_nutrition.density` — 고혈압은 1,000 kcal당 나트륨 `sodium_mg_per_1000kcal`, 당뇨는 열량 중 탄수화물 비율 `carbohydrate_energy_pct`, [영양 정의서](../data/food_nutrition_contract.md) 3.2)으로 후보끼리 비교해, 후보 중앙값보다 낮은 메뉴에 가산하고 이유를 붙인다(`meal-rules-5`). 값이 없는 레시피(매핑 전·일부 재료만 계산)는 비교에서 뺀다. 원천 1인분 표기값(`nutrition`)은 몇 인분 기준인지 근거가 없어 쓰지 않는다.

요청의 `preferred_ingredients`는 저장 프로필의 선호 재료와 함께 반영한다. `simple_cooking=true`이면 재료 6개 이하이고 누락된 중간 단계 없이 조리 1~4단계로 구성된 메뉴에 가점을 준다. 최근 섭취 기록은 식품 ID와 재료명으로 비교하고, 같은 시간대의 최근 2일 내 결과가 있었던 직전 2회에서 상위 3개로 제시한 메뉴는 순위를 낮춘다. 제외 조건은 항상 순위 계산 전에 적용한다.

고혈압은 나트륨, 당뇨는 탄수화물 공개 표기량을 비교한다. 수치가 양수이고 원천 품질 검사에서 의심으로 판정되지 않은 후보 중 중간값보다 낮은 메뉴에 가점을 준다. 한국 시간 기준 해당 월에 게시 중이고 현재 레시피 판본과 연결된 제철 재료에 가점을 주며, 원문과 쿠팡 검색 링크를 반환한다.

응답의 `recommendation_id`로 추천 실행을 식별한다. DB에는 계정 ID, 식사 시간, 평가 시각, 규칙 버전, 추천 레시피 판본과 이유·제철 근거를 저장한다. 요청의 건강 상태·알레르기 원문은 추천 이력에 저장하지 않는다. 후보가 없으면 빈 `items`를 반환한다.

## 식품 검색과 분량별 영양 계산

| 메서드·경로 | 요청·응답 |
| --- | --- |
| `GET /api/v1/foods` | `q`(식품명 부분 검색)·`limit`(1~100, 기본 20)·`offset`(0~10000). `data.items/total/limit/offset` |
| `GET /api/v1/foods/{food_id}` | 목록의 UUID. 기준량·영양값·분량 참고량·품질 표시·원천 판본 |
| `POST /api/v1/nutrition/calculate` | `items` 1~30개: `{food_id, revision_id, amount, unit}`. 분량별 `items`와 계산 가능한 음식의 `total` |

로그인 없이 공개 식품 정보로 계산하는 미리보기이며 섭취 기록을 저장하지 않는다. `food_id`는 내부 UUID, `revision_id`는 검색 응답의 `source.revision_id`를 전달한다. 같은 식품명이라도 식품 코드·기준 단위가 다를 수 있으므로 화면에서 기준량과 출처를 함께 보여 준다. 서버의 활성 식품 판본만 조회하며, 선택 후 데이터가 갱신되면 `FOOD_REVISION_CHANGED`(409)로 재선택을 요청한다. 없는 식품은 `FOOD_NOT_FOUND`(404), DB 오류는 재시도 가능한 `FOODS_UNAVAILABLE`(503)다.

예시 요청(실제 검색 결과의 UUID로 바꾼다):

```json
{"items":[{"food_id":"00000000-0000-0000-0000-000000000001","revision_id":"00000000-0000-0000-0000-000000000002","amount":150,"unit":"g"}]}
```

분량은 0보다 크고 10,000 이하의 유한한 JSON 숫자다. `g/kg/mL/ml/cc/L`는 기준 단위로 변환하며, `인분/그릇/공기/접시/대접/회분`은 원천에 g·mL로 표시된 1회분량 근거가 있을 때만 환산한다. `개/조각`은 중량 근거가 없어 `unconvertible`로 반환하고 g·mL 재입력을 안내한다. g↔mL 계산은 기존 데이터 계약의 1mL≈1g 근사이며 `status=approx_ml`, `approx_ml=true`와 주의 문구를 제공한다. 기준량이 불명확하면 `invalid`다. 실제 밀도·한 그릇 중량을 추정해 만들지 않는다.

`calculation_version=food-portion-v1`, 항목별 `source`(제공자·식품 코드·판본·원천 해시·적재 시각), 입력값과 환산 근거를 반환한다. 영양소 결측은 `null`이며 0과 구분한다. `total.complete`는 모든 음식의 분량 계산 성공 여부다. 모든 영양소가 채워졌다는 뜻은 아니므로 `missing_items`(영양소별 결측 음식 수)도 확인한다. 일부 음식만 계산되면 `excluded`에 제외 항목의 배열 위치·이유를 남기며, 전부 제외되면 합계도 `null`이다. 계산 응답은 `Cache-Control: no-store`다. 사진 분석·진단·섭취 확정 기능과 별개다.

## 확정 섭취 기록

모든 `/api/v1/meals` 요청은 서비스 Bearer 세션이 필요하며, 오류·입력 검증 응답까지 `Cache-Control: no-store`를 적용한다. 사용자 ID와 영양 수치를 요청에 넣지 않는다. 서버는 선택한 식품 판본과 분량으로 다시 계산해 저장하고 사용자별로 기록을 격리한다. 식단표·레시피 저장과 별개이며 사진 분석 없이 직접 선택한 음식도 기록할 수 있다.

| 메서드·경로 | 요청·응답 |
| --- | --- |
| `POST /api/v1/meals` | 헤더 `Idempotency-Key` 필수(16~128자, 영문·숫자·`_`·`-`, UUID 권장). 본문 `{eaten_at, items}`. 첫 저장 201, 같은 요청 재전송 200. `data={meal,replayed}` |
| `GET /api/v1/meals` | `limit`(1~50, 기본 20)·`offset`·선택 `day=YYYY-MM-DD`. 최신 섭취순 요약 페이지, `total`은 해당 사용자·날짜 조건의 건수 |
| `GET /api/v1/meals/{id}` | UUID 기록의 상세. 선택한 음식·분량·영양값·계산 근거 포함 |
| `PATCH /api/v1/meals/{id}` | `expected_version` 필수, `eaten_at` 또는 `items` 중 하나 이상. 변경 필드에 null 금지. `items`는 음식 목록 전체 교체이며 서버에서 재계산 |
| `DELETE /api/v1/meals/{id}?version=1` | 상세 응답의 `version` 필수. 성공 204. 이미 없거나 다른 사용자의 기록은 같은 404 |

`eaten_at`은 시간대가 있는 ISO 8601 시각이며 UTC로 정규화해 보관한다. `items`는 계산 미리보기와 같은 `{food_id,revision_id,amount,unit}` 1~30개다. `day` 조회는 한국 시간 자정부터 다음 날 자정까지를 적용한다. 목록 요약에는 `id/eaten_at/created_at/version/total/legacy_snapshot_missing`을 반환하고 음식별 세부 내용은 상세에서 읽는다.

저장 시 계산이 안 되는 항목을 조용히 빼지 않는다. 모든 음식의 분량이 환산 가능해야 하며, 원천 중량이 없는 그릇·개수 단위는 g·mL로 다시 확인한다(`PORTION_NOT_RECORDABLE`, 422). 환산 후 중량은 기존 DB 규격에 맞춰 0.001~9,999,999.999 g·mL, 소수점 셋째 자리까지 표현 가능해야 한다. g↔mL 근사는 명시적으로 표시하며, 영양소 결측은 그대로 null과 `missing_items`로 보관한다. 식품 판본이 바뀌었으면 미리보기와 같은 409로 재선택을 요청한다.

상세의 `items[]`에는 `food_id/revision_id/food_code/name/order_no/amount/amount_unit/nutrients/calculation_version/calculation`을 반환한다. `calculation`은 저장 시점의 입력 분량·환산 근거·근사 여부·원천 판본을 보관한 스냅샷이다. 원천 갱신은 과거 기록의 수치를 바꾸지 않는다. 섭취 시각만 수정할 때도 음식과 당시 영양값은 유지한다. 이전 버전에서 저장한 스냅샷 없는 기록은 기존 수치를 그대로 반환하고 `calculation=null`, `legacy_snapshot_missing=true`로 알린다. 근거를 새로 만들어 채우지 않는다.

미리보기 `/nutrition/calculate`와 식사 생성·수정의 `items[]`는 선택적으로 `origin`을 받는다. `method`는 `manual/photo/similar_food/ingredient_estimate`, `quantity_basis`는 `user_entered/source_serving/ai_estimate/user_adjusted`다. `recognized_name`(최대 60자)은 manual 이외 방법에서 필수이며, `ingredient_name`(최대 60자)은 ingredient_estimate에서 필수다. 선택 `reference_recipe_name`은 최대 200자이고 재료 추정일 때만 허용한다. manual 이외에는 `amount_is_estimate=true`가 필요하다. 이 값은 사용자가 확인한 입력 맥락으로, 서버가 검증한 AI 실행 증명이나 영양 수치의 출처를 대체하지 않는다. DB 계산·출처 판본은 서버가 결정한다. 응답은 항목별 `origin`(식사 상세에서는 `calculation.origin`)으로 돌려준다.

같은 요청의 선택 `analysis_context.excluded_ingredients[]`에는 `dish_name/ingredient_name/reason`을 최대 48개 받는다. 이름은 각각 최대 60자, reason은 `user_excluded/unmatched/water`다. 해당 음식에서 빠진 재료와 조리용 물을 명시하며 미리보기·생성·상세·목록에 유지한다. `null`은 과거 정보 미기록, 빈 배열은 기록된 제외 재료 없음으로 구분한다. 목록·상세의 `contains_estimates`는 저장한 항목의 추정 분량 여부에서 서버가 계산한다. 시간만 수정하거나 `analysis_context`를 생략하면 기존 맥락을 유지하며, 명시적인 빈 배열로 초기화할 수 있다(수정 요청의 명시적 null은 거부). 생성 키의 요청 해시에는 제공된 입력 맥락도 포함하되, 추가 전 앱의 저장 재시도가 충돌하지 않도록 null인 새 선택 필드는 해시에서 제외한다.

같은 사용자의 같은 키·같은 요청은 기록을 하나만 생성한다. 날짜는 UTC 기준으로 비교하므로 같은 시각의 다른 시간대 표기도 같은 요청이다. 같은 키로 다른 내용을 보내면 `IDEMPOTENCY_KEY_REUSED`(409), 기록을 삭제한 뒤 그 생성 요청을 재전송하면 `MEAL_ALREADY_DELETED`(409)다. 수정 후 최초 생성 요청을 재전송하면 같은 기록의 **현재 상태**와 `replayed=true`를 반환한다. 신규 저장에는 새 키, 네트워크 재시도에는 기존 키를 사용한다.

수정·삭제는 `version`으로 경합을 확인하며 오래된 버전은 `MEAL_VERSION_CHANGED`(409)로 막는다. 변경을 반영하기 전에 상세를 다시 읽도록 앱에서 안내한다. 타인과 없는 기록은 `MEAL_NOT_FOUND`(404)로 구분하지 않는다. DB 실패는 재시도 가능한 `MEALS_UNAVAILABLE`(503)이며 기록·음식·중복 방지 이력을 함께 롤백한다. 요청 키 원문과 입력 원문은 중복 방지 테이블에 남기지 않고 해시와 기록 링크만 보관한다. 기록 삭제 시 링크를 비워 재시도에 의한 복원을 막고, 사용자 DB 행 삭제 시 그 사용자의 기록·음식·요청 이력을 cascade 삭제한다. 세션 폐기와 프로필 동의 철회는 사용자 DB 행 삭제와 다르다.

마이그레이션은 `20261118_01 → 20261119_01 → 20261120_01` 단일 경로다. 중간의 복지 메모 마이그레이션은 PR #58과 같은 파일을 재사용하며 기존 저장 항목을 유지한다. 새 섭취 마이그레이션은 기존 기록을 version=1로 보존하고 순서·스냅샷 컬럼을 nullable로 추가한다. 배포에는 `alembic upgrade head`가 필요하며 운영 DB를 자동 downgrade하지 않는다. 코드·CI 검증과 main 병합·기업 서버 배포·앱 화면 연결은 별도 상태로 관리한다.

### 음식별 오류 위치와 앱 연결

식품이 없거나 판본이 바뀐 오류에는 기존 오류 구조의 `error.fields`를 사용한다. `body.items.N.food_id`(`reason=not_found`), `body.items.N.revision_id`(`revision_changed`), 기록할 수 없는 분량은 `body.items.N.amount`(`unrecordable`)로 대상 항목의 0부터 시작하는 배열 위치를 제공한다. 요청 값·개인정보는 포함하지 않는다. 기존 오류 코드·상태와 공통 스키마는 유지하며 앱은 해당 음식만 다시 고르거나 분량을 바꾸도록 표시한다.

앱의 실제 기록 경로는 **영양분석 → 먹은 음식 직접 입력 → 음식 검색/분량 확인 → 영양 확인 → 저장**이다. 검색과 미리보기는 공개 정보로 처리하고, 기록·목록·상세·수정·삭제에는 앱의 현재 계정 세션을 사용한다. 한국 날짜로 기록을 조회하며, 수정은 `expected_version`, 삭제는 `version`을 보내 충돌 시 최신 기록을 확인한다. 생성 요청의 키와 확정 입력은 기기 보안 저장소에 서버·사용자별로 보관해 유실된 응답을 같은 키로 재확인한다. 인증 만료 후 새 게스트로 자동 재전송하지 않는다. 새 API 배포와 실제 휴대폰 확인 전에는 통합 완료로 처리하지 않는다.

## 식단표 기반 장보기

| 메서드·경로 | 요청·응답 |
| --- | --- |
| `GET /api/v1/shopping-lists/{plan_date}` | Bearer 세션, `YYYY-MM-DD`. `{plan_date,planned_meals,items,warnings}` |
| `PATCH /api/v1/shopping-lists/{plan_date}/items/{item_key}` | `{source_hash,checked}`. `checked`는 JSON boolean, `item_key/source_hash`는 조회한 64자리 해시. 성공 `{item_key,source_hash,checked}` |

해당 사용자의 날짜별 식단표에 저장된 **레시피 판본**의 재료를 모은다. 메뉴마다 원문 전체 분량을 한 번씩 사용하며 인분을 자동으로 나누거나 늘리지 않는다. 같은 레시피를 두 끼에 담으면 두 번 반영한다. 레시피가 갱신돼도 저장 판본을 조용히 교체하지 않고 `sources[].is_active=false`와 주의 문구를 반환한다. 재료가 없는 메뉴도 `planned_meals/warnings`에 남긴다.

`items[]`는 `item_key/source_hash/name/amount/unit/amount_text/combined/checked/shopping_search_url/sources`다. 같은 원문 재료명과 명확한 단위끼리만 합산한다. g·kg·mg는 g, mL·ml·cc·L는 mL로 모으고 **g와 mL는 합치지 않는다**. 개수·계량 단위는 같은 단위끼리 더하며 g·mL로 추정 환산하지 않는다. 준비 형태가 다른 원문 이름도 유지한다. 분수는 정확히 계산하고 소수로 끝나지 않으면 `amount_text`에 `2/3`처럼 표시한다. ‘약간’·범위·복합 분량 등은 `combined=false`, `amount/unit=null`과 원문 분량으로 남긴다.

`sources[]`에는 식단 항목 UUID·끼니·레시피 ID/이름/판본·재료 UUID·구획·원문 재료명/분량·활성 여부가 있다. `item_key`는 이름·단위 그룹이고 `source_hash`는 구성 메뉴·재료·분량·원천 상태를 식별한다. 필요 재료가 달라지면 기존 체크는 미확인으로 표시한다. 낡은 목록으로 체크하면 `SHOPPING_LIST_CHANGED`(409), 본인의 해당 날짜 목록에 없는 항목은 `SHOPPING_ITEM_NOT_FOUND`(404)다. 다른 사용자의 체크는 읽거나 변경하지 않는다.

체크만 `shopping_checks`에 저장하며 식단·체크 변경은 사용자 행 잠금으로 직렬화한다. 마지막 메뉴나 하루 식단표 전체를 지우면 해당 날짜 체크도 지운다. 사용자 행 삭제 시 cascade 삭제한다. DB 실패는 재시도 가능한 `SHOPPING_UNAVAILABLE`(503), 모든 응답은 `Cache-Control: no-store`다. 마이그레이션 `20261120_02`는 `20261120_01` 다음에 체크 테이블만 추가하고 기존 식단·섭취 기록을 유지한다. downgrade는 체크를 제거하므로 운영 자동 복구에 사용하지 않는다.

외부 주소는 HTTPS `www.coupang.com/np/search?q=...`로 생성하며 **공개 재료명만** 인코딩한다. 프로필·건강·소득·위치를 넣지 않는다. 앱은 호스트·경로·검색어를 검증하고 사용자 선택으로 외부 페이지를 연다. 가격·재고·배송비·구매는 외부 페이지에서 확인하며 자동 주문·가격 수집·제휴 링크는 구현하지 않는다. 앱 진입은 **내 식단 → 이 날의 장보기 목록**, 개별 재료 검색은 레시피 상세에서도 제공한다. HTTP·위젯 시험과 main 병합·기업 서버 배포·실기기 종단 확인은 별도 상태다.
### 복지 조회·추천과 저장

복지 조회·추천 경로는 9절의 DTO로 실제 DB에 연결한다. `GET /api/v1/welfare`는 게시 중인 서비스의 활성 판본 중 상세 준비 완료·품질 보류가 아닌 자료만 반환한다. 검색은 제목·요약·지원 대상의 문자 그대로 부분 검색이며 `%`·`_`를 검색 와일드카드로 해석하지 않는다. 지역을 생략하면 전체 지역을 조회한다. 지역을 주면 데이터 모듈 `services_for`의 줄임말·시군구 해석과 내 시군구 → 내 시도 전체 → 전국 순서를 따른다. 기록된 사업 종료일이 지난 항목은 목록·추천에서 제외한다. 지역 해석 실패 시 전국 사업 또는 시도 전체까지 안내하며 추천 응답의 `warnings`에 이유를 넣는다.

`POST /api/v1/welfare/recommendations`는 같은 지역 범위 안에서 지원 대상 원문의 연령 하한 표현 및 독거·1인 가구 관련 문구를 정렬 단서로만 사용한다(`welfare-candidates-v1`). 조건에 해당한다는 이유로 자격을 확정하거나, 문구가 없다는 이유로 사업을 제외하지 않는다. 응답은 공식 출처·확인 시각·현재 활성 `revision_id`, 원문 기반 이유, `application_status=unknown`, 세부 자격·신청 여부 확인 안내를 제공한다. 요청의 연령·가구 정보는 저장하지 않으며 응답은 `Cache-Control: no-store`다. 이 경로는 생성형 답변/RAG API가 아니다.

아래 저장 경로에는 Bearer 세션이 필요하다. 사용자 ID는 인증 정보에서 결정하며 정상 응답은 `Cache-Control: no-store`다. 기본 저장/해제는 기존 `saved_welfare_services`를 사용한다. 진행 메모는 Alembic `20261119_01`의 nullable 두 컬럼을 추가한 뒤 사용하며 기존 저장 행은 유지한다.

| 메서드 | 경로 (`/api/v1` 접두사) | 동작 |
| --- | --- | --- |
| GET | `/saved-welfare?limit=20&offset=0&q=검색어` | 최신 저장순 `{items: [{service_id, title}], limit, offset, total}` |
| GET | `/saved-welfare/{service_id}` | `{saved: boolean}` |
| PUT | `/saved-welfare/{service_id}` | 게시 중인 사업 저장, 반복해도 한 건 |
| DELETE | `/saved-welfare/{service_id}` | 본인 저장 해제, 반복해도 204 |
| GET | `/saved-welfare/{service_id}/note` | 본인 저장 항목의 `{service_id, note, updated_at}` |
| PATCH | `/saved-welfare/{service_id}/note` | `{note: string 또는 null}`로 본인 메모 수정/비우기 |

철회·품질 보류된 사업은 신규 저장할 수 없다(404). 이미 저장한 사업은 목록에서 `title=null`로 유지해 해제할 수 있다. 공식 신청 안내·문의처는 상세 API로 제공한다. 메모는 사용자의 개인 기록이며 실제 신청 제출이나 공식 접수/자격 판정과 구분한다.

메모는 먼저 본인 목록에 저장한 사업에서만 조회·수정할 수 있다. 미저장·다른 사용자의 항목은 동일하게 404를 반환하며 메모를 쓰면서 자동 저장하지 않는다. `note`는 필수 필드이고 최대 2,000자다. 앞뒤 공백을 제거하고 `null`·빈 문자열·공백만 보내면 메모만 비운다. 수정 시각은 서버의 시간대가 포함된 시각이며, 동시 수정은 마지막 반영 내용이 남는다. 메모는 평문으로 표시하고 공개 복지 상세·저장 목록 요약·공유 문구에는 포함하지 않는다. 원천이 철회돼도 본인 기존 메모는 조회·수정할 수 있으며, 저장 해제 시 해당 메모도 함께 삭제된다. 반복 저장(PUT)은 기존 메모를 덮어쓰지 않는다.

### 급식소·제철·생활 가이드 조회

공개 조회 API이며 공통 성공 응답과 `limit`(1~100)·`offset`(0~10000)·선택 `q`(1~100자)를 사용한다. 목록에 `items/total/limit/offset`을 제공한다. 검색은 문자 그대로의 부분 검색으로 `%`·`_`를 와일드카드로 해석하지 않는다. 게시 해제된 자료의 상세는 404, UUID 형식·월·페이지 입력 오류는 422, DB 연결 실패는 재시도 가능한 `CONTENT_UNAVAILABLE`(503)다.

| 메서드·경로 (`/api/v1` 접두사) | 입력·응답 |
| --- | --- |
| `GET /meal-facilities` | 선택 `region/district`, `district`는 `region`과 함께. 지역 생략 시 전체 지역, 선택 시 내 시군구 → 같은 시도 다른 시군구 순. 이름·주소 검색. `warnings`로 지역 해석 결과 안내 |
| `POST /meal-facilities/nearby` | 본문에 필수 `latitude/longitude`, 선택 `radius_km`(0.5~50, 기본 5), `region/district`, 공통 `q/limit/offset`. 좌표가 있는 반경 내 시설은 지역 경계와 무관하게 거리순, 같은 시군구의 좌표 없는 시설은 마지막에 표시. 각 시설에 `distance_km`·`match` 추가 |
| `GET /meal-facilities/{facility_id}` | 목록의 UUID `id`. 이름·지역·주소·좌표(없으면 null)·대상·운영 시간·연락처·출처·확인일·주의사항 |
| `GET /seasonal-foods` | 선택 `month`(1~12), 생략 시 KST 현재 월. 이름 검색, 상세 본문을 제외한 요약과 이미지·쇼핑 검색 링크 |
| `GET /seasonal-foods/{food_id}` | 목록의 UUID `id`. 요약 + 원천 상세 글(`detail`)·재료명(`terms`)·원천 관련 레시피 이름 |
| `GET /seasonal-foods/{food_id}/recipes` | 실제 DB 레시피 연결. 기존 `RecipeRecord` 페이지 구조, 이름 검색·페이지 조회. 선택 `exclude_allergens` 반복 키(서버 알레르기 이름, 최대 19개)로 제외 후 건수·페이지 계산 |
| `GET /life-guides` | 제목 검색·페이지 조회. `id/slug/title/source_reference/checked_on` |
| `GET /life-guides/{slug}` | 가이드 요약 + 배열 순서대로 `steps`(단계 객체, `text` 등). 게시된 가이드만 조회 |

급식소는 원천 품질 표시와 조회 시점의 운영 종료일을 확인해 종료·미운영 시설을 제외한다. 시작 전 시설과 오래된 자료는 `cautions/quality_flags`에 안내한다. 원천 `reference_date`(자료 기준일)와 `checked_on`(원천 확인일)을 구분하며, 이용 자격·당일 운영·식사 제공 여부를 확정하지 않는다.

위치 허용 시 `/meal-facilities/nearby`에 HTTPS POST 본문으로 좌표를 전달한다. 좌표는 이번 검색 계산에만 쓰며 사용자·프로필·작업·시설 테이블에 저장하거나 응답으로 되돌리지 않는다. 성공·검증 오류·DB/내부 오류는 모두 `Cache-Control: no-store`다. 좌표를 URL 쿼리로 보내지 않는다. 서버의 공통 오류 응답은 잘못 입력한 좌표나 DB 세부 내용을 포함하지 않는다. 서버 앞단에서도 본문 로깅을 켜지 않아야 한다.

`latitude`는 -90~90, `longitude`는 -180~180의 유한 숫자이며 문자열·불리언은 받지 않는다. `district`는 기존과 같이 `region`과 함께 사용한다. 위치를 거부하거나 얻지 못하면 기존 지역 GET 조회를 사용한다. 거리는 약 10m 단위로 반올림한 직선거리(km)이며 실제 이동 거리·당일 운영을 뜻하지 않는다. `match`는 `district`(같은 시군구의 반경 내 시설), `nearby`(그 외 반경 내 시설), `district_no_coords`(거리 미확인)이고, 마지막 유형의 `distance_km`는 null이다. 지역 없이 검색하면 좌표 없는 시설은 거리순 결과에 넣지 않는다. 조회된 결과를 거리·이름·UUID의 일정한 순서로 정렬한 뒤 페이지를 자르며 `total`은 그 검색 전체 후보 수다. 기존 GET·상세 응답 형식과 DB 스키마는 바꾸지 않는다. 앱의 위치 권한·지역 대체 선택은 후속 앱 연결에서 구현한다.

제철 식재료는 `is_published=true`이고 상세가 `ok`인 항목만 제공한다. `content_sha256`·`provider/source_id/source_url/checked_on`으로 원천을 식별한다. 목록은 전체 상세 본문을 보내지 않고 상세 조회 시 읽어온다. `official_related_recipes`는 원천의 레시피 이름이며 앱에서 바로 조회 가능한 레시피 ID라는 뜻이 아니다. 앱 연결에는 `/recipes` 조회를 사용한다. 이 조회는 연결 당시 판본과 현재 활성 레시피 판본이 같은 자료만 제공하고, 연결 재적재 전의 낡은 판본은 숨긴다. `shopping_search_url`은 재료명으로 이동하는 외부 쿠팡 검색 주소이며 가격·재고·주문 API가 아니다.

제철 연결 레시피의 `exclude_allergens`는 일반 레시피 조회와 같은 판정 함수를 사용한다. 검출·확인 필요·판정 불가 항목에 제외 조건이 걸리거나 알레르기 분석이 완전하지 않은 레시피를 제외한 뒤 `total`과 페이지를 계산한다. 제외 조건이 있는 응답은 오류를 포함해 `Cache-Control: no-store`다. 공개 조회이며 계정 프로필을 저장·수정하지 않는다. 질환별 맞춤 추천은 식단 추천 API에서 수행한다.

식단 추천의 `seasonal_ingredients[]`는 이름·공식 원문·쿠팡 검색 주소 외에 `seasonal_food_id`(UUID)와 `month`(1~12)를 제공한다. 앱은 해당 월·상세 안내 연결에 사용할 수 있다. 두 필드는 이전 응답과의 호환을 위해 선택 값이며, 실제 추천은 현재 활성 레시피에 연결되고 공개·상세 정상인 KST 현재 월 자료만 반영한다.

### 관리자 수집 작업 현황

`GET /api/v1/admin/data-jobs`는 관리자 Bearer 세션이 필요하다. 공통 페이지·선택 `status`(`queued/running/succeeded/failed/cancelled`)·선택 `q`(오류 단계 코드 검색)를 지원한다. `kind=public_data_daily`이면서 `user_id=null`인 공통 작업만 최신 생성순으로 반환한다. 응답 항목은 `id/kind/status/attempts/next_run_at/created_at/started_at/finished_at/error_code`다. 개인 사진·AI 작업, 원천 인증 정보, DB 연결 문자열과 전체 실행 로그는 포함하지 않는다.

관리자 미인증은 401, 일반 사용자 접근은 403, DB 오류는 재시도 가능한 `DATA_JOBS_UNAVAILABLE`(503)이며 응답은 `Cache-Control: no-store`다. 이 조회는 작업 전체 상태와 첫 실패 단계를 보여 주는 읽기 전용 API다. 단계별 건수·건너뜀 사유·RAG 검증은 실행기의 상태 파일로 별도 확인하며, 여기서 수집을 시작하거나 재시도·예약 등록하지 않는다. 성공 상태 하나만으로 모든 RAG 단계가 실행됐다고 판단하지 않는다.

### 관리자 전용 로그인

`POST /api/v1/admin/login`은 `{username, password}`를 받아 기존 `SessionData` 형식의 관리자 Bearer 세션을 반환한다. 아이디는 영문 소문자·숫자·점·밑줄·하이픈 3~64자로 정규화하며, 비밀번호는 로그인 시 최대 128자/512 UTF-8 바이트다. 비밀번호는 `SecretStr`로 처리하고 요청·오류·로그에 원문을 내보내지 않는다. 발급 뒤 웹은 `/admin/me`에서 서버 권한·사용자·만료를 다시 확인한다.

관리자 생성·비밀번호 재설정·비활성화는 운영자 전용 `app.jobs.provision_admin` CLI만 제공한다. 기본 관리자·공개 가입·웹의 권한 변경/비밀번호 변경 API는 없다. 비밀번호 정책은 15~128자이며, 고유 salt와 고정 비용 scrypt(N=2^16, r=8, p=2, 64MiB)를 사용한다. 관리자 계정은 일반 앱 사용자와 별도로 만든다. 재설정은 명시적 `--reset-password`가 필요하고 기존 세션을 폐기하며, 강등·비활성 사용자 권한을 자동으로 올리지 않는다. `--disable`도 기존 세션을 폐기한다.

없는 계정·비밀번호 불일치·잠김·비활성·권한 부족은 동일한 `ADMIN_LOGIN_FAILED`(401)로 응답하고 같은 해시 비용을 수행한다. 계정별 연속 실패 5회는 15분 잠금이며 잠긴 동안 시도해도 기한을 연장하지 않는다. 연결 peer별 5분/30회 제한은 `ADMIN_LOGIN_RATE_LIMITED`(429)와 `Retry-After`를 반환한다. 클라이언트의 전달 헤더를 직접 신뢰하지 않고 ASGI 연결 peer를 사용하므로 프록시 구성에 따라 같은 peer 제한을 공유할 수 있다. DB에는 peer의 SHA-256 키·기간·횟수만 보관하며 요청 처리 중 24시간 지난 창을 정리한다. API 프로세스당 해시 동시 실행은 2개로 제한하고 과부하는 `ADMIN_LOGIN_BUSY`(503)로 반환한다.

새 관리자 로그인에는 기본 1시간의 절대 재인증 기한을 적용한다(`ADMIN_SESSION_TTL_SECONDS`, 300~28,800초). 세션 갱신도 원래 기한을 넘지 못한다. `20261120_04`는 nullable `sessions.reauthenticate_at`과 관리자 자격·시도 제한 테이블을 추가하며 기존 사용자/카카오/게스트 세션에는 null로 두어 이전 동작을 유지한다. 모든 관리자 로그인 성공·오류는 `Cache-Control: no-store`이며 DB/해시 실패는 비밀값 없이 재시도 가능한 503으로 반환한다. 이 구현은 운영 계정 생성·관리자 웹 배포·CORS 설정 완료를 뜻하지 않는다.

### 관리자 생활 가이드 작성·검수·게시

아래 경로는 모두 관리자 Bearer 세션이 필요하며 성공·오류 응답에 `Cache-Control: no-store`를 적용한다. 관리자 웹은 민찬 담당의 기존 `src/admin` 구조를 사용한다. 이번 API 구현과 웹 로그인·화면 연결·서버 배포는 별도다.

| 메서드·경로 (`/api/v1` 접두사) | 계약 |
| --- | --- |
| `GET /admin/life-guides` | `limit/offset/q`(제목의 문자 그대로 검색), 선택 `review_status`·`is_published`. 요약·판본·검수/게시 상태·검수자/시각·관리 갱신 시각 |
| `POST /admin/life-guides` | `slug/title/steps/source_reference/checked_on`. 201, 항상 비공개 `draft`, `version=1` |
| `GET /admin/life-guides/{guide_id}` | UUID로 초안 포함 상세 조회. 요약 + 단계·비공개 검수 의견 |
| `PUT /admin/life-guides/{guide_id}` | `expected_version`과 `title/steps/source_reference/checked_on` 전체. 수정하면 비공개 초안으로 전환하고 이전 검수 결과를 비운다. `slug`는 변경하지 않는다 |
| `POST /admin/life-guides/{guide_id}/actions` | `expected_version/action`, 선택 `note`. 상태 전환 후 새 판본·현재 상태 반환 |
| `GET /admin/life-guides/{guide_id}/audit` | 페이지 조회. 선택 `q`는 작업명 문자 그대로 검색. 작업·행위자 ID·전후 판본/상태·서버 요청 ID·기록 시각 |

새 주소 `slug`는 소문자 영문·숫자·하이픈(최대 128자), 제목은 1~200자, 출처 설명은 1~1,000자다. 단계는 배열 순서대로 1~30개, 각 단계는 `text`(1~3,000자)와 선택 `title`(1~120자)을 받는다. 공백만인 값·알 수 없는 필드는 거부한다. `checked_on`은 한국 날짜 기준 미래일을 허용하지 않는다. 내용은 JSON 텍스트로 전달하며 HTML 실행 기능을 제공하지 않는다.

상태 흐름은 `draft/rejected → submit → review → approve → approved → publish`다. 승인은 바로 게시하지 않는다. `review → reject`에는 1~1,000자의 사유가 필요하며, 승인에도 선택 의견을 남길 수 있다. 의견은 관리자 상세에만 표시한다. `unpublish`는 게시 중인 가이드만 비공개로 전환하고 검수 결과·내용을 보존한다. 재게시에는 승인 상태가 필요하다. 수정은 게시를 내리고 `draft`로 되돌리므로 웹은 수정 전에 공개 중단을 안내해야 한다. 검수/게시에는 기존 자료의 내용도 같은 기준으로 검증한다.

수정·상태 변경은 행 잠금과 정수 `expected_version`으로 충돌을 막는다. 오래된 판본은 `GUIDE_VERSION_CHANGED`(409), 잘못된 상태 전환은 `GUIDE_STATE_CHANGED`(409), 기존 내용이 검증 기준에 맞지 않으면 `GUIDE_CONTENT_INVALID`(409)로 반환하며 최신 상태를 다시 확인해야 한다. 이름이 같은 주소는 `GUIDE_SLUG_EXISTS`(409), 없는 가이드는 `GUIDE_NOT_FOUND`(404), DB 실패는 재시도 가능한 `GUIDE_ADMIN_UNAVAILABLE`(503)다. 성공한 변경마다 판본을 1 올리고 상태 변경과 감사 행을 같은 트랜잭션에 저장한다. 감사 저장 실패 시 가이드 변경도 롤백한다.

감사는 생성·수정·검수 요청·승인·반려·게시·비공개 작업의 메타데이터만 기록한다. 원문 전체·검수 의견·토큰은 복제하지 않는다. 관리자 계정을 삭제하면 행위자/검수자 FK는 null로 바뀌고 감사 이력은 유지한다. 감사 수정·삭제 및 가이드 영구 삭제 API는 제공하지 않는다. 공개 조회 응답에는 검수 의견·관리자 ID·감사 자료를 추가하지 않는다.

마이그레이션 `20261120_03`은 `20261120_02` 다음에 가이드 관리 필드와 `guide_audit_events`를 추가한다. 기존 게시 자료는 `approved`로 옮겨 공개 상태·주소·내용을 유지하며 검수자·검수 시각은 알 수 없으므로 null로 둔다. 기존 행의 `updated_at` 초기값은 관리 필드 도입 시각이며 원천 확인일을 대신하지 않는다. 운영 복구에 자동 downgrade를 사용하지 않는다.

### 6.4 콘텐츠 주제 요청

모든 경로는 `/api/v1` 이후 부분이며 인증이 필요하고 성공·오류·검증 응답 모두 `Cache-Control: no-store`다. 프로필 동의와 별개의 명시적 요청이며, 입력 내용은 운영자가 확인한다. 사용자 목록·상세에는 본인 자료만 보이고 다른 사용자의 ID는 없는 자료와 동일하게 404다.

| 경로 | 동작 |
| --- | --- |
| `POST /content-topic-requests` | `submission_id`(클라이언트 생성 UUID v4), `kind`(`life_guide`/`video`), `topic`(공백 제거 후 1~60자 한 줄). 새 접수 201, 동일 전송 재시도 200. `data.request`, `data.replayed` 반환 |
| `POST /content-topic-requests/withdraw-submission` | 접수와 같은 본문으로 전송 번호를 취소하고 200 `TopicRecord` 반환. 접수 전이어도 원문 없는 취소 기록을 만들며, 같은 번호로 늦게 도착한 POST는 취소 상태를 유지 |
| `GET /content-topic-requests` | 본인 목록. 공통 `limit/offset/q`와 선택 `kind/status/submission_id`. 생성 시각 내림차순·ID 정렬. 전송 UUID 조회는 자료를 생성하지 않음 |
| `GET /content-topic-requests/{request_id}` | 본인 요청·처리 상태·답변·현재 게시된 연결 가이드 |
| `DELETE /content-topic-requests/{request_id}` | 본인 취소. 원문·답변·연결을 지우고 `withdrawn` 반환. 반복 취소는 같은 결과 |
| `GET /admin/content-topic-requests`, `GET /admin/content-topic-requests/{request_id}` | 관리자 처리함·상세. 취소된 요청 제외. 사용자 ID·프로필은 응답에 포함하지 않음 |
| `PUT /admin/content-topic-requests/{request_id}` | 관리자 `expected_version`, `status`(`reviewing/completed/declined`), 선택 `reply/guide_id`. 완료·보류에는 1~1,000자 답변 필요 |
| `GET /admin/content-topic-requests/{request_id}/audit` | 관리자 페이지 조회. 생성·처리·취소의 행위자 ID·전후 상태/판본/연결 ID·서버 요청 ID·시각만 기록 |

상태는 `received → reviewing → completed/declined`이며 검토 없이 바로 완료·보류할 수도 있다. 완료·보류를 다른 결정으로 바꾸려면 먼저 `reviewing`으로 되돌린다. 같은 최종 상태의 답변 보완은 허용한다. 생활 가이드 요청 완료에는 승인 후 게시된 `guide_id`가 반드시 필요하며, 영상 요청에는 가이드를 연결하지 않는다. 이 API는 영상 제작이나 게시를 자동 실행하지 않는다. 연결 가이드가 나중에 비공개로 바뀌면 본인 응답의 `guide`는 null이며 비공개 내용은 공개하지 않는다.

`submission_id`는 같은 계정에서 같은 주제 전송을 재시도하는 동안 유지한다. 같은 번호로 종류·내용을 바꾸면 `TOPIC_SUBMISSION_CHANGED`(409)다. 응답을 못 받았으면 목록을 `submission_id`만으로 조회해 해당 계정의 접수 기록(0~1건)을 확인할 수 있다. 이 조회는 새로 접수하지 않으므로 기록이 확인되면 해당 요청 ID에 DELETE를 보낼 수 있다. 조회 시점에 결과가 없다는 사실은 아직 처리 중인 POST의 취소 완료를 뜻하지 않으므로 앱은 전송 번호와 미확인 상태를 보존해야 한다. 취소 후에도 원문 없는 접수 번호·입력 해시를 남겨 늦은 재전송이 취소한 요청을 되살리지 못하게 한다. 새 요청은 새 번호를 사용한다. 재시도는 추가 접수로 세지 않고, 취소를 포함한 새 접수는 계정별 최근 24시간 최대 5건이다. 초과 시 `TOPIC_REQUEST_LIMIT`(429)와 `Retry-After`(초)를 반환한다.

요청 수정·취소·감사 저장은 한 트랜잭션이고, 관리자 판본 충돌은 `TOPIC_VERSION_CHANGED`(409)다. 가이드 누락/비게시/잘못된 종류는 422 또는 `TOPIC_GUIDE_UNAVAILABLE`(409), DB 실패는 재시도 가능한 `TOPIC_REQUEST_UNAVAILABLE`(503)다. 취소된 요청은 관리자 처리함·상세·감사에서도 숨긴다. 감사에는 주제·답변·프로필·인증 값이 복제되지 않는다. 계정 삭제는 요청과 감사 자료를 함께 삭제하고 관리자 계정만 삭제하면 처리 이력을 보존하며 행위자 FK를 null로 바꾼다. 프로필 동의 철회는 기존 계약대로 프로필만 삭제하며, 주제 취소는 별도 DELETE로 수행한다.

조회 결과가 없어도 취소하려면 `withdraw-submission`에 보관한 동일 본문을 보낸다. 접수와 전송 번호 취소는 사용자 행의 `FOR NO KEY UPDATE` 잠금으로 직렬화하며, 감사 행의 외래 키 확인과 잠금 순환을 만들지 않는다. 접수 전 취소 기록은 `was_submitted=false`로 구분하고 원문을 저장하지 않는다. 이 기록은 정상 접수 5건 한도와 별도로 최근 24시간 최대 20건이며, 초과 시 `TOPIC_CANCEL_LIMIT`(429)와 `Retry-After`를 반환한다. 이미 접수되었던 요청은 취소해도 정상 접수 한도에 포함된다. 같은 번호의 취소 재시도는 추가로 세지 않는다.

`20261120_05`는 `content_topic_requests`, `topic_request_audit`를 추가한다. `20261120_06`은 `was_submitted`를 추가하고 기존 행을 true로 유지하며, false 행은 취소 상태만 허용한다. 앱은 AI 도우미의 생활 안내에서 게시된 안내 전체 단계를 읽고, 생활 안내·놀이터 영상에서 주제 접수·답변·취소를 이용한다. 전송 전에 서버·계정별 보안 저장소에 전송 번호와 본문을 보관하고, 불명확한 전송은 같은 번호로 확인·재시도·취소한다. 관리자 처리 화면 연결·실제 배포는 별도다. 기존 경로를 제거하지 않는다.

## 7. 미구현 예정 API

다음은 후속 경로다. 현재 서버에서 호출하면 404가 반환된다. 카탈로그 DTO와 표본은 9절에 정의했다. 나머지 기능의 세부 계약은 착수 시 관련 담당자와 맞춘다.

| 영역 | 예정 경로 | 상태 |
| --- | --- | --- |
| 사진 영양 분석 | `POST /api/v1/nutrition/analyses`, `GET /api/v1/nutrition/analyses/{id}`, `POST /api/v1/nutrition/analyses/{id}/confirm` | 미구현 |
| 복지 RAG | `POST /api/v1/welfare/ask` | 검색·답변 생성 후속, 맞춤 목록 추천과 별도 |
| 도우미 | `POST /api/v1/assistant/messages` | 미구현 |
| 관리자 운영 | `/api/v1/admin/*` | 전용 로그인·권한·수집 조회·생활 가이드 검수/게시/감사 구현. 시설·제철 검수·작업 재시도는 후속 |

이 표는 예정 경로의 요약이며 전체 기능의 확정 계약은 아니다. 신규 기능의 채택 상태는 최종 기획서, 기능별 계획은 구현계획서를 따른다.

## 8. 게스트·카카오 인증·관리자 진입

| 메서드·경로 | 요청 | 성공 |
| --- | --- | --- |
| `POST /api/v1/auth/guest` | JSON `{}`, 인증 없음 | 201, 새 `user_id`·`role=user`·`access_token`·`token_type=Bearer`·`expires_at` |
| `POST /api/v1/auth/kakao` | JSON `{access_token}`, 카카오 토큰 | 200, 같은 카카오 사용자에 서비스 세션 발급 |
| `POST /api/v1/auth/kakao/link` | JSON `{access_token}`, 기존 서비스 Bearer | 200, 기존 사용자 ID와 `kakao_linked=true` |
| `GET /api/v1/auth/me` | Bearer 세션 | 200, `user_id`·`role`·`expires_at` |
| `POST /api/v1/auth/refresh` | Bearer 세션, 본문 없음 | 200, 같은 사용자에 새 토큰. 이전 토큰은 즉시 폐기 |
| `DELETE /api/v1/auth/session` | Bearer 세션, 본문 없음 | 200, `data.revoked=true`. 해당 세션만 폐기 |
| `GET /api/v1/admin/me` | 관리자 Bearer 세션 | 200, 사용자 식별·현재 서버 권한 |

모두 공통 `data/meta` 응답을 사용한다. 발급/갱신은 `Cache-Control: no-store`이며 토큰은 이 두 응답에서만 공개한다. 일반 조회에는 토큰·해시를 내보내지 않는다. 발급 본문에 `role`·`user_id` 등 추가 필드를 보내면 422다. 없는 토큰·알 수 없는 토큰·만료·폐기·비활성 사용자는 모두 401로 처리한다. 인증이 유효하지만 일반 사용자이면 `/admin/me`는 403이다.

토큰은 256비트 난수 기반 opaque 문자열이며 DB에는 SHA-256 해시만 저장한다. 기본 유효기간은 7일, `SESSION_TTL_SECONDS`는 300~2,592,000초로 제한한다. 갱신은 유효한 기존 토큰을 한 번 소비하고 새 토큰을 같은 트랜잭션에 저장한다. 동시 갱신은 하나만 성공한다. 별도 장기 refresh token은 없으며 만료 후에는 갱신할 수 없다.

앱은 세션을 보안 저장소에 보관하고 로그·일반 설정 저장소에 넣지 않는다. 새 게스트 발급은 새 사용자 생성이므로 앱 시작마다 호출하지 않는다. 카카오 연결 사용자는 재로그인해 같은 사용자 ID를 복구한다. 미연결 게스트의 만료 후 복구는 제공하지 않는다. DB 마이그레이션 전 발급/조회는 저장소 오류 503이 될 수 있다.

관리자 권한은 공개 API로 신청/변경할 수 없다. 운영자가 게스트 발급으로 확인한 사용자 UUID에 서버 DB 자격으로 아래 CLI를 실행한다. CLI는 사용자 ID와 결과 권한만 출력한다. 권한은 매 요청 DB에서 읽으므로 `user`로 내리면 기존 토큰도 다음 관리자 요청부터 403이다. 기본 관리자·공유 비밀번호·자동 승격은 없다.

```powershell
# src/backend, 운영자가 대상 사용자 ID를 확인한 뒤 실행
python -m app.jobs.set_user_role <사용자-UUID> --role admin
python -m app.jobs.set_user_role <사용자-UUID> --role user
```

공개 운영 전 HTTPS·발급 호출 제한·앱 보안 저장소·관리자 로그인 절차를 연결해야 한다. 현재 구현은 세션과 권한 경계이며 관리자 운영 화면/감사 기능 완료를 뜻하지 않는다.

## 9. 앱·관리자 카탈로그 DTO 인계

DTO 구현은 `app/schemas/catalog.py`에 있다. 레시피 목록·상세와 식단 추천은 DB에 연결되었으며 [openapi.json](./openapi.json)에 포함한다. 나머지 예정 경로의 기계 판독 계약은 [catalog.openapi.json](./catalog.openapi.json), JSON 예제는 [api_examples.json](./api_examples.json)이다. 공개 원천 조회는 개인 프로필을 읽지 않는다. 개인 기록은 `CurrentAuth`의 사용자로 제한한다.

| 경로 | 요청 필드 | 성공 `data` |
| --- | --- | --- |
| `GET /recipes` | `limit=20`(1~100), `offset=0`(0~10000), 선택 `q`·`category`·`cooking_method`·반복 `exclude_allergens` | `items[]`, `limit`, `offset`, `total` |
| `GET /recipes/{recipe_id}` | COOKRCP01 원천 ID 문자열, 예 `108` | `RecipeRecord` |
| `POST /meal/recommendations` | 필수 `meal_time`(`breakfast/lunch/dinner/snack`), 선택 `exclude_allergens=[]`·`exclude_ingredients=[]`·`preferred_ingredients=[]`·`health_conditions=[]`·`soft_food=false`·`simple_cooking=false`·`limit=5`(1~20) | `recommendation_id`, `items[].item`·`reasons[]`·`seasonal_ingredients[]`·`matched_preferences[]`, `evaluated_at`, `rules_version`, `warnings[]` |
| `GET /welfare` | `limit`·`offset`·선택 `q`, 선택 `scope`(`central_nationwide`/`local`, 없으면 둘 다), 선택 `region`·`district`(`district`는 `region`과 함께) | 같은 페이지 구조의 `WelfareRecord` |
| `GET /welfare/{service_id}` | 원천 ID 문자열, 예 `WLF00000060` | `WelfareRecord` |
| `POST /welfare/recommendations` | 필수 `age`(0~120)·`region`(1~50자), 선택 `district`·`lives_alone`·`limit=5`(1~20) | 같은 추천 구조의 `WelfareRecord` |

모든 경로에는 `/api/v1` 접두사를 붙인다. `q`는 1~100자다. 알레르기는 데이터 계약의 19종 이름을 사용하고 앱의 `달걀`을 `알류`로 매핑한다. 배열 쿼리는 `?exclude_allergens=알류&exclude_allergens=우유`처럼 같은 키를 반복한다. JSON은 snake_case, 알 수 없는 요청 필드는 422다. 제외 재료는 항목당 1~100자·최대 30개다. 정렬은 원천 ID 오름차순을 기본으로 하고, 조회 구현 시 같은 필터의 `total`·페이지 일관성을 시험한다.

레시피 응답은 [데이터 담당 계약](../data/recipe_contract.md)의 재료·단계·알레르기 근거·품질 필드를 그대로 보존한다. 누락 영양값은 `null`이며 0으로 채우지 않는다. `_g`는 g, `_mg`는 mg, `_kcal`는 kcal지만 `basis=per_serving_unverified`여서 g당/1인분 확정 계산으로 쓰지 않는다. 재료로 계산한 영양은 `computed_nutrition`에 따로 싣는다([영양 정의서](../data/food_nutrition_contract.md) 3.4): 재료 목록 전체 합계 `total`(`basis=whole_recipe`), 재료 원문에 'N인분'이 있을 때만 `per_serving`, 비교 값 `density`, 화면 안내 `notices[]`(`label`을 그대로 표시). 지금 판본이 아직 식품 매핑 전이면 `null`이다. 화면은 `per_serving`이 있으면 1인분, 없으면 "레시피 전체(재료 기준)"로 `total`을 보여 주고, `nutrition`을 함께 보여 줄 때는 "원문 표기"로 구분한다. `hold`는 목록/추천에서 제외하고 알레르기의 `detected`와 `needs_check.candidates` 모두 필터 대상으로 삼는다. `complete=false`를 안전 확인 완료로 표시하지 않는다. `quality.issues[].detail`은 구조화된 JSON 객체다.

복지는 지원 대상·선정 기준·지원 내용·신청 안내·문의처를 구분한다. `application[].method/description`과 `contacts[].name/contact`는 XML의 `servSeDetailNm/servSeDetailLink`를 옮긴 표시 필드이며, `description/contact`가 반드시 URL이라는 뜻은 아니다. 사업은 중앙(`scope=central_nationwide`, `region_scope=national`)과 지자체(`scope=local`)로 나뉘고, 지자체는 `region_scope`가 `province`(시도 전체, `sgg=null`) 또는 `district`이며 `ctpv`·`sgg`는 정규화한 시도·시군구 이름이다([복지 데이터 계약](../data/welfare_contract.md) 2·3절, DB는 `welfare_revisions.normalized`). `region`·`district`를 주면 내 시군구 사업 → 내 시도 전체 사업 → 전국 사업 순이며, 지역 입력은 줄임말·옛 이름을 데이터 계약의 `services_for`와 같은 규칙으로 해석한다. 신청 기간이 확인되지 않은 중앙 사업은 `application_status=unknown`을 유지한다. 수집 대기·게시 보류 자료를 정상 추천으로 노출하지 않는다. 신청 가능 여부·수급 자격 확정 결과를 만들어 넣지 않는다.

레시피 출처는 `provider/service/source_id/fetched_at/raw_sha256`, 복지는 `provider/source_id/source_url/checked_at/detail_checked_at/raw_sha256`를 제공한다. 두 출처의 `revision_id`는 DB 판본 UUID이며 수집 원문 표본에서는 `null`이다. DB 조회 구현에서는 활성 판본을 채운다. 기존 공통 `meta.revision`은 정수 계약을 유지하며 원천 ID나 DB UUID를 대신 넣지 않는다. 시간은 시간대 포함 ISO 8601이며 미수집 시각은 추정하지 않는다.

빈 목록·추천은 200과 `items=[]`, 없는 ID 또는 노출 불가 자료는 404, 잘못된 입력은 422, 저장소 일시 장애는 503을 사용한다. 추천 이유·규칙 버전은 실제 추천 구현에서 생성한다. 현재 표본은 공개 원천을 DTO로 검증한 예시이며 추천 기능 실행 결과가 아니다.

## 10. 레시피 DB 조회와 프로필

`GET /api/v1/recipes`와 `GET /api/v1/recipes/{recipe_id}`는 공개 경로다. COOKRCP01의 활성 DB 판본만 사용하며 `hold`를 제외한다. 상세 출처의 `revision_id`는 실제 판본 UUID다. 알레르기 제외 시 검출 항목·확인 필요 후보·원재료명으로 판정 불가한 항목을 함께 확인한다. 재료 분석이 불완전한 레시피도 제외한다. 제외 조건은 원재료명 기반 필터이며 제조 과정의 교차 접촉 여부는 원천 데이터로 확인할 수 없다.

프로필은 Bearer 세션으로 식별한 본인에게만 접근을 허용한다. 모든 성공 응답에 `Cache-Control: no-store`를 붙인다.

| 메서드·경로 | 동작 |
| --- | --- |
| `GET /api/v1/profile` | 저장된 프로필과 동의·수정 시각 반환. 미등록이면 `data=null` |
| `PATCH /api/v1/profile` | 최초 저장은 `consent=true` 필수. 이후 전달한 선호 항목만 수정 |
| `DELETE /api/v1/profile` | 프로필·동의 시각 삭제. 반복 호출도 200, `data=null` |

```json
{
  "consent": true,
  "preferences": {
    "age": 70,
    "region": "대구",
    "district": "남구",
    "lives_alone": true,
    "soft_food": true,
    "preferred_ingredients": ["두부"],
    "excluded_ingredients": [],
    "exclude_allergens": ["알류", "우유"]
  }
}
```

`age`는 0~120 정수, 지역·재료명은 공백 제거 후 1~100자다. 재료 목록은 30개, 알레르기는 계약상 19종으로 제한한다. 스칼라의 `null`과 배열의 `[]`로 해당 값을 지운다. 미전달 항목과 최초 동의 시각은 유지한다. 최초 동의 없이 저장하면 409, 빈 변경·알 수 없는 필드·잘못된 값은 422, DB 장애는 503이다. `{"consent":false}`는 동의를 철회하며 프로필을 삭제한다. 철회 요청에 `preferences` 객체를 함께 보내면 422다. 프로필 삭제 후 새 저장에는 다시 동의해야 한다. 게스트 세션은 별도 수명주기를 따른다.

저장은 `profiles.user_id`로 사용자를 고유하게 연결한다. 같은 사용자의 변경·철회는 사용자 행 잠금으로 직렬화한다. 배포 시 `20261109_01` 마이그레이션을 적용한다. 동의 화면의 안내 문구와 앱 입력·보안 저장소 연결은 프런트 연동 작업에서 제공한다.

## 11. Flutter·React 연동 기준

| 설정 | 로컬 개발 값 | 요청 예 |
| --- | --- | --- |
| Flutter Android 에뮬레이터 `API_BASE_URL` | `http://10.0.2.2:8000` | `GET /api/v1/recipes?limit=1` |
| React 관리자 `VITE_API_BASE_URL` | `http://127.0.0.1:8000` | `GET /api/v1/admin/me` |

기본 주소에는 스킴·호스트·포트만 넣고, 요청 경로에 `/api/v1`을 붙인다. React 개발 서버가 `http://localhost:5173`에서 실행되면 백엔드 `CORS_ORIGINS`에 그 주소를 등록한다. Swagger 문서는 PC에서 `http://127.0.0.1:8000/docs`로 접속한다. 기업 서버용 HTTPS 주소는 배포 작업에서 확정한다.

- 성공 시 최상위 `data`를 DTO로 읽는다. 목록은 `data.items`, 추천은 `data.items[].item`과 `reasons`를 읽는다. JSON 키는 `snake_case`이며, 원천 ID는 숫자처럼 보여도 문자열로 유지한다.
- HTTP 오류는 `error.code`로 분기하고 `error.message`를 표시한다. 입력 오류는 `error.fields`, 서버가 재시도 가능하다고 표시한 오류는 `error.retryable`을 읽는다. JSON 본문이 없는 네트워크·프록시 오류는 앱의 기본 안내로 처리한다.
- React는 관리자 요청에 `Authorization: Bearer <access_token>`을 보내고 `data.role`을 확인한다. 401은 세션 재확인, 403은 권한 부족 상태로 표시한다. Flutter와 React 모두 토큰·프로필을 요청 및 응답 로그에서 제외한다.

Flutter의 레시피 목록·상세·식단 추천·세션·프로필·식단표·레시피 저장은 서버 연결을 제공한다. 복지 화면은 아직 번들 자료를 사용한다. 복지 목록·상세·후보 추천·저장 서버 API는 이번 작업 브랜치에 구현했으며, 앱 DTO 연결과 기업 서버 재배포 후 실제 자료로 검증해야 한다. 오류 파서는 `error.message`를 읽는다.

## 사진 음식의 유사 후보와 영양 참고값

`POST /api/v1/ai/food-photo`의 `foods[].matches[]`는 기존 `food`·`serving`에 `match_basis`를 추가한다. `name`은 인식 이름과 정확히 일치하는 DB 음식이고, `similar`는 부분 일치 또는 음식명 별칭·정규화·이름 유사도 규칙으로 찾은 후보다. 이 규칙은 영양성분의 동등성을 보장하지 않는다.

유사 후보는 활성 영양 DB의 `음식` 분류에서 최대 5건을 반환한다. 기준량·열량이 없는 자료와 비활성 판본은 제외하며, 원재료를 조리 음식 대신 자동 연결하지 않는다. 영양값과 기준량·출처 판본은 `food`의 실제 DB 값을 사용하고, 누락 성분은 `null`을 유지한다. 관련 후보가 없으면 빈 목록을 반환한다. 유사 후보에 사용할 이름 메타데이터는 요청 안에서 한 번만 읽으며 앱에서 전체 DB를 검색하지 않는다.

앱은 유사 후보를 자동 선택하지 않는다. 기준량과 열량·탄수화물·단백질·지방·나트륨을 참고값으로 표시한 뒤 사용자가 선택한다. 다음 화면의 `/nutrition/calculate`는 선택한 실제 `food_id`·`revision_id`와 확인한 분량을 사용한다. 사진 후보의 예상 분량은 `amount_is_estimate=true`로 구분한다. 재료 추정·합산은 이 기능에 포함하지 않는다.

## 예상 재료로 영양 계산하기

`POST /api/v1/ai/food-ingredients`는 서비스 세션과 `allow_external_processing=true`, `dish_name`(1~60자), `standard_serving_grams`(10~1500 정수)를 받는다. 사진은 다시 전송하지 않는다. 활성 공공 레시피에 이름이 일치·포함되는 항목이 있으면 출처 판본과 최대 2,000자의 재료 구성을 참고한다. 레시피의 원문 총량을 검증된 1인분으로 취급하지 않으며, NVIDIA가 일반적인 조리법에 따른 1인분 재료량을 제안한다.

응답 `ingredients[]`는 최대 8개이며 각 항목은 `name`, `amount_g`, `matches[]`, `is_water`를 제공한다. AI 응답에는 영양 수치를 허용하지 않는다. 재료량은 양수·최대 1,500g·소수점 셋째 자리까지, 합계는 최대 2,500g으로 제한하고 중복 이름을 거부한다. 기존 재료 매핑 규칙으로 활성 원재료·가공식품 DB에 연결하며, 모호한 후보는 사용자 확인을 요구한다. 조리용 물은 제외임을 명시하고, 연결하지 못한 재료는 빈 후보로 남긴다. `reference_recipe`는 실제 참고한 공개 레시피의 ID·판본·이름이며 없으면 `null`이다.

이 API는 계산 결과나 식사 기록을 자동 저장하지 않는다. 앱에서 재료 종류·분량을 확인하고, 미연결 재료를 직접 찾거나 명시적으로 제외한 뒤 기존 `/nutrition/calculate`와 `/meals`를 사용한다. 다른 인식 음식과도 한 끼로 합산하며, 제외한 재료와 보이지 않는 기름·양념 때문에 전체 요리의 실제 영양과 다를 수 있다는 안내를 유지한다. 모든 선택량은 예상 분량으로 표시한다. 기존 AI 일일 한도·동시 실행 제한·세션 재확인·응답 검증을 공유하고, 개인 프로필이나 사진을 재료 추정 요청에 포함하지 않는다.

## 복지 근거 답변 API (2026-11-25)

인증된 `POST /api/v1/ai/welfare-chat`는 질문과 외부 처리 동의, 선택적 시도·시군구를 받아 기존 KURE-v1/pgvector 복지 인덱스를 검색한다. 게시 원본·판본·지역·종료일을 대조하고 출처 번호·공식 링크·확인일을 반환한다. 자료가 없으면 자격·지원 내용을 생성하지 않고, AI 실패 시 검색된 자료를 보여준다. 모델과 인덱스 준비 전에는 명시적 503이며 기본 설정은 비활성이다. 요청·응답·별도 서비스 및 운영 준비는 [복지 RAG 안내](../data/welfare_rag_api.md)를 따른다. 새 DB 마이그레이션은 없다.
