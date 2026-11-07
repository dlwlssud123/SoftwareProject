"""서버 실측 도구의 판정·동시 측정·프로세스 메모리 (모델 없이)."""

import time

from agetech_data.rag import bench


def test_judge_thresholds():
    q_ok = {"p95_ms": 400}
    mem = {"available": 4000, "swap_used": 100}
    assert all(bench.judge(q_ok, None, mem, mem, mem).values())
    assert bench.judge({"p95_ms": 600}, None, mem, mem, mem)["p95_ok"] is False
    conc = {"p95_ms": 1200}
    assert bench.judge(q_ok, conc, mem, mem, mem)["concurrent_p95_ok"] is False
    low = {"available": 900, "swap_used": 100}
    assert bench.judge(q_ok, None, mem, low, mem)["memory_ok"] is False
    grown = {"available": 4000, "swap_used": 300}
    assert bench.judge(q_ok, None, mem, mem, grown)["swap_ok"] is False
    unknown = {"available": None, "swap_used": None}
    assert set(bench.judge(q_ok, None, unknown, unknown, unknown)) == {"p95_ok"}   # 모르는 값은 판정하지 않음


def test_concurrent_latency_runs_jobs_in_parallel():
    def slow(q):
        time.sleep(0.05)

    lat, wall = bench.concurrent_latency(slow, ["a", "b", "c", "d"], concurrency=4, rounds=2)
    assert len(lat) == 8 and all(x >= 0.04 for x in lat)
    assert wall < 0.05 * 8 * 0.75                     # 순서대로였다면 0.4초 — 동시라 훨씬 짧음


def test_stats_top_processes_and_passages():
    s = bench._stats([0.1, 0.2, 0.3, 0.4])
    assert s["n"] == 4 and s["max_ms"] == 400 and s["p50_ms"] == 250
    top = bench.top_processes()
    assert set(top) == {"processes", "by_name"}       # 리눅스가 아니면 빈 목록
    assert bench.sample_passages(0) == []
    assert len(bench.sample_passages(5)) == 5
