# 레시피·영양 데이터 DB 마이그레이션 계획

- 작성일: 2026-11-04
- 상태(2026-11-09 갱신): 원천·판본·인증·프로필 테이블, Alembic·적재 CLI와 레시피 목록·상세 API를 구현했다. 재료 매핑·계산 결과와 앱 연결은 후속 범위다.
- 대상: PostgreSQL 16 + pgvector, Python 3.12 공통 FastAPI, 병합된 `agetech_data` 데이터 모듈
- 근거: [구현계획서](./구현계획서.md), [영양 데이터 인계 규격](../data/food_nutrition_contract.md), [레시피 보완 결과](../data/recipe_correction_report.md)

## 1. 저장 방향

레시피와 식품 영양 원천을 분리하고, 재료별 매핑으로 연결한다. 레시피별 계산 합계는 재생성 가능한 별도 결과로 저장한다. API는 이를 한 응답으로 조합한다.

이름으로 식품을 직접 연결하지 않는다. 내부 식별자는 UUID, 원천 식별자는 `provider + source_id`를 사용한다. 식품 원천 ID는 `food_code`이며 레시피 원천 ID는 `RCP_SEQ`다. 변경된 자료는 새 판본으로 추가하고 이전 판본을 덮어쓰지 않는다.

## 2. 최초 계획 시점의 입력과 품질 기준 (2026-11-04)

사용자 요청에 따라 50건만 이관하는 초기 순서를 변경했다. 2026-11-05 공식 API 전체 레시피 1,156건과 식품 품목대표 8,807건을 수집·적재했다. 현재 입력 위치·해시·검증 결과는 [전체 적재 기록](../data/public_db_import.md)을 따른다. 아래 표는 최초 설계 당시의 입력 이력이다.

| 입력 | 상태·용도 |
| --- | --- |
| `src/frontend/assets/data/recipes.json` | 레시피 수집 원본 50건. 변경 없이 보존 |
| `src/frontend/assets/data/recipe_source.json` | 원래 API 제공처·수집일·건수 |
| `src/frontend/assets/data/recipe_corrections.json` | 외부 공식 원문 확인 후 보완한 필드·수정 전후 값·출처·확인자·확인일 |
| `data/processed/recipes_corrected.json` | 보완 CLI가 생성하는 적용본. 원본과 같은 행 목록 형식 |
| `data/processed/recipe_correction_audit.json` | 원본·보완 목록·적용본 해시, 적용 내역, 적용 전후 품질 |
| `data/raw/nutrition/foodntr_v03_representative.json` | 식품 영양 API 03 원본. Git 제외이며 현재 체크아웃에는 없음 |
| `data/processed/foods_v03.json` | 식품 원본으로 다시 생성할 정제 식품 |
| `data/processed/recipe_ingredient_nutrition.json` | 원천과 보완 목록을 함께 적용해 생성할 재료 매핑·기여량 |
| `src/data/agetech_data/resources/ingredient_food_map.json` | 식품 수동 매핑표와 근거·사람 검토 여부 |

기존 영양 보고서의 8,807건은 다른 수집 시점의 기록이다. 실제 이관 전에 파일·건수·SHA-256·수집 메타를 확보하고 전체 매핑을 다시 검증한다. 표본 fixture를 전체 원본으로 대체하지 않는다.

기존 원본의 조리 단계 누락은 2건·4단계, 재료 괄호 이상은 2건이다. 같은 보완 목록을 백엔드 적재와 데이터 처리에 적용하며 Flutter 연결은 후속 작업이다. ID 38의 표고버섯 기둥 분량과 `INFO_WGT` 47건은 확인 가능한 중량이 없어 미확정 값으로 유지한다.

## 3. 1차 스키마

아래는 전체 목표 테이블과 책임이다. 원천·판본·단계·재료·import run 7개 테이블의 DDL은 Alembic `20261105_01`에 구현했다. 매핑·계산 결과 테이블은 후속 리비전 범위다.

