# 무료급식소·이달의 식재료 DB 적재

| 항목 | 내용 |
|---|---|
| 작성 | 최재영 (데이터) |
| 대상 | 시설·제철 API(이진녕), 관리자 자료 상태(김민찬) |
| 저장 구조 | #18 `meal_facilities`·`seasonal_ingredients` + Alembic `20261111_01`(원천 칸·`seasonal_foods`·`seasonal_recipe_links`) |
| 입력 | 갱신 수집본 `data/raw/facilities/free_meal.json`, `data/raw/seasonal/food_month.json` (`refresh`가 만듦, gitignore) |
| 정제 | `agetech_data.facilities.revision`, `agetech_data.seasonal.revision` — 필드 정의서(`meal_facility_contract.md`·`seasonal_contract.md`)와 같은 정제 |
| 적재 | `python -m app.jobs.import_meal_facilities`, `python -m app.jobs.import_seasonal` (기본은 파일만 보는 dry run) |

## 1. 정한 것 (데이터 기준)

- **원천 행과 수동 행을 구분한다.** 원천에서 온 행은 `provider`·`source_id`·`normalized`·`content_sha256`·`last_seen_at`·`last_seen_run_id`가 다 있고, 관리자가 직접 넣은 행(예: 남구청에서 확인한 경로식당)은 다 NULL이다(CHECK 제약). 적재는 수동 행을 건드리지 않는다.
- **급식소 칸**
  - `source_id` = `facility_id`(시설명·주소 해시, 같은 장소 다른 일정은 `-2`). 다시 적재할 때 이 값으로 같은 시설을 찾는다.
  - `checked_on` = **수집 날짜(KST)**, `reference_date` = **원천 자료 기준일**(화면의 '자료 기준일'). 둘을 따로 둔다.
  - `hours_text` = 요일 원문 + `" / "` + 시간 원문(`수+목 / 중식(11:20-12:20)`), `eligibility_text` = 대상 원문, `contact_text` = 전화번호, `address` = 도로명(없으면 지번).
  - `quality_flags` = 정의서 2절 표시 그대로. 구조화 값(`days`·`meals`·`targets`·`merged_from` 등)은 `normalized`에 있다.
  - 위도·경도는 `Numeric(8,5)`에 맞춰 소수 5자리로 반올림해 넣는다(약 1m). 원래 값은 `normalized`에 있다.
  - **게시**: 운영 종료·미운영(`operation_ended`·`not_operating`)은 행은 넣고 `is_published = false`. 나머지는 게시.
  - **시도·시군구를 못 정한 시설은 넣지 않는다**(`sigungu` NOT NULL, 지역 조회에 걸 수 없음) — 적재 결과 `skipped`에 이유와 함께 남는다. 지금은 0곳이다.
    - 주소에서 시군구만 못 읽은 경우(`전라남도 완도군신지면 …`처럼 붙어 있음)는 **같은 시도의 제공 지자체 시군구**로 채우고 `sgg_from_provider`를 붙인다(정제 규칙 추가, 1곳). 다른 시도 지자체의 시군구는 쓰지 않는다.
  - 판단 기준일(`reference_stale`·`operation_ended` 계산)은 실행 날짜가 아니라 수집 날짜다. 매일 갱신하면 하루 안에 맞춰진다.
