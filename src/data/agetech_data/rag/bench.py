"""서버 실측: KURE-v1 모델 로드 시간·메모리, 질문 임베딩 지연(p50/p95), 문서 임베딩 속도 → 서버 옮김 판정.

    uv run python -m agetech_data.rag.bench                 # 결과 요약 + JSON
    uv run python -m agetech_data.rag.bench --json-out bench.json

옮기는 기준(docs/data/rag_embedding_decision.md 3절): 질문 임베딩 p95 > 0.5초, 또는 모델을 올린 뒤
남은 메모리 < 1GB, 또는 측정 중 스왑 사용이 100MB 넘게 늘면 ARM 서버로.
인덱스·정제 데이터가 없어도 돈다(질문은 평가 질문, 문서는 커밋된 레시피 표본으로 측정).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path

from agetech_data import paths

P95_LIMIT_SEC = 0.5
MIN_AVAILABLE_MB = 1024
SWAP_GROWTH_MB = 100
FULL_INDEX_CHUNKS = 2880     # 2026-11-07 인덱스 기준 청크 수 (전체 임베딩 시간 추정용)


# ── 메모리 ──────────────────────────────────────────────────────────────

def system_memory_mb() -> dict:
    """{'available', 'total', 'swap_used'} MB. 모르면 None."""
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        kv = {}
        for line in meminfo.read_text().splitlines():
            k, _, v = line.partition(":")
            kv[k] = int(v.split()[0]) // 1024 if v.split() else 0
        return {"available": kv.get("MemAvailable"), "total": kv.get("MemTotal"),
                "swap_used": (kv.get("SwapTotal", 0) - kv.get("SwapFree", 0))}
    if sys.platform == "win32":
        import ctypes
        import ctypes.wintypes as wt

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", wt.DWORD), ("dwMemoryLoad", wt.DWORD),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        s = MEMORYSTATUSEX()
        s.dwLength = ctypes.sizeof(s)
        ctypes.WinDLL("kernel32").GlobalMemoryStatusEx(ctypes.byref(s))
        commit = (s.ullTotalPageFile - s.ullAvailPageFile) - (s.ullTotalPhys - s.ullAvailPhys)
        return {"available": s.ullAvailPhys >> 20, "total": s.ullTotalPhys >> 20, "swap_used": max(commit, 0) >> 20}
    return {"available": None, "total": None, "swap_used": None}


def process_memory_mb() -> dict:
    """{'rss', 'peak'} MB (이 프로세스)."""
    status = Path("/proc/self/status")
    if status.exists():
        kv = {}
        for line in status.read_text().splitlines():
            k, _, v = line.partition(":")
            if k in ("VmRSS", "VmHWM"):
                kv[k] = int(v.split()[0]) // 1024
        return {"rss": kv.get("VmRSS"), "peak": kv.get("VmHWM")}
    if sys.platform == "win32":
        import ctypes
        import ctypes.wintypes as wt

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        k32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
        k32.GetCurrentProcess.restype = wt.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(PMC), wt.DWORD]
        c = PMC()
        c.cb = ctypes.sizeof(PMC)
        psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb)
        return {"rss": c.WorkingSetSize >> 20, "peak": c.PeakWorkingSetSize >> 20}
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {"rss": None, "peak": peak // (1024 * 1024) if sys.platform == "darwin" else peak // 1024}


# ── 측정 ────────────────────────────────────────────────────────────────

def _pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, round(p * (len(xs) - 1))))]


def sample_passages(n: int) -> list[str]:
    """인덱스 청크가 있으면 실제 청크, 없으면 커밋된 레시피 표본을 청크로 만들어 n개까지 반복."""
    texts: list[str] = []
    chunks_file = paths.RAG_INDEX_DIR / "chunks.jsonl"
    if chunks_file.exists():
        lines = chunks_file.read_text(encoding="utf-8").splitlines()
        step = max(1, len(lines) // n)
        texts = [json.loads(line)["content"] for line in lines[::step][:n]]
    if not texts:
        from agetech_data.rag.chunks import recipe_chunks

        sample = json.loads(paths.RECIPE_API_SAMPLE.read_text(encoding="utf-8"))
        records = [s["recipe"] for s in sample["samples"]]     # {"cases": [...], "recipe": 계약 레코드}
        for rec in records:
            texts += [c.content for c in recipe_chunks(rec, "bench")]
    return (texts * (n // max(1, len(texts)) + 1))[:n]


def run_bench(repeat: int = 3, passages: int = 64, threads: int | None = None, batch_size: int = 16) -> dict:
    import torch

    from agetech_data.rag.embedder import KureEmbedder
    from agetech_data.rag.evaluate import load_questions

    if threads:
        torch.set_num_threads(threads)
    questions = [q["q"] for q in load_questions()["questions"]]
    texts = sample_passages(passages)
    sys_before, proc_before = system_memory_mb(), process_memory_mb()

    emb = KureEmbedder(batch_size=batch_size, threads=threads)
    t = time.perf_counter()
    _ = emb.model
    load_sec = time.perf_counter() - t
    sys_loaded, proc_loaded = system_memory_mb(), process_memory_mb()

    for q in questions[:3]:          # 준비
        emb.embed_query(q)
    lat = []
    for _ in range(repeat):
        for q in questions:
            t = time.perf_counter()
            emb.embed_query(q)
            lat.append(time.perf_counter() - t)

    t = time.perf_counter()
    emb.embed_passages(texts)
    passage_sec = time.perf_counter() - t
    per_sec = len(texts) / passage_sec if passage_sec else 0.0
    sys_after, proc_after = system_memory_mb(), process_memory_mb()

    p95 = _pct(lat, 0.95)
    checks = {"p95_ok": p95 <= P95_LIMIT_SEC}
    if sys_loaded["available"] is not None:
        checks["memory_ok"] = min(sys_loaded["available"], sys_after["available"]) >= MIN_AVAILABLE_MB
    if sys_before["swap_used"] is not None and sys_after["swap_used"] is not None:
        checks["swap_ok"] = sys_after["swap_used"] - sys_before["swap_used"] <= SWAP_GROWTH_MB
    return {
        "host": platform.node(), "platform": platform.platform(), "machine": platform.machine(),
        "python": platform.python_version(), "torch": torch.__version__, "cpu_count": os.cpu_count(),
        "torch_threads": torch.get_num_threads(), "model_id": emb.model_id,
        "load_sec": round(load_sec, 1),
        "query": {"n": len(lat), "p50_ms": round(statistics.median(lat) * 1000), "p95_ms": round(p95 * 1000),
                  "max_ms": round(max(lat) * 1000)},
        "passages": {"n": len(texts), "avg_chars": round(sum(map(len, texts)) / len(texts)),
                     "sec": round(passage_sec, 1), "per_sec": round(per_sec, 2),
                     "full_index_min_estimate": round(FULL_INDEX_CHUNKS / per_sec / 60, 1) if per_sec else None},
        "memory_mb": {"system_before": sys_before, "system_after_load": sys_loaded, "system_after": sys_after,
                      "process_before": proc_before, "process_after_load": proc_loaded, "process_after": proc_after},
        "limits": {"p95_sec": P95_LIMIT_SEC, "min_available_mb": MIN_AVAILABLE_MB, "swap_growth_mb": SWAP_GROWTH_MB},
        "checks": checks,
        "verdict": "stay" if all(checks.values()) else "move",
    }


def summary(r: dict) -> str:
    m = r["memory_mb"]
    lines = [
        f"서버 {r['host']} ({r['machine']}, CPU {r['cpu_count']}개, torch 스레드 {r['torch_threads']}, "
        f"Python {r['python']}, torch {r['torch']})",
        f"모델 로드 {r['load_sec']}초 / 프로세스 메모리 {m['process_after_load']['rss']}MB (최대 {m['process_after']['peak']}MB)",
        f"질문 임베딩 {r['query']['n']}회: p50 {r['query']['p50_ms']}ms · p95 {r['query']['p95_ms']}ms · "
        f"최대 {r['query']['max_ms']}ms (기준 p95 ≤ {int(P95_LIMIT_SEC * 1000)}ms)",
        f"문서 임베딩 {r['passages']['n']}개(평균 {r['passages']['avg_chars']}자): {r['passages']['sec']}초, "
        f"초당 {r['passages']['per_sec']}개 → 전체 {FULL_INDEX_CHUNKS}개 약 {r['passages']['full_index_min_estimate']}분",
        f"시스템 남은 메모리 {m['system_before']['available']} → 모델 올린 뒤 {m['system_after_load']['available']} → "
        f"끝 {m['system_after']['available']}MB / 스왑 사용 {m['system_before']['swap_used']} → "
        f"{m['system_after']['swap_used']}MB",
        "판정: " + ("이 서버 유지 (기준 모두 통과)" if r["verdict"] == "stay"
                   else "ARM 서버로 옮김 — " + ", ".join(k for k, ok in r["checks"].items() if not ok)),
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="KURE-v1 서버 실측")
    ap.add_argument("--repeat", type=int, default=3, help="평가 질문 전체를 몇 번 반복할지")
    ap.add_argument("--passages", type=int, default=64, help="문서 임베딩 속도를 잴 청크 수")
    ap.add_argument("--threads", type=int, default=None)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args(argv)
    r = run_bench(args.repeat, args.passages, args.threads, args.batch_size)
    print(summary(r))
    text = json.dumps(r, ensure_ascii=False, indent=1)
    if args.json_out:
        args.json_out.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0 if r["verdict"] == "stay" else 2


if __name__ == "__main__":
    raise SystemExit(main())