| 테이블 | 핵심 필드·역할 |
| --- | --- |
| `data_import_runs` | 입력 파일 해시·원천 메타·보완 목록/매핑표/정규화 코드 버전·상태·검증 건수. 매핑 결과 집합의 판본도 식별 |
| `recipes` | UUID, provider, source_id, active_revision_id. `UNIQUE(provider, source_id)` |
| `recipe_revisions` | recipe_id, raw JSONB, raw_sha256, effective_sha256, 보완 목록 해시, 정규화 버전, 이름·방법·품질 상태·원문 영양값·원문 기준량·확인 시각 |
| `recipe_steps` | recipe_revision_id, source_no, stated_no, source_field, text_raw, text_clean, 이미지 주소, 보완 출처. 원래 단계 번호 유지 |
| `recipe_ingredients` | recipe_revision_id, order_no, line_no, section, raw_item, name_raw, 정제 이름, amount_text. 확정되지 않은 분량은 null |
| `foods` | UUID, provider, food_code, active_revision_id. `UNIQUE(provider, food_code)` |
| `food_revisions` | food_id, raw JSONB·해시·정규화 버전, 이름, basis_amount, basis_unit, 출처, 날짜, quality_flags, 영양성분 컬럼 |
| `recipe_ingredient_mappings` | import_run_id, recipe_ingredient_id, food_revision_id(nullable), match_status, rule, rationale, 후보 목록, 환산량·단위·환산 근거·근사 여부 |
| `recipe_nutrition_summaries` | recipe_revision_id, mapping_run_id(`data_import_runs` 참조), calculation_version, 성분별 합계·결측 수, coverage, 계산 상태, 기준량 종류 |

매핑은 `(import_run_id, recipe_ingredient_id)`로 유일하게 유지한다. 요약의 `(recipe_revision_id, mapping_run_id, calculation_version)`도 유일하게 유지한다. 따라서 계산 당시 사용한 재료 매핑 집합과 식품 판본을 다시 찾을 수 있다. 데이터 적재 완료 run의 매핑·합계는 불변으로 보관한다.

레시피 판본 중복 방지 키에는 레시피 ID, 원본/적용본 해시, 정규화 버전, 보완 목록 해시를 포함한다. 식품 판본도 식품 ID, 원문 해시, 정규화 버전으로 구분한다. 원문이 같아도 파서·단위 해석이 바뀌면 새 가공 판본을 만들 수 있어야 한다.

### 3.1 컬럼·제약

- 영양 성분·분량은 `NUMERIC`과 Python `Decimal`을 사용한다. 정밀도·소수점 범위는 실제 원본 최댓값과 계산 오차 시험 후 DDL에 고정한다. 현 가공 코드의 float 결과를 이관한다고 원래 정밀도가 복원되는 것은 아니므로 원문 숫자·JSON도 보존한다.
- 영양 성분이 없으면 `NULL`이다. 실제 0과 결측을 구분한다.
- `basis_unit`은 확인된 `g` 또는 `mL`, 미확정이면 null이다. 기준량이 있으면 양수여야 한다.
- 단계와 재료는 각각 `(recipe_revision_id, source_no)`, `(recipe_revision_id, order_no)`로 유일해야 한다.
- FK와 함께 `recipes(provider, source_id)`, `foods(provider, food_code)`, `recipe_ingredients(recipe_revision_id)`, `recipe_ingredient_mappings(recipe_ingredient_id, import_run_id)`에 필요한 인덱스를 둔다.
- 활성 판본이 다른 레시피·식품 소유의 판본을 가리킬 수 없도록 소유 ID를 포함한 복합 FK로 검사한다. 초기 적재는 활성 포인터를 null로 생성한 뒤 같은 트랜잭션에서 연결한다.
- 미매핑 재료도 저장한다. 식품 판본 FK를 null로 두고 `candidate`·`unmapped` 상태를 유지한다.
- 삭제 정책은 원천·이력 보존을 우선한다. 확정 섭취가 참조하는 식품·레시피 판본에 cascade 삭제를 적용하지 않는다.

