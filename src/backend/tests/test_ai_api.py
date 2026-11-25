import base64
from threading import BoundedSemaphore
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from test_auth import guest
from test_foods_api import foods_db  # noqa: F401
from test_nvidia_ai import picture
from test_public_data_import import corrections, snapshot
from test_topic_requests import parallel

from app.api import ai
from app.core.config import get_settings
from app.jobs.import_public_data import apply_import, prepare_import
from app.models import AIUsageBucket, AuthSession, Food, MealLog
from app.schemas.ai import ChatAnswer, FoodInference, IngredientInference
from app.services import nvidia_ai

BASE = "/api/v1/ai"


def ingredient_body():
    return {
        "dish_name": "검증레시피",
        "standard_serving_grams": 250,
        "allow_external_processing": True,
    }


@pytest.fixture
def ingredients_db(ai_db, tmp_path, monkeypatch):
    client, db = ai_db
    source = [
        {
            "FOOD_CD": "R101-008000301-0003",
            "FOOD_NM_KR": "멥쌀, 백미, 생것",
            "AMT_NUM1": "360",
        },
        {"FOOD_CD": "ONION_RAW", "FOOD_NM_KR": "양파, 생것", "AMT_NUM1": "40"},
        {
            "FOOD_CD": "R114-022000000-0000",
            "FOOD_NM_KR": "콩기름",
            "AMT_NUM1": "900",
            "DB_GRP_NM": "가공식품",
        },
        {
            "FOOD_CD": "ONION_DISH",
            "FOOD_NM_KR": "양파볶음",
            "AMT_NUM1": "120",
            "DB_GRP_NM": "음식",
        },
    ]
    rows = [{"DB_GRP_NM": "원재료성", "SERVING_SIZE": "100g", **row} for row in source]
    apply_import(
        db,
        prepare_import(
            "nutrition",
            nutrition_path=snapshot(tmp_path, dataset="nutrition", rows=rows),
        ),
    )
    recipe_path = snapshot(
        tmp_path,
        rows=[
            {
                "RCP_SEQ": "1",
                "RCP_NM": "검증레시피",
                "RCP_PARTS_DTLS": "쌀 100g, 물 200ml",
                "MANUAL01": "1. 끓인다.",
                "RCP_PAT2": "밥",
                "INFO_ENG": "0",
            }
        ],
    )
    apply_import(
        db,
        prepare_import(
            "recipes", recipes_path=recipe_path, corrections_path=corrections(tmp_path)
        ),
    )
    db.commit()
    estimate = Mock(
        return_value=IngredientInference.model_validate(
            {
                "ingredients": [
                    {"name": "쌀", "amount_g": 80},
                    {"name": "양파", "amount_g": 50},
                    {"name": "식용유", "amount_g": 5},
                ]
            }
        )
    )
    monkeypatch.setattr(nvidia_ai, "estimate_ingredients", estimate)
    return client, db, estimate


def test_ingredient_estimate_requires_auth_and_consent(ai_db, monkeypatch):
    client, _ = ai_db
    provider = Mock()
    monkeypatch.setattr(nvidia_ai, "estimate_ingredients", provider)
    read(client.post(BASE + "/food-ingredients", json=ingredient_body()), 401)
    _, headers = guest(client)
    for update_body in (
        {"allow_external_processing": False},
        {"dish_name": "\u0000"},
        {"standard_serving_grams": 9999},
        {"profile": {"age": 70}},
    ):
        read(
            client.post(
                BASE + "/food-ingredients",
                json={**ingredient_body(), **update_body},
                headers=headers,
            ),
            422,
        )
    provider.assert_not_called()


def test_estimated_ingredients_use_recipe_reference_and_db_nutrition_only(
    ingredients_db,
):
    client, db, provider = ingredients_db
    _, headers = guest(client)
    result = read(
        client.post(BASE + "/food-ingredients", json=ingredient_body(), headers=headers)
    )
    assert result["reference_recipe"]["recipe_id"] == "1"
    assert result["reference_recipe"]["revision_id"]
    provider.assert_called_once_with(
        "검증레시피",
        250,
        {"name": "검증레시피", "ingredients_text": "쌀 100g, 물 200ml"},
    )
    items = result["ingredients"]
    assert [
        item["matches"][0]["food"]["nutrients"]["energy_kcal"] for item in items
    ] == [360, 40, 900]
    assert all(item["matches"][0]["match_basis"] == "name" for item in items)
    assert all(
        item["matches"][0]["food"]["nutrients"]["protein_g"] is None for item in items
    )
    assert db.scalar(select(func.count()).select_from(MealLog)) == 0
    portions = [
        {
            "food_id": item["matches"][0]["food"]["food_id"],
            "revision_id": item["matches"][0]["food"]["source"]["revision_id"],
            "amount": item["amount_g"],
            "unit": "g",
            "amount_is_estimate": True,
        }
        for item in items
    ]
    calculation = read(
        client.post("/api/v1/nutrition/calculate", json={"items": portions})
    )
    assert calculation["total"]["nutrients"]["energy_kcal"] == 353
    assert all(item["amount_is_estimate"] for item in calculation["items"])


