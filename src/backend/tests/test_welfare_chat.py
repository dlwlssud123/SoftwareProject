import hashlib
import json
import math
from datetime import UTC, datetime
from threading import BoundedSemaphore
from unittest.mock import Mock
from uuid import uuid4

import pytest
from agetech_data.rag.embedder import MODEL_ID
from sqlalchemy import select, text
from test_auth import guest
from test_welfare_api import welfare_db  # noqa: F401

from app.api import ai
from app.core.config import get_settings
from app.core.errors import AppError
from app.models import AIUsageBucket, AuthSession, WelfareRevision, WelfareService
from app.schemas.welfare_chat import WelfareGroundedAnswer
from app.services import nvidia_ai, rag_embedding

BASE = "/api/v1/ai/welfare-chat"


@pytest.fixture
def rag_db(request, monkeypatch):
    client, db = request.getfixturevalue("welfare_db")
    monkeypatch.setenv("WELFARE_RAG_ENABLED", "true")
    monkeypatch.setenv("RAG_EMBEDDING_URL", "http://embedding:8091")
    monkeypatch.setenv("RAG_EMBEDDING_TOKEN", uuid4().hex)
    monkeypatch.setenv("NVIDIA_AI_ENABLED", "true")
    monkeypatch.setenv("NVIDIA_API_KEY", "fixture")
    get_settings.cache_clear()
    monkeypatch.setattr(ai, "_slots", BoundedSemaphore(2))
    monkeypatch.setattr(
        nvidia_ai,
        "build_opener",
        Mock(side_effect=AssertionError("External requests forbidden")),
    )
    vector = Mock(return_value=[1] + [0] * 1023)
    monkeypatch.setattr(rag_embedding, "embed_query", vector)
    generated = Mock(
        return_value=WelfareGroundedAnswer(
            answer="공식 자료를 확인해 보세요. [1]", citations=[1]
        )
    )
    monkeypatch.setattr(nvidia_ai, "welfare_chat", generated)
    schema = db.scalar(text("SELECT current_schema()"))
    assert schema.startswith("import_test_") and len(schema) == 44
    db.execute(text(f'SET search_path TO "{schema}", public'))
    digest = hashlib.sha256(b"welfare-test").hexdigest()
    version = "welfare-test." + digest[:12]
    rows = (
        db.execute(
            text(
                "SELECT * FROM rag_source_active WHERE source_type IN ('welfare_central','welfare_local') ORDER BY source_id"
            )
        )
        .mappings()
        .all()
    )
    db.execute(
        text(
            "INSERT INTO rag_index_version (index_version,manifest_version,binding_sha256,embedding_model,chunk_count,manifest_sha256,data_versions,status,activated_at) VALUES (:version,'welfare-test',:digest,:model,:count,:digest,'[]','active',now())"
        ),
        {
            "version": version,
            "digest": digest,
            "model": MODEL_ID,
            "count": len(rows) + 1,
        },
    )
    for i, row in enumerate(rows):
        service = db.scalar(
            select(WelfareService).where(WelfareService.source_id == row["source_id"])
        )
        revision = db.get(WelfareRevision, service.active_revision_id)
        normalized = revision.normalized
        scope = (
            "national" if service.scope == "central_nationwide" else normalized["scope"]
        )
        score = 0.80 + i * 0.02
        common = dict(
            version=version,
            sid=row["source_id"],
            kind=row["source_type"],
            title=revision.title,
            digest=digest,
            fingerprint=row["record_sha256"],
            scope=scope,
            ctpv=normalized.get("ctpv"),
            sgg=normalized.get("sgg"),
            end=normalized.get("period_end"),
            model=MODEL_ID,
            vector=json.dumps([score, math.sqrt(1 - score * score)] + [0] * 1022),
            url="https://www.bokjiro.go.kr/ssis-tbu/",
            checked=datetime(2026, 11, 18, tzinfo=UTC),
        )
        for n in range(1, 3 if i == 0 else 2):
            db.execute(
                text(
                    "INSERT INTO rag_chunk (index_version,chunk_id,source_type,source_id,section,chunk_no,title,content,content_sha256,region_scope,ctpv,sgg,source_url,source_checked_at,period_end,data_version,source_record_sha256,embedding_model,embedding) "
                    "VALUES (:version,:cid,:kind,:sid,'all',:n,:title,:content,:digest,:scope,:ctpv,:sgg,:url,:checked,:end,'test',:fingerprint,:model,CAST(:vector AS vector))"
                ),
                {
                    **common,
                    "cid": f"{row['source_type']}:{row['source_id']}:all:{n}",
                    "n": n,
                    "content": revision.title
                    + " 지원 내용은 공식 자료에서 확인하고 주민센터에 문의하세요.",
                },
            )
    db.commit()
    try:
        yield client, db, vector, generated
    finally:
        get_settings.cache_clear()


