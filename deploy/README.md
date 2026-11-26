# 기업 개발 서버 배포와 CI/CD

대상은 `kapje90@210.90.113.81:1190`, 작업 경로는 `~/Documents/ValueFlow`다. 기존 Docker·다른 프로젝트·방화벽은 변경하지 않는다. `valueflow-server` Compose 프로젝트에 API와 PostgreSQL+pgvector를 분리한다. DB는 호스트에 포트를 열지 않고 API는 서버의 `127.0.0.1:18081`에만 연결한다. 외부 HTTPS 주소는 기업의 포트·프록시 담당자와 별도로 확정한다.

## 자동화 흐름

`PR → Ruff·PostgreSQL 테스트·이미지 빌드·배포/복귀 시험 → main 병합 → GHCR 이미지 게시 → 개발 서버 배포 → health 확인`

- 빌드와 테스트는 GitHub 제공 runner에서 실행한다. 기업 서버에는 CI runner를 설치하지 않는다.
- 서버에는 검증한 이미지 아카이브를 SSH로 전달한다. 서버용 GHCR 토큰이나 Git 소스 체크아웃이 필요하지 않다.
- 커밋 SHA를 이미지 라벨과 대조한 뒤, 실제 이미지 ID를 서버 `.env`에 기록한다.
- DB 백업 → Alembic upgrade → API 교체 → Docker health 확인 순서다. 실패하면 이전 이미지와 Compose 설정을 복원한다. DB를 자동 downgrade하지 않으며 백업은 `backups/`에 유지한다.
- `VALUEFLOW_CD_ENABLED=true`인 경우에만 `main` 검증·게시 성공 후 CD를 실행한다. PR이나 임의 작업 브랜치는 서버에 배포하지 않는다. 겹친 배포는 GitHub concurrency와 서버 `flock`으로 직렬화한다.
- API·DB에 각각 메모리 768 MiB·CPU 1 제한을 둔다. 현재 서버 여유 자원은 `preflight.sh`로 다시 확인한다. 무거운 임베딩 작업은 이 API 컨테이너에 상주시키지 않는다.

## 첫 배포 패키지 준비

작업 PC에서 아래 명령을 실행한다. 기존 백엔드 `.env`의 숫자 `KAKAO_APP_ID`를 재사용한다. `deploy/.local`에 배포 전용 SSH 키와 기존에 신뢰한 서버 호스트키를 준비하고, Docker 이미지를 빌드한다. 이 단계는 GitHub나 서버 설정을 변경하지 않는다.

```powershell
python deploy/make-first-bundle.py
scp -P 1190 dist/valueflow-first-deploy.tar.gz kapje90@210.90.113.81:Documents/
ssh -p 1190 kapje90@210.90.113.81
```

패키지에는 배포 코드·이미지·공개키·숫자 앱 ID만 들어간다. 개인키·Native 앱 키·API 인증키·로컬 DB·실제 `.env`는 넣지 않는다. SSH 비밀번호는 서버 접속 창에서 직접 입력한다.

## 서버 터미널에서 실행

먼저 별도 폴더에 패키지를 풀고 서버 상태를 확인한다.

```bash
mkdir -p ~/Documents/ValueFlow-bootstrap
tar -xzf ~/Documents/valueflow-first-deploy.tar.gz -C ~/Documents/ValueFlow-bootstrap
cd ~/Documents/ValueFlow-bootstrap
bash deploy/preflight.sh
```

Docker 접근 권한·현재 사용 포트·기존 `valueflow-server`가 다른 경로에 없는지 확인한 뒤 실행한다. Docker가 권한 오류를 내면 기업 담당자와 해당 계정의 Docker 사용 권한부터 확인한다.

```bash
bash run-first.sh
curl --fail http://127.0.0.1:18081/api/v1/health/ready
```

첫 실행은 `.env`가 없을 때만 무작위 DB 비밀번호를 만든다. 기존 설정과 볼륨을 덮어쓰거나 삭제하지 않는다. API 포트가 사용 중이면 첫 실행 때 `API_PORT=빈포트 bash run-first.sh`로 지정한다. 공유 서버에서 기존 Docker를 재설치·재시작하거나 `docker system prune`을 실행하지 않는다.

