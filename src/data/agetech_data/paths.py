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

# 가공 결과(gitignore 대상, 명령으로 재생성)
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
RECIPES_VALIDATED = PROCESSED_DIR / "recipes_validated.json"

# 커밋하는 보고서
REPORTS_DIR = REPO_ROOT / "docs" / "data"
RECIPE_QUALITY_REPORT = REPORTS_DIR / "recipe_quality_report.md"

# 식약처 식품영양성분DB (공공데이터포털 FoodNtrCpntDbInfo03) 수집 원본 — gitignore 대상
NUTRITION_RAW_DIR = REPO_ROOT / "data" / "raw" / "nutrition"
NUTRITION_RAW = NUTRITION_RAW_DIR / "foodntr_v03_representative.json"
