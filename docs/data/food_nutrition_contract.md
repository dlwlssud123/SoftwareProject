# 식품 영양 데이터 필드 정의서 (데이터 → 서버·앱 인계)

| 항목 | 내용 |
|---|---|
| 작성 | 최재영 (데이터) |
| 대상 | 저장 구조·사진 분석·영양 계산 API(이진녕), 영양 표시 화면(김찬형), 품질 평가(김민찬) |
| 원천 | 식품의약품안전처_식품영양성분DB정보 Open API **03 판본** (`FoodNtrCpntDbInfo03`), `DB_CLASS_NM=품목대표` |
| 생성 명령 | `uv run python -m agetech_data.nutrition.client` → `uv run python -m agetech_data.nutrition.build` |
| 상태 | 초안. DB 스키마는 저장 구조 작업에서 확정하며, 이 문서는 필드 의미·단위·결측 규칙을 정한다 |

## 1. 꼭 지킬 규칙

1. **식별자는 `food_code`(원본 `FOOD_CD`)다.** 식품명은 중복된다. 같은 음식명이 식품코드 계열별로 여러 행 있고, 100g 기준 행과 100mL 기준 행이 섞여 있다(예: `기장밥` 5행).
2. **함량은 기준량(`basis_amount` `basis_unit`)당 값이다.** 기준량은 `100g` 또는 `100mL`다. 품목대표 8,807건 중 음식 3,142건이 100mL 기준이다. g 분량으로 계산하려면 단위를 반드시 확인한다.
3. **결측은 `null`이고 0이 아니다.** 합계를 낼 때 결측 성분은 "자료 없음"으로 표시하고 0으로 채우지 않는다.
4. **g ↔ mL는 데이터에서 환산하지 않는다.** 밀도 근거가 없다. 레시피 계산에서 mL 기준 식품에 g 분량을 쓴 경우는 `basis_ml_approx=true`로 표시하고 1mL≈1g으로 근사했다.
5. **원문은 보존하고, 근거가 있는 원천 오류만 보정표로 고친다.** 수집 원본 파일은 바꾸지 않는다. 정제 단계에서 `src/data/agetech_data/resources/food_corrections.json`을 적용하고, 고친 레코드에는 원래 값(`corrections`)과 `corrected` 표시를 남긴다(2.1절). 근거가 없는 의심값은 고치지 않고 `quality_flags`로만 표시한다.
6. **AMT_NUM 번호는 판본마다 바뀐다.** 03 판본 기준은 `src/data/agetech_data/resources/foodntr_v03_fields.json`(공식 명세 추출본)이다. 예: 23=콜레스테롤, 24=포화지방산.

## 2. 정제 식품 — `data/processed/foods_v03.json`

최상위: `schema_version`, `input`(원본 경로·sha256·수집 메타), `nutrients`(성분 키 → 원본 필드·공식 항목명), `foods[]`

| 필드 | 형식 | 원본 | 설명 |
|---|---|---|---|
| `food_code` | 문자열 | `FOOD_CD` | 식별자 (예: `R106-191040001-0000`) |
| `name` | 문자열 | `FOOD_NM_KR` | 식품명. 원재료성은 `상위, 세부, 상태` 계층 (예: `파, 대파, 생것`), 음식은 `대표_세부` (예: `국밥_돼지머리`) |
| `db_group` | 문자열 | `DB_GRP_NM` | `음식` / `원재료성` / `가공식품` |
| `db_class` | 문자열 | `DB_CLASS_NM` | `품목대표` (현재 수집 범위) |
| `category1` | 문자열·null | `FOOD_CAT1_NM` | 식품대분류명 |
| `ref_name` | 문자열·null | `FOOD_REF_NM` | 대표식품명 |
| `basis_text` | 문자열·null | `SERVING_SIZE` | 영양성분함량기준량 원문 |
| `basis_amount`, `basis_unit` | 수·null, `g`/`mL`/null | 〃 | 파싱 결과. 형식이 다르면 null + `invalid_basis` |
| `food_weight_text` / `_amount` / `_unit` | | `Z10500` | 식품중량 원문·파싱 (예: `900.000g`). 의미는 명세의 "식품중량" 그대로이며 1회 섭취량으로 단정하지 않는다 |
| `serving_ref_text` | 문자열·null | `NUTRI_AMOUNT_SERVING` | 1회 섭취참고량 원문 (대부분 비어 있음) |
| `source_name`, `create_method` | 문자열·null | `SUB_REF_NAME`, `CRT_MTH_NM` | 출처명, 데이터생성방법(분석/산출/수집) |
| `research_date`, `update_date` | 문자열·null | `RESEARCH_YMD`, `UPDATE_DATE` | 데이터생성일자, 수정일자 (갱신 감지에 사용) |
| `nutrients` | 객체 | `AMT_NUM*` | 아래 성분 키 → 기준량당 값 또는 null |
| `raw_sha256` | 문자열 | 원본 행 | 원본 행 해시 (변경 감지·추적) |
| `corrections` | 객체 배열 | | 보정 기록 `{field, from, to, reason, evidence, by, at}`. 보정이 없으면 `[]`. `from`이 원래(원천) 값이다 (2.1절) |
| `quality_flags` | 문자열 배열 | | 아래 품질 표시 |

