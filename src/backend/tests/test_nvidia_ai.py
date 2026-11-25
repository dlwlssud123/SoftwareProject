import base64
import io
import json
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest
from PIL import Image, PngImagePlugin
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.ai import (
    ChatAnswer,
    ChatRequest,
    FoodInference,
    IngredientInference,
    PhotoRequest,
)
from app.services import nvidia_ai


def picture(*, size=(64, 64), metadata=False):
    output = io.BytesIO()
    info = PngImagePlugin.PngInfo()
    if metadata:
        info.add_text("Author", "private-person")
    Image.new("RGB", size, "green").save(output, format="PNG", pnginfo=info)
    return output.getvalue()


@pytest.fixture
def configured(monkeypatch):
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://test@localhost/test",
        nvidia_ai_enabled=True,
        nvidia_api_key=SecretStr("fixture"),
    )
    monkeypatch.setattr(nvidia_ai, "get_settings", lambda: settings)
    return settings


def test_preprocessing_removes_metadata_and_resizes_without_writing_files():
    clean = nvidia_ai.sanitize_photo(
        base64.b64encode(picture(size=(1500, 1200), metadata=True))
    )
    with Image.open(io.BytesIO(clean)) as decoded:
        assert decoded.format == "JPEG" and decoded.size == (1024, 819)
        assert not decoded.getexif() and "Author" not in decoded.info
    assert b"private-person" not in clean


@pytest.mark.parametrize(
    "raw", [b"not an image", b"", b"x" * (nvidia_ai.MAX_IMAGE_BYTES + 1)]
)
def test_invalid_images_never_reach_provider(raw, monkeypatch):
    provider = Mock()
    monkeypatch.setattr(nvidia_ai, "build_opener", provider)
    with pytest.raises(AppError) as error:
        nvidia_ai.sanitize_photo(base64.b64encode(raw))
    assert error.value.status_code == 422
    provider.assert_not_called()


def test_oversized_dimensions_and_animated_images_are_rejected():
    for raw in [picture(size=(4097, 1))]:
        with pytest.raises(AppError):
            nvidia_ai.sanitize_photo(base64.b64encode(raw))
    output = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(
        output,
        format="PNG",
        save_all=True,
        append_images=[Image.new("RGB", (10, 10), "blue")],
    )
    with pytest.raises(AppError):
        nvidia_ai.sanitize_photo(base64.b64encode(output.getvalue()))


def reply(content, *, finish="stop"):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = json.dumps(
        {"choices": [{"finish_reason": finish, "message": {"content": content}}]}
    ).encode()
    return response


def test_ingredient_provider_uses_bounded_text_reference_not_photo_or_profile(
    configured, monkeypatch
):
    opener = Mock()
    opener.open.return_value = reply('{"ingredients":[{"name":"양파","amount_g":50}]}')
    monkeypatch.setattr(nvidia_ai, "build_opener", lambda *_: opener)
    reference = {"name": "양파요리", "ingredients_text": "양파 50g, 기름 5g"}
    result = nvidia_ai.estimate_ingredients("양파요리", 200, reference)
    assert result.ingredients[0].amount_g == 50
    body = json.loads(opener.open.call_args.args[0].data)
    payload = json.loads(body["messages"][1]["content"])
    assert payload == {
        "dish_name": "양파요리",
        "suggested_cooked_serving_grams": 200,
        "reference_recipe": reference,
    }
    assert "image_url" not in json.dumps(body) and "profile" not in payload


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{"name": "양파", "amount_g": 0}],
        [{"name": "양파", "amount_g": "50"}],
        [{"name": "양파", "amount_g": 50, "energy_kcal": 20}],
        [{"name": "양파", "amount_g": 50}, {"name": "양파", "amount_g": 50}],
        [{"name": f"재료{i}", "amount_g": 10} for i in range(9)],
        [{"name": "재료1", "amount_g": 1400}, {"name": "재료2", "amount_g": 1400}],
    ],
)
def test_ingredient_model_rejects_unbounded_guessed_nutrients_or_duplicates(rows):
    with pytest.raises(ValidationError):
        IngredientInference.model_validate({"ingredients": rows})


