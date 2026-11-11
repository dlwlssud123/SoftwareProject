# 식품 영양 데이터 필드 정의서 (데이터 → 서버·앱 인계)

| 항목 | 내용 |
|---|---|
| 작성 | 최재영 (데이터) |
| 대상 | 저장 구조·사진 분석·영양 계산 API(이진녕), 영양 표시 화면(김찬형), 품질 평가(김민찬) |
| 원천 | 식품의약품안전처_식품영양성분DB정보 Open API **03 판본** (`FoodNtrCpntDbInfo03`), `DB_CLASS_NM=품목대표` |
| 생성 명령 | `uv run python -m agetech_data.nutrition.client` → `uv run python -m agetech_data.nutrition.build` → `uv run python -m agetech_data.nutrition.sample`(사진·영양 API 표본, 7절) |
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
| `serving_ref_text` | 문자열·null | `NUTRI_AMOUNT_SERVING` | 1회 섭취참고량 원문 (가공식품 950건에만 있음, 음식은 모두 비어 있음) |
| `dish_serving_text` | 문자열·null | `DISH_ONE_SERVING` | 1회분량 참고량 원문 (10/31 수집본은 모두 비어 있음). 인분 환산 근거로 쓴다(7절) |
| `source_name`, `create_method` | 문자열·null | `SUB_REF_NAME`, `CRT_MTH_NM` | 출처명, 데이터생성방법(분석/산출/수집) |
| `research_date`, `update_date` | 문자열·null | `RESEARCH_YMD`, `UPDATE_DATE` | 데이터생성일자, 수정일자 (갱신 감지에 사용) |
| `nutrients` | 객체 | `AMT_NUM*` | 아래 성분 키 → 기준량당 값 또는 null |
| `raw_sha256` | 문자열 | 원본 행 | `NUM`까지 포함한 전체 원본 행 해시 (원문 추적) |
| `source_sha256` | 문자열 | 원본 행 | 응답 번호 `NUM`만 제외한 내용 해시. 나머지 모든 필드는 포함 (보정 검증용) |
| `corrections` | 객체 배열 | | 보정 기록 `{field, from, to, reason, evidence, by, at, source_sha256?}`. 보정이 없으면 `[]`. `from`이 원래(원천) 값이다 (2.1절) |
| `quality_flags` | 문자열 배열 | | 아래 품질 표시 |

**성분 키** (단위는 키 이름 끝): `energy_kcal`, `water_g`, `protein_g`, `fat_g`, `ash_g`, `carbohydrate_g`, `sugars_g`, `fiber_g`, `calcium_mg`, `iron_mg`, `phosphorus_mg`, `potassium_mg`, `sodium_mg`, `vitamin_a_ug_rae`, `vitamin_b1_mg`, `vitamin_b2_mg`, `niacin_mg`, `vitamin_c_mg`, `vitamin_d_ug`, `cholesterol_mg`, `sat_fat_g`, `trans_fat_g`, `salt_equiv_g`, `refuse_pct`

**품질 표시** (`quality_flags`): `invalid_basis`, `suspicious_name`(예: `test` 행), `unparsed_value`, `missing_energy`, `missing_sodium`, `proximate_exceeds_basis`, `sat_fat_exceeds_fat`, `sugars_exceeds_carbohydrate`, `energy_macro_mismatch`(참고), `same_name_multiple_rows`, `corrected`(보정표로 고침), `correction_stale`(보정표 항목이 지금 원천과 맞지 않아 적용 안 함 — 다시 확인). 앱 노출에서 `invalid_basis`·`suspicious_name` 행은 제외를 권장한다.

### 2.1 원천 오류 보정 — `src/data/agetech_data/resources/food_corrections.json`

