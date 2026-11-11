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
- **레시피 판본 하나 = `recipe_computed_nutrition` 한 행**: `computed`(11개 성분 합계), `computed_missing`(성분별 값 없는 재료 수), `coverage`, `complete`(물을 뺀 모든 재료가 계산에 들어갔는지), `items`·`items_used`·`grams_used_pct`, 계산기 판본·매핑표 해시·`mapping_sha256`.
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

- 수동 매핑표는 앱의 50건을 기준으로 만든 것(148건)이라 전체 1,156건에서는 후보만 있는 재료가 많다. **자주 나오는데 못 정한 재료**(적재 결과 `unresolved_top`): 버터 106, 후추 96, 올리고당 67, 생강 66, 찹쌀가루 48, 밥 45, 전분 43, 빵가루 40, 통후추 34, 녹말가루 34, 맛간장 32, 파슬리가루 29, 월계수잎 28, 육수 26, 튀김기름 25 … → 매핑표에 더하면 완전 계산 레시피가 늘어난다(후속).
- 50건만 보면 파일 산출물과 같은 값이다(같은 함수, 데이터 시험에서 대조).

## 5. 남은 것

- 위 미해결 재료를 매핑표에 더하기(근거 적고 확인) → 다시 `--apply`.
- 정의서 6절의 "레시피 재료 매핑 — 아직 표 없음" 줄은 PR #22가 고치는 자리라, #22 병합 뒤 이 문서를 가리키게 한 줄 고친다.
- 매일 갱신 명령(#26)에 레시피·식품 적재 뒤 `map_recipe_foods --apply`를 넣는다.
