# 복지 RAG API와 KURE 질문 임베딩 서비스

2026-11-25 구현. 최재영 담당의 KURE-v1 규약·검색 SQL·원본 게시 지문 검증을 재사용한다. API·앱 코드를 연결한 것과 실제 기업 서버의 모델·인덱스 준비 및 운영 활성화는 구분한다.

## 흐름과 API

AI 도우미의 **복지 물어보기 → 질문 입력 → 선택적으로 지역 지정 → 외부 처리 동의 → 공식 자료 검색 → 답변과 출처 확인** 순서다. 지역을 선택하지 않으면 전국 사업만 찾는다. 나이·건강·소득·사용자 프로필을 모델에 자동 전달하지 않는다. 기존 생활·요리 대화는 변경하지 않는다.

인증된 `POST /api/v1/ai/welfare-chat`에 `message`, `allow_external_processing: true`를 보내며 `region`, `district`는 선택이다. 시군구만 보내는 요청은 거절한다. 기존 AI 동시 요청 수·사용자/전체 일간 한도·응답 후 세션 재검증을 적용한다. 질문·답변은 DB에 저장하지 않고 응답은 no-store다.

- `answer_status`: generated / references_only / no_evidence.
- `evidence_status`: 기존 evidence_status의 ok / weak / none.
- `sources`: 사용한 자료 번호·사업 ID·종류·제목·발췌·공식 HTTPS 주소·청크의 자료 확인 시각. 모델이 만든 주소를 사용하지 않는다.
- `region`, `district`, `notes`: 재영님 지역 정규화 결과. 지역이 불명확하면 전국 또는 시도 범위로 제한한 이유를 표시한다.
- `index_version`: 검색한 활성 DB 인덱스 판본. 사용자의 질문이나 동의 정보가 아니다.

KURE 모델·revision·1024차원·정규화 규약이 일치해야 한다. 질문 임베딩 후 `docs/data/sql/rag_search.sql`의 SELECT를 그대로 실행한다. 복지 종류만, 게시 중인 원본과 지문이 같은 활성 청크만 검색하고 종료일·지역을 적용하며 같은 사업은 한 청크만 쓴다. SQL 날짜 판단은 한국 시간으로 실행한다. SQL 파일은 API 이미지에도 포함한다.

1위 유사도 0.40 미만은 모델에 근거를 보내지 않는다. 0.40~0.53 미만은 앱에서 관련성이 약할 수 있음을 표시한다. 모델은 자료 번호를 인용해야 하며 없는 번호·본문 인용과 번호 불일치·모델 생성 URL은 사용하지 않고 자료만 보여준다. AI 장애 시에도 검색된 자료를 확인할 수 있다. 생성 후 자료·활성 판본이 바뀌거나 세션이 폐기되면 예전 답변을 반환하지 않는다. 인용 번호 검사만으로 문장별 사실성이나 수급 자격을 보증하지는 않는다.

## 별도 임베딩 서비스

API는 HTTP 클라이언트만 사용하고 torch·KURE 가중치를 올리지 않는다. `agetech_data.rag.serve`가 기존 KureEmbedder를 한 프로세스에 한 번 로드한다. `/embed`는 질문만 받아 같은 MODEL_ID와 정규화된 1024개 벡터를 반환한다. 토큰 인증·입력 크기 제한·접속 시간 제한을 적용하고 질문·요청 로그를 기록하지 않는다. 모델 로드가 끝난 뒤에만 `/health`를 제공한다.

개발 환경에서 실행하려면 저장소 루트의 기존 embed extra 환경을 사용한다. RAG_EMBEDDING_TOKEN은 안전하게 생성한 32자 이상의 공유 토큰을 비공개 환경에 설정하며 코드·채팅·명령 인자에 넣지 않는다.

```powershell
uv sync --locked --extra embed
uv run --extra embed python -m agetech_data.rag.serve
```

서비스 설정은 `WELFARE_RAG_ENABLED`, `RAG_EMBEDDING_URL`(경로 없는 origin), `RAG_EMBEDDING_TOKEN`, `RAG_EMBEDDING_TIMEOUT_SECONDS`다. 기본값은 비활성이다. 다른 모델 API로 대체하거나 서로 다른 모델의 문서·질문 벡터를 섞지 않는다.

## 기업 서버 준비 순서

1. 현재 서버 가용 메모리·스왑·CPU 사용을 확인한다. KURE의 기존 실측은 약 3GB 수준이며 선택적 컨테이너 한도는 4GB·2 CPU다. 공유 서버에 무조건 구동하지 않는다.
2. 현재 코드의 저장소 루트에서 아래 이미지 빌드를 수행하고 해당 이미지를 서버에 전달한다. 임베딩 이미지는 기존 API 이미지와 별개이며, 현재 백엔드 Actions가 이 선택적 이미지를 자동 게시하지는 않는다.

   ```bash
   docker build -f deploy/embedding.Dockerfile -t valueflow-embedding:local .
   ```

3. 기존 기업 서버 .env에 공유 토큰과 `EMBEDDING_IMAGE=valueflow-embedding:local`, `RAG_EMBEDDING_URL=http://embedding:8091`을 비공개로 설정한다. WELFARE_RAG_ENABLED는 초기 확인 전 false로 유지한다.
4. 새 compose.yaml이 반영된 기존 ValueFlow 작업 폴더에서 `docker compose --profile rag up -d embedding`으로 별도 서비스를 시작한다. 호스트 포트는 공개하지 않는다. 최초 모델 다운로드가 필요하며 캐시는 embedding_cache 볼륨에 남는다.
5. `docker compose --profile rag exec -T embedding python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8091/health', timeout=3).read().decode())"`로 모델 로드와 준비 상태를 확인한다. 캐시 준비 후 HF_HUB_OFFLINE=1로 고정하여 시작 시 외부 조회를 막을 수 있다.
6. 재영님이 만든 실제 `data/processed/rag`의 CSV·manifest를 준비한다. 기존 배포·적재 공통 잠금 아래 원본 복지 자료와 RAG를 `app.jobs.load_rag_index --index`의 apply/verify 절차로 적재하고 게시 원본 지문·MODEL_ID·차원·활성 판본을 대조한다. 기존 표와 적재 CLI를 재사용하므로 새 DB 마이그레이션은 없다.
7. 검증 후 WELFARE_RAG_ENABLED=true로 API를 재생성하고 실제 앱에서 전국·지역 질문, 근거 없음, 출처 열기, 서비스 실패를 확인한다. 이후 API 자동배포는 기본 compose의 RAG 환경 설정을 유지하며 임베딩 서비스는 명시적으로 구동한 상태여야 한다.

기존 daily_refresh의 문서 임베딩 배치는 별도 KURE 프로세스를 쓸 수 있다. 질문 서비스와 배치가 동시에 모델 두 개를 올리지 않도록 정기 실행 순서·메모리 배치를 맞추는 것은 자동 적재 운영 작업에서 확인해야 한다. API 컨테이너에 무거운 모델을 설치하여 해결하지 않는다.

## 검증 범위

실제 PostgreSQL의 기존 게시 뷰·벡터 SQL로 지역·종료일·중복·판본·게시 중단과 응답 중 원본 변경을 검사한다. 임베딩 HTTP 테스트는 전송·인증·차원·모델 계약의 테스트 더블을 사용하며 실제 KURE 정확도 측정을 대신하지 않는다. Flutter에서는 동의 취소·오류·출처·큰 글씨를 검사한다. 실제 모델 로드·원천 인덱스 적재·기업 서버 자원 실측·APK 실기기 검증은 별도 완료 근거가 필요하다.
