from unittest.mock import Mock
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.errors import AppError


def assert_request_id(response):
    request_id = response.json()["meta"]["request_id"]
    assert str(UUID(request_id)) == request_id
    assert response.headers["X-Request-ID"] == request_id


def test_liveness_without_database(client):
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"
    assert_request_id(response)


def test_request_ids_are_unique_and_server_generated(client):
    first = client.get("/api/v1/health/live", headers={"X-Request-ID": "external"})
    second = client.get("/api/v1/health/live")

    assert first.headers["X-Request-ID"] != "external"
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]


def test_missing_route_uses_error_envelope(client):
    response = client.get("/api/v1/missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "HTTP_404"
    assert "data" not in response.json()
    assert_request_id(response)


def test_method_not_allowed_preserves_allow_header(client):
    response = client.post("/api/v1/health/live")

    assert response.status_code == 405
    assert "GET" in response.headers["Allow"]
    assert response.json()["error"]["code"] == "HTTP_405"
    assert_request_id(response)


def test_readiness_with_available_database(client):
    from app.core.database import get_db

    session = Mock(spec=Session)
    client.app.dependency_overrides[get_db] = lambda: session

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json()["data"]["database"] == "ok"
    assert response.json()["meta"]["checked_at"].endswith("Z")
    assert_request_id(response)


def test_readiness_failure_is_retryable_and_hides_internal_error(client):
    from app.core.database import get_db

    session = Mock(spec=Session)
    session.execute.side_effect = OperationalError(
        "SELECT 1", {}, Exception("private-database-password")
    )
    client.app.dependency_overrides[get_db] = lambda: session

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"
    assert response.json()["error"]["retryable"] is True
    assert "private-database-password" not in response.text
    assert_request_id(response)


def test_validation_error_identifies_field_without_echoing_input(client):
    class Input(BaseModel):
        age: int

    @client.app.post("/__test/validate")
    def validate(payload: Input):
        return {"age": payload.age}

    response = client.post("/__test/validate", json={"age": "private-input"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["fields"][0]["field"] == "body.age"
    assert "private-input" not in response.text
    assert_request_id(response)


def test_business_error_preserves_public_code(client):
    @client.app.get("/__test/conflict")
    def conflict():
        raise AppError(409, "REVISION_CONFLICT", "최신 자료를 확인해 주세요.")

    response = client.get("/__test/conflict")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REVISION_CONFLICT"
    assert response.json()["error"]["retryable"] is False
    assert_request_id(response)


def test_unexpected_error_is_safe_and_readable_by_admin_web(client, caplog):
    @client.app.get("/__test/failure")
    def fail():
        raise RuntimeError("private-token-and-health-data")

    response = client.get(
        "/__test/failure", headers={"Origin": "http://localhost:5173"}
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert "private-token-and-health-data" not in response.text
    assert "private-token-and-health-data" not in caplog.text
    assert response.headers["X-Request-ID"] in caplog.text
    assert_request_id(response)


def test_admin_web_preflight_allows_authorization_and_idempotency_key(client):
    response = client.options(
        "/api/v1/health/live",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization,Idempotency-Key",
        },
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"


def test_untrusted_origin_is_not_allowed(client):
    response = client.get(
        "/api/v1/health/live", headers={"Origin": "https://untrusted.example"}
    )

    assert "Access-Control-Allow-Origin" not in response.headers


def test_openapi_and_swagger_are_available(client):
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/health/live" in response.json()["paths"]
    assert "/api/v1/health/ready" in response.json()["paths"]
    ready_responses = response.json()["paths"]["/api/v1/health/ready"]["get"][
        "responses"
    ]
    assert ready_responses["503"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
    assert "500" in ready_responses
    assert client.get("/docs").status_code == 200