새 서버 DB는 빈 상태다. 첫 구동 확인 후 레시피·영양·복지 원본을 별도로 전달하거나 수집하고 [데이터 적재 절차](../docs/data/public_data_refresh.md)를 진행한다. 첫 패키지는 기기에서 쓰던 사용자 DB를 복사하지 않는다. 현재 로컬 계정 데이터까지 옮길 때는 원본·대상 DB를 확인한 별도 이관이 필요하다.

## 초기 레시피·영양 적재

`python deploy/make-seed-bundle.py`는 공개 원천 두 파일의 출처·완전성·건수·체크섬을 확인하고 `dist/valueflow-initial-data.tar.gz`를 만든다. `.env`·개인키·사용자 DB는 포함하지 않는다. 현재 준비된 파일은 2026-11-05 KST 수집본이며 레시피 1,156건·식품 영양 8,807건이다. 레시피 중 품질 보류 5건은 조회에서 제외된다.

```powershell
scp -P 1190 dist/valueflow-initial-data.tar.gz kapje90@210.90.113.81:Documents/
```

로그인한 서버에서 새 폴더에 풀고 실행한다.

```bash
seed_dir=$(mktemp -d "$HOME/Documents/ValueFlow-seed.XXXXXX")
tar -xzf ~/Documents/valueflow-initial-data.tar.gz -C "$seed_dir"
cd "$seed_dir"
bash seed-first.sh "$HOME/Documents/ValueFlow"
curl --fail 'http://127.0.0.1:18081/api/v1/recipes?limit=1'
```

스크립트는 배포와 같은 잠금을 잡고 DB를 먼저 백업한다. 배포된 이미지와 DB 네트워크를 재사용하는 일회성 컨테이너에서 `alembic upgrade head` → 원천 dry-run → 레시피/식품 적재 → 적재 검증 → 계산 영양 매핑 → 매핑 검증을 수행한다. 각 단계는 별도 트랜잭션이므로 중간 실패 시 결과를 확인한 뒤 재시도한다. DB를 자동 복원·삭제하지 않는다. 원천 파일은 읽기 전용으로 연결하며 API 컨테이너를 재시작하지 않고 서비스 포트를 추가하지 않는다. 적재 컨테이너만 `seed.compose.yaml`로 메모리 상한 1,536MiB·healthcheck 비활성화를 적용한다. 기존 API·DB 메모리 제한은 그대로다.

복지·급식소·제철·RAG는 이 패키지에 포함하지 않는다. 이들 수집본과 임베딩 실행 환경을 준비한 다음 별도 적재한다. 해당 파일이 없는 상태에서 전체 `daily_refresh --skip-refresh --verify`를 실행하면 미존재 파일 단계가 실패하므로 두 원천 초기 적재와 구분한다. 새 서버의 실제 적재는 서버 명령의 출력·검증 결과를 확인한 뒤 완료로 기록한다.

## GitHub 설정과 활성화

첫 수동 배포와 앱의 서버 연결은 확인했다. 2026-11-19 자동 배포 도입을 결정했으며, 아래 인증·워크플로 검증을 끝내기 전에는 활성화 완료로 기록하지 않는다. 이 워크플로는 백엔드를 배포한다. Flutter APK 배포와 데이터 정기 적재 예약은 별도다.

첫 서버 구동 후, 서버의 패키지 압축을 푼 폴더에서 공개키를 등록한다.

```bash
bash deploy/authorize-key.sh github-actions.pub
```

이후 작업 PC에서 실행한다. `gh`는 저장소 설정 권한이 있는 계정으로 로그인되어 있어야 한다. 명령은 키 값을 출력하지 않고 development 환경의 GitHub Secrets에 저장한다.

```powershell
python deploy/configure-github.py --configure
```

`--configure`는 `VALUEFLOW_CD_ENABLED=false`로 저장한다. 전용 개인키는 `development` 환경 Secret으로 전송되므로 해당 키와 GitHub 저장소에 대한 등록 승인을 받은 뒤 실행한다. 서버 비밀번호·실행 `.env`는 전송하지 않는다. `--directory`·`--host`·`--port`·`--user`로 대상 설정을 바꿀 수 있다.