def payload(**kwargs):
    return {
        "message": "혼자 사는데 안부를 확인해 주는 지원이 있나요?",
        "allow_external_processing": True,
        **kwargs,
    }


def ask(client, headers, status=200, **kwargs):
    response = client.post(BASE, json=payload(**kwargs), headers=headers)
    assert response.status_code == status, response.text
    assert response.headers["Cache-Control"] == "no-store"
    return response.json()["data" if status == 200 else "error"]


def test_rag_requires_auth_consent_and_rejects_profile_or_orphan_district(rag_db):
    client, _, vector, generated = rag_db
    assert client.post(BASE, json=payload()).status_code == 401
    _, headers = guest(client)
    for body in (
        {"allow_external_processing": False},
        {"profile": {"age": 70}},
        {"district": "남구"},
        {"message": "\x00"},
    ):
        ask(client, headers, 422, **body)
    vector.assert_not_called()
    generated.assert_not_called()


def test_rag_search_reuses_sql_with_region_dedupe_dates_and_official_sources(rag_db):
    client, _, vector, generated = rag_db
    _, headers = guest(client)
    result = ask(client, headers, region="대구", district="남구")
    assert result["answer_status"] == "generated" and result["provider"] == "NVIDIA"
    assert result["region"] == "대구광역시" and result["district"] == "남구"
    assert result["sources"][0]["url"].startswith("https://www.bokjiro.go.kr/")
    assert result["sources"][0]["checked_at"].startswith("2026-11-18")
    question, context = generated.call_args.args
    assert question == payload()["message"]
    assert "남구 일반 안내" in context and "대구 전체 안내" in context
    assert "다른 지역 안내" not in context and "종료 사업" not in context
    assert context.count("전국 일반 안내 지원 내용") == 1
    assert "확인 2026-11-18" in context
    vector.assert_called_once_with(question)


def test_without_region_only_national_sources_are_used(rag_db):
    client, _, _, generated = rag_db
    _, headers = guest(client)
    result = ask(client, headers)
    assert result["region"] is None
    context = generated.call_args.args[1]
    assert "전국 독거 지원" in context and "남구 일반 안내" not in context
    assert "다른 지역 안내" not in context


@pytest.mark.parametrize("failure", ["withdrawn", "stale", "retracted", "expired"])
def test_unpublished_changed_and_expired_chunks_are_not_evidence(rag_db, failure):
    client, db, _, generated = rag_db
    row = db.scalar(select(WelfareService).where(WelfareService.source_id == "WLF101"))
    if failure == "withdrawn":
        row.publication_status = "withdrawn"
    if failure == "stale":
        db.get(WelfareRevision, row.active_revision_id).fingerprint = "f" * 64
    if failure in ("retracted", "expired"):
        sql = (
            "UPDATE rag_chunk SET status='retracted'"
            if failure == "retracted"
            else "UPDATE rag_chunk SET period_end='2000-01-01'"
        )
        db.execute(text(sql + " WHERE source_id='WLF101'"))
    db.commit()
    _, headers = guest(client)
    ask(client, headers)
    assert "전국 독거 지원" not in generated.call_args.args[1]


def test_low_evidence_never_calls_generator(rag_db):
    client, db, _, generated = rag_db
    db.execute(
        text("UPDATE rag_chunk SET embedding=CAST(:v AS vector)"),
        {"v": json.dumps([0, 1] + [0] * 1022)},
    )
    db.commit()
    _, headers = guest(client)
    result = ask(client, headers)
    assert result["answer_status"] == "no_evidence" and result["sources"] == []
    generated.assert_not_called()