def test_unmatched_ingredient_remains_unresolved_and_water_is_explicit(ingredients_db):
    client, db, provider = ingredients_db
    provider.return_value = IngredientInference.model_validate(
        {
            "ingredients": [
                {"name": "등록되지않은특수식재료XYZ", "amount_g": 10},
                {"name": "물", "amount_g": 100},
            ]
        }
    )
    _, headers = guest(client)
    result = read(
        client.post(
            BASE + "/food-ingredients",
            json={**ingredient_body(), "dish_name": "없는레시피XYZ"},
            headers=headers,
        )
    )
    assert result["reference_recipe"] is None
    assert result["ingredients"][0]["matches"] == []
    assert result["ingredients"][0]["is_water"] is False
    assert result["ingredients"][1]["is_water"] is True
    assert result["ingredients"][1]["matches"] == []
    assert db.scalar(select(func.count()).select_from(MealLog)) == 0


def test_revoked_session_discards_ingredient_result(ingredients_db):
    from datetime import UTC, datetime
    from uuid import UUID

    client, db, provider = ingredients_db
    identity, headers = guest(client)
    original = provider.return_value

    def revoke(*_args):
        db.execute(
            update(AuthSession)
            .where(AuthSession.user_id == UUID(identity["user_id"]))
            .values(revoked_at=datetime.now(UTC))
        )
        db.commit()
        return original

    provider.side_effect = revoke
    read(
        client.post(
            BASE + "/food-ingredients", json=ingredient_body(), headers=headers
        ),
        401,
    )


@pytest.fixture
def ai_db(request, monkeypatch):
    database = request.getfixturevalue("foods_db")
    monkeypatch.setenv("NVIDIA_AI_ENABLED", "true")
    monkeypatch.setenv("NVIDIA_API_KEY", "fixture")
    get_settings.cache_clear()
    # API tests must never fall through to the real key or an external endpoint.
    monkeypatch.setattr(
        nvidia_ai,
        "build_opener",
        Mock(side_effect=AssertionError("External requests forbidden in tests")),
    )
    monkeypatch.setattr(ai, "_slots", BoundedSemaphore(2))
    yield database[0], database[1]
    get_settings.cache_clear()


def read(response, status=200):
    assert response.status_code == status, response.text
    assert response.headers["Cache-Control"] == "no-store"
    return response.json()["error" if status >= 400 else "data"]


def chat_payload():
    return {
        "message": "식단 추천 사용법을 알려주세요.",
        "allow_external_processing": True,
    }


def test_ai_requires_authentication_and_explicit_processing_consent(ai_db, monkeypatch):
    client, _ = ai_db
    call = Mock()
    monkeypatch.setattr(nvidia_ai, "chat", call)
    read(client.post(BASE + "/chat", json=chat_payload()), 401)
    _, headers = guest(client)
    read(
        client.post(
            BASE + "/chat",
            json={**chat_payload(), "allow_external_processing": False},
            headers=headers,
        ),
        422,
    )
    read(
        client.post(
            BASE + "/chat", json={**chat_payload(), "user_id": "other"}, headers=headers
        ),
        422,
    )
    call.assert_not_called()


def test_chat_uses_real_provider_interface_without_saving_prompt(ai_db, monkeypatch):
    client, db = ai_db
    _, headers = guest(client)
    call = Mock(
        return_value=ChatAnswer(answer="식단추천에서 식생활 서비스를 눌러주세요.")
    )
    monkeypatch.setattr(nvidia_ai, "chat", call)
    result = read(client.post(BASE + "/chat", json=chat_payload(), headers=headers))
    assert result["provider"] == "NVIDIA" and result["answer"]
    call.assert_called_once_with(chat_payload()["message"])
    assert db.scalar(select(func.count()).select_from(AIUsageBucket)) == 2
    assert db.scalar(select(func.count()).select_from(MealLog)) == 0


