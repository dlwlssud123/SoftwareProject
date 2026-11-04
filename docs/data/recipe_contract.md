# 레시피 데이터 필드 정의서 (데이터 → 서버·앱 인계)

| 항목 | 내용 |
|---|---|
| 작성 | 최재영 (데이터) |
| 대상 | 레시피 API(이진녕), 레시피 화면·알레르기 필터(김찬형), 품질 평가(김민찬) |
| 원천 | 식품안전나라 조리식품 레시피 DB `COOKRCP01` ([명세](https://www.foodsafetykorea.go.kr/api/newDatasetDetail.do?svc_no=COOKRCP01)) |
| 생성 명령 | `uv run python -m agetech_data.recipes.contract` (앱 50건) / `--input data/raw/recipes/cookrcp01_all.json --no-sample` (전체 1,156건) |
| 표본 | [`docs/data/samples/recipe_api_sample.json`](samples/recipe_api_sample.json) — 대표 사례 6건 |
| 품질 보고서 | [앱 50건](recipe_quality_report.md) · [전체 1,156건](recipe_quality_report_all.md) |
| 기준 | 기획서 CORE-01 "제외 재료를 우선 적용", CORE-02 "재료·분량·원문 번호를 보존", CORE-04 "영양 수치·기준량·출처는 상세에서 확인" |

## 1. 꼭 지킬 규칙

1. **식별자는 `recipe_id`(원천 `RCP_SEQ`, 예: `"28"`) 문자열이다.**
2. **원문 값을 고치거나 채우지 않는다.** 비어 있는 단계·분량·중량은 비어 있는 그대로 오고, 이상은 `quality`에 표시만 한다. 예외는 이미지 주소의 https 전환 하나다(5번).
3. **`quality.status`로 노출을 정한다.** `hold`는 노출 보류 후보(원문 보완 전), `flagged`는 노출하되 이상 표시, `ok`는 그대로 노출.
4. **알레르기는 재료명 기반 추정이다.** 원천에 알레르기 칸이 없다. 화면에 "재료명으로 추정했어요. 가공식품은 제품 원재료 표시를 확인해 주세요" 같은 안내를 함께 둔다. 필터는 안전한 쪽으로 쓴다.
   - `detected`에 사용자 알레르기가 있으면 제외한다. `kind`가 `direct`든 `usually`든 똑같이 제외한다.
   - `needs_check`의 `candidates`에 사용자 알레르기가 있으면 제외하거나 "확인 필요"로 표시한다.
   - `complete: false`이면 재료명이 잘렸을 수 있어 추정이 불완전하다.
5. **이미지 주소는 https로 준다.** 원천은 `http://www.foodsafetykorea.go.kr/…`인데, 같은 경로가 https로 제공된다(http 요청은 https로 302 이동, 11/05 확인). Android 9 이상은 기본 설정에서 http 요청을 막는다.
6. **영양 수치의 기준량을 단정하지 않는다.** `nutrition.basis = "per_serving_unverified"`는 1인분으로 보이지만 명세에 기준량이 적혀 있지 않다는 뜻이다(아래 2.3).

## 2. 레코드 — `data/processed/recipes_api.json`

최상위: `schema_version`, `contract`, `input`(원문 경로·sha256), `records[]`

| 필드 | 형식 | 원천 | 설명 |
|---|---|---|---|
| `recipe_id` | 문자열 | `RCP_SEQ` | 식별자 |
| `name` | 문자열 | `RCP_NM` | 메뉴명 |
| `category` | 문자열·null | `RCP_PAT2` | 요리종류: 반찬·일품·후식·밥·국&찌개·기타 |
| `cooking_method` | 문자열·null | `RCP_WAY2` | 조리방법: 끓이기·굽기·볶기·찌기·튀기기·기타 |
| `hashtag` | 문자열·null | `HASH_TAG` | 대표 재료 **한 단어**(목록 아님). 전체의 69%가 비어 있음 |
| `images.small`, `images.large` | 문자열·null | `ATT_FILE_NO_MAIN`, `ATT_FILE_NO_MK` | 대표 이미지(소·대), https |
| `ingredients_text` | 문자열·null | `RCP_PARTS_DTLS` | 재료 원문(줄바꿈 유지). 분리가 이상할 때 그대로 보여 줄 대체용 |
| `ingredients[]` | 객체 배열 | `RCP_PARTS_DTLS` | 2.1 |
| `steps[]` | 객체 배열 | `MANUAL01~20`, `MANUAL_IMG01~20` | 2.2 |
| `missing_step_nos` | 정수 배열 | | 비어 있는 단계 번호. 화면에 "원문에 n단계가 없어요" 안내 |
| `nutrition` | 객체 | `INFO_*` | 2.3 |
| `sodium_tip` | 문자열·null | `RCP_NA_TIP` | 저감 조리법 TIP |
| `allergens` | 객체 | (재료명에서 추정) | 2.4 |
| `quality` | 객체 | | 2.5 |
| `source` | 객체 | | `provider`, `service`, `source_id`, `fetched_at`(수집 시각), `raw_sha256`(원문 행 해시) |

### 2.1 `ingredients[]`

| 키 | 설명 |
|---|---|
| `order_no` | 원문 순서(1부터) |
| `section` | 직전 섹션 제목 원문(예: "양념장"), 없으면 null |
| `name` | 괄호를 뺀 이름(검색·매핑용) / `name_raw`: 원문 이름 그대로(예: "황태(채)") |
| `amount_text` | 분량 원문(예: "15g(10개)", "약간"), 없으면 null |
| `amount`, `unit` | 숫자·단위로 읽은 참고값(예: 15, "g"). 못 읽으면 null |
| `amount_kind` | `measured` 숫자 분량 / `qualitative` 약간·적당량 / `none` 분량 없음 |

### 2.2 `steps[]`

| 키 | 설명 |
|---|---|
| `no` | 단계 번호. 문장 앞 번호 우선, 없으면 원천 칸 번호. **다시 매기지 않는다** |
| `text` | 표시용 문장(앞 번호·끝 이미지 표식 제거) |
| `image` | 단계 이미지(https)·null |
| `source_field` | 원천 칸(예: `MANUAL02`) |

### 2.3 `nutrition`

| 키 | 설명 |
|---|---|
| `basis` | `per_serving_unverified`: 명세에서 기준량이 적힌 필드는 `INFO_WGT` '중량(1인분)'뿐이고, 열량 등은 기준량·단위 표기가 없음 |
| `serving_weight_g` | 1인분 중량(`INFO_WGT`). **전체 1,156건 중 871건(75%), 앱 50건 중 47건이 비어 있음** → 1인분이 몇 g인지 모름 |
| `ingredient_servings` | 재료 원문의 'N인분' 표기(`[2인분]`·`2인분 기준`, 재료 분량의 기준). 전체 62건(2인분 48·1인분 13·4인분 1)만 있음. 없으면 재료 분량이 몇 인분 기준인지 모름 |
| `energy_kcal`, `carbohydrate_g`, `protein_g`, `fat_g`, `sodium_mg` | 원문 값(숫자로만 읽음). 단위는 값 범위로 판단(명세에 단위 표기 없음) |
| `energy_from_macros_kcal`, `energy_ratio` | 탄수화물×4 + 단백질×4 + 지방×9, 그 값 ÷ 원문 열량 |
| `suspect` | 비율이 0.5 미만 또는 2 초과면 true(`nutrition_energy_mismatch`). 수치를 그대로 보여 주지 말고 "원문 영양값 확인 중" 등으로 표시할 것을 권장 |

- 전체 1,156건 중 1,029건(89%)은 계산 열량과 원문 열량이 ±25% 안에서 맞는다. 이상 의심은 88건이다.
- 앱 50건 중 이상 의심은 9건이며, 모두 271~281번 찌개류다. 탄수화물·단백질·지방이 원문 열량의 1/5 안팎이라, 이 묶음은 기준량이 다르게 입력된 것으로 보인다(원문 확인 필요).

### 2.4 `allergens`

```json
{"basis": "ingredient_name",
 "detected": [{"allergen": "밀", "kind": "usually",
               "evidence": [{"ingredient": "저염간장", "term": "간장", "kind": "usually"}]}],
 "needs_check": [{"ingredient": "우렁이", "term": "우렁", "candidates": ["조개류"]}],
 "not_determinable": ["아황산류"],
 "complete": true}
```

| 키 | 설명 |
|---|---|
| `detected[].allergen` | 법정 표시 대상 19종 이름(알류·우유·메밀·땅콩·대두·밀·고등어·게·새우·돼지고기·복숭아·토마토·아황산류·호두·닭고기·쇠고기·오징어·조개류·잣). 앱 선택지 "달걀"은 `알류` |
| `detected[].kind` | `direct` 재료 자체(두부→대두) / `usually` 보통 원료로 들어가는 가공식품(간장→대두·밀, 굴소스→조개류·밀). 근거 중 하나라도 direct면 direct |
| `evidence[]` | 근거 재료명·맞은 단어·구분. `from`이 있으면 이름이 아닌 곳에서 찾은 것: `item_text`(항목 원문의 괄호·같은 줄에 붙은 다음 재료), `section_title`(제목 줄로 읽힌 재료) |
| `needs_check[]` | 물질을 정할 수 없는 재료와 후보(예: 갈비→쇠고기·돼지고기, 육수→쇠고기·닭고기·돼지고기, 콩→대두, 소라→조개류) |
| `not_determinable` | 재료명으로 판별할 수 없는 물질(첨가물인 아황산류) |
| `complete` | 재료 원문 이상(괄호 미닫힘 등)이 없으면 true |

규칙은 [`src/data/agetech_data/resources/allergen_rules.json`](../../src/data/agetech_data/resources/allergen_rules.json)에 있다. 근거는 「식품 등의 표시·광고에 관한 법률 시행규칙」 별표 2이며 11/05에 확인했다. 실제 재료명 1,857종에서 찾은 오탐은 제외 규칙과 테스트로 막아 두었다. 예: 스파게티는 게가 아니고, 겨잣가루는 잣이 아니며, 땅콩호박은 땅콩이 아니다. 우삼겹은 돼지고기가 아니라 쇠고기다.

### 2.5 `quality`

| 키 | 설명 |
|---|---|
| `status` | `ok` / `flagged` / `hold` |
| `issues[]` | 경고·오류만, `code`·`severity`·`label`·`detail`. 코드 목록은 품질 보고서 2절 |
| `info_codes` | 참고 수준 코드만 (예: `serving_weight_missing`, `step_text_without_image`) |
| `missing_fields` | 비어 있는 원천 필드 (명세 순서, 예: `INFO_WGT`, `HASH_TAG`) |

## 3. 앱 현재 규칙과 다른 점 (화면 담당 확인)

앱의 현재 규칙(`src/frontend/lib/models/recommendations.dart` `Recipe.fromPublicData`)은 재료 원문 전체에서 단어가 들어 있는지만 본다. 전체 1,156건으로 비교하면 다음과 같다.

| 물질 | 둘 다 | 앱만 | 이번 규칙만 | 차이의 주된 이유 |
|---|---|---|---|---|
| 알류 | 228 | 0 | 42 | 이번 규칙은 메추리알·마요네즈도 찾음 |
| 우유 | 290 | 5 | 49 | 앱은 땅콩버터·피넛버터·코코넛우유·아몬드우유·식물성 생크림도 우유로 봄 / 이번 규칙은 요거트·연유·파마산 등도 찾음 |
| 대두 | 497 | 45 | 54 | 앱은 땅콩·완두콩·병아리콩·토마토콩카세의 '콩'을 대두로 봄 / 이번 규칙은 고추장·두반장(usually)도 찾음 |
| 새우 | 124 | 0 | 3 | 이번 규칙은 대하도 찾음 |
| 밀 | 421 | 1 | 160 | 앱은 호밀가루를 밀로 봄 / 이번 규칙은 국수·소면·파스타·빵가루·고추장(usually) 등도 찾음 |
| 땅콩 | 38 | 1 | 1 | 앱은 땅콩호박을 땅콩으로 봄 / 이번 규칙은 피넛버터도 찾음 |

API가 `allergens`를 주면 앱은 위 규칙을 계속 유지할 필요가 없다. 앱 선택지에 없는 물질(쇠고기·조개류 등)도 레코드에 있으니, 선택지를 늘릴지는 화면 쪽에서 정하면 된다.

## 4. 알려진 제한

- 알레르기 추정은 재료명만 본다. 가공식품 원료는 제품마다 다르고, 아황산류는 판별할 수 없다. 수급·의료 판단이 아니라 "피할 재료 후보"로만 쓴다.
- 재료 원문 형식이 레시피마다 달라 한 항목에 여러 재료가 붙어 읽히는 경우가 있다(예: `흰살생선 100g [흰 살생선 양념] 달걀흰자 15g`). 알레르기는 항목 원문까지 보며 보완하지만, 재료 목록 표시에는 그대로 남는다.
- 1인분 중량과 재료 분량의 인분 기준이 대부분 없어, 사진 분량과의 비교나 g당 환산에는 식품 영양 매핑(`food_nutrition_contract.md`)의 계산값을 함께 봐야 한다.
- JSON 키 이름은 snake_case로 두었다. 공통 API 계약의 규칙이 정해지면 그에 맞춘다.
