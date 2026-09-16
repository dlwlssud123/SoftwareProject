# ValueFlow - 3-2 소프트웨어 프로젝트 (Software Project)

> **팀명**: ValueFlow  
> **주제**: 기업 연계 현장 실습 신청 예정

---

## 팀원 소개 및 역할 분담 (Team Members & Roles)

| 이름 (학번) | 구분 / 직무 | 담당 역할 및 업무 상세 |
| :--- | :--- | :--- |
| **이진녕** (22212025) | **조장** / Tech Lead & Backend | • 기술 리딩 및 시스템 총괄<br>• 백엔드 코어 기능 개발<br>• 배포 및 인프라 환경 구축 |
| **조의현** (22212096) | **팀원** / PM & Planning | • 프로젝트 총괄 매니징 및 일정/리소스 관리<br>• 요구사항 명세서 정의<br>• 중간/최종 산출물 검수 |
| **김찬형** (22313524) | **팀원** / Frontend | • 프론트엔드 코어 UI/UX 설계 및 공통 컴포넌트 개발<br>• 클라이언트 상태 관리 및 백엔드 API 연동 |
| **최재영** (21622137) | **팀원** / Data & AI | • 데이터 수집/정제 및 ETL 파이프라인 구축<br>• 데이터 분석<br>• 분석 데이터 가공, 서빙 API 및 시각화 데이터 지원 |
| **김민찬** (22211993) | **팀원** / Data & Docs | • 데이터 수집 및 정제 보조<br>• 데이터 시각화 및 검증<br>• 개발 문서화 관리 |

---

## 🛠️ 기술 스택 (Tech Stack)

### Frontend

### Backend & AI

### DevOps & Tools

---

## 프로젝트 구조 (Directory Structure)

```text
3-2SWProject/
├── data/                       # 데이터 관리 디렉토리 (.gitignore 적용)
│   ├── raw/                    # 원천 원본 데이터셋
│   └── processed/              # 전처리 및 가공된 데이터셋
├── docs/                       # 프로젝트 관련 문서
│   ├── images/                 # README 및 문서용 이미지/다이어그램
│   ├── 주간보고서(양식).hwp
│   └── 프로젝트 수행계획서(양식).hwp
├── src/                        # 애플리케이션 소스 코드
│   ├── frontend/               # 프론트엔드 코드베이스
│   ├── backend/                # 백엔드 API & 서버 코드베이스
│   ├── ai/                     # AI / 머신러닝 모델 및 파이프라인
│   └── utils/                  # 공통 유틸리티 및 헬퍼 함수
├── tests/                      # 단위 테스트 및 통합 테스트
├── .gitignore                  # Git 추적 제외 설정
└── README.md                   # 프로젝트 안내 및 협업 가이드
```

---

##  시작 가이드 (Getting Started)

### 1. 사전 요구사항 (Prerequisites)

### 2. 저장소 클론 (Clone Repository)
```bash
git clone https://github.com/dlwlssud123/SoftwareProject.git
cd SoftwareProject
```

### 3. 환경 설정 (Environment Variables)
- 프로젝트 루트 또는 각 서브 디렉토리에 `.env` 파일을 생성하고 필요한 환경변수를 설정합니다.
```bash
# 예시: .env.example을 복사하여 .env 생성
cp .env.example .env
```

---

##  협업 가이드 (Collaboration Rules)

###  Git Branch 전략 (GitHub Flow 기반)
- `main`: 배포 및 최종 제출 가능한 안정적인 상태 유지
- `develop`: 개발 통합 브랜치 (기능 병합용)
- `feature/<기능명>`: 새로운 기능 개발 (예: `feature/login-ui`, `feature/data-pipeline`)
- `fix/<버그명>`: 버그 수정 (예: `fix/api-cors-error`)
- `docs/<문서명>`: 문서 추가 및 수정 (예: `docs/readme-update`)

###  Commit Message 컨벤션
Commit 메시지는 다음 형식을 준수합니다: `타입: 작업 내용 요약`

| 타입 | 설명 |
| :--- | :--- |
| `feat` | 새로운 기능 추가 |
| `fix` | 버그 수정 |
| `docs` | 문서 수정 (README, 보고서 등) |
| `style` | 코드 포맷팅, 세미콜론 누락 수정 (코드 동작 변경 없음) |
| `refactor` | 코드 리팩토링 |
| `test` | 테스트 코드 추가 및 수정 |
| `chore` | 빌드 업무, 패키지 매니저 설정, 기타 변경 사항 |

**예시**:
```bash
git commit -m "feat: 카카오 소셜 로그인 API 연동"
git commit -m "fix: 회원가입 시 이메일 유효성 검사 오류 수정"
```

###  Pull Request (PR) 규칙
1. 작업 완료 후 본인의 `feature/*` 브랜치에서 `develop` (또는 `main`) 브랜치로 PR을 생성합니다.
2. 최소 1명 이상의 팀원 리뷰 및 승인(Approve) 후 Merge를 진행합니다.
3. PR 템플릿에 작업 내용, 스크린샷, 테스트 결과를 상세히 기재합니다.
