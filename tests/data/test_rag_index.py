"""RAG 인덱스 갱신·검색·평가 (가짜 임베더, numpy 필요: uv sync --extra embed)."""

import copy
import json
from datetime import date

import pytest

np = pytest.importorskip("numpy")

from rag_samples import FakeEmbedder, payloads  # noqa: E402

from agetech_data.rag import index as ix  # noqa: E402
from agetech_data.rag.index import build_index, load_index  # noqa: E402
from agetech_data.rag.search import RECIPE_TYPES, WELFARE_TYPES, IndexSearcher, format_context  # noqa: E402


def test_build_index_reuses_unchanged_and_lists_changes(tmp_path):
    welfare, recipes = payloads()
    emb = FakeEmbedder()
    m1 = build_index(welfare, recipes, emb, index_dir=tmp_path)
    assert m1["count"] == 7 and m1["embedded_this_run"] == 7 and m1["changes"]["added"] == 7
    manifest, chunks, vectors = load_index(tmp_path)
    assert vectors.shape == (7, 64) and chunks[0]["chunk_id"].startswith("welfare_central:")
    assert manifest["model_id"] == "fake@1" and manifest["by_source_type"]["recipe"] == 2

    m2 = build_index(welfare, recipes, emb, index_dir=tmp_path)          # 그대로 → 임베딩 0
    assert m2["embedded_this_run"] == 0 and m2["changes"]["unchanged"] == 7

    welfare2 = copy.deepcopy(welfare)
    welfare2["records"][0]["benefits"] = "월 보상금 15만원 지급"
    welfare2["records"] = [r for r in welfare2["records"] if r["serv_id"] != "WLF9"]
    m3 = build_index(welfare2, recipes, emb, index_dir=tmp_path)
    changes = json.loads((tmp_path / "changes.json").read_text(encoding="utf-8"))
    assert m3["embedded_this_run"] == 1
    assert changes["changed"] == ["welfare_local:WLF00004828:all:1"]
    assert changes["removed"] == ["welfare_local:WLF9:all:1"] and changes["added"] == []

    assert build_index(welfare2, recipes, FakeEmbedder("other@2"), index_dir=tmp_path)["embedded_this_run"] == 6


def test_cache_survives_interrupted_run(tmp_path, monkeypatch):
    welfare, recipes = payloads()

    class Boom(FakeEmbedder):
        def embed_passages(self, texts, show_progress=False):
            if self.calls:
                raise KeyboardInterrupt
            return super().embed_passages(texts)

    monkeypatch.setattr(ix, "SAVE_EVERY", 3)
    with pytest.raises(KeyboardInterrupt):
        build_index(welfare, recipes, Boom(), index_dir=tmp_path)
    assert not (tmp_path / "manifest.json").exists()                      # 끝나지 않은 인덱스는 없음
    emb = FakeEmbedder()
    m = build_index(welfare, recipes, emb, index_dir=tmp_path)
    assert m["embedded_this_run"] == 4 and emb.calls == 4                   # 앞의 3개는 캐시에서


def test_load_index_detects_tampering(tmp_path):
    build_index(*payloads(), FakeEmbedder(), index_dir=tmp_path)
    with (tmp_path / "chunks.jsonl").open("a", encoding="utf-8") as f:
        f.write("\n")
    with pytest.raises(RuntimeError):
        load_index(tmp_path)


def _searcher(tmp_path, **kw):
    build_index(*payloads(**kw.pop("payload", {})), FakeEmbedder(), index_dir=tmp_path, **kw)
    _, chunks, vectors = load_index(tmp_path)
    return IndexSearcher(chunks, vectors, FakeEmbedder())


def test_search_filters_region_ended_allergens(tmp_path):
    s = _searcher(tmp_path)
    region = s.resolve("대구", "남구")
    assert (region.ctpv, region.sgg) == ("대구광역시", "남구")
    hits = s.search("이미용 할인", ctpv="대구", sgg="남구", k=10, source_types=WELFARE_TYPES,
                    as_of=date(2026, 11, 7))
    assert {h.source_id for h in hits} == {"WLF00004828", "WLF00001164", "WLF8"}   # 부산 남구·끝난 사업 없음
    assert hits[0].source_id == "WLF00004828" and hits[0].rank == 1
    assert {h.source_id for h in s.search("기초연금", k=10, source_types=WELFARE_TYPES)} == {"WLF00001164"}
    ended = s.search("끝난 사업", ctpv="대구", sgg="남구", k=10, include_ended=True, as_of=date(2026, 11, 7))
    assert "WLF7" in {h.source_id for h in ended}
    no_soy = s.search("두부 계란찜", k=10, source_types=RECIPE_TYPES, allergies=["대두"])
    assert [h.source_id for h in no_soy] == ["397"]
    assert format_context(no_soy).startswith("[1] [레시피] 호박죽")


