# 레시피 재료 → 식품 매핑·계산 영양 DB 적재

| 항목 | 내용 |
|---|---|
| 작성 | 최재영 (데이터) |
| 대상 | 사진 분석·영양 백엔드(이진녕, 11/22~), 레시피 상세의 계산 영양 표시(김찬형), 관리자 매핑 검수(김민찬) |
| 저장 구조 | Alembic `20261111_02` — `recipe_ingredient_foods`(재료 하나), `recipe_computed_nutrition`(레시피 판본 하나), `recipe_ingredients`에 유일 조건 `(recipe_revision_id, id)` 하나 |
| 계산 | `agetech_data.nutrition.recipe_map` → `nutrition.build.ingredient_nutrition` — 보고서(`nutrition_mapping_report.md`)·파일 산출물(`recipe_ingredient_nutrition.json`)과 **같은 함수** |
| 명령 | `python -m app.jobs.map_recipe_foods` (기본 dry run, `--apply`·`--verify`) — 레시피·식품 적재(`import_public_data`) 뒤 |

## 1. 정한 것 (데이터 기준)

- **입력은 전부 DB다.** 활성 레시피 판본의 재료(`recipe_ingredients.parsed`) × 활성 식품 판본(`food_revisions.normalized`, 보정 반영) × 수동 매핑표(`resources/ingredient_food_map.json`). 파일을 따로 넘기지 않아서, 앱이 보여 주는 레시피·식품과 매핑이 항상 같다.
- **재료 하나 = `recipe_ingredient_foods` 한 행** (정의서 6절 제안대로 (레시피 판본, `order_no`) 단위). `recipe_ingredient_id`는 같은 판본의 재료 행만 가리킨다(복합 FK).
  - `match_status`: `reviewed`(사람이 확인한 수동 매핑) · `curated`(근거만 있는 수동 매핑) · `exact`(규칙 일치, 후보 1개) · `water` · `candidate`(후보만) · `unmapped`. 앞의 셋만 영양 계산에 쓴다.
  - 쓰는 매핑이면 `food_id`·`food_revision_id`(**계산에 쓴 식품 판본**)가 있고, 아니면 둘 다 NULL(CHECK). `candidate`는 `candidates`에 상위 5개 후보.
  - `reviewed_by`·`reviewed_on` = 수동 매핑표의 확인자·확인일(정의서 6절 "curated → reviewed 전환 이력"). `reviewed`일 때만 있다(CHECK). 매핑표 자체의 바뀐 이력은 git에 있다.
  - `grams`·`gram_status`·`gram_basis` = g 환산과 근거 문장(정의서 3절). `contribution` = 성분별 기여량(g ÷ 기준량 × 함량), 계산에 들어간 재료만. `basis_ml_approx` = mL 기준 식품을 1mL≈1g으로 계산했는지.
- **레시피 판본 하나 = `recipe_computed_nutrition` 한 행**: `computed`(11개 성분 합계), `computed_missing`(성분별 값 없는 재료 수), `coverage`(정성 분량 `qualitative_items`·`complete_except_qualitative` 포함 — 정의서 3절), `complete`(물을 뺀 모든 재료가 계산에 들어갔는지), `items`·`items_used`·`grams_used_pct`, 계산기 판본·매핑표 해시·`mapping_sha256`.
  - 원천 레시피가 적어 둔 영양(`recipe_revisions.source_*`)과는 **다른 값**이다. 섞어 쓰지 않는다. 화면은 `complete = false`면 "일부 재료 기준"으로 보여 준다(정의서 3절).
