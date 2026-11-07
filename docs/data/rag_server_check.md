# RAG 서버 측정 절차 — 기업 서버에 계속 둘지, ARM 서버로 옮길지

| 항목 | 내용 |
|---|---|
| 작성 | 최재영 (데이터) |
| 함께 할 사람 | 이진녕(백엔드 띄우기), 최재영(측정) |
| 결정 | 2026-11-07 "기업 서버에서 먼저, 시연에 문제가 될 만큼 느리면 최재영 서버(ARM)" — `rag_embedding_decision.md` 3절 |
| 도구 | `uv run python -m agetech_data.rag.bench` (옵션은 아래) |

임베딩 모델만 혼자 재면 **최소 조건**만 확인된다. 시연 때는 한 서버에 PostgreSQL·FastAPI·임베딩 모델이 같이 돌고 요청이 겹치므로, **백엔드와 같이 띄운 상태**에서 다시 재야 실제 판정이 된다.

## 0. 사전 점검 (서버에서, 1분)

```bash
free -h                         # 남은 메모리·스왑 (11/06: 여유 약 5.9GB, 스왑 2GB 꽉 참)
top -b -o %MEM -n 1 | head -20  # 무엇이 메모리를 쓰는지
nproc; df -h .; docker ps       # 코어 수, 디스크, 이미 떠 있는 컨테이너
```

- 아무것도 안 올렸는데 스왑이 꽉 차 있으면, 다른 프로그램이 메모리를 쓰고 있다는 뜻이다. 서버 관리자(기업)에게 무엇인지 확인한다.
- `bench` 결과에도 측정 직전 메모리를 많이 쓰던 프로그램 이름별 합계가 찍힌다(`top_memory_before`, 리눅스만).

## 1단계 — 임베딩 혼자 (최소 조건)

```bash
git clone -b feature/rag-index-pipeline https://github.com/silversky621/AgeTech.git && cd AgeTech
docker run --rm -v "$PWD":/app -w /app -e UV_PROJECT_ENVIRONMENT=/opt/venv \
  -v agetech-uv-cache:/root/.cache/uv -v agetech-hf-cache:/root/.cache/huggingface \
  python:3.12-slim bash -c "pip install -q uv && uv sync --extra embed && \
  uv run python -m agetech_data.rag.bench --label solo --json-out bench_solo.json"
```

- 결과가 `move`이면 **여기서 끝 — ARM 서버로 옮긴다.** 혼자서도 안 되면 백엔드와 같이는 당연히 안 된다.
- `stay`여도 아직 합격이 아니다 → 2단계.
- 두 번째 실행부터는 `-e HF_HUB_OFFLINE=1`을 붙인다(모델을 다시 확인하러 인터넷에 나가지 않게).

## 2단계 — 백엔드와 같이 (실제 판정)

**주의: 모델이 두 번 올라가지 않게 한다.** 백엔드가 이미 KURE를 올린 상태에서 `bench`를 돌리면 모델이 두 개(약 6GB)라 실제보다 나쁘게 나온다. 둘 중 하나로 잰다.

### 2-A. 백엔드는 임베딩 없이, `bench`가 모델 역할 (백엔드에 RAG를 붙이기 전)

1. 이진녕: PostgreSQL + FastAPI를 시연과 같은 설정(워커 수, 다른 기능 포함)으로 띄운다. 임베딩 모델은 아직 올리지 않는다.
2. 최재영: 같은 서버에서

   ```bash
   uv run python -m agetech_data.rag.bench --label with-backend --concurrency 4 --threads 4 --passages 0 \
     --json-out bench_with_backend.json
   ```

   - `--concurrency 4`: 질문 4개가 동시에 들어오는 상황(시연 중 여러 명이 같이 누를 때)
   - `--threads 4`: torch가 코어를 다 잡지 않게 절반만 — 백엔드 요청이 같이 느려지지 않게
   - `--passages 0`: 문서 임베딩(전체 CPU를 수십 초 잡음)은 빼고 질문 임베딩만
3. 측정하는 동안 앱이나 `curl`로 백엔드 API를 몇 번 불러, 눈에 띄게 느려지지 않는지 본다.

### 2-B. 임베딩이 붙은 AI 도우미 API를 바깥에서 동시에 호출 (백엔드에 RAG를 붙인 뒤)

- 서버의 임베딩 모델은 프로세스 하나에만 올린다(FastAPI 워커 1개, 또는 작은 임베딩 서비스 하나).
- 질문 → 임베딩 → pgvector 검색 → (대화 AI 호출 전까지) 시간을 API 로그나 응답 헤더로 남기고, 동시에 4개씩 40번 정도 불러 p95를 본다.
- 대화 AI(외부 API) 응답 시간은 서버 사양과 무관하므로 따로 적는다.

## 판정 기준

| 항목 | 기준 | 넘으면 |
|---|---|---|
| 질문 임베딩 p95 (혼자) | ≤ 0.5초 | 옮김 |
| 질문 임베딩 p95 (동시 4개) | ≤ 1.0초 | 옮김 |
| 서버 전체 남은 메모리 (모델·백엔드 다 올린 뒤) | ≥ 1GB | 옮김 |
| 측정 중 스왑 증가 | ≤ 100MB | 옮김 |
| 백엔드 API | 측정 중에도 체감상 느려지지 않음 | 스레드를 줄여 다시 재고, 그래도 느리면 옮김 |

`bench`는 위 앞의 네 개를 자동으로 판정한다(종료 코드 0 = 유지, 2 = 옮김).

## 시연 운영 규칙 (어느 서버든)

1. **인덱스는 미리 만들어 넣는다.** 처음 전체 임베딩(약 25분, CPU 전부)은 서버에서 하지 않는다. `rag.export`의 CSV·`load_index.sql`로 넣는다.
2. **매일 갱신은 밤에**(예: 03:00). 시연 시간대에는 갱신을 멈춘다. 갱신이 실패해도 이전 판본이 그대로 검색된다.
3. 모델은 **프로세스 하나에만**, torch 스레드는 **코어의 절반**, `HF_HUB_OFFLINE=1`.
4. 시연 전날 `load_index.sql`로 활성 판본을 확인하고, 직전 판본을 남겨 둔다(되돌리기용).

## 기록

| 날짜 | 서버 | 단계 | 혼자 p95 | 동시 4 p95 | 남은 메모리 | 스왑 증가 | 판정 | 메모 |
|---|---|---|---:|---:|---:|---:|---|---|
| 11/07 | 최재영 노트북(참고, 서버 아님) | 1 | 105ms(스레드 8) | — | 1,174MB | +433MB | move | 노트북 자체 메모리 부족 |
| 11/07 | 최재영 노트북(참고, 서버 아님) | 2-A 형식 | 79ms(스레드 4) | 167ms | 1,022MB | +806MB | move | 백엔드 없이 옵션만 시험 |
| | 기업 서버 | 1 | | | | | | |
| | 기업 서버 | 2-A | | | | | | |