**성분 키** (단위는 키 이름 끝): `energy_kcal`, `water_g`, `protein_g`, `fat_g`, `ash_g`, `carbohydrate_g`, `sugars_g`, `fiber_g`, `calcium_mg`, `iron_mg`, `phosphorus_mg`, `potassium_mg`, `sodium_mg`, `vitamin_a_ug_rae`, `vitamin_b1_mg`, `vitamin_b2_mg`, `niacin_mg`, `vitamin_c_mg`, `vitamin_d_ug`, `cholesterol_mg`, `sat_fat_g`, `trans_fat_g`, `salt_equiv_g`, `refuse_pct`

**품질 표시** (`quality_flags`): `invalid_basis`, `suspicious_name`(예: `test` 행), `unparsed_value`, `missing_energy`, `missing_sodium`, `proximate_exceeds_basis`, `sat_fat_exceeds_fat`, `sugars_exceeds_carbohydrate`, `energy_macro_mismatch`(참고), `same_name_multiple_rows`, `corrected`(보정표로 고침), `correction_stale`(보정표 항목이 지금 원천과 맞지 않아 적용 안 함 — 다시 확인). 앱 노출에서 `invalid_basis`·`suspicious_name` 행은 제외를 권장한다.

### 2.1 원천 오류 보정 — `src/data/agetech_data/resources/food_corrections.json`

| 항목 | 내용 |
|---|---|
| 형식 | `corrections[]` = `{food_code, food_name, field, from, to, reason, evidence, raw_sha256, by, at}`. `field`는 `basis_text`(기준량 — `basis_amount`·`basis_unit`도 다시 읽음) 또는 `nutrients.<성분 키>` |
| 적용 조건 | 원본 행 해시(`raw_sha256`)와 원래 값(`from`)이 **둘 다** 지금 수집본과 같을 때만 적용한다 |
| 원천이 바뀌면 | 식약처가 행을 고치거나 다시 수집해 해시·값이 달라지면 적용하지 않고 `correction_stale`을 붙인다. 보고서 6절에 "다시 확인 필요"로 나온다 |
| 품질 표시 | 보정한 값으로 다시 계산한다(예: 기준량을 고치면 `invalid_basis`·`proximate_exceeds_basis` 다시 판정) |
| 넣는 기준 | 데이터 자체로 오류가 확실하거나(물리적으로 불가능한 값, 같은 값의 다른 공식 행) 외부 공식 근거가 있을 때만 넣는다. `evidence`에 근거를 적는다 |

**현재 보정 (10/31 수집본)**: 분말 9건(커피믹스·커피가루 2종·디카페인커피·녹차라떼·쌍화차·율무차·인삼차·홍차복숭아분말)의 기준량 `100mL` → `100g`. 기준량이 100mL인데 수분 1~4g·열량 350~470kcal로 액체에서는 나올 수 없는 값이고, 고친 뒤 수분·단백질·지방·회분·탄수화물의 합이 9건 모두 100.0g으로 맞는다. 커피믹스는 같은 값의 원재료성 행(100g 기준)도 있다.