def test_dedupe_keeps_best_chunk_per_source(tmp_path):
    s = _searcher(tmp_path, max_chars=600, payload={"benefits": "지원 내용 문장입니다. " * 120})
    hits = s.search("지원 내용 문장", ctpv="대구", sgg="남구", k=10)
    keys = [(h.chunk["source_type"], h.source_id) for h in hits]
    assert len(keys) == len(set(keys))
    assert len(s.search("지원 내용 문장", ctpv="대구", sgg="남구", k=50, dedupe=False)) > len(hits)


def test_export_csv_matches_table_columns(tmp_path):
    import csv

    from agetech_data.rag.export import COLUMNS, pg_array, pg_vector, write_csv

    assert pg_array([]) == "{}" and pg_array(['a"b', "c,d"]) == '{"a\\"b","c,d"}'
    assert pg_vector([0.5, -0.25]) == "[0.5,-0.25]"
    build_index(*payloads(), FakeEmbedder(), index_dir=tmp_path)
    manifest, chunks, vectors = load_index(tmp_path)
    n = write_csv(manifest, chunks, vectors, tmp_path / "rag_chunk.csv")
    with (tmp_path / "rag_chunk.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert n == len(rows) == 7 and list(rows[0]) == COLUMNS
    assert {r["index_version"] for r in rows} == {manifest["index_version"]}
    nat = next(r for r in rows if r["source_id"] == "WLF00001164")
    assert nat["ctpv"] == "" and nat["region_scope"] == "national" and nat["embedding_model"] == "fake@1"
    assert len(nat["embedding"].strip("[]").split(",")) == 64
    assert next(r for r in rows if r["source_id"] == "28")["allergens"] == '{"대두","알류"}'


def test_load_script_registers_loading_then_switches_only_when_counts_match(tmp_path):
    from agetech_data.rag.export import load_script

    build_index(*payloads(), FakeEmbedder(), index_dir=tmp_path)
    manifest, _, _ = load_index(tmp_path)
    sql = load_script(manifest, "a" * 64)
    v = manifest["index_version"]
    assert f"WHERE index_version = '{v}') AS already" in sql                     # 같은 판본이면 건너뜀
    assert sql.index("'loading'") < sql.index("\\copy rag_chunk (index_version, chunk_id") < sql.index("AS ok")
    assert "count(*) = 7 AND coalesce(bool_and(embedding_model = 'fake@1'), false) AS ok" in sql
    switch = sql[sql.index("\\if :ok"):]
    assert switch.index("SET status = 'retired' WHERE status = 'active'") < switch.index("SET status = 'active'")
    assert "SET status = 'failed'" in switch and "RAISE EXCEPTION" in switch


def test_index_version_kept_when_unchanged_and_new_when_changed(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    welfare, recipes = payloads()
    times = iter([datetime(2026, 11, 7, 1, 0, tzinfo=timezone.utc), datetime(2026, 11, 8, 1, 0, tzinfo=timezone.utc)])
    monkeypatch.setattr(ix, "new_index_version", lambda now=None: next(times).strftime("%Y%m%dT%H%M%SZ"))
    assert build_index(welfare, recipes, FakeEmbedder(), index_dir=tmp_path)["index_version"] == "20261107T010000Z"
    assert build_index(welfare, recipes, FakeEmbedder(), index_dir=tmp_path)["index_version"] == "20261107T010000Z"
    welfare["records"] = welfare["records"][1:]
    assert build_index(welfare, recipes, FakeEmbedder(), index_dir=tmp_path)["index_version"] == "20261108T010000Z"


def test_manifest_sources_explain_chunk_counts(tmp_path):
    from rag_samples import recipe_rec

    welfare, recipes = payloads(benefits="지원 내용 문장입니다. " * 120)
    recipes["records"].append(recipe_rec("33", status="hold"))
    m = build_index(welfare, recipes, FakeEmbedder(), index_dir=tmp_path, max_chars=600)
    r = m["sources"]["recipe"]
    assert (r["records"], r["excluded"], r["indexed_records"], r["chunks"]) == (3, {"hold": 1}, 2, 2)
    local = m["sources"]["welfare_local"]
    assert local["records"] == local["indexed_records"] == 4 and local["split_records"] == 4
    assert local["chunks"] == m["by_source_type"]["welfare_local"] > 4
    assert sum(s["chunks"] for s in m["sources"].values()) == m["count"]


def test_metadata_only_change_makes_new_version_without_reembedding(tmp_path, monkeypatch):
    welfare, recipes = payloads()
    times = iter(["V1", "V2"])
    monkeypatch.setattr(ix, "new_index_version", lambda now=None: next(times))
    emb = FakeEmbedder()
    build_index(welfare, recipes, emb, index_dir=tmp_path)
    welfare["records"][0]["period_end"] = "2026-12-31"          # 본문 밖 칸만 바뀜
    m = build_index(welfare, recipes, emb, index_dir=tmp_path)
    assert m["index_version"] == "V2" and m["changes"]["changed"] == 1 and m["embedded_this_run"] == 0
    _, chunks, _ = load_index(tmp_path)
    assert next(c for c in chunks if c["source_id"] == "WLF00004828")["period_end"] == "2026-12-31"


def test_search_uses_only_chunks_matching_active_source_records(tmp_path):
    s = _searcher(tmp_path)
    region = s.resolve("대구", "남구")
    q = FakeEmbedder().embed_query("이미용 할인")
    active = {(c["source_type"], c["source_id"]): c["source_record_sha256"] for c in s.chunks}
    assert all(active.values())                                      # 모든 청크에 원본 해시가 있음
    assert s.search_vector(q, region=region, active_sources=active)[0].source_id == "WLF00004828"
    gone = {k: v for k, v in active.items() if k[1] != "WLF00004828"}            # 원본 표에서 내려감
    assert "WLF00004828" not in {h.source_id for h in s.search_vector(q, region=region, active_sources=gone)}
    stale = {**active, ("welfare_local", "WLF00004828"): "0" * 64}           # 원본이 바뀌었는데 인덱스는 옛것
    assert "WLF00004828" not in {h.source_id for h in s.search_vector(q, region=region, active_sources=stale)}


def test_searcher_refuses_other_model(tmp_path):
    from agetech_data.rag.search import IndexSearcher

    build_index(*payloads(), FakeEmbedder(), index_dir=tmp_path)
    assert IndexSearcher.from_index(tmp_path, FakeEmbedder()).model_id == "fake@1"
    with pytest.raises(ValueError):
        IndexSearcher.from_index(tmp_path, FakeEmbedder("other@2"))


def test_evaluate_metrics_and_threshold():
    from agetech_data.rag.evaluate import gold_ids, metrics, suggest_threshold

    chunks = [{"source_type": "recipe", "source_id": "1", "title": "호박죽"},
              {"source_type": "recipe", "source_id": "2", "title": "버섯 된장국"},
              {"source_type": "recipe", "source_id": "3", "title": "버섯볶음"}]
    assert gold_ids({"kind": "recipe", "name_any": ["죽"]}, chunks) == {("recipe", "1")}
    assert gold_ids({"kind": "recipe", "name_all": ["버섯", "국"]}, chunks) == {("recipe", "2")}
    assert gold_ids({"kind": "welfare", "ids": ["W1"]}, chunks) == {("welfare", "W1")}

    def row(kind, rank, sim):
        return {"kind": kind, "all": {"rank": rank, "top1_similarity": sim}, "typed": {"rank": rank}}
    rows = [row("welfare", 1, 0.7), row("welfare", 3, 0.5), row("welfare", None, 0.4),
            row("recipe", 1, 0.8), row("none", None, 0.3), row("none", None, 0.45)]
    assert metrics(rows, "all")["welfare"] == {"n": 3, "hit@1": 0.333, "hit@3": 0.667, "hit@5": 0.667,
                                               "mrr@10": 0.444}
    th = suggest_threshold(rows)
    assert th["separable"] and 0.45 < th["threshold"] <= 0.7
    assert th["kept_positives"] == 2 and th["rejected_negatives"] == 2


def test_evaluate_run_end_to_end(tmp_path):
    from agetech_data.rag.evaluate import render_report, run

    s = _searcher(tmp_path)
    questions = {"profile": {"ctpv": "대구", "sgg": "남구"}, "questions": [
        {"id": "W1", "kind": "welfare", "q": "이미용 할인", "ids": ["WLF00004828"]},
        {"id": "R1", "kind": "recipe", "q": "호박죽", "name_any": ["죽"]},
        {"id": "N1", "kind": "none", "q": "자동차 엔진오일"}]}
    result = run(s, FakeEmbedder(), questions)
    assert result["region"]["sgg"] == "남구"
    assert [r["all"]["rank"] for r in result["rows"]][:2] == [1, 1]
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    report = render_report(manifest, result, questions)
    assert "| W1 | 이미용 할인 | 1 | **경로우대사업**" in report
    assert "제안 문턱값" in report