워크플로와 배포 스크립트를 PR로 올리고 검토·병합한 뒤, `main`의 첫 실행에서 `checks`와 `publish`가 성공했는지 확인한다. 이때 `deploy`는 비활성 상태라 건너뛴다. 서버에 공개키를 등록한 다음 아래 순서로 활성화·첫 자동 배포를 확인한다.

```powershell
python deploy/configure-github.py --enable
gh workflow run backend-ci.yml --repo dlwlssud123/SoftwareProject --ref main
gh run list --repo dlwlssud123/SoftwareProject --workflow backend-ci.yml --branch main --limit 3
```

`--enable`은 전용 키로 서버에 접속해서 기존 API의 health와 배포 기록을 확인한 뒤에만 자동 배포를 켠다. 첫 Actions 실행에서는 GitHub runner에서 SSH 접속까지 성공하는지 추가로 검증한다. `gh run watch RUN_ID --repo dlwlssud123/SoftwareProject --exit-status`로 끝까지 확인하고, `deploy` 성공과 서버 `.state/current-release`의 커밋이 해당 실행의 SHA와 일치하는지 확인한다. 이후 앱에서 로그인·추천·저장을 다시 점검한다.

자동 배포를 중지하려면 아래 명령으로 다음 실행을 차단한다. 이미 진행 중인 배포를 취소하거나 현재 서버 버전을 변경하는 명령은 아니다.

```powershell
gh variable set VALUEFLOW_CD_ENABLED --repo dlwlssud123/SoftwareProject --body false
```

| 위치 | 이름 | 역할 |
| --- | --- | --- |
| GitHub development Secrets | `VALUEFLOW_SSH_KEY` | 배포 전용 개인키 |
| GitHub development Secrets | `VALUEFLOW_KNOWN_HOSTS` | 사전에 신뢰한 서버 호스트키 |
| Repository Variables | `VALUEFLOW_DEPLOY_HOST/PORT/USER/DIR` | 배포 대상 |
| Repository Variables | `VALUEFLOW_CD_ENABLED` | 첫 검증 후 `true`로 활성화 |
| 서버 `.env` | `DATABASE_URL`, `POSTGRES_*`, `KAKAO_APP_ID` 등 | 실행 설정, GitHub로 전송하지 않음 |

`development` 환경에는 `main` 브랜치 배포 정책을 등록한다. 현재 구성은 이 정책 하나만 허용하여 다른 브랜치·태그의 작업이 배포 키를 받지 않게 한다. 이미 추가 승인·대기 보호 규칙이 있는 환경은 설정 도구가 덮어쓰지 않고 중단한다. 기존에 별도 등록한 허용 브랜치 정책은 자동 삭제하지 않으므로 환경 정책 목록을 확인한다.

호스트키 검사를 끄지 않는다. 기존 `known_hosts`에 서버가 없으면 담당자가 알려준 지문과 대조하고 서버에 직접 접속해 신뢰한 후 설정한다. 연결 키는 기존 SSH 키와 별개이며 삭제하려면 서버의 `authorized_keys`에서 `valueflow-actions` 항목만 제거하고 GitHub의 해당 Secret을 폐기한다.

## 앱 연결과 접속 확인

음식 사진·AI 대화를 배포할 때는 해당 API가 있는 이미지와 `20261124_02`까지의 마이그레이션이 필요하다. 서버 `.env`에만 `NVIDIA_API_KEY`를 보관하고 시험용 사용 조건을 확인한 뒤 `NVIDIA_AI_ENABLED=true`를 설정한다. Compose가 이 값들과 모델·타임아웃·일일 한도를 API 컨테이너에 전달한다. 기본값은 비활성이며 기존 키 없는 배포는 그대로 유지한다. 키를 GitHub 변수·APK·배포 아카이브에 넣지 않는다.

방화벽·도메인 변경 전에는 작업 PC에서 터널을 열어 확인한다.