**고치지 않고 표시만 하는 것** (원인을 확인했지만 일괄 보정 근거가 없음):
- `sat_fat_exceeds_fat` 144건: 142건이 제품 표시에서 옮긴 수집값(대부분 빵·과자)이고 포화지방/지방 배율이 제각각(1.2배 이하 9건, 1.2~10배 111건, 10배 초과 20건, 지방 0 4건)이라 단위 실수 하나로 설명되지 않는다. 화면에서 이 행의 포화지방은 "자료 확인 필요"로 보여 주기를 권장한다.
- `sugars_exceeds_carbohydrate` 22건: 대부분 측정 오차 수준(예: 탄수화물 3.37g, 당류 3.42g)이다.
- `proximate_exceeds_basis` 42건: 수집 빵류가 대부분이며 108~154%로 제각각이다.
- 레시피 계산에 쓰는 식품 중 위에 걸리는 것은 가공식품 `통조림햄` 1건이었고, 매핑을 원재료성 분석 행으로 바꿨다(PR #16).
- 값 자체가 의심되는 것(예: 가공식품 `간장/저염`의 나트륨이 일반 양조간장보다 5%만 낮음)은 외부 공식 근거(제품 영양표시, 같은 DB의 상용제품 값 등)를 찾으면 보정한다.

## 3. 레시피 재료 영양 — `data/processed/recipe_ingredient_nutrition.json`

최상위: `schema_version`, `input`(영양 원본·레시피 원본 경로와 sha256), `summary`, `recipes[]`

`recipes[]`: `source_id`(RCP_SEQ), `name`, `quality_status`(레시피 품질 검증의 ok/flagged/hold), `raw_sha256`, `ingredients[]`, `computed`(계산 합계), `computed_missing`(성분별 결측 재료 수), `coverage`, `source_values`(원문 `INFO_*` 문자열 그대로)

`ingredients[]`:

| 필드 | 설명 |
|---|---|
| `order_no`, `line_no`, `section`, `raw_item`, `name`, `amount_text` | 레시피 원문 보존 필드 (레시피 품질 검증과 같은 값) |
| `grams.grams` | g 환산값 또는 null |
| `grams.status` | `direct`(원문 g) / `direct_paren`(원문 괄호 g) / `approx_ml`(mL→1mL≈1g) / `count_unit` / `qualitative` / `missing` / `unparsed` |
| `grams.basis` | 환산 근거 문장 |
| `match.status` | `reviewed` / `curated` / `exact` / `water` / `candidate` / `unmapped` |
| `match.food_code`, `match.food_name` | 매핑된 식품 (`candidate`·`unmapped`이면 null) |
| `match.rule`, `match.rationale` | 매핑 규칙(`raw`, `variety`, `manual` 등)과 근거 |
| `match.candidates[]` | `candidate`일 때 상위 후보 `{food_code, name, db_group, score}` |
| `contribution` | 성분별 기여량 = g ÷ 기준량 × 기준량당 함량. 매핑 상태가 `reviewed`/`curated`/`exact`이고 g 환산된 경우만 값, 아니면 null |
| `basis_ml_approx` | mL 기준 식품을 g 분량으로 계산했으면 true |

`coverage`: `items`, `items_used`, `grams_converted`(물 제외), `grams_used`, `grams_used_pct`, `complete`(물을 뺀 모든 재료가 계산에 들어갔는지)

**화면 표시 권장**: `complete=false`인 레시피의 `computed`는 "일부 재료 기준"이라고 표시한다. 레시피 원문 `INFO_*`와 섞어 쓰지 않는다.

## 4. 코드에서 쓰는 함수 (서버 연동용)

```python
from agetech_data.nutrition.foods import clean_foods
from agetech_data.nutrition.match import FoodIndex, match_ingredient, search_dishes

foods = clean_foods(raw["items"])                    # 원본 행 → 정제 레코드
dish_index = FoodIndex(foods, ("음식",))              # 사진 분석 음식명 검색용
search_dishes("계란말이", dish_index, limit=5)        # → [{food_code, name, basis_unit, score}, …] 사용자 확인용 후보
ingredient_index = FoodIndex(foods)                  # 원재료성·가공식품
match_ingredient("다진 마늘", ingredient_index)       # → MatchResult(status, food_code, food_name, rule, rationale, candidates)
```

- `search_dishes`는 **후보 목록**이다. 최종 음식·분량은 사용자 확인 후 확정한다(기획서 CORE-04). 점수가 같으면 100g 기준 행이 앞에 온다.
- 영양 계산은 서버에서 확정한 `food_code`와 분량(g)으로 한다. 외부 AI가 말한 영양값은 쓰지 않는다.

## 5. 수집·갱신과 오류 동작

| 상황 | 동작 |
|---|---|
| 키 없음 | `client` 종료 코드 1, 기존 원본 유지. 키 이름은 `.env.example` 참고 (`DATA_GO_KR_SERVICE_KEY`) |
| API 간헐 오류(HTTP 500 등) | 페이지마다 최대 5회 재시도(대기 2·4·6·8초) |
| 키 미등록·기한 만료(결과코드 30 등) | 재시도하지 않고 실패, 기존 원본 유지 |
| 건수가 totalCount와 다름 / 식품코드 중복 | 실패, 기존 원본 유지 |
| 성공 | 원본을 통째로 교체(임시 파일 → 이름 바꾸기). 이후 `build`로 정제·매핑 재생성 |

출력·로그·파일에 키와 키가 들어간 URL을 남기지 않는다. 자동 갱신 일정·실패 시 캐시 유지 정책은 "공공데이터 자동 갱신" 작업에서 정한다.

## 6. DB 적재 시 제안 (저장 구조 작업에서 확정)

- 식품: `food_code` 기본키, `basis_amount`·`basis_unit`·성분 컬럼(null 허용), `raw_sha256`·`update_date`로 변경 감지, `quality_flags` 배열.
- 레시피 재료 매핑: (레시피 ID, `order_no`) 단위로 `match.status`·`food_code`·`grams`·`grams.status` 저장. `curated`→`reviewed` 전환 이력(확인자·일시)을 남길 수 있게 한다.
- 수동 매핑표 원본은 `src/data/agetech_data/resources/ingredient_food_map.json`(커밋 대상)이며, 관리자 화면에서 검수하게 되면 이 파일 형식을 기준으로 옮긴다.

## 7. 알려진 제한

- 개수 단위(개·장·알·뿌리 등)는 출처 있는 개당 중량표가 없어 g으로 환산하지 않는다.
- `curated` 매핑은 사람 확인 전이다. 보고서(`docs/data/nutrition_mapping_report.md`) 3절에서 검토한다.
- 부위가 적히지 않은 고기(돼지고기·소고기)와 종이 적히지 않은 새우·조개는 `candidate`로 남아 계산에서 빠진다.
- 가공식품 상용제품(약 33만 건)은 수집하지 않았다. 필요하면 `--db-class 상용제품`으로 별도 수집한다.
