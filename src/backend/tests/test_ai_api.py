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
from test_topic_requests import parallel

from app.api import ai
from app.core.config import get_settings
from app.models import AIUsageBucket, AuthSession, MealLog
from app.schemas.ai import ChatAnswer, FoodInference
from app.services import nvidia_ai

BASE = "/api/v1/ai"


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
    assert call.call_args.args[0].startswith(b"\xff\xd8")
    assert db.scalar(select(func.count()).select_from(MealLog)) == 0


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
    for item in old_body["items"]:
        del item["amount_is_estimate"]
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