@pytest.mark.parametrize(
    "answer,citations",
    [
        ("없는 자료입니다. [5]", [5]),
        ("출처 없는 답변", [1]),
        ("https://example.test 안내 [1]", [1]),
    ],
)
def test_model_cannot_invent_citations_or_urls(rag_db, answer, citations):
    client, _, _, generated = rag_db
    generated.return_value = WelfareGroundedAnswer(answer=answer, citations=citations)
    _, headers = guest(client)
    result = ask(client, headers)
    assert result["answer_status"] == "references_only" and result["sources"]
    assert "example.test" not in result["answer"]


def test_provider_failure_keeps_retrieved_sources(rag_db):
    client, _, _, generated = rag_db
    generated.side_effect = AppError(503, "AI_UNAVAILABLE", "unavailable")
    _, headers = guest(client)
    result = ask(client, headers)
    assert result["answer_status"] == "references_only" and result["model"] is None
    assert len(result["sources"]) == 2


@pytest.mark.parametrize("failure", ["missing", "different-model", "disabled"])
def test_unavailable_index_and_disabled_rag_fail_explicitly(
    rag_db, monkeypatch, failure
):
    client, db, vector, generated = rag_db
    if failure == "missing":
        db.execute(text("UPDATE rag_index_version SET status='retired'"))
    if failure == "different-model":
        db.execute(text("UPDATE rag_index_version SET embedding_model='another-model'"))
    if failure == "disabled":
        monkeypatch.setenv("WELFARE_RAG_ENABLED", "false")
        get_settings.cache_clear()
    db.commit()
    _, headers = guest(client)
    error = ask(client, headers, 503)
    assert error["code"] == (
        "RAG_NOT_CONFIGURED" if failure == "disabled" else "RAG_INDEX_UNAVAILABLE"
    )
    generated.assert_not_called()
    if failure == "disabled":
        vector.assert_not_called()
        assert db.scalar(select(AIUsageBucket.calls).limit(1)) is None


def test_withdrawal_during_generation_never_returns_old_answer(rag_db):
    client, db, _, generated = rag_db

    def withdraw(*_):
        row = db.scalar(
            select(WelfareService).where(WelfareService.source_id == "WLF101")
        )
        row.publication_status = "withdrawn"
        db.commit()
        return WelfareGroundedAnswer(answer="오래된 답변 [1]", citations=[1])

    generated.side_effect = withdraw
    _, headers = guest(client)
    assert ask(client, headers, 503)["code"] == "RAG_SOURCES_CHANGED"


def test_logout_during_generation_never_returns_private_response(rag_db):
    client, db, _, generated = rag_db

    def revoke(*_):
        for session in db.scalars(select(AuthSession)):
            session.revoked_at = datetime.now(UTC)
        db.commit()
        return WelfareGroundedAnswer(answer="안내 [1]", citations=[1])

    generated.side_effect = revoke
    _, headers = guest(client)
    ask(client, headers, 401)


def test_existing_daily_limit_applies_to_welfare_chat(rag_db, monkeypatch):
    client, _, _, generated = rag_db
    monkeypatch.setenv("AI_DAILY_USER_LIMIT", "1")
    get_settings.cache_clear()
    _, headers = guest(client)
    ask(client, headers)
    assert ask(client, headers, 429)["code"] == "AI_DAILY_LIMIT"
    assert generated.call_count == 1


@pytest.mark.parametrize("score,status", [(0.4, "weak"), (0.3998, "none")])
def test_sql_similarity_boundary_matches_data_team_rounding(rag_db, score, status):
    client, db, _, generated = rag_db
    db.execute(
        text("UPDATE rag_chunk SET embedding=CAST(:v AS vector)"),
        {"v": json.dumps([score, math.sqrt(1 - score * score)] + [0] * 1022)},
    )
    db.commit()
    _, headers = guest(client)
    result = ask(client, headers)
    assert result["evidence_status"] == status
    assert generated.call_count == (0 if status == "none" else 1)