```powershell
ssh -N -p 1190 -L 18081:127.0.0.1:18081 kapje90@210.90.113.81
```

브라우저는 `http://127.0.0.1:18081/docs`, Android 에뮬레이터는 `API_BASE_URL=http://10.0.2.2:18081`을 사용한다. 다른 PC·실제 휴대폰에서 접근하려면 기업에서 허용한 HTTPS 주소를 설정하고 APK를 다시 빌드한다. 카카오 로그인 callback은 앱의 Native 키·패키지·서명 키 해시 설정을 유지한다.

## 로컬 검증과 운영 기록

```bash
for script in deploy/*.sh; do bash -n "$script"; done
docker build -f src/backend/Dockerfile --label org.opencontainers.image.revision="$(git rev-parse HEAD)" -t valueflow-backend:ci .
bash deploy/test-release.sh valueflow-backend:ci "$(git rev-parse HEAD)"
```

`test-release.sh`는 임시 프로젝트에서 첫 배포·DB 백업·잘못된 커밋 이미지 거부·불량 API의 이전 이미지 복귀·DB 행 유지를 검증한다. 이 테스트가 만든 고유 이름의 컨테이너와 볼륨만 정리한다. 실제 배포의 마지막 기록은 `.state/current-release`, 백업은 `backups/*.dump`에서 확인한다. 백업과 배포 아카이브 정리는 디스크 상황과 복구 보관 기간을 정한 뒤 진행한다.

현재 로컬 검증과 실제 기업 서버·GitHub Actions 검증은 구분한다. SSH 키 등록과 첫 서버 구동 전에는 자동 배포가 연결됐다고 판정하지 않는다.

구성 근거는 [GitHub 이미지 게시](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images), [공유 runner 보안 지침](https://docs.github.com/en/actions/reference/security/secure-use), [uv Docker 구성](https://docs.astral.sh/uv/guides/integration/docker/)이다.

## 선택적 KURE 임베딩 서비스

기본 배포는 RAG 모델을 기동하지 않는다. 실제 자원과 원천 인덱스 확인 후 `rag` 프로필의 embedding 서비스를 별도 이미지로 준비하며 호스트 포트를 열지 않는다. 기존 API 자동배포는 해당 이미지를 빌드·게시하지 않는다. 환경 변수·토큰·모델 캐시·준비 확인·정기 배치와의 메모리 조정은 [복지 RAG 안내](../docs/data/welfare_rag_api.md)를 따른다.

## 공공데이터 정기 갱신 예약 실행 (4번 작업)

서버 배포 디렉토리의 `refresh.sh`는 일회성 API 컨테이너를 띄워 DB 잠금과 데이터 볼륨 마운트 하에 안전하게 `daily_refresh.py`를 실행한다.

- **복지 매일 갱신**: 화~일 03:00 KST (`--welfare-only --verify`)
- **레시피·영양 주간 갱신**: 월 03:00 KST (`--verify`)
- **예약 방식**:
  1. **GitHub Actions 스케줄러 (`.github/workflows/data-refresh.yml`)**: 매일 18:00 UTC (03:00 KST)에 기업 서버로 SSH 연결해 `refresh.sh`를 자동 호출하며, `workflow_dispatch`를 통한 즉시 수동 실행 및 상태 확인도 지원한다.
  2. **서버 crontab 등록** (KST 시간대 서버 기준):
     ```cron
     0 3 * * 1 /home/kapje90/Documents/ValueFlow/refresh.sh --verify >> /home/kapje90/Documents/ValueFlow/data/processed/cron.log 2>&1
     0 3 * * 0,2-6 /home/kapje90/Documents/ValueFlow/refresh.sh --welfare-only --verify >> /home/kapje90/Documents/ValueFlow/data/processed/cron.log 2>&1
     ```
- 장애 시 스냅샷 롤백과 DB 트랜잭션 롤백으로 기존 정상 데이터가 안전하게 유지되며, 최근 성공 시각과 실패 단계는 `job_runs` 테이블 및 관리자 웹 **[수집 작업]** 화면에서 확인할 수 있다.