- **제철 칸**
  - `seasonal_foods`: (월, 원천 순번) 하나 = 한 행. 이름·이미지·상세 글(`detail`, 원문)·농진청 관련 레시피·쇼핑 검색 링크·`content_sha256`(상세 글 RAG 청크를 붙일 해시)·`links_sha256`.
  - `seasonal_ingredients`(#18): 레시피 재료명 → 식재료. `seasonal_food_id`·`match_term`·`match_kind`(`official`/`alias`)로 연결 근거를 남긴다. `(seasonal_food_id, month)`는 `seasonal_foods(id, month)`를 가리켜서 다른 달로 붙일 수 없다.
  - `seasonal_recipe_links`: 레시피 → 식재료, `share`(물·육수 뺀 g 무게 중 제철 재료 비율, 주재료·고명 구분)·`weight_g`·연결된 재료명. **연결할 때 쓴 레시피 판본**(`recipe_revision_id`)을 같이 남긴다.
  - **레시피 연결은 DB 활성 레시피 판본으로 계산한다.** 파일(`recipes_api_all.json`) 대신 DB를 쓰는 이유: 앱이 보여 주는 레시피와 연결이 같아야 해서. 그래서 레시피를 먼저 적재해야 한다(활성 레시피가 없으면 거부).
  - `(월, 레시피 재료명)`은 #18 유일 조건 그대로다. 같은 달 두 식재료가 한 재료명에 걸리면 적재를 멈춘다 → 연결 규칙(`resources/seasonal_terms.json`)을 고친다. 지금은 0건.
  - 관리자가 직접 넣은 `seasonal_ingredients` 행이 있는 (월, 재료명)은 자동 매핑을 넣지 않는다(수동이 이김, 결과의 `manual_overrides`).

## 2. 적재 규칙

- 두 작업 모두 레시피·식품·복지 적재와 **같은 잠금**(`pg_advisory_xact_lock`)을 잡는다. 한 트랜잭션이라 중간에 실패하면 아무것도 남지 않는다.
- 수집본 확인: `meta.complete = true`, 건수, `items_sha256`(수집기가 씀), 서비스 이름, 수집 시각(시간대 필수·미래 금지). 급식소는 `row_id` 중복, 제철은 12개월이 다 있는지도 본다.
- 같은 입력 지문(수집본 파일 + 정제 버전, 제철은 + 활성 레시피 목록 + 연결 규칙)이면 `already_imported`로 끝난다. 더 오래된 수집본은 거부한다.
- 새 완전한 수집본에서 빠진 원천 행은 지우지 않고 게시만 내린다(`newly_unpublished`). 제철은 그 식재료의 재료명 매핑·레시피 연결도 지운다.
- 제철 연결은 연결 내용(`links_sha256`)이나 연결된 레시피 판본이 바뀐 식재료만 다시 만든다. 레시피가 새 판본이 되면 같은 제철 수집본이라도 다시 적재하면 새 판본으로 연결된다.
- 제철 상세가 하나라도 실패한 수집본은 `complete = false`라 기본으로 거부한다. `--allow-partial-details`로 넣으면 실패한 식재료는 **예전 상세 글을 유지**한다(`kept_previous_details`).
- `--verify`: 다시 계산한 결과와 표를 전부 대조한다(칸 값, 재료명 매핑, 연결·판본·비중, 빠진 원천 행이 게시돼 있지 않은지).

## 3. 명령

저장소 루트에서 `src/backend/.venv`(또는 `uv sync --locked`)로 실행한다. DB 연결은 `src/backend/.env`.

```powershell
cd src/backend
.venv/Scripts/python.exe -m alembic upgrade head
# 레시피를 먼저(제철 연결이 DB 활성 레시피를 씀)
.venv/Scripts/python.exe -m app.jobs.import_public_data --dataset recipes --apply
.venv/Scripts/python.exe -m app.jobs.import_meal_facilities            # dry run: 건수·게시·품질 표시
.venv/Scripts/python.exe -m app.jobs.import_meal_facilities --apply
.venv/Scripts/python.exe -m app.jobs.import_meal_facilities --verify
.venv/Scripts/python.exe -m app.jobs.import_seasonal --apply
.venv/Scripts/python.exe -m app.jobs.import_seasonal --verify
```

- 지금 디스크의 11/07 수집본은 `complete`·`items_sha256`이 없어서 거부된다 → `refresh --source meal_facilities seasonal_foods`로 한 번 다시 받는다(급식소 2회·제철 약 135회 호출, 한도 여유 있음).

## 4. 조회 예 (API 쪽)

```sql
-- 위치 거부: 내 시군구 → 같은 시도
SELECT name, hours_text, eligibility_text, contact_text, reference_date, quality_flags
FROM meal_facilities WHERE is_published AND sido = :sido AND sigungu = :sigungu ORDER BY name;

-- 이달의 식재료와 주재료 비중 높은 활성 레시피
SELECT f.name, rv.name AS recipe, l.share
FROM seasonal_foods f
JOIN seasonal_recipe_links l ON l.seasonal_food_id = f.id
JOIN recipes rc ON rc.id = l.recipe_id AND rc.active_revision_id = l.recipe_revision_id
JOIN recipe_revisions rv ON rv.id = l.recipe_revision_id
WHERE f.is_published AND f.month = :month
ORDER BY f.name, l.share DESC NULLS LAST;
```

- `rc.active_revision_id = l.recipe_revision_id` 조건으로, 레시피만 새로 적재되고 제철 적재가 아직 안 돈 사이에도 옛 판본 연결은 보이지 않는다.
- 시설 결과마다 정의서 3절의 `cautions`와 "이용 전 전화로 확인"을 붙인다(`agetech_data.facilities.query.CAUTIONS`). 위치 허용 시 반경 조회는 좌표 칸으로 계산한다.

## 5. 실데이터 확인 (2026-11-11, pgvector/pgvector:pg16 빈 DB, Alembic head)

입력: 디스크 수집본(레시피 10/31, 급식소·제철 11/07)에 `complete`·`items_sha256` 두 칸만 더한 복사본.

| 항목 | 결과 |
|---|---|
| 레시피 | 1,156건 적재, 활성 1,151 |
| 급식소 | 원천 1,282행 → 시설 1,244곳 모두 적재, 게시 1,040 / 비게시 204(운영 종료·미운영). 대구시 게시 37곳, 남구 2곳(남구종합사회복지관·희망의집) |
| 제철 | 식재료 123개 / 재료명 매핑 581개(official 495·alias 86) / 레시피 연결 4,755건, 레시피 1,126개 |
| 다시 적재 | 두 작업 모두 `already_imported`, 추가 행 0 |
| verify | 두 작업 모두 통과 |

- 제철 연결이 파일 기준(레시피 1,124개·4,748건)보다 7건 많은 것은 **보완표로 고친 레시피 33·36**이다. 원문 기준 파일에서는 보류라 빠졌고, DB에는 보완된 판본이 활성이라 연결됐다.
- 같은 이름의 다른 레시피(예: 버섯 리조또 788·919)는 원천에 따로 있는 레시피라 각각 연결된다.

## 6. 남은 것

- 관리자가 원천 시설을 숨기는 기능은 아직 없다. 생기면 적재가 그 표시를 지키도록 칸 하나(예: 관리자 숨김)를 더하고 `is_published` 계산에 넣는다.
- 매일 갱신 명령(#26)에 `import_meal_facilities`·`import_seasonal`을 레시피 적재 뒤에 넣는다.
- 제철 상세 글 RAG 청크는 `seasonal_foods.content_sha256`에 붙인다(복지 청크가 `welfare_revisions.content_sha256`에 붙는 것과 같은 방식).
