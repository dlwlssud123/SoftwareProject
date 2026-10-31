# 레시피 원본 품질 검증 보고서 (식품안전나라 COOKRCP01)

> 이 파일은 `uv run python -m agetech_data.recipes.validate`로 생성됩니다. 직접 고치지 마세요.

| 항목 | 값 |
|---|---|
| 입력 파일 | `src/frontend/assets/data/recipes.json` |
| 입력 sha256 | `d5db8e9435fe6679…` |
| 제공처·서비스 | 식품안전나라 · COOKRCP01 |
| 수집 시각(fetchedAt) | 2026-10-26T07:46:53.482870+00:00 |
| 수집 모드 | authenticated |
| 레시피 수 (원본 전체) | 50 (전체 1156건 중) |
| 가공 결과 | `data/processed/recipes_validated.json` (gitignore, 명령으로 재생성) |

## 1. 요약

| 판정 | 의미 | 건수 | 비율 |
|---|---|---|---|
| `ok` | 정상 | 45 | 90.0% |
| `flagged` | 표시 후 사용 | 3 | 6.0% |
| `hold` | 노출 보류 후보 | 2 | 4.0% |

- 조리 단계: 총 213개. **중간 누락이 있는 레시피 2건, 누락 단계 4개**
- 재료 항목: 총 534개. 괄호 설명이 있는 항목 483개(원문 그대로 보존)

## 2. 판정 기준

| 코드 | 수준 | 설명 | 처리 |
|---|---|---|---|
| `name_missing` | 오류(hold) | 메뉴명(RCP_NM) 없음 | 원문 보완 전까지 앱 노출 보류, 보완 요청 |
| `steps_none` | 오류(hold) | 조리 단계 문장이 하나도 없음 | 원문 보완 전까지 앱 노출 보류, 보완 요청 |
| `step_first_missing` | 오류(hold) | 1단계(준비 과정) 누락 | 원문 보완 전까지 앱 노출 보류, 보완 요청 |
| `step_gap` | 경고(flagged) | 마지막 단계 이전 번호가 비어 있음(중간 누락) | 노출하되 이상 표시, 보완 요청 목록 |
| `step_number_mismatch` | 경고(flagged) | 원본 칸 번호(MANUALnn)와 문장 앞 번호가 다름 | 노출하되 이상 표시, 보완 요청 목록 |
| `step_number_duplicate` | 경고(flagged) | 문장 앞 번호가 중복됨 | 노출하되 이상 표시, 보완 요청 목록 |
| `step_image_without_text` | 경고(flagged) | 단계 이미지만 있고 문장이 없음 | 노출하되 이상 표시, 보완 요청 목록 |
| `step_unnumbered` | 참고 | 문장 앞 번호 없음(칸 번호로 대체) | 집계만 (원문 보존) |
| `step_trailing_marker` | 참고 | 문장 끝 이미지 표식 문자(a/b/c 등) | 집계만 (원문 보존) |
| `step_text_without_image` | 참고 | 단계 문장은 있으나 이미지 없음 | 집계만 (원문 보존) |
| `ingredients_none` | 오류(hold) | 재료 원문(RCP_PARTS_DTLS) 없음 | 원문 보완 전까지 앱 노출 보류, 보완 요청 |
| `ingredients_unparsed` | 오류(hold) | 재료 항목을 하나도 분리하지 못함 | 원문 보완 전까지 앱 노출 보류, 보완 요청 |
| `ingredient_unclosed_paren` | 경고(flagged) | 괄호가 닫히지 않음 | 노출하되 이상 표시, 보완 요청 목록 |
| `ingredient_unmatched_close_paren` | 경고(flagged) | 여는 괄호 없이 닫는 괄호가 있음 | 노출하되 이상 표시, 보완 요청 목록 |
| `ingredient_amount_missing` | 경고(flagged) | 분량 표기 없음 | 노출하되 이상 표시, 보완 요청 목록 |
| `ingredient_unit_missing` | 경고(flagged) | 숫자 분량에 단위가 없음 | 노출하되 이상 표시, 보완 요청 목록 |
| `ingredient_qualitative_amount` | 참고 | 정성 분량(약간·적당량 등) | 집계만 (원문 보존) |
| `ingredient_no_space_after_comma` | 참고 | 쉼표 뒤 공백 없음 | 집계만 (원문 보존) |
| `ingredient_trailing_period` | 참고 | 재료 원문 끝 마침표 | 집계만 (원문 보존) |
| `ingredient_mixed_format` | 참고 | 한 레시피 안에 분량 표기 형식이 섞여 있음 | 집계만 (원문 보존) |

## 3. 조리 단계 누락

