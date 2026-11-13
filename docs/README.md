# ValueFlow 문서 안내

팀이 개발 기준으로 사용하는 공개 문서는 이 저장소의 `docs/`에서 관리한다. 진행 상황과 담당자·마감은 Asana에서 관리하고, 문서 변경 PR과 관련 작업을 서로 링크한다.

| 문서 | 위치 |
| --- | --- |
| 기획·구현 기준 | [최종 기획서](설계/최종기획서.md), [구현계획서](설계/구현계획서.md) |
| 앱·서버 실행 | [Flutter 앱](../src/frontend/README.md), [백엔드](../src/backend/README.md) |
| API 계약 | [API 명세](설계/API_명세서.md), [실행 API OpenAPI](설계/openapi.json), [예정 조회 API OpenAPI](설계/catalog.openapi.json), [요청·응답 예제](설계/api_examples.json) |
| DB와 수집 | [DB 마이그레이션 계획](설계/DB_마이그레이션_계획.md), [공공데이터 갱신](data/public_data_refresh.md), [레시피·영양 적재](data/public_db_import.md), [복지 적재](data/welfare_db_import.md) |
| 데이터 계약 | [레시피](data/recipe_contract.md), [식품영양](data/food_nutrition_contract.md) |
| RAG | [임베딩 모델 결정안](data/rag_embedding_decision.md), [검색 인덱스 정의서](data/rag_index_contract.md), [검색 SQL](data/sql/rag_search.sql) |

## 변경 방법

1. 공개 가능한 기획·설계·검증 문서는 Markdown으로 작성한다. 같은 주제는 기존 파일을 수정하고 변경 이력은 Git에서 확인한다.
2. API·데이터 계약이 바뀌면 관련 코드, 명세, 생성된 예제를 같은 PR에서 갱신한다. 문서만 바뀌면 `docs/<작업명>` 브랜치에서 문서 PR을 열고 링크와 내용을 확인한다.
3. PR에는 변경 이유와 영향받는 문서, 관련 Asana 작업을 적는다. 팀원이 검토한 뒤 `main`에 Squash merge하고, 시연·제출본은 기준 커밋이나 태그와 연결한다.

## 공개 범위

이 저장소는 공개되어 있다. 공개 승인된 기획·설계·요약 문서를 커밋한다. 기업 비공개 회의록, 개인 서류, 실제 사용자 자료와 운영 비밀은 팀 전용 저장소에서 관리한다. 발표 영상·편집용 PPT·제출 원본은 팀 전용 저장소에서 기준본을 정하고, 공개 가능한 설명과 검증 기록을 Git에 남긴다.

기획서와 구현계획서의 기능 범위·일정은 11/06 기준본을 바탕으로 한다. 이후 구현 현황은 API 명세와 백엔드 README, 11/07 모델 결정은 RAG 결정안에서 확인한다.
