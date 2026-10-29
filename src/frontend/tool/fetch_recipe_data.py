"""Fetch official COOKRCP01 data once for the offline presentation app."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from api_config import load_api_key


PROJECT = Path(__file__).resolve().parents[1]
DOCUMENTATION = "https://www.foodsafetykorea.go.kr/api/newDatasetDetail.do?svc_no=COOKRCP01"


def download(url):
    request = Request(url, headers={"User-Agent": "ValueFlow-data-import/1.0"})
    with urlopen(request, timeout=30) as response:
        return response.read(), response.headers.get_content_type()


def validate_rows(payload):
    service = payload.get("COOKRCP01", payload)
    result = service.get("RESULT", {})
    if result.get("CODE") != "INFO-000":
        raise ValueError("API가 정상 데이터를 반환하지 않았습니다. 인증키와 호출 한도를 확인해 주세요.")
    rows = service.get("row")
    if not isinstance(rows, list) or not rows:
        raise ValueError("API 응답에 레시피가 없습니다. 기존 JSON은 유지합니다.")
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("레시피 응답 형식이 올바르지 않습니다.")
        recipe_id = row.get("RCP_SEQ", "")
        if not isinstance(recipe_id, str) or not re.fullmatch(r"[0-9]+", recipe_id):
            raise ValueError("레시피 ID가 올바르지 않습니다.")
        if recipe_id in seen:
            raise ValueError("레시피 ID가 중복되었습니다.")
        seen.add(recipe_id)
        for field in ("RCP_NM", "RCP_PARTS_DTLS", "RCP_WAY2"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError("레시피의 이름, 재료 또는 조리 방법이 누락되었습니다.")
    return rows, service.get("total_count")


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=5, help="1~1000건. 인증키 없이 최대 5건.")
    args = parser.parse_args()
    api_key = load_api_key("FOODSAFETY_API_KEY")
    if not 1 <= args.limit <= 1000:
        parser.error("--limit은 1~1000 사이로 지정해 주세요.")
    if not api_key and args.limit > 5:
        parser.error("5건을 초과하려면 FOODSAFETY_API_KEY 환경변수를 설정해 주세요.")
    credential = quote(api_key, safe="") if api_key else "sample"
    url = f"https://openapi.foodsafetykorea.go.kr/api/{credential}/COOKRCP01/json/1/{args.limit}"
    try:
        content, _ = download(url)
        payload = json.loads(content.decode("utf-8-sig"))
        if not isinstance(payload, dict):
            raise ValueError("API 응답 형식이 올바르지 않습니다.")
        rows, total = validate_rows(payload)
        image_dir = PROJECT / "assets/images"
        image_dir.mkdir(parents=True, exist_ok=True)
        build_dir = PROJECT / "build"
        build_dir.mkdir(exist_ok=True)
        # Publish the new recipe cache only after all missing images are ready.
        with tempfile.TemporaryDirectory(prefix="recipe-import-", dir=build_dir) as temporary:
            staged = []
            for row in rows:
                image_path = image_dir / f"{row['RCP_SEQ']}.png"
                if image_path.is_file():
                    continue
                image_url = row.get("ATT_FILE_NO_MAIN") or row.get("ATT_FILE_NO_MK") or ""
                parts = urlsplit(image_url)
                if parts.scheme not in ("http", "https") or parts.hostname not in (
                    "www.foodsafetykorea.go.kr", "foodsafetykorea.go.kr"
                ):
                    raise ValueError("공식 레시피 이미지 주소가 누락되었거나 올바르지 않습니다.")
                image_url = urlunsplit(parts._replace(scheme="https"))
                image_bytes, content_type = download(image_url)
                if not image_bytes or not content_type.startswith("image/"):
                    raise ValueError("레시피 이미지 다운로드에 실패했습니다.")
                staged_path = Path(temporary) / image_path.name
                staged_path.write_bytes(image_bytes)
                staged.append((staged_path, image_path))
            for staged_path, image_path in staged:
                staged_path.replace(image_path)
        save_json(PROJECT / "assets/data/recipes.json", rows)
        save_json(PROJECT / "assets/data/recipe_source.json", {
            "provider": "식품안전나라",
            "service": "COOKRCP01",
            "documentationUrl": DOCUMENTATION,
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "mode": "authenticated" if api_key else "public_sample",
            "count": len(rows),
            "totalCount": total,
        })
    except HTTPError as error:
        parser.exit(1, f"API 또는 이미지 HTTP 오류({error.code}). 기존 레시피 JSON을 확인해 주세요.\n")
    except (URLError, TimeoutError):
        parser.exit(1, "네트워크 연결에 실패했습니다. 기존 레시피 JSON은 유지합니다.\n")
    except (ValueError, OSError):
        # Never print request URLs or upstream error text containing credentials.
        parser.exit(1, "응답 데이터 검증 또는 파일 저장에 실패했습니다. 기존 레시피 JSON을 확인해 주세요.\n")
    print(f"식품안전나라 API에서 {len(rows)}건 수집 → assets/data/recipes.json")
    print("추천 규칙은 lib/data/demo_repository.dart에서 관리합니다.")


if __name__ == "__main__":
    main()
