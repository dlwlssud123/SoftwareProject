"""AI 도우미 API 인계용 근거 표본: 질문 → 실제 검색 근거(프롬프트에 넣을 글) / 근거 없음 예시.

    uv run python -m agetech_data.rag.samples        # docs/data/samples/rag_context_sample.json

표본마다 앱 프로필 입력, 해석한 지역, 검색 조건, 상위 5개 근거(본문 전체·출처·확인 시각·유사도),
근거 판단(ok/weak/none), 프롬프트에 그대로 넣을 context 글을 담는다. 형식은 docs/data/rag_index_contract.md 5절.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from agetech_data import paths
from agetech_data.rag.search import (
    NO_EVIDENCE_BELOW,
    RECIPE_TYPES,
    WEAK_BELOW,
    WELFARE_TYPES,
    IndexSearcher,
    evidence_status,
    format_context,
)

SAMPLE_PATH = paths.REPORTS_DIR / "samples" / "rag_context_sample.json"
K = 5

# (id, 설명, 질문, 프로필 시도·시군구, 원천 종류, 알레르기)
CASES = [
    ("welfare_district", "대구 남구 사업이 1위 (시군구 사업)", "우리 동네에 머리 깎는 거 싸게 해 주는 데가 있다던데",
     ("대구", "남구"), "welfare", None),
    ("welfare_district_2", "대구 남구 사업 — 100세 어르신", "우리 어머니가 올해 백 살이신데 구청에서 뭐 주는 게 있나요",
     ("대구", "남구"), "welfare", None),
    ("welfare_province", "대구시 전체 사업이 1위", "밥 해 먹기가 힘든데 도시락 같은 거 집으로 갖다주는 데 없나",
     ("대구", "남구"), "welfare", None),
    ("welfare_mixed", "전국·남구 사업이 함께 (근거 약함 구간)", "혼자 사는데 누가 가끔 들여다보고 안부 좀 물어봐 주는 거 없나요",
     ("대구", "남구"), "welfare", None),
    ("welfare_national_rank2", "정답(기초연금)이 2위 — 상위 5개를 다 넘겨야 하는 이유", "65살 넘으면 나라에서 매달 주는 돈이 있다던데 그게 뭐예요?",
     ("대구", "남구"), "welfare", None),
    ("welfare_other_region", "서울 노원구 사용자 — 대구 남구 사업(경로우대사업)은 나오지 않아야 함",
     "우리 동네에 머리 깎는 거 싸게 해 주는 데가 있다던데", ("서울", "노원구"), "welfare", None),
    ("welfare_merged_region", "옛 이름 '광주광역시' 입력 → 전남광주통합특별시로 검색", "혼자 사는 노인 밥 챙겨 주는 서비스 있어요?",
     ("광주광역시", "광산구"), "welfare", None),
    ("recipe", "레시피 — 부드러운 음식", "속이 안 좋을 때 끓여 먹을 죽 좀 알려 줘", None, "recipe", None),
    ("recipe_allergy", "레시피 — 대두·알류 알레르기 사용자. 두부·달걀이 든 레시피는 모두 빠지므로 "
                       "대화 AI가 '대두 알레르기라 두부 요리는 뺐다'고 함께 말해야 함",
     "이가 시원찮아서 부드럽게 넘어가는 두부 반찬 뭐 있을까", None, "recipe", ["대두", "알류"]),
    ("none_low", "정답 없음 — 유사도가 낮아 근거 없음", "휴대폰 사진을 컴퓨터로 옮기는 방법", ("대구", "남구"), None, None),
    ("none_weak", "정답 없음인데 유사도가 꽤 나옴 — 대화 AI가 걸러야 함", "강아지 사료값도 지원해 주나요?",
     ("대구", "남구"), None, None),
    ("none_word_overlap", "정답 없음 — 글자만 겹침(날씨의 '대구' ↔ 생선 대구 요리)", "오늘 대구 날씨 어때요",
     ("대구", "남구"), None, None),
]

PROMPT_RULES = [
    "아래 [근거]에 있는 내용만으로 답한다. 근거에 없는 사업명·금액·전화번호·날짜는 만들지 않는다.",
    "근거가 질문과 맞지 않으면 '확인되지 않는다'고 말하고 공식 문의처(보건복지상담센터 129, 주민센터)를 안내한다.",
    "수급 자격을 판정하지 않는다. '대상·기준은 원문과 문의처로 확인'을 함께 안내한다.",
    "근거 번호와 출처(복지로 링크·확인 날짜)를 답 끝에 붙인다.",
    "레시피 영양값은 원문 값이고 기준량이 확인되지 않았다고 말한다. 알레르기는 재료를 직접 확인하라고 안내한다.",
]


def _types(kind: str | None):
    return WELFARE_TYPES if kind == "welfare" else RECIPE_TYPES if kind == "recipe" else None


def build_samples(searcher: IndexSearcher, manifest: dict, cases=CASES) -> dict:
    out = []
    for cid, desc, question, prof, kind, allergies in cases:
        region = searcher.resolve(*prof) if prof else None
        hits = searcher.search_vector(searcher.embedder.embed_query(question), k=K, source_types=_types(kind),
                                      region=region, allergies=allergies)
        status = evidence_status(hits)
        out.append({
            "id": cid, "description": desc, "question": question,
            "profile": None if not prof else {"ctpv_input": prof[0], "sgg_input": prof[1],
                                              "ctpv": region.ctpv, "sgg": region.sgg, "notes": region.notes},
            "filters": {"source_types": list(_types(kind) or []) or "all", "allergies": allergies or []},
            "evidence_status": status,
            "top1_similarity": hits[0].similarity if hits else None,
            "hits": [{"rank": h.rank, "similarity": h.similarity,
                      **{k: h.chunk[k] for k in ("chunk_id", "source_type", "source_id", "title", "section",
                                                  "region_scope", "ctpv", "sgg", "source_url", "source_checked_at",
                                                  "quality_status", "allergens", "content")}} for h in hits],
            "context": "" if status == "none" else format_context(hits),
        })
    return {
        "schema_version": 1,
        "description": "AI 도우미 API 인계용 RAG 근거 표본. `python -m agetech_data.rag.samples`로 생성 — 직접 고치지 마세요.",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "index": {k: manifest[k] for k in ("index_version", "model_id", "count", "data_versions")},
        "evidence_rules": {
            "none": f"1위 유사도 < {NO_EVIDENCE_BELOW} — 근거를 주지 않고 '확인되지 않음' + 공식 문의처",
            "weak": f"{NO_EVIDENCE_BELOW} ≤ 1위 < {WEAK_BELOW} — 근거를 주되 질문과 맞는지 대화 AI가 확인(정답 질문·정답 없는 질문이 섞이는 구간)",
            "ok": f"1위 ≥ {WEAK_BELOW} — 근거로 답함(그래도 PROMPT_RULES 지킴)",
        },
        "prompt_rules": PROMPT_RULES,
        "samples": out,
    }


def main(argv: list[str] | None = None) -> int:
    from agetech_data.rag.embedder import KureEmbedder

    ap = argparse.ArgumentParser(description="AI 도우미 API 인계용 RAG 근거 표본")
    ap.add_argument("--index", type=Path, default=paths.RAG_INDEX_DIR)
    ap.add_argument("--out", type=Path, default=SAMPLE_PATH)
    args = ap.parse_args(argv)
    from agetech_data.rag.index import load_index

    manifest, chunks, vectors = load_index(args.index)
    searcher = IndexSearcher(chunks, vectors, KureEmbedder(), model_id=manifest["model_id"])
    result = build_samples(searcher, manifest)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    for s in result["samples"]:
        top = s["hits"][0] if s["hits"] else None
        print(f"{s['id']:24} {s['evidence_status']:5} "
              + (f"{top['similarity']:.3f} {top['title']}" if top else "(결과 없음)"))
    print(f"→ {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
