"""인덱스 파일로 하는 근거 검색 — docs/data/sql/rag_chunk_draft.sql 검색 예와 같은 조건.

DB가 붙기 전 평가·표본용이고, 서버는 같은 조건을 SQL로 쓴다.
1. 시도·시군구 정규화(welfare.query.resolve_region) → 2. 조건으로 거르기(활성, 원천 종류, 지역,
끝난 사업, 알레르기) → 3. 코사인 유사도 순 → 4. 같은 원본(source_id)은 가장 가까운 청크 하나만.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

from agetech_data.welfare.query import RegionQuery, resolve_region

WELFARE_TYPES = ("welfare_central", "welfare_local")
RECIPE_TYPES = ("recipe",)


@dataclass
class Hit:
    rank: int
    similarity: float
    chunk: dict

    @property
    def source_id(self) -> str:
        return self.chunk["source_id"]

    @property
    def title(self) -> str:
        return self.chunk["title"]


class IndexSearcher:
    """model_id = 인덱스를 만든 모델(manifest["model_id"]). 질문 임베더 모델이 다르면 검색하지 않는다
    (SQL의 `embedding_model = :embedding_model` 조건과 같은 역할 — 다른 모델 벡터끼리 비교하면 순위가 의미 없음)."""

    def __init__(self, chunks: list[dict], vectors, embedder=None, model_id: str | None = None):
        import numpy as np

        if embedder is not None and model_id is not None and embedder.model_id != model_id:
            raise ValueError(f"인덱스 모델 {model_id} ≠ 질문 임베딩 모델 {embedder.model_id} — 섞어 쓰지 않음")
        self.chunks, self.vectors, self.embedder, self._np = chunks, np.asarray(vectors, dtype=np.float32), embedder, np
        self.model_id = model_id
        self._regions = [SimpleNamespace(ctpv=c["ctpv"], sgg=c["sgg"]) for c in chunks if c["ctpv"]]

    @classmethod
    def from_index(cls, index_dir=None, embedder=None) -> "IndexSearcher":
        """manifest를 검증해 읽고, 인덱스 모델과 질문 모델이 같은지 확인한다."""
        from agetech_data import paths
        from agetech_data.rag.index import load_index

        manifest, chunks, vectors = load_index(index_dir or paths.RAG_INDEX_DIR)
        return cls(chunks, vectors, embedder, model_id=manifest["model_id"])

    def resolve(self, ctpv: str | None, sgg: str | None = None) -> RegionQuery:
        return resolve_region(self._regions, ctpv, sgg)

    def _allowed(self, c: dict, source_types, region: RegionQuery | None, allergies: set[str],
                 today: str, include_ended: bool) -> bool:
        if c["status"] != "active" or (source_types and c["source_type"] not in source_types):
            return False
        scope = c["region_scope"]
        if scope in ("province", "district"):
            if region is None or not region.ctpv or c["ctpv"] != region.ctpv:
                return False
            if scope == "district" and c["sgg"] != region.sgg:
                return False
        if not include_ended and c["period_end"] and c["period_end"] < today:
            return False
        return not (allergies and allergies.intersection(c["allergens"]))

    def search_vector(self, qvec, *, k: int = 5, source_types=None, region: RegionQuery | None = None,
                      allergies=None, include_ended: bool = False, as_of: date | None = None,
                      dedupe: bool = True) -> list[Hit]:
        np = self._np
        today = (as_of or date.today()).isoformat()
        allergy_set = set(allergies or [])
        mask = np.array([self._allowed(c, source_types, region, allergy_set, today, include_ended)
                         for c in self.chunks], dtype=bool)
        if not mask.any():
            return []
        idx = np.flatnonzero(mask)
        sims = self.vectors[idx] @ np.asarray(qvec, dtype=np.float32)
        order = idx[np.argsort(-sims, kind="stable")]
        sim_of = dict(zip(idx.tolist(), sims.tolist()))
        hits, seen = [], set()
        for i in order.tolist():
            key = (self.chunks[i]["source_type"], self.chunks[i]["source_id"])
            if dedupe and key in seen:
                continue
            seen.add(key)
            hits.append(Hit(len(hits) + 1, round(float(sim_of[i]), 4), self.chunks[i]))
            if len(hits) >= k:
                break
        return hits

    def search(self, query: str, *, ctpv: str | None = None, sgg: str | None = None, **kw) -> list[Hit]:
        """질문 글 → 근거. ctpv·sgg는 앱 프로필 문자열 그대로(정규화는 여기서)."""
        if self.embedder is None:
            raise RuntimeError("embedder 가 없어 질문을 임베딩할 수 없음")
        region = self.resolve(ctpv, sgg) if ctpv else None
        return self.search_vector(self.embedder.embed_query(query), region=region, **kw)


def format_context(hits: list[Hit]) -> str:
    """대화 AI 프롬프트에 넣을 근거 글. 번호·출처·확인 시각을 붙인다."""
    out = []
    for h in hits:
        c = h.chunk
        meta = ", ".join(x for x in [c.get("source_url") or "", f"확인 {c['source_checked_at'][:10]}"
                                     if c.get("source_checked_at") else ""] if x)
        out.append(f"[{h.rank}] {c['content']}" + (f"\n(출처: {meta})" if meta else ""))
    return "\n\n".join(out)