영양소를 행마다 무제한 추가하는 EAV 구조는 1차 범위에 넣지 않는다. 자주 조회하는 고정 성분은 nullable 컬럼으로 두고 원문·품질·출처 같은 부가 자료는 JSONB로 보존한다.

## 4. 계산·보완 규칙

1. 원본 → 확인된 보완 적용 → 레시피 파싱 → 품질 검증 → 재료 매핑 → 계산 순서로 처리한다. 원본과 적용본 해시를 모두 기록한다.
2. 보완 대상의 현재 값이 예상 원문이나 이미 보완된 값과 다르면 중단하고 재검증한다. API 갱신 내용을 묵시적으로 덮어쓰지 않는다.
3. 레시피 `INFO_*`와 재료 계산 합계를 별도 필드·출처로 보존한다. 원문 영양값을 계산값으로 치환하지 않는다.
4. 계산 합계의 기준은 우선 `recipe_ingredients_total`이다. 인분·조리 후 중량 근거가 없으면 1인분·100g으로 변환하지 않는다.
5. 기존 `approx_ml` 및 `basis_ml_approx`는 밀도 미확인 근사로 보존한다. 단순 g↔mL 치환을 정확한 환산으로 승격하지 않는다.
6. 개수 단위·적당량·분량 없음은 확인된 중량 근거가 생기기 전까지 미계산으로 남긴다.
7. `curated`는 사람 검토 전 상태이며 `reviewed`로 자동 승격하지 않는다. 사람이 확인한 경우 수행자·시각을 남긴 새 매핑 run을 만든다.
8. 성분별 기여량이 하나도 없으면 요약을 0으로 저장하지 않는다. 기존 build의 초기 합계 0과 `items_used=0`을 함께 해석해 DB의 해당 합계는 null로 구분한다.
9. `coverage.complete`와 성분별 결측은 별개다. 일부 성분이 없는 재료가 포함되거나 미매핑 재료가 있으면 해당 성분의 부분 계산 여부·제외 재료 수를 함께 표시한다.
10. 과거 확정 섭취는 당시 판본·분량·계산 버전을 참조한다. 신규 데이터 재계산이 과거 기록을 바꾸지 않게 한다.

## 5. 구현·실행 순서와 완료 기준

| 순서 | 구현할 작업 | 완료 기준 |
| --- | --- | --- |
| 1 | 입력 사전 점검 | 레시피 50건·원본/보완 해시·식품 원본 파일·수집 메타 확보, 중복 코드·기준량·결측 집계 |
| 2 | Alembic 초기 구성 | 공통 `Base.metadata`, 서버 환경설정에서 DB 연결, 새 시험 DB에서 upgrade 확인. 설정·로그에 비밀번호 없음 |
| 3 | 원천·판본 테이블 | import_runs·recipes·foods·revisions·steps·ingredients와 제약 생성. 마이그레이션에 실제 데이터 삽입을 섞지 않음 |
| 4 | 별도 적재 CLI | `--dry-run`에서 DB 쓰기 없이 오류·신규/기존/변경 건수 출력, `--apply`에서 트랜잭션 적재 |
| 5 | 재료 매핑·계산 테이블 | 원천 식품 판본과 매핑 run 고정, 계산 값·누락·근사·출처 검증 |
| 6 | 활성 판본 전환 | 검증 완료된 판본만 기존 활성 포인터와 함께 원자적으로 전환, 실패 시 기존 활성 자료 유지 |
| 7 | 조회 API·앱 연결 | 레시피 목록·상세 API에서 공통 data/meta, 원천/계산 구분·품질·단위·출처·판본 반환 |
| 8 | 서버 이관·복구 연습 | 기업 서버에 같은 마이그레이션·입력 스냅샷 적용, 비교 검증 및 이전 활성 판본 복구 확인 |

