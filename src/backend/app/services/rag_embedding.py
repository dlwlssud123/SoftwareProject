"""Small HTTP client for the existing KURE worker; torch never enters the API."""

import json
import math
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from agetech_data.rag.embedder import DIM, MODEL_ID

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.kakao import NoRedirect


def unavailable(code="RAG_EMBEDDING_UNAVAILABLE"):
    return AppError(
        503,
        code,
        "복지 자료 검색을 준비 중이에요. 복지 추천에서 직접 찾아보거나 잠시 뒤 다시 이용해 주세요.",
        retryable=True,
    )


def validate_vector(value):
    if not isinstance(value, list) or len(value) != DIM:
        raise ValueError("Unexpected embedding dimensions")
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in value):
        raise ValueError("Invalid embedding values")
    norm = sum(x * x for x in value)
    if not math.isfinite(norm) or abs(norm - 1) > 0.002:
        raise ValueError("Embedding must be normalized")
    return value


def check_enabled():
    settings = get_settings()
    if (
        not settings.welfare_rag_enabled
        or not settings.rag_embedding_url
        or not settings.rag_embedding_token
    ):
        raise unavailable("RAG_NOT_CONFIGURED")
    return settings


def embed_query(message):
    settings = check_enabled()
    request = Request(
        settings.rag_embedding_url.rstrip("/") + "/embed",
        data=json.dumps(
            {"text": message, "model": MODEL_ID}, ensure_ascii=False
        ).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer "
            + settings.rag_embedding_token.get_secret_value(),
        },
        method="POST",
    )
    try:
        # Private worker traffic must not go through environment/system proxies.
        with build_opener(ProxyHandler({}), NoRedirect()).open(
            request, timeout=settings.rag_embedding_timeout_seconds
        ) as response:
            if (
                response.status != 200
                or response.headers.get_content_type() != "application/json"
            ):
                raise ValueError("Unexpected embedding response")
            payload = response.read(65537)
        if len(payload) > 65536:
            raise ValueError("Embedding response too large")
        result = json.loads(payload)
        if (
            not isinstance(result, dict)
            or set(result) != {"model", "vector"}
            or result["model"] != MODEL_ID
        ):
            raise ValueError("Embedding model mismatch")
        return validate_vector(result["vector"])
    except HTTPError as error:
        error.close()
        raise unavailable() from None
    except (URLError, OSError, ValueError, TypeError, OverflowError):
        raise unavailable() from None
