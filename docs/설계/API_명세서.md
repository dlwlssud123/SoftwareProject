# ValueFlow 공통 백엔드 API 명세서

- 작성일: 2026-11-03
- 갱신일: 2026-11-18
- API 경로 버전: `v1` / 애플리케이션 버전: `0.1.0`
- 구현 기준: `src/backend/app`의 실제 등록 경로·Pydantic 모델·예외 처리
- 로컬 주소: `http://127.0.0.1:8000`
- 서비스 API 접두사: `/api/v1`
- 실행 안내: [백엔드 README](../../src/backend/README.md)
- 기계 판독용 명세: [openapi.json](./openapi.json)

상태 확인, 게스트 세션 발급·조회·갱신·폐기, 관리자 권한 확인, 레시피 DB 목록·상세, 식단 추천과 동의 기반 프로필 CRUD를 구현했다. 복지 목록·상세와 복지 추천은 [예정 계약](./catalog.openapi.json) 및 [요청·응답 표본](./api_examples.json)을 제공한다. 기업 서버 주소와 HTTPS 경로는 배포 시 확정한다.

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

`openapi.json`은 실행 코드의 `app.openapi()`에서 생성한 스냅샷이다. `catalog.openapi.json`은 모든 경로에 `x-implementation-status: planned`를 붙인 별도 인계 문서다. 실행 서버에 예정 경로를 추가하지 않는다. `src/backend`에서 `python -m app.jobs.export_api_contract`로 둘을 재생성한다. 표본 갱신은 `PYTHONPATH=../data` 설정 후 같은 명령에 `--welfare-snapshot <실제 수집 JSON 경로>`를 전달한다. 실제/예정 스냅샷과 DTO 표본은 테스트에서 대조한다.

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

같은 사용자의 같은 키·같은 요청은 기록을 하나만 생성한다. 날짜는 UTC 기준으로 비교하므로 같은 시각의 다른 시간대 표기도 같은 요청이다. 같은 키로 다른 내용을 보내면 `IDEMPOTENCY_KEY_REUSED`(409), 기록을 삭제한 뒤 그 생성 요청을 재전송하면 `MEAL_ALREADY_DELETED`(409)다. 수정 후 최초 생성 요청을 재전송하면 같은 기록의 **현재 상태**와 `replayed=true`를 반환한다. 신규 저장에는 새 키, 네트워크 재시도에는 기존 키를 사용한다.

수정·삭제는 `version`으로 경합을 확인하며 오래된 버전은 `MEAL_VERSION_CHANGED`(409)로 막는다. 변경을 반영하기 전에 상세를 다시 읽도록 앱에서 안내한다. 타인과 없는 기록은 `MEAL_NOT_FOUND`(404)로 구분하지 않는다. DB 실패는 재시도 가능한 `MEALS_UNAVAILABLE`(503)이며 기록·음식·중복 방지 이력을 함께 롤백한다. 요청 키 원문과 입력 원문은 중복 방지 테이블에 남기지 않고 해시와 기록 링크만 보관한다. 기록 삭제 시 링크를 비워 재시도에 의한 복원을 막고, 사용자 DB 행 삭제 시 그 사용자의 기록·음식·요청 이력을 cascade 삭제한다. 세션 폐기와 프로필 동의 철회는 사용자 DB 행 삭제와 다르다.

마이그레이션은 `20261118_01 → 20261119_01 → 20261120_01` 단일 경로다. 중간의 복지 메모 마이그레이션은 PR #58과 같은 파일을 재사용하며 기존 저장 항목을 유지한다. 새 섭취 마이그레이션은 기존 기록을 version=1로 보존하고 순서·스냅샷 컬럼을 nullable로 추가한다. 배포에는 `alembic upgrade head`가 필요하며 운영 DB를 자동 downgrade하지 않는다. 코드·CI 검증과 main 병합·기업 서버 배포·앱 화면 연결은 별도 상태로 관리한다.

## 7. 미구현 예정 API

다음은 후속 경로다. 현재 서버에서 호출하면 404가 반환된다. 카탈로그 DTO와 표본은 9절에 정의했다. 나머지 기능의 세부 계약은 착수 시 관련 담당자와 맞춘다.

| 영역 | 예정 경로 | 상태 |
| --- | --- | --- |
| 사진 영양 분석 | `POST /api/v1/nutrition/analyses`, `GET /api/v1/nutrition/analyses/{id}`, `POST /api/v1/nutrition/analyses/{id}/confirm` | 미구현 |
| 복지 | `GET /api/v1/welfare`, `GET /api/v1/welfare/{service_id}`, `POST /api/v1/welfare/recommendations` | DTO 계약 제공·실제 조회 후속 |
| 복지 RAG | `POST /api/v1/welfare/ask` | 검색·답변 생성 후속, 맞춤 목록 추천과 별도 |
| 도우미 | `POST /api/v1/assistant/messages` | 미구현 |
| 관리자 운영 | `/api/v1/admin/*` | `/admin/me` 권한 확인 구현. 검수·게시·재시도는 후속 |

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

현재 Flutter 화면은 `DemoRepository`의 번들 JSON과 기기 내 규칙으로 식단·복지를 추천한다. 서버 전환은 연결된 레시피 목록·상세와 세션·프로필부터 진행한다. 식단 추천은 실행 API에서 확인할 수 있다. 복지 목록·상세·추천은 [예정 OpenAPI](./catalog.openapi.json)와 [JSON 표본](./api_examples.json)으로 화면을 먼저 맞추고, 실제 서버 연결은 해당 기능이 구현된 뒤 검증한다. [Flutter 통신 PR #6](https://github.com/dlwlssud123/SoftwareProject/pull/6)의 오류 파서는 화면 연동 시 `error.message`를 읽도록 맞춘다.