위 순서는 최초 계획이다. 현재 원천 테이블 DDL·적재 CLI와 활성 레시피 목록·상세 API를 구현·검증했다. 재료 매핑·계산 테이블·앱 연결·기업 서버 배포는 후속 작업이다. 스키마 변경은 Alembic으로, 실제 데이터는 별도 CLI로 처리한다.

### 5.1 적재의 재실행·실패 처리

- 입력·보완 목록·파서·매핑표·계산 버전이 모두 같으면 기존 결과를 재사용한다. 같은 파일 재실행으로 레시피·식품·판본·합계가 늘어나지 않아야 한다.
- 식품 원천만 바뀌면 새 식품 판본을 만들고 영향받은 매핑·합계를 새 run으로 계산한다. 레시피 원문 판본을 불필요하게 새로 만들지 않는다.
- 식품 누락·참조 불일치·보완 충돌·필수 필드 오류는 실패 run으로 기록하고 활성화하지 않는다. 이미 실행된 실패 작업의 오류 내역은 트랜잭션 롤백 후 별도로 기록한다.
- 부분 수집·실패 파일을 정상 전체 자료로 교체하지 않는다. 원본 수집기의 완결성 확인을 통과한 파일만 입력한다.
- 새 자료가 원천에서 사라져도 이관 중 즉시 물리 삭제하지 않는다. 검토 후 비활성화하고 참조 이력을 유지한다.

## 6. 검증 시나리오

- 빈 시험 DB에 upgrade → fixture 적재 → 목록·상세 조회가 가능하다.
- 같은 스냅샷 2회 적재 시 건수·판본·합계가 동일하다.
- 레시피 하나·식품 하나를 각각 변경하면 필요한 판본과 계산만 추가된다.
- 이름이 같은 다른 식품 코드·100g/100mL 자료가 잘못 합쳐지지 않는다.
- 미매핑·결측·0·근사 환산·부분 계산이 API에서도 구분된다.
- 단계 보완 전후 원본 해시는 보존되고 적용본에는 ID 33·36의 1~5단계가 모두 존재한다.
- 매핑을 바꿔도 과거 run·확정 섭취의 재현 결과는 동일하다.
- 중간 예외·보완 충돌 시 새 자료가 부분 게시되지 않는다.
- 운영 DB를 삭제하는 downgrade로 복구하지 않고 이전 활성 판본·애플리케이션으로 되돌리는 절차를 확인한다. 스키마 downgrade는 폐기 가능한 시험 DB에서만 검증한다.

## 7. 우선 작업 단위

Alembic, 원천·판본 적재와 레시피 목록·상세 API를 구현했다. 다음 작업은 매핑 run·영양 요약·복지 조회와 앱 연결이다. 데이터 담당과 식품 코드·단위·매핑 상태를, 앱 담당과 DTO를 확인한다. 현재 경로와 동의 프로필은 [API 명세서](API_명세서.md)를 따른다.

현재 레시피 보완본은 다음 명령으로 검증·생성한다. 저장소 루트에서 데이터 모듈이 설치되었거나 `PYTHONPATH=src/data`가 설정된 Python 3.12 환경을 사용한다.

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src/data'
src/backend/.venv/Scripts/python.exe -m agetech_data.recipes.correct
```

영양 원본을 확보한 다음 기존 `agetech_data.nutrition.build`를 실행한다. 이 경로도 동일한 보완 목록을 적용하고 입력 해시에 보완 목록 판본을 기록한다.

## 8. 기술 근거

- [PostgreSQL 16 Numeric Types](https://www.postgresql.org/docs/16/datatype-numeric.html): exact numeric 저장과 소수 자릿수 설정.
- [Alembic Tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html): 리비전·upgrade/downgrade와 마이그레이션 환경 구성.
