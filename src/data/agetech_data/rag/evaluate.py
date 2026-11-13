"""검색 평가: 평가 질문 → Hit@1·3·5, MRR@10, '근거 없음' 문턱값 제안 → 보고서.

    uv run python -m agetech_data.rag.evaluate        # docs/data/rag_search_report.md 생성

- 질문: resources/rag_eval_questions.json (프로필 지역 = 시범 지역 대구 남구)
- 두 방식으로 잰다. 전체 검색 = 복지·레시피를 한꺼번에(AI가 종류를 모를 때, 더 엄격) /
  종류 지정 = 복지 질문은 복지만, 레시피 질문은 레시피만.
- 정답 판정은 같은 원본(source_id) 기준. 같은 원본의 청크 여러 개는 가장 가까운 하나만 센다.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from agetech_data import paths
from agetech_data.rag.search import FOOD_TYPES, RECIPE_TYPES, SEASONAL_TYPES, WELFARE_TYPES, IndexSearcher

K = 10


def load_questions(path: Path = paths.RAG_EVAL_QUESTIONS) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def gold_ids(q: dict, chunks: list[dict]) -> set[tuple[str, str]]:
    """(원천 묶음, source_id) 집합. 원천 묶음은 'welfare' / 'recipe' / 'seasonal'."""
    if q["kind"] == "welfare":
        return {("welfare", i) for i in q.get("ids", [])}
    if q["kind"] == "recipe":
        titles = {c["source_id"]: c["title"] for c in chunks if c["source_type"] == "recipe"}
        any_, all_ = q.get("name_any"), q.get("name_all")
        return {("recipe", sid) for sid, t in titles.items()
                if (any_ and any(w in t for w in any_)) or (all_ and all(w in t for w in all_))}
    if q["kind"] == "seasonal":     # 같은 식재료가 여러 달에 나오면(source_id 가 달라도) 이름이 같으면 정답
        names = set(q.get("names", []))
        return {("seasonal", c["source_id"]) for c in chunks
                if c["source_type"] == "seasonal" and c["title"].split(" ", 1)[1] in names}
    return set()


def _group(source_type: str) -> str:
    return source_type if source_type in ("recipe", "seasonal") else "welfare"


TYPES_BY_KIND = {"welfare": WELFARE_TYPES, "recipe": RECIPE_TYPES, "seasonal": SEASONAL_TYPES}
# AI 도우미가 쓰는 주제 묶음: 복지 / 음식(레시피 + 제철 식재료)
TOPIC_BY_KIND = {"welfare": WELFARE_TYPES, "recipe": FOOD_TYPES, "seasonal": FOOD_TYPES}
MODES = (("전체 검색", "all"), ("주제 묶음", "topic"), ("종류 지정", "typed"))


def run(searcher: IndexSearcher, embedder, questions: dict) -> dict:
    prof = questions.get("profile") or {}
    region = searcher.resolve(prof.get("ctpv"), prof.get("sgg")) if prof.get("ctpv") else None
    embedder.embed_query("준비")          # 모델 올리기·첫 호출은 시간 측정에서 뺀다
    rows, latencies = [], []
    for q in questions["questions"]:
        gold = gold_ids(q, searcher.chunks)
        t = time.perf_counter()
        qvec = embedder.embed_query(q["q"])
        latencies.append(time.perf_counter() - t)
        result = {"id": q["id"], "kind": q["kind"], "q": q["q"], "gold_count": len(gold)}
        for mode, types in (("all", None), ("topic", TOPIC_BY_KIND.get(q["kind"])), ("typed", TYPES_BY_KIND.get(q["kind"]))):
            hits = searcher.search_vector(qvec, k=K, source_types=types, region=region)
            rank = next((h.rank for h in hits if (_group(h.chunk["source_type"]), h.source_id) in gold), None)
            result[mode] = {
                "rank": rank,
                "top1_similarity": hits[0].similarity if hits else None,
                "hits": [{"rank": h.rank, "source_type": h.chunk["source_type"], "source_id": h.source_id,
                          "title": h.title, "similarity": h.similarity,
                          "gold": (_group(h.chunk["source_type"]), h.source_id) in gold} for h in hits[:5]],
            }
        rows.append(result)
    return {"region": None if region is None else {"ctpv": region.ctpv, "sgg": region.sgg, "notes": region.notes},
            "rows": rows, "query_latency_sec": latencies}


def metrics(rows: list[dict], mode: str) -> dict:
    out = {}
    for kind in ("welfare", "recipe", "seasonal"):
        rs = [r for r in rows if r["kind"] == kind]
        if not rs:
            continue
        ranks = [r[mode]["rank"] for r in rs]
        out[kind] = {
            "n": len(rs),
            **{f"hit@{k}": round(sum(1 for x in ranks if x and x <= k) / len(rs), 3) for k in (1, 3, 5)},
            "mrr@10": round(sum(1 / x for x in ranks if x) / len(rs), 3),
        }
    return out


def suggest_threshold(rows: list[dict], mode: str = "all") -> dict:
    """정답이 1위인 질문의 1위 유사도 vs 정답 없는 질문의 1위 유사도 → 둘을 가장 잘 가르는 값."""
    pos = sorted(r[mode]["top1_similarity"] for r in rows
                 if r["kind"] != "none" and r[mode]["rank"] == 1 and r[mode]["top1_similarity"] is not None)
    neg = sorted(r[mode]["top1_similarity"] for r in rows
                 if r["kind"] == "none" and r[mode]["top1_similarity"] is not None)
    if not pos or not neg:
        return {"positives": pos, "negatives": neg, "threshold": None}
    candidates = sorted(set(pos + neg))
    best = None
    for i, t in enumerate(candidates):
        # t 이상이면 '근거 있음'. 정답 질문은 남기고 정답 없는 질문은 거르는 수
        mid = t if i == 0 else (candidates[i - 1] + t) / 2
        kept = sum(1 for p in pos if p >= mid)
        rejected = sum(1 for n in neg if n < mid)
        score = (kept / len(pos) + rejected / len(neg)) / 2
        if best is None or score > best[0] + 1e-9:
            best = (score, mid, kept, rejected)
    _, th, kept, rejected = best
    return {"positives": pos, "negatives": neg, "threshold": round(th, 3),
            "kept_positives": kept, "rejected_negatives": rejected,
            "separable": max(neg) < min(pos)}


def _pct(v: float) -> str:
    return f"{v * 100:.0f}%"


SOURCE_LABELS = {"welfare_central": "복지(중앙부처)", "welfare_local": "복지(지자체)", "recipe": "레시피",
                 "seasonal": "이달의 식재료"}


def render_sources(manifest: dict) -> list[str]:
    """manifest['sources'] → 청크 산출 근거 표 (원본 → 제외 → 색인 → 나뉜 원본 → 청크)."""
    src = manifest.get("sources")
    if not src:
        return []
    lines = ["### 청크 산출 근거", "",
             "| 원천 | 원본 | 제외 | 색인한 원본 | 그중 나뉜 원본 | 청크 | 원본당 최대 |",
             "|---|---:|---|---:|---:|---:|---:|"]
    total = 0
    for st, s in src.items():
        ex = ", ".join(f"{k} {v}" for k, v in s["excluded"].items()) or "—"
        lines.append(f"| {SOURCE_LABELS.get(st, st)} | {s['records']:,} | {ex} | {s['indexed_records']:,} | "
                     f"{s['split_records']:,} | {s['chunks']:,} | {s['max_chunks_per_record']} |")
        total += s["chunks"]
    lines += [f"| 합계 | | | | | {total:,} | |", "",
              "- 청크 수 = 색인한 원본 수 + 나뉜 원본이 늘린 조각 수. 1,000자를 넘는 원본만 항목 경계로 나눈다.",
              "- 레시피 제외 `hold` = 조리 단계 누락 등 노출 보류(`recipe_contract.md` 규칙 3). "
              "보완표로 고친 레시피는 보완 후 행으로 만든다(`recipes.contract --corrections`).",
              "- 이달의 식재료는 상세(유래·영양·고르는 법·보관·먹는 법)를 받은 게시 식재료만 색인한다.", ""]
    return lines


def render_report(manifest: dict, result: dict, questions: dict) -> str:
    rows = result["rows"]
    th = suggest_threshold(rows, "all")
    lat = sorted(result["query_latency_sec"])
    reg = result["region"] or {}
    kinds = {"welfare": "복지", "recipe": "레시피", "seasonal": "제철 식재료"}
    lines = [
        "# RAG 검색 평가 보고서 (KURE-v1, 시범 지역 대구 남구)",
        "",
        "> 이 파일은 `uv run python -m agetech_data.rag.evaluate`로 생성됩니다. 직접 고치지 마세요.",
        "",
        "| 항목 | 값 |",
        "|---|---|",
        f"| 모델 | `{manifest['model_id']}` ({manifest['dim']}차원, fp32 원본) |",
        f"| 인덱스 | 청크 {manifest['count']}개 ({', '.join(f'{k} {v}' for k, v in manifest['by_source_type'].items())}), "
        f"생성 {manifest['built_at']} |",
        f"| 인덱스 판본 | `{manifest.get('index_version', '—')}` |",
        f"| 원천 판본 | {', '.join(f'`{v}`' for v in manifest['data_versions'])} |",
        f"| 프로필 지역 | 입력 `{questions['profile']['ctpv']} {questions['profile']['sgg']}` → "
        f"`{reg.get('ctpv')} {reg.get('sgg')}` (전국 + 대구시 전체 + 남구 사업만 검색) |",
        f"| 질문 | {len(rows)}개 — 복지 {sum(r['kind'] == 'welfare' for r in rows)}, "
        f"레시피 {sum(r['kind'] == 'recipe' for r in rows)}, 제철 식재료 {sum(r['kind'] == 'seasonal' for r in rows)}, "
        f"정답 없음 {sum(r['kind'] == 'none' for r in rows)} |",
        "",
    ]
    lines += render_sources(manifest)
    lines += [
        "## 1. 요약",
        "",
        "| 방식 | 종류 | 질문 | Hit@1 | Hit@3 | Hit@5 | MRR@10 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for label, mode in MODES:
        for kind, v in metrics(rows, mode).items():
            lines.append(f"| {label} | {kinds[kind]} | {v['n']} | {_pct(v['hit@1'])} | {_pct(v['hit@3'])} | "
                         f"{_pct(v['hit@5'])} | {v['mrr@10']:.3f} |")
    lines += [
        "",
        "- **전체 검색**: 복지·레시피·제철 식재료를 한꺼번에 검색. **주제 묶음**(AI 도우미 권장): 복지 질문은 복지만, "
        "음식 질문(레시피·제철)은 레시피 + 제철 식재료. **종류 지정**: 레시피 질문은 레시피만, 제철 질문은 제철만.",
        "- 전체 검색은 계절 말이 든 복지 질문(예: 겨울 난방비)에서 제철 식재료가 상위를 차지할 수 있어, AI 도우미는 "
        "질문 주제(복지 / 음식)를 먼저 정하고 그 묶음만 검색한다(`search.WELFARE_TYPES` / `search.FOOD_TYPES`).",
        "- Hit@k: 정답 사업·레시피가 상위 k개 안에 있는 질문 비율. 같은 원본의 청크 여러 개는 가장 가까운 하나만 셈.",
        "- 레시피 정답은 이름 규칙(예: 이름에 '죽')을 만족하는 레시피 전부라 복지보다 쉬움.",
        "",
        "## 2. '근거 없음' 문턱값",
        "",
    ]
    if th["threshold"] is not None:
        lines += [
            f"- 정답이 1위인 질문 {len(th['positives'])}개의 1위 유사도: 최소 {min(th['positives']):.3f}, "
            f"중앙값 {statistics.median(th['positives']):.3f}",
            f"- 정답 없는 질문 {len(th['negatives'])}개의 1위 유사도: 최대 {max(th['negatives']):.3f}, "
            f"중앙값 {statistics.median(th['negatives']):.3f}",
            f"- **제안 문턱값 {th['threshold']:.3f}** (전체 검색 기준): 1위 유사도가 이보다 낮으면 '근거 없음'으로 보고 "
            f"공식 문의처를 안내. 이 값에서 정답 질문 {th['kept_positives']}/{len(th['positives'])}개를 남기고 "
            f"정답 없는 질문 {th['rejected_negatives']}/{len(th['negatives'])}개를 거름"
            + ("" if th["separable"] else " — **두 분포가 겹침**: 문턱값만으로 완전히 가를 수 없어 대화 AI도 근거와 질문이 맞는지 한 번 더 확인해야 함"),
            "- 질문 수가 적어 잠정값. 실제 이용 질문이 쌓이면 다시 정한다.",
        ]
    lines += [
        "",
        "## 3. 질문별 결과 (전체 검색)",
        "",
        "| ID | 질문 | 정답 순위 | 1위 | 2위 | 3위 |",
        "|---|---|---:|---|---|---|",
    ]
    for r in rows:
        hits = r["all"]["hits"]
        cells = []
        for h in hits[:3]:
            mark = "**" if h["gold"] else ""
            cells.append(f"{mark}{h['title']}{mark} ({h['similarity']:.3f})")
        cells += [""] * (3 - len(cells))
        rank = "—" if r["kind"] == "none" else (str(r["all"]["rank"]) if r["all"]["rank"] else f">{K}")
        if r["kind"] != "none" and r.get("topic") and r["topic"]["rank"] != r["all"]["rank"]:
            rank += f" (주제 묶음 {r['topic']['rank'] or f'>{K}'})"
        lines.append(f"| {r['id']} | {r['q']} | {rank} | " + " | ".join(cells) + " |")
    lines += ["", "굵은 글씨 = 정답.", ""]
    missed = [r for r in rows if r["kind"] != "none" and not (r["all"]["rank"] and r["all"]["rank"] <= 5)]
    lines += ["## 4. 상위 5개 안에 정답이 없는 질문", ""]
    if missed:
        for r in missed:
            lines.append(f"- {r['id']} \"{r['q']}\" — " + ", ".join(
                f"{label} 순위 {r[mode]['rank'] or f'>{K}'}" for label, mode in MODES if mode in r))
    else:
        lines.append("- 없음")
    lines += [
        "",
        "## 5. 질문 임베딩 시간 (이 보고서를 만든 컴퓨터)",
        "",
        f"- {len(lat)}회: 중앙값 {statistics.median(lat) * 1000:.0f}ms, 최대 {max(lat) * 1000:.0f}ms "
        "(모델을 올리고 1회 준비한 뒤). 서버 실측은 `python -m agetech_data.rag.bench`",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="RAG 검색 평가 보고서")
    ap.add_argument("--index", type=Path, default=paths.RAG_INDEX_DIR)
    ap.add_argument("--questions", type=Path, default=paths.RAG_EVAL_QUESTIONS)
    ap.add_argument("--report", type=Path, default=paths.RAG_SEARCH_REPORT)
    ap.add_argument("--detail", type=Path, default=paths.RAG_INDEX_DIR / "eval_detail.json")
    args = ap.parse_args(argv)

    from agetech_data.rag.embedder import KureEmbedder
    from agetech_data.rag.index import load_index

    manifest, chunks, vectors = load_index(args.index)
    emb = KureEmbedder()
    questions = load_questions(args.questions)
    searcher = IndexSearcher(chunks, vectors, emb, model_id=manifest["model_id"])
    result = run(searcher, emb, questions)
    args.report.write_text(render_report(manifest, result, questions), encoding="utf-8", newline="\n")
    args.detail.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for label, mode in MODES:
        print(label, json.dumps(metrics(result["rows"], mode), ensure_ascii=False))
    print("문턱값", json.dumps({k: v for k, v in suggest_threshold(result["rows"]).items()
                                if k not in ("positives", "negatives")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
