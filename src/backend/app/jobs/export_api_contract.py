"""Export runtime OpenAPI and separate planned DTOs without adding fake routes."""

import argparse
import json
from pathlib import Path

from pydantic.json_schema import models_json_schema

from app.schemas.catalog import (
    Page,
    RecipeRecommendationRequest,
    RecipeRecommendationResponse,
    RecipeRecord,
    WelfareDetailResponse,
    WelfareListQuery,
    WelfareListResponse,
    WelfareRecommendationRequest,
    WelfareRecommendationResponse,
    WelfareRecord,
)
from app.schemas.common import ErrorResponse, ResponseMeta, SuccessResponse

ROOT = Path(__file__).resolve().parents[4]
PLANNED = (
    (
        "/api/v1/meal/recommendations",
        "post",
        RecipeRecommendationRequest,
        RecipeRecommendationResponse,
    ),
    ("/api/v1/welfare", "get", WelfareListQuery, WelfareListResponse),
    ("/api/v1/welfare/{service_id}", "get", None, WelfareDetailResponse),
    (
        "/api/v1/welfare/recommendations",
        "post",
        WelfareRecommendationRequest,
        WelfareRecommendationResponse,
    ),
)


def handoff_schema() -> dict:
    models = {ErrorResponse}
    for _, _, request, response in PLANNED:
        models.add(response)
        if request:
            models.add(request)
    refs, schemas = models_json_schema(
        [(m, "validation") for m in sorted(models, key=lambda m: m.__name__)],
        ref_template="#/components/schemas/{model}",
    )
    paths = {}
    for path, method, request, response in PLANNED:
        operation = {
            "x-implementation-status": "planned",
            "description": "DTO 인계 계약. 실행 서버에는 등록되지 않아 현재 404를 반환한다.",
            "security": [],
            "parameters": [],
            "responses": {
                "200": {
                    "description": "계약 표본; 실제 조회 연결은 후속 작업",
                    "content": {
                        "application/json": {"schema": refs[(response, "validation")]}
                    },
                },
                **{
                    str(code): {
                        "description": "공통 오류",
                        "content": {
                            "application/json": {
                                "schema": refs[(ErrorResponse, "validation")]
                            }
                        },
                    }
                    for code in (404, 422, 503)
                },
            },
        }
        if request and method == "post":
            operation["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {"schema": refs[(request, "validation")]}
                },
            }
        elif request:
            query = request.model_json_schema(
                ref_template="#/components/schemas/{model}"
            )
            operation["parameters"] = [
                {
                    "name": name,
                    "in": "query",
                    "required": name in query.get("required", []),
                    "schema": schema,
                    "style": "form",
                    "explode": True,
                }
                for name, schema in query["properties"].items()
            ]
        if "{" in path:
            name = path.split("{")[1].split("}")[0]
            operation["parameters"].append(
                {
                    "name": name,
                    "in": "path",
                    "required": True,
                    "schema": {
                        "type": "string",
                        "pattern": "^[0-9]+$" if name == "recipe_id" else "^WLF[0-9]+$",
                    },
                }
            )
        paths[path] = {method: operation}
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "ValueFlow 예정 카탈로그 API 계약",
            "version": "2026-11-07",
            "description": "앱·관리자 DTO 선행 개발용. 실제 서버 명세는 openapi.json.",
        },
        "paths": paths,
        "components": {"schemas": schemas["$defs"]},
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs/설계")
    parser.add_argument(
        "--welfare-snapshot",
        type=Path,
        help="실제 수집 XML 스냅샷에서 응답 예제도 생성",
    )
    args = parser.parse_args(argv)
    from app.main import create_app

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, schema in (
        ("openapi.json", create_app().openapi()),
        ("catalog.openapi.json", handoff_schema()),
    ):
        (args.output_dir / name).write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if args.welfare_snapshot:
        examples = build_examples(args.welfare_snapshot)
        (args.output_dir / "api_examples.json").write_text(
            json.dumps(examples, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print("Runtime and planned API contracts exported")
    return 0


def build_examples(welfare_snapshot: Path) -> dict:
    from agetech_data.textutil import sha256_json
    from agetech_data.welfare.central_snapshot import aware_time, normalize_item

    recipe_samples = json.loads(
        (ROOT / "docs/data/samples/recipe_api_sample.json").read_text(encoding="utf-8")
    )
    recipe = RecipeRecord.model_validate(recipe_samples["samples"][0]["recipe"])
    snapshot = json.loads(welfare_snapshot.read_text(encoding="utf-8"))
    meta = snapshot["meta"]
    row = normalize_item(
        next(i for i in snapshot["items"] if i.get("detail_xml")),
        aware_time(meta["fetched_at"]),
    )
    welfare = WelfareRecord(
        service_id=row["source_id"],
        scope=row["normalized"]["scope"],
        **{
            key: row[key]
            for key in (
                "title",
                "summary",
                "target_text",
                "selection_text",
                "benefit_text",
                "criteria_year",
                "application_status",
                "detail_state",
                "quality_status",
                "issues",
            )
        },
        application=[
            {
                "method": item.get("servSeDetailNm", ""),
                "description": item.get("servSeDetailLink", ""),
            }
            for item in row["application"]
        ],
        contacts=[
            {
                "name": item.get("servSeDetailNm", ""),
                "contact": item.get("servSeDetailLink", ""),
            }
            for item in row["contacts"]
        ],
        source={
            "provider": meta["provider"],
            "source_id": row["source_id"],
            "source_url": row["source_url"],
            "checked_at": row["checked_at"],
            "detail_checked_at": row["checked_at"],
            "raw_sha256": sha256_json(row["raw"]),
        },
    )
    example_meta = ResponseMeta(request_id="00000000-0000-4000-8000-000000000001")

    def envelope(data):
        return SuccessResponse(data=data, meta=example_meta).model_dump(
            mode="json", by_alias=True
        )

    return {
        "description": "실제 공개 원천의 DTO 표본. 서버 조회/추천 결과가 아니며 DB 판본은 미연결(null). request_id는 예시 값.",
        "requests": {
            "recipe_list": {
                "method": "GET",
                "path": "/api/v1/recipes?limit=20&offset=0&exclude_allergens=알류&exclude_allergens=우유",
            },
            "recipe_detail": {
                "method": "GET",
                "path": f"/api/v1/recipes/{recipe.recipe_id}",
            },
            "recipe_recommendation": {
                "method": "POST",
                "path": "/api/v1/meal/recommendations",
                "body": RecipeRecommendationRequest(
                    meal_time="lunch", exclude_allergens=["알류", "우유"]
                ).model_dump(),
            },
            "welfare_list": {
                "method": "GET",
                "path": "/api/v1/welfare?limit=20&offset=0&scope=central_nationwide",
            },
            "welfare_detail": {
                "method": "GET",
                "path": f"/api/v1/welfare/{welfare.service_id}",
            },
            "welfare_recommendation": {
                "method": "POST",
                "path": "/api/v1/welfare/recommendations",
                "body": WelfareRecommendationRequest(
                    age=70, region="대구", district="남구", lives_alone=True
                ).model_dump(),
            },
        },
        "responses": {
            "recipe_detail": envelope(recipe),
            "welfare_detail": envelope(welfare),
            "recipe_list": envelope(Page(items=[recipe], limit=20, offset=0, total=1)),
            "welfare_list": envelope(
                Page(items=[welfare], limit=20, offset=0, total=1)
            ),
            "empty_list": envelope(Page(items=[], limit=20, offset=0, total=0)),
            "validation_error": ErrorResponse.model_validate(
                {
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "입력값을 확인해 주세요.",
                        "fields": [{"field": "body.age", "reason": "less_than_equal"}],
                        "retryable": False,
                    },
                    "meta": example_meta.model_dump(),
                }
            ).model_dump(mode="json"),
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
