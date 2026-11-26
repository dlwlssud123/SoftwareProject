import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest
from agetech_data.rag.embedder import DIM, MODEL_ID
from agetech_data.rag.serve import create_server
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.core.errors import AppError
from app.services import rag_embedding


@pytest.fixture
def worker(monkeypatch):
    class Embedder:
        model_id, dim = MODEL_ID, DIM
        received = []

        def embed_query(self, query):
            self.received.append(query)
            return [1.0] + [0.0] * (DIM - 1)

    embedder = Embedder()
    token = uuid4().hex
    server = create_server(("127.0.0.1", 0), embedder, token)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://test@localhost/test",
        welfare_rag_enabled=True,
        rag_embedding_url=f"http://127.0.0.1:{server.server_port}",
        rag_embedding_token=SecretStr(token),
    )
    monkeypatch.setattr(rag_embedding, "get_settings", lambda: settings)
    try:
        yield settings, embedder
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_real_http_worker_and_client_keep_exact_model_and_query_only(worker):
    settings, embedder = worker
    result = rag_embedding.embed_query("안부를 확인해 주는 지원이 있나요?")
    assert result == [1.0] + [0.0] * 1023
    assert embedder.received == ["안부를 확인해 주는 지원이 있나요?"]
    with urlopen(settings.rag_embedding_url + "/health", timeout=3) as response:
        assert json.load(response) == {
            "status": "ok",
            "model": MODEL_ID,
            "dimension": DIM,
        }


@pytest.mark.parametrize(
    "change", ["auth", "model", "extra", "empty", "too_long", "null"]
)
def test_worker_rejects_bad_requests_before_embedding(worker, change):
    settings, embedder = worker
    value = {"text": "지원 안내", "model": MODEL_ID}
    token = settings.rag_embedding_token.get_secret_value()
    if change == "auth":
        token = "incorrect"
    if change == "model":
        value["model"] = "different-model"
    if change == "extra":
        value["profile"] = {"age": 70}
    if change == "empty":
        value["text"] = " "
    if change == "too_long":
        value["text"] = "가" * 501
    if change == "null":
        value["text"] = "안내\x00"
    request = Request(
        settings.rag_embedding_url + "/embed",
        data=json.dumps(value).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + token,
        },
    )
    with pytest.raises(HTTPError) as error:
        urlopen(request, timeout=3)
    assert error.value.code == (401 if change == "auth" else 422)
    error.value.close()
    assert embedder.received == []


@pytest.mark.parametrize(
    "vector",
    [
        [0] * DIM,
        [1] * DIM,
        [1] * (DIM - 1),
        [True] + [0] * 1023,
        [float("nan")] + [0] * 1023,
    ],
)
def test_worker_or_client_never_accepts_bad_vectors(vector):
    with pytest.raises(ValueError):
        rag_embedding.validate_vector(vector)


def test_worker_failure_is_generic_and_never_returns_query(worker, monkeypatch):
    _, embedder = worker

    def failed(_):
        raise RuntimeError("private internal details")

    monkeypatch.setattr(embedder, "embed_query", failed)
    with pytest.raises(AppError) as error:
        rag_embedding.embed_query("지원 안내")
    assert error.value.code == "RAG_EMBEDDING_UNAVAILABLE"
    assert "private" not in error.value.message


@pytest.mark.parametrize(
    "origin",
    [
        "https://example.test/api",
        "https://example.test?q=1",
        "https://example.test#fragment",
        "file:///tmp/model",
        "http://embedding:bad",
    ],
)
def test_embedding_config_rejects_non_origin_addresses(origin):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql+psycopg://test@localhost/test",
            rag_embedding_url=origin,
        )