def test_disabled_ai_returns_actionable_error_without_provider_call(ai_db, monkeypatch):
    client, db = ai_db
    _, headers = guest(client)
    monkeypatch.setenv("NVIDIA_AI_ENABLED", "false")
    get_settings.cache_clear()
    call = Mock()
    monkeypatch.setattr(nvidia_ai, "chat", call)
    assert (
        read(client.post(BASE + "/chat", json=chat_payload(), headers=headers), 503)[
            "code"
        ]
        == "AI_DISABLED"
    )
    call.assert_not_called()
    assert db.scalar(select(func.count()).select_from(AIUsageBucket)) == 0


def test_photo_defaults_to_source_serving_or_explicit_ai_estimate(ai_db, monkeypatch):
    client, db = ai_db
    _, headers = guest(client)
    inference = FoodInference.model_validate(
        {
            "is_food": True,
            "foods": [
                {"name": "쌀밥", "confidence": "high", "standard_serving_grams": 150},
                {"name": "우유", "confidence": "medium", "standard_serving_grams": 250},
            ],
        }
    )
    call = Mock(return_value=inference)
    monkeypatch.setattr(nvidia_ai, "recognize", call)
    body = {
        "image_base64": base64.b64encode(picture()).decode(),
        "allow_external_processing": True,
    }
    result = read(client.post(BASE + "/food-photo", json=body, headers=headers))
    rice, milk = result["foods"]
    assert rice["matches"][0]["serving"]["amount"] == 200
    assert rice["matches"][0]["serving"]["basis"] == "source_serving"
    assert milk["matches"][0]["serving"]["amount"] == 250
    assert milk["matches"][0]["serving"]["basis"] == "ai_estimate"
    assert rice["matches"][0]["food"]["nutrients"]["energy_kcal"] == 150
    assert rice["matches"][0]["match_basis"] == "name"
    assert call.call_args.args[0].startswith(b"\xff\xd8")
    assert db.scalar(select(func.count()).select_from(MealLog)) == 0


@pytest.fixture
def similar_db(ai_db, tmp_path):
    client, db = ai_db
    rows = [
        {"FOOD_CD": "FRIED_EGG", "FOOD_NM_KR": "볶음밥_달걀"},
        {"FOOD_CD": "RAW", "FOOD_NM_KR": "새우볶음밥재료", "DB_GRP_NM": "원재료성"},
        {"FOOD_CD": "BAD_BASIS", "FOOD_NM_KR": "볶음밥_새우", "SERVING_SIZE": "?"},
        {"FOOD_CD": "NO_ENERGY", "FOOD_NM_KR": "볶음밥_새우", "AMT_NUM1": ""},
    ]
    rows += [
        {"FOOD_CD": f"FRIED_{index}", "FOOD_NM_KR": f"볶음밥_채소{index}"}
        for index in range(7)
    ]
    source = [
        {
            "DB_GRP_NM": "음식",
            "SERVING_SIZE": "100g",
            "AMT_NUM1": "180",
            "AMT_NUM3": "5",
            "AMT_NUM13": "0",
            **row,
        }
        for row in rows
    ]
    path = snapshot(tmp_path, dataset="nutrition", rows=source)
    apply_import(db, prepare_import("nutrition", nutrition_path=path))
    db.commit()
    return client, db


def recognized_foods(client, monkeypatch, names):
    _, headers = guest(client)
    monkeypatch.setattr(
        nvidia_ai,
        "recognize",
        lambda _: FoodInference.model_validate(
            {
                "is_food": True,
                "foods": [
                    {
                        "name": name,
                        "confidence": "medium",
                        "standard_serving_grams": 200,
                    }
                    for name in names
                ],
            }
        ),
    )
    return read(
        client.post(
            BASE + "/food-photo",
            headers=headers,
            json={
                "image_base64": base64.b64encode(picture()).decode(),
                "allow_external_processing": True,
            },
        )
    )["foods"]


def test_similar_candidates_use_active_dishes_and_real_source_nutrients(
    similar_db, monkeypatch
):
    client, db = similar_db
    result = recognized_foods(client, monkeypatch, ["계란볶음밥"])[0]
    assert result["name"] == "계란볶음밥"
    match = result["matches"][0]
    assert match["match_basis"] == "similar"
    assert match["food"]["name"] == "볶음밥_달걀"
    assert match["food"]["source"]["food_code"] == "FRIED_EGG"
    assert match["food"]["nutrients"]["energy_kcal"] == 180
    assert match["food"]["nutrients"]["sodium_mg"] == 0
    assert match["food"]["nutrients"]["fat_g"] is None
    assert match["food"]["source"]["revision_id"]
    assert match["serving"]["amount"] == 200
    assert db.scalar(select(func.count()).select_from(MealLog)) == 0