| 항목 | 내용 |
|---|---|
| 형식 | `corrections[]` = `{food_code, food_name, field, from, to, reason, evidence, raw_sha256, by, at, source_sha256?}`. `field`는 `basis_text`(기준량 — `basis_amount`·`basis_unit`도 다시 읽음) 또는 `nutrients.<성분 키>` |
| 적용 조건 | `source_sha256`가 있으면 내용 해시와 원래 값(`from`)이 **둘 다** 일치해야 한다. 구형 항목은 기존 `raw_sha256`와 `from`으로 검증한다. 원본 해시는 계속 보존한다 |
| 원천이 바뀌면 | 응답 번호 `NUM`만 달라진 경우는 같은 내용으로 본다. 영양값·식품명·기준량 등 다른 필드나 응답 스키마가 달라지면 적용하지 않고 `correction_stale`을 붙인다. 보고서 6절에 "다시 확인 필요"로 나온다 |
| 품질 표시 | 보정한 값으로 다시 계산한다(예: 기준량을 고치면 `invalid_basis`·`proximate_exceeds_basis` 다시 판정) |
| 넣는 기준 | 데이터 자체로 오류가 확실하거나(물리적으로 불가능한 값, 같은 값의 다른 공식 행) 외부 공식 근거가 있을 때만 넣는다. `evidence`에 근거를 적는다 |

**현재 보정 (10/31 수집본)**: 분말 9건(커피믹스·커피가루 2종·디카페인커피·녹차라떼·쌍화차·율무차·인삼차·홍차복숭아분말)의 기준량 `100mL` → `100g`. 기준량이 100mL인데 수분 1~4g·열량 350~470kcal로 액체에서는 나올 수 없는 값이고, 고친 뒤 수분·단백질·지방·회분·탄수화물의 합이 9건 모두 100.0g으로 맞는다. 커피믹스는 같은 값의 원재료성 행(100g 기준)도 있다.

**11/09 해시 재검증**: 로컬 11/05 수집본에서 9건 모두 `NUM`만 기존 보정 원본보다 1 작았다. `NUM`만 +1한 행의 전체 해시가 기존 `raw_sha256`와 모두 정확히 일치하여 다른 필드가 그대로임을 확인했다. 기존 원본 해시는 유지하고 `NUM`만 제외한 `source_sha256`를 추가했다. 재검증 기준·시각은 보정표의 `hash_validation`에 기록했다.

DB 적재는 정제 레코드까지 판본 지문에 포함한다. 원본이 같고 보정표만 바뀌어도 새 식품 판본이 생성되며, 원본·보정 내역을 함께 보관한다. 보정하지 않은 성분은 원본의 소수 정밀도를 유지하고, 보정한 성분만 해당 `to` 값을 저장한다. 이 변경은 스키마 마이그레이션이 필요 없으며 기존 DB 갱신은 명시적인 적재 명령으로 실행한다.