| ID | 메뉴명 | 원문에 있는 단계(칸) | 누락 번호 | 판정 |
|---|---|---|---|---|
| 33 | 사과 새우 북엇국 | MANUAL02, MANUAL03, MANUAL05 | 1, 4 | `hold` |
| 36 | 저염 된장으로 맛을 낸 황태해장국 | MANUAL03, MANUAL04, MANUAL05 | 1, 2 | `hold` |

## 4. 재료·분량 형식 이상 (경고)

| ID | 메뉴명 | 코드 | 원문 줄 | 원문 항목 |
|---|---|---|---|---|
| 38 | 표고버섯 청경채국 | `ingredient_amount_missing` | 1 | `표고버섯 기둥` |
| 642 | 훈제오리가슴살크러스트 | `ingredient_unclosed_paren` | 3 | `후춧가루(0.5g` |
| 276 | 맑은부대찌개 | `ingredient_unclosed_paren` | 7 | `소금(0.1g` |

## 5. 점검 항목별 집계

| 코드 | 수준 | 설명 | 레시피 수 | 발생 수 |
|---|---|---|---|---|
| `step_first_missing` | 오류(hold) | 1단계(준비 과정) 누락 | 2 | 2 |
| `step_gap` | 경고(flagged) | 마지막 단계 이전 번호가 비어 있음(중간 누락) | 2 | 2 |
| `step_trailing_marker` | 참고 | 문장 끝 이미지 표식 문자(a/b/c 등) | 1 | 3 |
| `ingredient_unclosed_paren` | 경고(flagged) | 괄호가 닫히지 않음 | 2 | 2 |
| `ingredient_amount_missing` | 경고(flagged) | 분량 표기 없음 | 1 | 1 |
| `ingredient_qualitative_amount` | 참고 | 정성 분량(약간·적당량 등) | 8 | 11 |
| `ingredient_no_space_after_comma` | 참고 | 쉼표 뒤 공백 없음 | 1 | 1 |
| `ingredient_trailing_period` | 참고 | 재료 원문 끝 마침표 | 1 | 1 |

## 6. 재료 표기 형식 분포

| 분량 표기 형식 | 항목 수 | 비율 |
|---|---|---|
| 괄호 안 분량 `돼지고기(50g)` | 274 | 51.3% |
| 이름 뒤 분량 `연두부 75g(3/4모)` | 248 | 46.4% |
| 정성 분량 `참깨 약간` | 11 | 2.1% |
| 분량 없음 | 1 | 0.2% |

| 섹션 표기 방식 | 섹션 수 |
|---|---|
| 콜론 `●양념장 : …` | 46 |
| 콜론 없는 머리말 `재료 닭가슴살(60g)…` | 23 |
| 제목만 있는 줄 `고명` | 10 |

표기 참고 항목(내용 문제는 아님):

| ID | 메뉴명 | 코드 | 원문 발췌 |
|---|---|---|---|
| 161 | 유자 대구조림 | `ingredient_no_space_after_comma` | `g(1/10개),청파프리카 1` |
| 645 | 겨자소스로 구운 산마샐러드 | `ingredient_trailing_period` | `겨자가루(10g).` |

## 7. 원본 추적과 보완 원칙

- 가공 결과의 레시피마다 원본 행 sha256(`raw_sha256`)을, 단계마다 원본 칸(`source_field`)·칸 번호(`source_no`)·문장 앞 번호(`stated_no`)·원문(`text_raw`)을 보존합니다. 단계 번호를 다시 매기지 않습니다.
- 재료는 원문 조각(`raw_item`)과 원문 줄 번호(`line_no`)를 보존하고, 이를 `name_raw`와 `amount_text`로 나누기만 합니다. 수식어(다진 등)와 괄호 설명은 지우지 않습니다.
- 비어 있는 단계와 분량은 **임의로 채우지 않습니다.** 원문 보완은 재수집했을 때 원본에 값이 생긴 경우에만 반영합니다.
- `hold` 레시피는 원문 보완 전까지 앱 노출 보류를 권고합니다. `flagged` 레시피는 노출하되 앱에서 누락·이상을 표시합니다.
- 수작업 보완이 필요해지면 출처 URL·확인자·확인일을 함께 남기는 별도 파일로 관리합니다(후속 작업).

## 8. 참고 (이번 범위 밖)

영양 필드의 빈 값 건수입니다. 영양값 검증은 공공 영양 DB 매핑 작업에서 다룹니다.

| 필드 | 빈 값 | 비율 |
|---|---|---|
| `INFO_WGT` | 47 | 94.0% |
| `INFO_ENG` | 0 | 0.0% |
| `INFO_CAR` | 0 | 0.0% |
| `INFO_PRO` | 0 | 0.0% |
| `INFO_FAT` | 0 | 0.0% |
| `INFO_NA` | 0 | 0.0% |
