# 전체 레시피·식품 DB 적재

2026-11-05 로컬 PostgreSQL 16.15에 공식 API의 전체 레시피와 식품 품목대표를 적재했다. 기존 앱의 50건 JSON은 유지한다. 기업 서버에는 아직 적용하지 않았다.

## PR #7 통합 후 레시피 판본 갱신 (2026-11-05)

새 필드·영양 검증을 반영해 `recipe-validation-v2` 및 알레르기 규칙 해시로 레시피를 다시 적재했다. 아래 최초 적재 표와 품질 수치는 v1 시점의 이력이다.

- 최신 품질: 정상 **905** / 주의 **246** / 보류 **5**. 활성 레시피는 1,151건이다.
- 원천 레시피 수 1,156건은 그대로이며 새 판본 1,156건을 추가했다. 기존 1,156판본은 보존한다.
- 식품 파서 버전은 유지하며 식품 판본은 8,807건으로 추가되지 않았다.
- 새 recipe-only run: `8d2ecb05-81cf-4201-8a4c-40ec4e2c4270`, 입력 지문 `e283d3d39172aaec6e5e337a54048d2b90596c6b06285d9a65a56579c68308ce`.
- recipe-only apply를 다시 실행했을 때 추가 행·판본은 모두 0건이다. all verify에서 레시피 1,156건과 식품 8,807건 대조를 통과했다.
- 적용된 검증 정보는 `data_import_runs.inputs.recipe_validation`에 저장한다. 검증 코드가 바뀌면 버전을 올리고, 알레르기 규칙 내용 변경은 해시로 새 판본을 구분한다.

## 최초 적재 범위와 결과

| 항목 | 적재·검증 결과 |
| --- | --- |
| COOKRCP01 전체 레시피 | 1,156건 / 판본 1,156건 |
| 레시피 품질 | 정상 987, 주의 164, 보류 5 |
| 활성 레시피 | 1,151건. 보류 자료는 원본·판본에 보존하고 활성 포인터를 null로 유지 |
| 조리 단계 / 재료 | 6,721개 / 12,993개 |
| 공식 확인 보완 | 6개 필드. ID 33·36은 각각 5단계 저장 |
| 식품영양 API 03 | `DB_CLASS_NM=품목대표` 전체 8,807건 / 판본 8,807건 |
| 식품 기준 단위 | g 5,489건, mL 3,317건, 미확정 1건. 미확정은 null 유지 |
| 재실행 | 같은 입력의 추가 레시피·식품·판본 모두 0건, import run 1개 유지 |
| 전수 대조 | 레시피 1,156건·식품 8,807건의 DB 원본·해시·원문 영양값·식품 단위 일치 |
| 스키마 | Alembic `20261105_01`, metadata 비교 시 추가 변경 없음 |

보류 원천 ID는 691, 692, 799, 831, 2980이다. 원천 수집·파싱 결과의 보류이며 임의 보충하지 않았다. 품질 판정은 현재 체크아웃의 파서 `public-data-v1` 기준이다.

이번 식품 범위는 기존 수집기 기본값인 **품목대표 전체**다. 상용제품 전체·건강기능식품 자료는 포함하지 않는다. 2026-11-09 레시피 목록·상세의 활성 판본 조회 API를 구현했다. 재료 매핑·계산 영양 요약·앱 API 연결은 후속 작업이다. 원문 영양값과 재료 계산값은 출처를 구분한다.

레시피·식품은 데이터셋별 성공 적재의 `meta.fetched_at`을 대조해 더 오래된 수집본의 활성화를 거부한다. 같은 수집 시각의 검증기·보완 목록 재처리는 허용한다. 수집 시각이 있는 이력 이후에는 시각이 없는 신규 입력도 거부한다. 시각 없는 과거 파일만 존재하는 환경에서는 기존 적재를 지원하며 파일 간 시간 순서를 추정하지 않는다. 완전히 같은 입력 지문의 재실행은 기존 멱등 처리로 종료한다. `--dataset all`도 어느 한 데이터셋이 오래됐으면 전체 트랜잭션을 반영하지 않는다.

## 재현 입력

- 레시피: `data/raw/recipes/cookrcp01_all.json` — 공식 COOKRCP01 전체 수집, `meta.complete=true`, 1,156건.
- 식품: `data/raw/nutrition/foodntr_v03_representative.json` — API 03, 품목대표 8,807건.
- 보완: `src/frontend/assets/data/recipe_corrections.json` — 원본은 변경하지 않고 적용본·감사 내역을 별도 저장.
- 완료 run: `595fda32-996c-43b3-aee1-c678dd7a6513`.
- 입력·보완·파서 지문: `3a6029602ac5fc4d71d798f5dd687e02d099491b643aa4cb6202448a0a036f26`.