def test_fallback_filters_raw_invalid_missing_energy_and_inactive_rows(
    similar_db, monkeypatch
):
    client, db = similar_db
    egg = db.scalar(select(Food).where(Food.food_code == "FRIED_EGG"))
    egg.active_revision_id = None
    db.commit()
    raw, valid, inactive = recognized_foods(
        client, monkeypatch, ["새우볶음밥", "채소볶음밥", "계란볶음밥"]
    )
    assert raw["matches"] == []
    assert inactive["matches"] == []
    candidates = valid["matches"]
    assert candidates and len(candidates) <= 5
    codes = {item["food"]["source"]["food_code"] for item in candidates}
    assert not codes & {"RAW", "BAD_BASIS", "NO_ENERGY", "FRIED_EGG"}
    assert all(item["match_basis"] == "similar" for item in candidates)


def test_fallback_metadata_is_loaded_once_and_candidates_are_bounded(
    similar_db, monkeypatch
):
    client, _ = similar_db
    index = Mock(wraps=ai._similar_food_index)
    monkeypatch.setattr(ai, "_similar_food_index", index)
    foods = recognized_foods(client, monkeypatch, ["채소볶음밥", "계란볶음밥"])
    assert len(foods[0]["matches"]) == 5
    assert all(0 < len(food["matches"]) <= 5 for food in foods)
    index.assert_called_once()


def test_name_match_does_not_build_fallback_index(ai_db, monkeypatch):
    client, _ = ai_db
    index = Mock(side_effect=AssertionError("Fallback should be lazy"))
    monkeypatch.setattr(ai, "_similar_food_index", index)
    assert recognized_foods(client, monkeypatch, ["쌀밥"])[0]["matches"]
    index.assert_not_called()


def test_partial_name_match_is_also_marked_for_user_confirmation(ai_db, monkeypatch):
    client, _ = ai_db
    matches = recognized_foods(client, monkeypatch, ["밥"])[0]["matches"]
    assert matches[0]["food"]["name"] == "쌀밥"
    assert matches[0]["match_basis"] == "similar"


def test_nonfood_or_unmatched_food_is_not_filled_with_sample_nutrition(
    ai_db, monkeypatch
):
    client, _ = ai_db
    _, headers = guest(client)
    body = {
        "image_base64": base64.b64encode(picture()).decode(),
        "allow_external_processing": True,
    }
    monkeypatch.setattr(
        nvidia_ai, "recognize", lambda _: FoodInference(is_food=False, foods=[])
    )
    assert (
        read(client.post(BASE + "/food-photo", json=body, headers=headers))["foods"]
        == []
    )
    monkeypatch.setattr(
        nvidia_ai,
        "recognize",
        lambda _: FoodInference.model_validate(
            {
                "is_food": True,
                "foods": [
                    {
                        "name": "DB에 없는 음식",
                        "confidence": "low",
                        "standard_serving_grams": 180,
                    }
                ],
            }
        ),
    )
    assert (
        read(client.post(BASE + "/food-photo", json=body, headers=headers))["foods"][0][
            "matches"
        ]
        == []
    )


def test_bad_photo_does_not_consume_daily_budget(ai_db, monkeypatch):
    client, db = ai_db
    _, headers = guest(client)
    call = Mock()
    monkeypatch.setattr(nvidia_ai, "recognize", call)
    body = {
        "image_base64": base64.b64encode(b"not an image" * 5).decode(),
        "allow_external_processing": True,
    }
    read(client.post(BASE + "/food-photo", json=body, headers=headers), 422)
    assert db.scalar(select(func.count()).select_from(AIUsageBucket)) == 0
    call.assert_not_called()


def test_estimated_portion_is_calculated_and_kept_in_saved_meal(ai_db):
    from test_foods_api import choice

    client, _ = ai_db
    _, headers = guest(client)
    item = {**choice(client, "쌀밥", 200), "amount_is_estimate": True}
    preview = read(client.post("/api/v1/nutrition/calculate", json={"items": [item]}))
    assert preview["items"][0]["amount_is_estimate"] is True
    assert preview["total"]["nutrients"]["energy_kcal"] == 300
    saved = read(
        client.post(
            "/api/v1/meals",
            json={"items": [item], "eaten_at": "2026-11-24T12:00:00+09:00"},
            headers={**headers, "Idempotency-Key": str(uuid4())},
        ),
        201,
    )["meal"]
    detail = read(client.get(f"/api/v1/meals/{saved['id']}", headers=headers))
    assert detail["items"][0]["calculation"]["amount_is_estimate"] is True
    assert detail["total"]["nutrients"]["energy_kcal"] == 300