**고치지 않고 표시만 하는 것** (원인을 확인했지만 일괄 보정 근거가 없음):
- `sat_fat_exceeds_fat` 144건: 142건이 제품 표시에서 옮긴 수집값(대부분 빵·과자)이고 포화지방/지방 배율이 제각각(1.2배 이하 9건, 1.2~10배 111건, 10배 초과 20건, 지방 0 4건)이라 단위 실수 하나로 설명되지 않는다. 화면에서 이 행의 포화지방은 "자료 확인 필요"로 보여 주기를 권장한다.
- `sugars_exceeds_carbohydrate` 22건: 대부분 측정 오차 수준(예: 탄수화물 3.37g, 당류 3.42g)이다.
- `proximate_exceeds_basis` 42건: 수집 빵류가 대부분이며 108~154%로 제각각이다.
- 레시피 계산에 쓰는 식품 중 위에 걸리는 것은 가공식품 `통조림햄` 1건이었고, 매핑을 원재료성 분석 행으로 바꿨다(PR #16).
- 값 자체가 의심되는 것은 외부 공식 근거(제품 영양표시, 같은 DB의 상용제품 값 등)와 맞춰 보고, 근거가 있을 때만 보정한다.
  - **확인했지만 정상인 것 — 가공식품 `간장/저염`**(P112-005000400-F002-001, 나트륨 4,530mg/100mL): 같은 DB 상용제품을 식품명으로 조회(2026-11-09)한 결과 저염간장 5개 중앙값 4,520mg/100mL, 일반 진간장·양조간장 221개 중앙값 6,000mg/100mL로, 저염 제품과 같고 일반 간장보다 약 25% 낮다. 처음에 의심한 이유(일반 간장보다 5%만 낮아 보임)는 100g 기준(원재료성 `간장, 개량, 양조` 4,783mg/100g)과 100mL 기준을 단위를 맞추지 않고 비교한 착오였다. **비교할 때는 기준량 단위를 먼저 맞춘다.**

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

**DB 적재**: 같은 계산을 DB 활성 판본(레시피 재료 × 식품)으로 돌려 `recipe_ingredient_foods`(재료 하나)·`recipe_computed_nutrition`(레시피 판본 하나)에 넣는다 — `python -m app.jobs.map_recipe_foods`, 칸 대응·규칙은 [`recipe_food_map_db.md`](recipe_food_map_db.md).

## 4. 코드에서 쓰는 함수 (서버 연동용)

```python
from agetech_data.nutrition.dish_eval import meal_search_indexes
from agetech_data.nutrition.foods import clean_foods
from agetech_data.nutrition.match import FoodIndex, match_ingredient, search_dishes
from agetech_data.nutrition.portion import meal_total, portion_nutrients

foods = clean_foods(raw["items"])                    # 원본 행 → 정제 레코드
by_code = {f.food_code: f for f in foods}
dish_index, raw_index = meal_search_indexes(foods)   # 사진 분석 음식명 검색용 (음식 DB군, 원재료성)
search_dishes("계란말이", dish_index, limit=5, raw_index=raw_index)
#   → [{food_code, name, db_group, basis_unit, score, match}, …] 사용자 확인용 후보 (7절)
p = portion_nutrients(by_code["D109-416000000-0001"], 60, "g")   # 사용자가 확인한 식품·분량 → Portion (7절)
meal_total([p, ...])                                 # 한 끼 합계
ingredient_index = FoodIndex(foods)                  # 원재료성·가공식품 (레시피 재료 매핑용)
match_ingredient("다진 마늘", ingredient_index)       # → MatchResult(status, food_code, food_name, rule, rationale, candidates)
```

- `search_dishes`는 **후보 목록**이다. 최종 음식·분량은 사용자 확인 후 확정한다(기획서 CORE-04). 점수가 같으면 100g 기준 행이 앞에 온다.
- 영양 계산은 서버에서 확정한 `food_code`와 분량으로 한다. 외부 AI가 말한 영양값은 쓰지 않는다.

## 5. 수집·갱신과 오류 동작

| 상황 | 동작 |
|---|---|
| 키 없음 | `client` 종료 코드 1, 기존 원본 유지. 키 이름은 `.env.example` 참고 (`DATA_GO_KR_SERVICE_KEY`) |
| API 간헐 오류(HTTP 500 등) | 페이지마다 최대 5회 재시도(대기 2·4·6·8초) |
| 키 미등록·기한 만료(결과코드 30 등) | 재시도하지 않고 실패, 기존 원본 유지 |
| 건수가 totalCount와 다름 / 식품코드 중복 | 실패, 기존 원본 유지 |
| 성공 | 원본을 통째로 교체(임시 파일 → 이름 바꾸기). 이후 `build`로 정제·매핑 재생성 |

출력·로그·파일에 키와 키가 들어간 URL을 남기지 않는다. 자동 갱신 일정·실패 시 캐시 유지 정책은 "공공데이터 자동 갱신" 작업에서 정한다.

## 6. DB 적재

- **식품 — 적재됨** (`src/backend/app/jobs/import_public_data.py`, 이진녕): 정제 식품을 `foods`(`provider`, `food_code`)와 판본 표 `food_revisions`로 넣는다. 판본은 `fingerprint`(원문 해시·정제 결과·파서 버전)로 구분하고, 기준량(`basis_*`)·성분은 2.1절 보정을 적용한 값이다. 레코드 전체는 `normalized`에 들어가서 보정의 원래 값·근거(`corrections`)도 함께 남고, 수집 원본은 `raw`·`raw_sha256`에 있다.
- **레시피 재료 매핑 — 아직 표 없음 (제안)**: (레시피 ID, `order_no`) 단위로 `match.status`·`food_code`·`grams`·`grams.status` 저장. `curated`→`reviewed` 전환 이력(확인자·일시)을 남길 수 있게 한다. 지금 DB의 `recipe_ingredients`는 원문 재료 줄(`raw_item`·`name`·`amount_text`·`parsed`)만 가진다.
- 수동 매핑표 원본은 `src/data/agetech_data/resources/ingredient_food_map.json`(커밋 대상)이며, 관리자 화면에서 검수하게 되면 이 파일 형식을 기준으로 옮긴다.

## 7. 사진·영양 API — 음식명 → 후보 → 사용자 확인 → 영양값

사진 분석·영양 계산 백엔드(이진녕)와 식사 기록 화면(김찬형)에 넘기는 입력 형식이다. 실제 수집본으로 만든 표본은 `docs/data/samples/nutrition_api_sample.json`(단일 음식 17건 + 한 끼 2건, `uv run python -m agetech_data.nutrition.sample`로 재생성, 같은 수집본이면 같은 출력).

### 7.1 흐름

| 단계 | 하는 쪽 | 표본 필드 |
|---|---|---|
| 1. 사진 → 음식명 문자열 | 사진 분석 모델 | `recognized_name` |
| 2. 음식명 → 식품 후보 | 서버, `search_dishes(name, dish_index, limit=5, raw_index=raw_index)` | `search.candidates[]` |
| 3. 음식·분량 확인·수정 | 사용자(앱) | `confirm` = {`food_code`, `amount`, `unit`} |
| 4. 영양값 계산 | 서버, `food_code`로 식품 행 조회 → `portion_nutrients(food, amount, unit)` | `food`, `result` |
| 5. 한 끼 합계 | 서버, `meal_total([...])` | `meals[].total` |

### 7.2 후보 — `search.candidates[]`

| 필드 | 설명 |
|---|---|
| `food_code`, `name`, `db_group`, `basis_unit` | 식품 행 (2절). `db_group`은 보통 `음식`, 보조 후보는 `원재료성` |
| `score` | 0~1. 정렬용이며 같은 `match` 안에서만 비교할 것 |
| `match` | 찾은 방식: `name` 음식명 일치 · `alias_code` 별칭표가 식품을 직접 지정(예: 배추김치 → 원재료성 `김치, 배추 김치`) · `family` 대표 음식명만 일치, 세부 종류 확인 필요(예: 순두부찌개 → `순두부찌개_김치`) · `partial` 일부 일치(예: 불고기 → `소불고기`) · `ingredient` 음식 DB군에 맞는 이름이 없어 원재료성에서 찾음(예: 사과 → `사과, 생것`) · `category` 이름이 너무 넓어 종류를 골라야 함(예: 떡 → 가래떡·백설기·절편·인절미·송편·시루떡) |

- 표본에는 화면 설명용으로 `basis_text`·`create_method`·`food_weight_text`·`quality_flags`를 덧붙였다. 서버는 `food_code`로 2절 레코드를 조회하면 된다.
- 화면 권장: `name`·`alias_code`이면 1순위를 미리 선택하고, `family`·`partial`·`ingredient`이면 "이 음식이 맞나요?" 확인을 강조한다. 후보가 없으면 음식명을 직접 고치게 한다.
- **넓은 이름(`category`)**: 떡·전(부침개)·생선구이(생선)·생선조림·나물·죽·수육은 사진만으로 종류를 정할 수 없어 자주 먹는 종류를 **목록 순서대로 모두** 돌려준다(`limit`과 상관없음). 화면은 `dish_choice_question(name)`이 돌려주는 질문(예: "어떤 떡인가요?", 표본의 `search.ask`)과 함께 종류를 버튼으로 보여 주고, 고른 행으로 3단계를 이어 간다. 종류마다 100g 기준 행이 있으면 그 행을 쓴다.
- 별칭표는 `src/data/agetech_data/resources/dish_aliases.json`: `aliases`(맞춤법·다른 이름, `food_code` 직접 지정. 예: 보쌈 → `제육(돼지고기 수육)`, 믹스커피 → `커피, 커피가루, 설탕, 크림, 물에 탄것(중량 12g)`, 대구식 찜갈비 → `갈비찜_고춧가루`, 대구식 뭉티기 → `소고기, 한우(1등급), 우둔, 생것`)와 `broad`(넓은 이름과 종류 목록). `name`에는 DB 음식명을 그대로 적는다(`_` 포함).
  - 뭉티기를 `육회`로 잡지 않은 이유: 육회(음식)는 양념·배 등이 섞여 100g당 단백질 9.9g·나트륨 418mg이고, 생 살코기(우둔)는 23.0g·50mg이다. 육회로 잡으면 단백질이 절반 이하로 잡힌다. 찍어 먹는 장은 계산에 넣지 않는다(필요하면 한 끼에 양념장을 따로 추가).
- 검색 품질은 정답 표본 93건(`resources/dish_search_gold.json`)으로 확인하며 결과는 `nutrition_mapping_report.md` 7절에 있다. 1순위 일치 93건, 알려진 미해결 0건. 이 중 2건(탕후루, "알 수 없는 음식")은 후보가 없어야 맞는 항목이다(DB에 없는 음식·인식 실패 문구 → 화면에서 음식명 직접 수정).
- 한 글자 검색어(귤·김 등)는 원재료성 보조 후보를 첫 이름이 같은 식품만 낸다(떡 → 떡조개 같은 오답 방지).

### 7.3 사용자 확인 값 — `confirm` (서버 입력)

| 필드 | 형식 | 설명 |
|---|---|---|
| `food_code` | 문자열 | 후보 중 사용자가 고른 식품 |
| `amount` | 수 | 0보다 커야 한다. 숫자 문자열(`"150"`)도 받는다 |
| `unit` | 문자열 | `g` `kg` `mL` `ml` `cc` `L` → 계산 / `인분` `그릇` `공기` `접시` `대접` `회분` → 원천의 1인분 중량이 있을 때만 계산 / 그 밖(`개`·`조각`·`마리` 등) → 계산 안 함 |

### 7.4 계산 결과 — `result` (`Portion`)

| `status` | 뜻 | `nutrients` |
|---|---|---|
| `computed` | 분량 단위(g·mL)가 기준량 단위와 같아 그대로 계산 | 값 |
| `approx_ml` | g↔mL가 달라 **1mL≈1g 근사**로 계산(밀도 근거 없음). 화면에 "근사" 표시 | 값 |
| `unconvertible` | 인분인데 원천 1인분 중량이 없음 / 개수 단위 / 단위 없음 → g·mL로 다시 입력받기 | null |
| `invalid` | 분량이 0 이하·숫자 아님·숫자 범위 초과, 식품 기준량 오류, 환산량·성분 계산이 비유한 값인 경우 | null |

| 필드 | 설명 |
|---|---|
| `input` | 사용자가 확인한 `{amount, unit}` 그대로 |
| `amount`, `amount_unit` | g 또는 mL로 바꾼 분량 (계산 안 했으면 null) |
| `serving` | 인분을 환산했으면 근거 `{field, label, text}` (예: `DISH_ONE_SERVING`, 1회분량 참고량, `250g`) |
| `basis` | 식품 기준량 `{amount, unit, text}` |
| `factor` | 분량 ÷ 기준량 |
| `approx_ml` | 1mL≈1g 근사 여부 |
| `nutrients` | `energy_kcal`·`protein_g`·`fat_g`·`carbohydrate_g`·`sugars_g`·`fiber_g`·`sodium_mg`·`potassium_mg`·`calcium_mg`·`cholesterol_mg`·`sat_fat_g` (소수 둘째 자리). **null = 원천에 값 없음(0 아님)** |
| `missing` | 값이 없는 성분 키 목록 |
| `note` | 화면·로그용 설명 |

### 7.5 한 끼 합계 — `total` (`meal_total`)

| 필드 | 설명 |
|---|---|
| `items`, `items_calculated` | 음식 수, 계산된(`computed`·`approx_ml`) 음식 수 |
| `excluded[]` | 계산에서 빠진 음식 `{index, food_code, status, note}` |
| `complete` | 모든 음식이 계산됐는지. false면 합계 옆에 "일부 음식 제외" 표시 |
| `approx_ml_items` | 1mL≈1g 근사로 계산된 음식 수 |
| `nutrients` | 성분별 합계. 값이 있는 음식만 더하며, 모든 음식에 값이 없으면 null |
| `missing_items` | 성분별로 값이 없어 합계에서 빠진 음식 수 (예: `{"sugars_g": 1}`) |

인분 근거는 올바른 숫자 형식의 유한한 양수만 사용한다. 앞선 근거가 `0g`·잘못된 쉼표·범위 초과이면 다음 근거를 확인하고, 모두 유효하지 않으면 `unconvertible`이다. 분량과 개별 영양값의 범위 초과는 `invalid`이며, 개별 음식은 유한해도 한 끼 합계가 표현 범위를 넘으면 `meal_total`이 명시적인 `ValueError`를 반환하므로 API에서 입력 오류로 처리한다.

### 7.6 데이터에서 확인한 주의점 (10/31 수집본)

- **1인분 중량 근거가 없다.** 음식 4,048건 모두 1회분량 참고량(`DISH_ONE_SERVING`)·1회 섭취참고량(`NUTRI_AMOUNT_SERVING`)이 비어 있어 지금은 인분·그릇 입력이 모두 `unconvertible`이다. 식품중량(`Z10500`, 예: 김치찌개 400g·쌀밥 100g)은 값이 있지만 명세 항목명이 '식품중량'일 뿐 1인분이라는 근거가 없어 계산에 쓰지 않는다. 데이터는 식품중량을 `food_weight_text`·`_amount`·`_unit`(2절)으로 원문 그대로 넘긴다. 화면에 보인다면 "참고 중량(식품중량)"으로만 쓰고, 인분 계산·"1인분 = ○g" 안내에는 쓰지 않는다. 보일지 말지는 화면에서 정한다.
- **같은 음식명이 기준량·생성 방법이 다른 여러 행이다.** 식품기원코드 1·3은 분석값이며 대부분 100g 기준(906건, 100mL 2건), 4~7은 100mL 기준·산출(3,140건)이다. 원천에 식품기원명이 비어 있어 4~7의 차이는 알 수 없다. 같은 음식이라도 값 차이가 크다(김치찌개 열량 61kcal/100g 분석 vs 19kcal/100mL 산출, 미역국 나트륨 168mg/100g vs 339mg/100mL). 검색은 100g 분석 행을 앞에 둔다.
- **100mL 기준 행만 있는 음식이 있다.** 고등어구이·제육볶음·도라지나물·달걀찜 등. g으로 입력하면 `approx_ml`이다.
- **원재료성 식품은 결측이 많다.** 당류·포화지방산·식이섬유·콜레스테롤(보고서 6절). 과일 등 `ingredient` 후보는 `missing`이 자주 있다. 음식 100g 기준 행은 906건 중 2건만 합산 성분(7.4절 11개)에 결측이 있다.
- **기준량 표기가 잘못된 행이 있었다.** 가공식품 `커피믹스`(P109-202020000-0081)는 기준량이 100mL로 적혀 있었지만 값이 커피믹스 가루(원재료성, 100g)와 똑같다(426kcal, 수분 1.7g). 2.1절 보정표로 기준량을 100g으로 고쳤다(수집 원본은 그대로, 원래 값은 `corrections`에 남음). 마시는 믹스커피는 가루가 아니라 원재료성 '물에 탄것(중량 12g)'(51kcal/100g)으로 연결한다.
- **1인분·개수 단위 환산의 출처 후보 (확인 전)**: 밥 1공기·달걀 1개 같은 눈대중 중량은 농촌진흥청 국가표준식품성분표의 눈대중량 자료가 출처가 될 수 있다. 이용 조건·형식을 아직 확인하지 않았다. 커피믹스 1봉 = 12g은 위 식품명 자체가 근거다.

## 8. 알려진 제한

- 개수 단위(개·장·알·뿌리 등)는 출처 있는 개당 중량표가 없어 g으로 환산하지 않는다.
- 수동 매핑표는 2026-11-09에 모두 확인했다(`reviewed`, 확인자 최재영). 새로 넣는 매핑은 확인 전까지 `curated`이며 보고서(`docs/data/nutrition_mapping_report.md`) 3절에 나온다.
- 부위·품종이 적히지 않은 재료는 매핑표의 기본값으로 계산한다(돼지고기·소고기 → 앞다리, 새우 → 대하 등, 이유는 매핑표 `rationale`). 저염 제품 항목이 없는 저염된장·저염소금은 일반 제품으로 근사해 나트륨이 실제보다 많게 잡힌다.
- 먹지 않는 약재(오가피·당귀), 같은 레시피에서 이미 계산되는 소스, DB에 없는 재료는 '매핑하지 않음'(`unmapped`, `rule=manual:no_match`)으로 정했다. 쌀뜨물은 물로 취급한다.
- 가공식품 상용제품(약 33만 건)은 수집하지 않았다. 필요하면 `--db-class 상용제품`으로 별도 수집한다.
