"""레포 내 기본 입출력 경로.

코드·데이터 위치가 팀 합의로 바뀌면 이 파일(과 pyproject.toml 의 module-root)만 고친다.
모든 CLI 는 여기 값을 기본값으로만 쓰고, 인자로 덮어쓸 수 있다.
"""

from __future__ import annotations

from pathlib import Path

# src/data/agetech_data/paths.py → 레포 루트
REPO_ROOT = Path(__file__).resolve().parents[3]

# 원본: 현재는 앱 자산 폴더의 수집 결과를 읽기만 한다 (src/frontend 는 수정 금지).
FRONTEND_DATA_DIR = REPO_ROOT / "src" / "frontend" / "assets" / "data"
RECIPES_RAW = FRONTEND_DATA_DIR / "recipes.json"
RECIPES_SOURCE_META = FRONTEND_DATA_DIR / "recipe_source.json"
RECIPE_CORRECTIONS = FRONTEND_DATA_DIR / "recipe_corrections.json"
RECIPES_ALL_RAW = REPO_ROOT / "data" / "raw" / "recipes" / "cookrcp01_all.json"
WELFARE_RAW = REPO_ROOT / "data" / "raw" / "welfare" / "central_all.json"

# 가공 결과(gitignore 대상, 명령으로 재생성)
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
RECIPES_VALIDATED = PROCESSED_DIR / "recipes_validated.json"
RECIPES_CORRECTED = PROCESSED_DIR / "recipes_corrected.json"
RECIPE_CORRECTION_AUDIT = PROCESSED_DIR / "recipe_correction_audit.json"

# 커밋하는 보고서
REPORTS_DIR = REPO_ROOT / "docs" / "data"
RECIPE_QUALITY_REPORT = REPORTS_DIR / "recipe_quality_report.md"
RECIPE_CORRECTION_REPORT = REPORTS_DIR / "recipe_correction_report.md"

# 식약처 식품영양성분DB (공공데이터포털 FoodNtrCpntDbInfo03) 수집 원본 — gitignore 대상
NUTRITION_RAW_DIR = REPO_ROOT / "data" / "raw" / "nutrition"
NUTRITION_RAW = NUTRITION_RAW_DIR / "foodntr_v03_representative.json"

# 갱신 수집 원본(최신본) — gitignore 대상. 판본 스냅샷은 각 폴더의 snapshots/<소스>/ 아래
RECIPES_COLLECTED = REPO_ROOT / "data" / "raw" / "recipes" / "cookrcp01_all.json"
WELFARE_RAW_DIR = REPO_ROOT / "data" / "raw" / "welfare"
WELFARE_CENTRAL_RAW = WELFARE_RAW_DIR / "central_elderly.json"
WELFARE_LOCAL_RAW = WELFARE_RAW_DIR / "local_elderly.json"

# 갱신 상태(관리자 화면·worker 가 읽음)와 실행 기록 — gitignore 대상
REFRESH_STATUS = PROCESSED_DIR / "refresh_status.json"
REFRESH_LOG = PROCESSED_DIR / "refresh_log.jsonl"

# 복지 정제 결과(gitignore)와 지역별 보고서(커밋)
WELFARE_PROCESSED = PROCESSED_DIR / "welfare_elderly.json"
WELFARE_REGIONAL_REPORT = REPORTS_DIR / "welfare_regional_report.md"

# 영양 매핑 가공 결과(gitignore)와 보고서(커밋)
FOODS_PROCESSED = PROCESSED_DIR / "foods_v03.json"
RECIPE_NUTRITION = PROCESSED_DIR / "recipe_ingredient_nutrition.json"
NUTRITION_MAPPING_REPORT = REPORTS_DIR / "nutrition_mapping_report.md"

RECIPES_API = PROCESSED_DIR / "recipes_api.json"
RECIPE_API_SAMPLE = REPORTS_DIR / "samples" / "recipe_api_sample.json"
