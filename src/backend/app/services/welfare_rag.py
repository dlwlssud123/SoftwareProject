"""Connect Jaeyoung's published-source SQL and evidence rules to welfare answers."""

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

from agetech_data.rag.embedder import MODEL_ID
from agetech_data.rag.search import WELFARE_TYPES, Hit, evidence_status, format_context
from agetech_data.welfare.query import resolve_region
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.errors import AppError
from app.schemas.welfare_chat import WelfareChatResult, WelfareChatSource
from app.services import nvidia_ai, rag_embedding

SEARCH_SQL = Path(__file__).resolve().parents[4] / "docs/data/sql/rag_search.sql"


@lru_cache
def search_statement():
    sql = SEARCH_SQL.read_text(encoding="utf-8")
    start = sql.index("SELECT chunk_id")
    return text(sql[start : sql.index(";", start)])


@dataclass
class Retrieval:
    index_version: str
    region: object
    hits: list[Hit]


def retrieve(db, vector, region=None, district=None):
    try:
        db.execute(text("SET LOCAL TIME ZONE 'Asia/Seoul'"))
        version = (
            db.execute(
                text(
                    "SELECT index_version, embedding_model FROM rag_index_version WHERE status = 'active'"
                )
            )
            .mappings()
            .one_or_none()
        )
        if version is None or version["embedding_model"] != MODEL_ID:
            raise rag_embedding.unavailable("RAG_INDEX_UNAVAILABLE")
        regions = [
            SimpleNamespace(ctpv=row.ctpv, sgg=row.sgg)
            for row in db.execute(
                text(
                    "SELECT DISTINCT c.ctpv, c.sgg FROM rag_chunk c JOIN rag_index_version v ON v.index_version=c.index_version AND v.status='active' "
                    "JOIN rag_source_active s ON s.source_type=c.source_type AND s.source_id=c.source_id AND s.record_sha256=c.source_record_sha256 "
                    "WHERE c.source_type IN ('welfare_central','welfare_local') AND c.status='active' AND c.embedding_model=:model"
                ),
                {"model": MODEL_ID},
            )
        ]
        resolved = resolve_region(regions, region, district)
        rows = (
            db.execute(
                search_statement(),
                {
                    "q": json.dumps(vector),
                    "embedding_model": MODEL_ID,
                    "source_types": list(WELFARE_TYPES),
                    "ctpv": resolved.ctpv,
                    "sgg": resolved.sgg,
                    "allergies": [],
                },
            )
            .mappings()
            .all()
        )
        hits = []
        for rank, row in enumerate(rows, 1):
            chunk = dict(row)
            checked = chunk["source_checked_at"]
            chunk["source_checked_at"] = (
                checked.isoformat() if checked is not None else None
            )
            hits.append(
                Hit(rank, round(max(-1, min(1, float(row["similarity"]))), 4), chunk)
            )
        return Retrieval(version["index_version"], resolved, hits)
    except SQLAlchemyError:
        db.rollback()
        raise rag_embedding.unavailable("RAG_SEARCH_UNAVAILABLE") from None


def sources(hits):
    return [
        WelfareChatSource(
            number=h.rank,
            service_id=h.source_id,
            scope=h.chunk["source_type"],
            title=h.title,
            excerpt=h.chunk["content"][:1200],
            url=h.chunk["source_url"],
            checked_at=h.chunk["source_checked_at"],
        )
        for h in hits
    ]


def result(retrieval, answer, *, status, selected=None):
    return WelfareChatResult(
        answer=answer,
        provider="NVIDIA" if status == "generated" else "references",
        model=get_settings().nvidia_model if status == "generated" else None,
        answer_status=status,
        evidence_status=evidence_status(retrieval.hits),
        index_version=retrieval.index_version,
        region=retrieval.region.ctpv,
        district=retrieval.region.sgg,
        notes=retrieval.region.notes,
        sources=sources(selected if selected is not None else retrieval.hits),
    )


def signature(retrieval):
    return retrieval.index_version, [
        (
            h.chunk["chunk_id"],
            h.chunk["content"],
            h.chunk["source_url"],
            h.chunk["source_checked_at"],
        )
        for h in retrieval.hits
    ]


def answer(db, payload):
    vector = rag_embedding.embed_query(payload.message)
    found = retrieve(db, vector, payload.region, payload.district)
    if evidence_status(found.hits) == "none":
        return result(
            found,
            "검색한 복지 자료에서 질문에 맞는 안내를 확인하지 못했어요. 복지 추천에서 직접 찾아보거나 거주지 주민센터에 문의해 주세요.",
            status="no_evidence",
            selected=[],
        )
    context = format_context(found.hits)
    # Release the read transaction while the model responds; check current sources again afterwards.
    db.commit()
    generated = None
    try:
        generated = nvidia_ai.welfare_chat(payload.message, context)
    except AppError:
        pass  # A provider outage must not hide already-retrieved official sources.
    current = retrieve(db, vector, payload.region, payload.district)
    if signature(current) != signature(found):
        raise rag_embedding.unavailable("RAG_SOURCES_CHANGED")
    if generated is not None:
        selected = [h for h in found.hits if h.rank in generated.citations]
        reference_numbers = {
            int(number) for number in re.findall(r"\[(\d+)\]", generated.answer)
        }
        # Never render a model URL; all links come from validated DB metadata.
        if (
            len(selected) == len(generated.citations)
            and reference_numbers == set(generated.citations)
            and not re.search(r"https?://|www\.", generated.answer, re.I)
        ):
            return result(
                found, generated.answer, status="generated", selected=selected
            )
    return result(
        found,
        "관련 공식 자료를 찾았어요. 지금은 AI 설명을 만들지 못했으니 아래 자료에서 지원 내용과 신청 방법을 확인해 주세요.",
        status="references_only",
    )