def test_pre_ai_pending_receipt_hash_still_replays(ai_db):
    import hashlib
    import json

    from test_foods_api import choice

    from app.models import MealCreateRequest
    from app.schemas.meal_record import MealCreate

    client, db = ai_db
    _, headers = guest(client)
    body = {"items": [choice(client, "쌀밥")], "eaten_at": "2026-11-24T12:00:00+09:00"}
    key = str(uuid4())
    first = read(
        client.post(
            "/api/v1/meals", json=body, headers={**headers, "Idempotency-Key": key}
        ),
        201,
    )
    old_body = MealCreate.model_validate(body).model_dump(mode="json")
    old_body.pop("analysis_context")
    for item in old_body["items"]:
        del item["amount_is_estimate"]
        del item["origin"]
    old_hash = hashlib.sha256(
        json.dumps(old_body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    receipt = db.scalar(select(MealCreateRequest))
    assert receipt.request_hash == old_hash
    replay = read(
        client.post(
            "/api/v1/meals", json=body, headers={**headers, "Idempotency-Key": key}
        )
    )
    assert replay["replayed"] is True
    assert replay["meal"]["id"] == first["meal"]["id"]


def test_user_quota_is_atomic_with_global_counter(ai_db, monkeypatch):
    client, db = ai_db
    _, headers = guest(client)
    monkeypatch.setenv("AI_DAILY_USER_LIMIT", "1")
    get_settings.cache_clear()
    call = Mock(return_value=ChatAnswer(answer="안내예요."))
    monkeypatch.setattr(nvidia_ai, "chat", call)
    read(client.post(BASE + "/chat", json=chat_payload(), headers=headers))
    assert (
        read(client.post(BASE + "/chat", json=chat_payload(), headers=headers), 429)[
            "code"
        ]
        == "AI_DAILY_LIMIT"
    )
    assert list(db.scalars(select(AIUsageBucket.calls))) == [1, 1]
    call.assert_called_once()


def test_global_quota_cannot_be_bypassed_with_another_guest(
    ai_db, pg_connection, monkeypatch
):
    client, db = ai_db
    _, first = guest(client)
    _, second = guest(client)
    monkeypatch.setenv("AI_DAILY_GLOBAL_LIMIT", "1")
    get_settings.cache_clear()
    call = Mock(return_value=ChatAnswer(answer="안내예요."))
    monkeypatch.setattr(nvidia_ai, "chat", call)
    responses = parallel(
        SimpleNamespace(connection=pg_connection),
        [
            lambda http: http.post(BASE + "/chat", json=chat_payload(), headers=first),
            lambda http: http.post(BASE + "/chat", json=chat_payload(), headers=second),
        ],
    )
    assert sorted(response.status_code for response in responses) == [200, 429]
    call.assert_called_once()
    assert (
        db.scalar(
            select(AIUsageBucket.calls).where(AIUsageBucket.bucket_id == "global")
        )
        == 1
    )


def test_logout_during_upstream_call_does_not_return_answer(ai_db, monkeypatch):
    client, db = ai_db
    identity, headers = guest(client)

    def logged_out(_):
        from datetime import UTC, datetime
        from uuid import UUID

        db.execute(
            update(AuthSession)
            .where(AuthSession.user_id == UUID(identity["user_id"]))
            .values(revoked_at=datetime.now(UTC))
        )
        db.commit()
        return ChatAnswer(answer="폐기된 세션에 보여주면 안 되는 답변")

    monkeypatch.setattr(nvidia_ai, "chat", logged_out)
    response = client.post(BASE + "/chat", json=chat_payload(), headers=headers)
    read(response, 401)
    assert "폐기된 세션에 보여주면" not in response.text


def test_body_limit_is_enforced_before_provider_even_without_content_length(
    ai_db, monkeypatch
):
    client, _ = ai_db
    _, headers = guest(client)
    call = Mock()
    monkeypatch.setattr(nvidia_ai, "chat", call)

    def chunks():
        yield b'{"message":"'
        for _ in range(30):
            yield b"x" * 100000
        yield b'","allow_external_processing":true}'

    read(
        client.post(
            BASE + "/chat",
            content=chunks(),
            headers={**headers, "Content-Type": "application/json"},
        ),
        413,
    )
    call.assert_not_called()