def test_real_request_contract_uses_fixed_host_json_and_no_redirect_policy(
    configured, monkeypatch
):
    opener = Mock()
    opener.open.return_value = reply('{"answer":"안녕하세요!"}')
    make = Mock(return_value=opener)
    monkeypatch.setattr(nvidia_ai, "build_opener", make)
    result = nvidia_ai.chat("안녕하세요")
    assert result.answer == "안녕하세요!"
    request = opener.open.call_args.args[0]
    assert request.full_url == nvidia_ai.ENDPOINT
    assert request.get_header("Authorization") == "Bearer fixture"
    body = json.loads(request.data)
    assert body["model"] == configured.nvidia_model and body["stream"] is False
    assert len(body["messages"]) == 2 and body["messages"][1]["content"] == "안녕하세요"
    assert (
        make.call_args.args[0].redirect_request(None, None, None, None, None, None)
        is None
    )
    assert opener.open.call_args.kwargs["timeout"] == 25
    assert "fixture" not in repr(configured)


@pytest.mark.parametrize(
    "content,finish",
    [
        ("not json", "stop"),
        ('{"answer":""}', "stop"),
        ('{"answer":"hello","private":"data"}', "stop"),
        ('{"answer":"truncated"}', "length"),
    ],
)
def test_invalid_or_truncated_outputs_do_not_become_success(
    configured, monkeypatch, content, finish
):
    monkeypatch.setattr(
        nvidia_ai,
        "build_opener",
        lambda *_: Mock(open=Mock(return_value=reply(content, finish=finish))),
    )
    with pytest.raises(AppError) as error:
        nvidia_ai.chat("사용법")
    assert error.value.code == "AI_RESPONSE_INVALID"


@pytest.mark.parametrize(
    "failure,status",
    [
        (URLError("private-upstream-detail"), 503),
        (
            HTTPError(
                nvidia_ai.ENDPOINT,
                401,
                "private-upstream-detail",
                {},
                io.BytesIO(b"private error body"),
            ),
            503,
        ),
        (
            HTTPError(
                nvidia_ai.ENDPOINT, 429, "rate", {}, io.BytesIO(b"private error body")
            ),
            429,
        ),
    ],
)
def test_upstream_failures_hide_response_body_and_credentials(
    configured, monkeypatch, failure, status
):
    monkeypatch.setattr(
        nvidia_ai, "build_opener", lambda *_: Mock(open=Mock(side_effect=failure))
    )
    with pytest.raises(AppError) as error:
        nvidia_ai.chat("사용법")
    assert error.value.status_code == status
    assert "private" not in str(error.value) and "fixture" not in str(error.value)


def test_food_output_does_not_accept_guessed_nutrients_or_inconsistent_results():
    for body in [
        {
            "is_food": False,
            "foods": [
                {"name": "밥", "confidence": "high", "standard_serving_grams": 200}
            ],
        },
        {"is_food": True, "foods": []},
        {
            "is_food": True,
            "foods": [
                {
                    "name": "밥",
                    "confidence": "high",
                    "standard_serving_grams": 200,
                    "energy_kcal": 300,
                }
            ],
        },
    ]:
        with pytest.raises(ValidationError):
            FoodInference.model_validate(body)


def test_external_processing_requires_explicit_boolean_and_bounded_payload():
    for consent in (False, 1, "true"):
        with pytest.raises(ValidationError):
            ChatRequest(message="사용법", allow_external_processing=consent)
    with pytest.raises(ValidationError):
        PhotoRequest(image_base64="x" * 2800001, allow_external_processing=True)
    with pytest.raises(ValidationError):
        ChatAnswer(answer="\ud800")


def test_welfare_provider_receives_only_question_and_public_evidence(
    configured, monkeypatch
):
    from app.schemas.welfare_chat import WelfareGroundedAnswer

    opener = Mock()
    opener.open.return_value = reply('{"answer":"공식 자료 안내 [1]","citations":[1]}')
    monkeypatch.setattr(nvidia_ai, "build_opener", lambda *_: opener)
    result = nvidia_ai.welfare_chat("난방비 지원", "[1] 공개 지원 안내")
    assert isinstance(result, WelfareGroundedAnswer) and result.citations == [1]
    request = opener.open.call_args.args[0]
    body = json.loads(request.data)
    assert request.full_url == nvidia_ai.ENDPOINT
    assert json.loads(body["messages"][1]["content"]) == {
        "question": "난방비 지원",
        "official_evidence": "[1] 공개 지원 안내",
    }
    assert len(body["messages"]) == 2