원본 스냅샷과 `.env`는 Git에서 제외한다. 수집 시각이 달라진 새 파일은 별도 run이 될 수 있으나 원본·보완·파서가 동일한 각 자료의 판본은 재사용한다. 기업 서버에 동일 결과를 재현하려면 이 두 원본 파일과 보완 manifest를 안전하게 함께 전달해야 한다.

## 수집 및 적재 명령

저장소 루트에서 실행한다. Python 환경은 `src/backend/.venv` 또는 backend의 `uv sync --locked`로 준비한다. 두 API 키는 **루트 `.env`**, PostgreSQL 연결은 **`src/backend/.env`**에 설정한다. 인증키는 로그·커밋에 넣지 않는다.

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src/data'
src/backend/.venv/Scripts/python.exe -m agetech_data.recipes.client
src/backend/.venv/Scripts/python.exe -m agetech_data.nutrition.client

Set-Location src/backend
docker compose up -d --wait db
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m alembic check

# 기본값은 파일만 검사하는 dry run이다. DB에 연결하거나 쓰지 않는다.
.venv/Scripts/python.exe -m app.jobs.import_public_data --dataset all --dry-run
.venv/Scripts/python.exe -m app.jobs.import_public_data --dataset all --apply
.venv/Scripts/python.exe -m app.jobs.import_public_data --dataset all --verify
```

한 원천만 갱신할 때는 `--dataset recipes` 또는 `--dataset nutrition`을 사용한다. 경로는 `--recipes`, `--nutrition`, `--corrections`로 지정할 수 있다. `--verify`는 지정된 스냅샷 판본의 내용을 읽어 대조하며 활성 판본을 바꾸지 않는다. 과거 판본도 검증할 수 있다.

## 실패·중복·결측 처리

- 메타가 없는 50건 앱 자산, 부분 수집, 건수·해시 불일치, 중복/누락 원천 ID, 보완 원문 충돌은 적재 전에 중단한다.
- `--apply`는 PostgreSQL advisory transaction lock을 획득하고 전체 입력을 한 트랜잭션으로 처리한다. 실패하면 새 자료와 활성 포인터 변경을 모두 롤백한다. 오류 타입은 출력하되 DB URL·인증정보가 들어갈 수 있는 드라이버 메시지는 출력하지 않는다.
- 완료된 입력 지문은 다시 쓰지 않는다. 원천 ID는 provider와 함께 유일하며 변경된 원문은 새 판본으로 추가한다. 원천에서 사라진 행도 물리 삭제하지 않는다.
- 식품 판본과 입력 지문에는 정제 레코드도 포함한다. 원문이 같아도 검증된 보정 결과가 바뀌면 새 식품 판본을 만들고 기존 판본은 보존한다. `normalized`에는 원문 해시·내용 해시(`NUM` 제외)·보정 근거가 함께 저장된다.
- 레시피·식품 활성 판본은 복합 FK로 자신의 판본만 참조한다. 조리 번호·재료 순서도 판본 내 유일하다.
- 수치는 원문에서 `Decimal`로 읽고 PostgreSQL `NUMERIC`에 저장한다. 검증된 성분 보정은 해당 `to` 값만 반영하며, 나머지 성분의 원문 정밀도는 유지한다. 식품 전체 영양 필드도 정확한 십진 문자열 또는 null로 JSONB에 보존한다. 파서의 참고용 float는 원문과 함께 별도 JSON에 남는다.
- 레시피 영양 기준은 `per_serving_unverified`다. 중량·인분을 추정하거나 100g 기준으로 승격하지 않는다. 식품 g·mL는 서로 변환하지 않는다.
- 운영 복구 시 `downgrade`로 원천 이력을 삭제하지 않는다. 백업 및 이전 애플리케이션·활성 판본 복구 절차는 기업 서버 적용 전에 별도로 정한다.

## 검증

- backend: 기존 HTTP 검사와 파일 검증·격리 PostgreSQL 적재 테스트 24개 통과. 판본 추가·실패 롤백·다른 소유자 판본 FK 거절·null/0·소수 정밀도·g/mL 구분 포함.
- data: 113개 통과. 레시피 전체 페이지 수집·중복·건수 변경·네트워크 오류·기존 파일 보존과 영양 수집 전체 건수 변경·식품코드 누락 검증 포함.
- Ruff lint 및 backend 포맷 검사. 실제 전체 입력 dry-run → apply → 재실행 → verify, Alembic metadata 비교 완료.
- 기존 Starlette TestClient의 httpx 사용 중단 예정 경고 1건이 남아 있다.

Docker는 잔여 런타임 소켓 경로를 복구한 뒤 Engine 29.1.3 및 DB healthy 상태로 확인했다. 데이터 볼륨 초기화·DB 삭제·Docker 재설치는 수행하지 않았다.