- **옛 판본 행은 지우지 않는다.** 레시피가 새 판본이 되면 새 판본 행을 만들고, 옛 판본 행은 남긴다 — 식단표(#18 `meal_plan_entries`)가 고른 당시 판본을 가리킬 수 있어서.

## 2. 다시 계산하는 규칙

- 레시피마다 `mapping_sha256` = 매핑·계산 결과 + 계산에 쓴 식품 판본 + 계산기 판본 + 매핑표 해시. 이 값이 저장된 것과 다른 레시피만 지우고 다시 넣는다.
  - 식품 값이 바뀐 판본 → 그 식품을 쓰는 레시피만. 값이 같아도 새 식품 판본이면 가리키는 판본을 옮긴다.
  - 매핑표가 바뀜 → 모든 활성 레시피(어느 매핑표로 계산했는지 남기려고). 1,151건 기준 수십 초.
- 입력 지문(활성 레시피·식품 판본 목록, 매핑표, 계산기 판본)이 전과 같고 **저장된 행도 계산과 같을 때만** `already_mapped`로 끝난다. 매핑표를 고쳤다가 되돌린 경우(A → B → A)처럼 지문이 예전 실행과 같아도 저장된 행이 다르면 다시 맞춘다.
- 레시피·식품 적재와 **같은 잠금** 안에서 한 트랜잭션으로 돈다. 활성 레시피나 식품이 하나도 없으면 거부한다.
- `--verify`: 다시 계산한 결과와 모든 활성 판본의 요약·재료 행을 칸 단위로 대조한다.

## 3. 조회 예 (API 쪽)

```sql
-- 레시피 상세: 계산 영양과 완전성
SELECT n.computed, n.computed_missing, n.complete, n.grams_used_pct
FROM recipes r JOIN recipe_computed_nutrition n ON n.recipe_revision_id = r.active_revision_id
WHERE r.provider = 'foodsafetykorea:COOKRCP01' AND r.source_id = :recipe_id;

-- 재료별 근거(검수·설명 화면)
SELECT i.order_no, i.raw_item, f.match_status, fr.name AS food_name, f.grams, f.gram_status,
       f.contribution, f.reviewed_by, f.candidates
FROM recipe_ingredient_foods f
JOIN recipe_ingredients i ON i.id = f.recipe_ingredient_id
LEFT JOIN food_revisions fr ON fr.id = f.food_revision_id
WHERE f.recipe_revision_id = :revision_id ORDER BY i.order_no;

-- 식단표에서 고른 판본의 계산 영양(옛 판본이어도 남아 있음)
SELECT n.computed FROM meal_plan_entries m
JOIN recipe_computed_nutrition n ON n.recipe_revision_id = m.recipe_revision_id WHERE m.id = :entry_id;
```

- 사진으로 찍은 음식의 영양은 이 표가 아니라 정의서 7절 흐름(음식명 → 후보 → 사용자 확인 → `portion_nutrients`)이다. 이 표는 **레시피**의 계산 영양이다.

## 4. 실데이터 확인 (2026-11-11, pgvector/pgvector:pg16 빈 DB, Alembic head)

입력: 레시피 1,156건(10/31 수집본, 보완 6건 적용), 식품 품목대표 8,807건(10/31 수집본).

| 항목 | 결과 |
|---|---|
| 대상 | 활성 레시피 1,151건, 재료 12,983개 |
| 매핑 상태 | exact 4,893 · reviewed 4,280 · candidate 3,216 · unmapped 343 · water 251 (curated 0) |
| g 환산 | direct 11,427 · direct_paren 41 · approx_ml 91 · unparsed 464 · count_unit 670 · qualitative 201 · missing 89 |
| 계산에 들어간 재료 | 8,174개 (mL 기준 식품 1mL≈1g 근사 175개) |
| 레시피 완전성 | 물 뺀 모든 재료 계산 **76건**, 환산된 무게의 80% 이상 계산 455건 |
| 다시 실행 / verify | `already_mapped`, 다시 쓴 레시피 0 / 통과 |
| 걸린 시간 | 한 번 계산 약 20초(같은 재료명은 한 번만 매핑) |

- 수동 매핑표는 앱의 50건을 기준으로 만든 것(148건)이라 전체 1,156건에서는 후보만 있는 재료가 많았다. 자주 나오는데 못 정한 재료(적재 결과 `unresolved_top`: 버터 106, 후추 96, 올리고당 67, 생강 66, 찹쌀가루 48, 밥 45 …)는 아래 4.1처럼 매핑표에 더했다.
- 50건만 보면 파일 산출물과 같은 값이다(같은 함수, 데이터 시험에서 대조).

### 4.1 자주 나오는 재료 매핑 추가 뒤 (2026-11-13, 같은 입력)

전체 레시피에서 g 환산은 되는데 식품만 못 정한 재료 중 근거가 분명한 67개 이름을 매핑표에 더했다(11/13 확인 → `reviewed`). 정하는 기준은 기존 항목과 같다: 종류 미기재는 시판에 흔한 것, 원재료성 우선, 항목이 없으면 가장 가까운 항목으로 근사하고 근거에 무엇이 많게·적게 잡히는지 적음(예: 맛간장 → 양조간장, 통후추 → 검은 후추 가루).

| 항목 | 추가 전 (11/11) | 추가 뒤 |
|---|---|---|
| 매핑 상태 | reviewed 4,280 · candidate 3,216 · unmapped 343 | **reviewed 5,588**(+1,308) · candidate 1,937 · unmapped 314 (exact 4,893 · water 251 그대로) |
| 계산에 들어간 재료 | 8,174개 | **9,397개** |
| 물 뺀 모든 재료 계산 | 76건 | **163건** |
| 환산된 무게 계산 비율 | 평균 66.5% · 중앙값 71.9% · 80% 이상 455건 · 95% 이상 239건 | 평균 76.1% · 중앙값 84.6% · 80% 이상 614건 · 95% 이상 389건 |

- 앱 50건 결과는 그대로다(새 이름이 50건에 없음, 완전 계산 29건).
- 일부러 남긴 것: 종류·분량을 정할 근거가 없는 것 — 월계수잎(건져 냄), 육수(종류 미기재), 튀김기름(흡수량 모름), 깨소금(항목 없음, 소금 비율 모름), 김·치즈·식빵·라면·견과류·옥수수(종류 미기재), 물전분·물녹말(물 비율 모름), 마늘기름. 닭고기·어린잎은 11/09에 확인한 '매핑하지 않음' 결정 그대로.
- 계산 한계: 튀김옷용 빵가루·튀김가루처럼 일부만 먹는 재료도 원문 분량을 다 먹는 것으로 계산한다(원문에 먹는 양이 없음).

### 4.2 계량 단위·개당 중량 환산 뒤 (2026-11-13, 11/12 수집본, 4.1 매핑 포함)

g 환산에 `resources/unit_weights.json`을 쓴다(정의서 7.6절 끝·8절): 큰술 15·작은술 5·영문 `Ts`·`ts`·컵 200 mL → `approx_ml`(1mL≈1g 근사), 출처 있는 개당 중량(달걀·계란 1개 60 g, 사과 1개 200 g, 귤 1개 100 g, 참외 1개 300 g, 포도 1송이 300 g, 밥 1공기 210 g — 식약처 노인 영양지수 교육자료, 한국인 영양소 섭취기준) → 새 상태 `unit_weight`(Alembic `20261113_01`). 계산기 판본 `recipe-food-map-v2`.

| 항목 | 전 | 뒤 |
|---|---|---|
| g 환산 | count_unit 670 · unparsed 464 · approx_ml 91 | count_unit 552 · unparsed 252 · approx_ml 348 · **unit_weight 73** |
| 계산에 들어간 재료 | 9,397개 | **9,664개** |
| 물 뺀 모든 재료 계산 | 163건 | **170건** |
| 무게 80% 이상 계산 | 614건 | 624건 |

- 근거 문장은 행마다 `gram_basis`에 남는다(예: `원문 (1개) → 1개=60g(식품의약품안전처: '달걀 크기로 1개(60 g)'(16쪽), …)`).
- 1mL≈1g 근사라 가루 양념(후춧가루 ⅓Ts → 5 g)은 실제보다 무겁게 잡힌다.
- 남은 개수 단위 552줄(레몬·양파·버섯·새우 '마리'·깻잎 '장'·대추 '알' 등)은 출처가 더 필요하다(한국보건산업진흥원 2007 눈대중량 DB — 원문·이용 조건 확인 전).

### 4.3 정성 분량 따로 남기기 (2026-11-13, 계산기 `recipe-food-map-v3`)

'약간·적당량'(201줄)은 g을 지어내지 않고, `complete`도 엄격하게 둔다. 대신 `coverage.qualitative_items`(이름·분량 원문·매핑된 식품코드)와 `complete_except_qualitative`를 남긴다. 실DB(4.2와 같은 입력): `complete` 170건, `complete_except_qualitative` **185건**(정성 분량만 빠진 15건 — 빠진 것은 소금 7·후추 2·참기름 2 …). 매핑 결과 JSON에 `complete_except_qualitative_recipes`.

### 4.4 한국보건산업진흥원 눈대중량 DB로 개수 단위 더하기 (2026-11-13)

환산표에 한국보건산업진흥원 2007 「눈대중량의 부피 및 중량 환산 DB」(별첨 1) 가식부 중량 25종(36행)을 더했다(정의서 7.6절 끝). 같은 입력에서:

| 항목 | 전(4.3) | 뒤 |
|---|---|---|
| g 환산 | unit_weight 73 · count_unit 552 | **unit_weight 334** · count_unit 291 |
| 계산에 들어간 재료 | 9,664개 | **9,925개** |
| 물 뺀 모든 재료 계산 | 170건 | **188건** |
| 정성 분량만 빠진 것까지 | 185건 | **203건** |
| 무게 계산 비율 중앙값 · 80% 이상 | 84.4% · 624건 | 85.2% · 636건 |

- 앱 50건: 완전 계산 29 → 32건(`count_unit` 26 → 12).
- 남은 개수 단위 291줄: 레몬 32·새우 '마리' 19·아스파라거스 12·파프리카 12·통후추 '알' 9·인삼 8·아보카도 7·청양고추 6 … — 표에 없거나(레몬·아보카도·아스파라거스·인삼) 크기 폭이 넓어(새우) 정하지 않았다.

## 5. 남은 것

- 남은 후보 재료는 빈도순으로 계속(`unresolved_top`) — 근거가 필요한 것들(4.1 '일부러 남긴 것').
- g 환산이 안 돼 막히는 재료(소금·후춧가루 '약간', 달걀·양파·레몬 '1개' 등 — `qualitative`·`count_unit`)는 개수 단위 중량표 출처가 정해져야 한다(농촌진흥청 눈대중량 자료 후보, 확인 전).
- 매일 갱신 명령(#26)에 레시피·식품 적재 뒤 `map_recipe_foods --apply`를 넣는다.
