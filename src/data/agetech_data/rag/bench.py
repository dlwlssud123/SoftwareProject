"""서버 실측: KURE-v1 모델 로드 시간·메모리, 질문 임베딩 지연(혼자·동시), 문서 임베딩 속도 → 서버 옮김 판정.

    uv run python -m agetech_data.rag.bench                                  # 1단계: 혼자
    uv run python -m agetech_data.rag.bench --label with-backend --concurrency 4 --threads 4 --passages 0
                                                                             # 2단계: 백엔드를 띄운 채로

절차·기준은 docs/data/rag_server_check.md. 옮기는 기준: 질문 임베딩 p95 > 0.5초(동시 요청이면 > 1.0초),
또는 남은 메모리 < 1GB, 또는 측정 중 스왑 사용이 100MB 넘게 늘면 ARM 서버로.
메모리는 서버 전체 남은 양으로 재므로, 백엔드가 떠 있을 때 돌리면 그만큼 줄어든 상태에서 판정한다.
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
P95_CONCURRENT_LIMIT_SEC = 1.0      # 동시 요청일 때 (대화 AI 응답 수 초 안에서 1초는 견딜 만함)
MIN_AVAILABLE_MB = 1024
SWAP_GROWTH_MB = 100
FULL_INDEX_CHUNKS = 2880     # 2026-11-07 인덱스 기준 청크 수 (전체 임베딩 시간 추정용)


# ── 메모리 ──────────────────────────────────────────────────────────────

def system_memory_mb() -> dict:
    """{'available', 'total', 'swap_used', 'swap_free'} MB. 모르면 None."""
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        kv = {}
        for line in meminfo.read_text().splitlines():
            k, _, v = line.partition(":")
            kv[k] = int(v.split()[0]) // 1024 if v.split() else 0
        return {"available": kv.get("MemAvailable"), "total": kv.get("MemTotal"),
                "swap_used": (kv.get("SwapTotal", 0) - kv.get("SwapFree", 0)),
                "swap_free": kv.get("SwapFree") if kv.get("SwapTotal") else None}
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


def _stats(lat: list[float]) -> dict:
    return {"n": len(lat), "p50_ms": round(statistics.median(lat) * 1000), "p95_ms": round(_pct(lat, 0.95) * 1000),
            "max_ms": round(max(lat) * 1000)}


def top_processes(n: int = 8) -> dict:
    """리눅스: 메모리 많이 쓰는 프로세스와 이름별 합계(MB). 서버에서 무엇이 메모리를 쓰는지 같이 남긴다."""
    proc = Path("/proc")
    if not proc.exists():
        return {"processes": [], "by_name": []}
    rows = []
    for d in proc.iterdir():
        if not d.name.isdigit():
            continue
        try:
            text = (d / "status").read_text()
        except OSError:
            continue
        name, rss = "?", None
        for line in text.splitlines():
            key, _, value = line.partition(":")
            if key == "Name":
                name = value.strip() or "?"
            elif key == "VmRSS" and value.split():
                rss = int(value.split()[0]) // 1024
        if rss:
            rows.append({"pid": int(d.name), "name": name, "rss_mb": rss})
    by_name: dict[str, dict] = {}
    for r in rows:
        b = by_name.setdefault(r["name"], {"name": r["name"], "processes": 0, "rss_mb": 0})
        b["processes"] += 1
        b["rss_mb"] += r["rss_mb"]
    return {"processes": sorted(rows, key=lambda r: -r["rss_mb"])[:n],
            "by_name": sorted(by_name.values(), key=lambda b: -b["rss_mb"])[:n]}


def sample_passages(n: int) -> list[str]:
    """인덱스 청크가 있으면 실제 청크, 없으면 커밋된 레시피 표본을 청크로 만들어 n개까지 반복."""
    if n <= 0:
        return []
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


def concurrent_latency(embed, questions: list[str], concurrency: int, rounds: int) -> tuple[list[float], float]:
    """질문을 concurrency 개씩 동시에 임베딩(FastAPI 스레드풀에서 요청이 겹치는 상황). (요청별 지연, 전체 걸린 시간)."""
    from concurrent.futures import ThreadPoolExecutor

    def one(q: str) -> float:
        t = time.perf_counter()
        embed(q)
        return time.perf_counter() - t

    jobs = questions * rounds
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        lat = list(ex.map(one, jobs))
    return lat, time.perf_counter() - t0


def judge(query: dict, conc: dict | None, sys_before: dict, sys_loaded: dict, sys_after: dict) -> dict:
    checks = {"p95_ok": query["p95_ms"] <= P95_LIMIT_SEC * 1000}
    if conc:
        checks["concurrent_p95_ok"] = conc["p95_ms"] <= P95_CONCURRENT_LIMIT_SEC * 1000
    if sys_loaded.get("available") is not None and sys_after.get("available") is not None:
        checks["memory_ok"] = min(sys_loaded["available"], sys_after["available"]) >= MIN_AVAILABLE_MB
    if sys_before.get("swap_used") is not None and sys_after.get("swap_used") is not None:
        checks["swap_ok"] = sys_after["swap_used"] - sys_before["swap_used"] <= SWAP_GROWTH_MB
    return checks


SWAP_FULL_MB = 50       # 스왑 남은 양이 이보다 적으면 '꽉 참'


def warnings_for(sys_before: dict, sys_after: dict) -> list[str]:
    """판정과 별도로 꼭 알아야 할 것. 스왑이 이미 꽉 차 있으면 '스왑 증가' 기준은 늘 통과처럼 보이고,
    메모리가 모자라는 순간 느려지는 대신 OOM으로 프로세스가 강제 종료될 수 있다."""
    out = []
    free = sys_before.get("swap_free")
    if free is not None and free < SWAP_FULL_MB:
        out.append("스왑이 측정 전부터 꽉 차 있음 — '스왑 증가' 기준이 의미 없고, 메모리가 모자라면 OOM으로 "
                   "큰 프로세스(이 모델 포함)가 강제 종료될 수 있음. `vmstat 1 5`의 si·so로 실제 압박 여부 확인")
    return out


def run_bench(repeat: int = 3, passages: int = 64, threads: int | None = None, batch_size: int = 16,
              concurrency: int = 1, label: str = "solo") -> dict:
    import torch

    from agetech_data.rag.embedder import KureEmbedder
    from agetech_data.rag.evaluate import load_questions

    if threads:
        torch.set_num_threads(threads)
    questions = [q["q"] for q in load_questions()["questions"]]
    texts = sample_passages(passages)
    sys_before, proc_before, top_before = system_memory_mb(), process_memory_mb(), top_processes()

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

    conc = None
    if concurrency > 1:
        clat, wall = concurrent_latency(emb.embed_query, questions, concurrency, repeat)
        conc = {"concurrency": concurrency, **_stats(clat), "wall_sec": round(wall, 1),
                "throughput_qps": round(len(clat) / wall, 1) if wall else None}

    pz = None
    if texts:
        t = time.perf_counter()
        emb.embed_passages(texts)
        sec = time.perf_counter() - t
        per_sec = len(texts) / sec if sec else 0.0
        pz = {"n": len(texts), "avg_chars": round(sum(map(len, texts)) / len(texts)), "sec": round(sec, 1),
              "per_sec": round(per_sec, 2),
              "full_index_min_estimate": round(FULL_INDEX_CHUNKS / per_sec / 60, 1) if per_sec else None}
    sys_after, proc_after = system_memory_mb(), process_memory_mb()

    query = _stats(lat)
    checks = judge(query, conc, sys_before, sys_loaded, sys_after)
    return {
        "label": label, "host": platform.node(), "platform": platform.platform(), "machine": platform.machine(),
        "python": platform.python_version(), "torch": torch.__version__, "cpu_count": os.cpu_count(),
        "torch_threads": torch.get_num_threads(), "model_id": emb.model_id,
        "load_sec": round(load_sec, 1), "query": query, "concurrent": conc, "passages": pz,
        "memory_mb": {"system_before": sys_before, "system_after_load": sys_loaded, "system_after": sys_after,
                      "process_before": proc_before, "process_after_load": proc_loaded, "process_after": proc_after},
        "top_memory_before": top_before,
        "limits": {"p95_sec": P95_LIMIT_SEC, "concurrent_p95_sec": P95_CONCURRENT_LIMIT_SEC,
                   "min_available_mb": MIN_AVAILABLE_MB, "swap_growth_mb": SWAP_GROWTH_MB},
        "checks": checks,
        "warnings": warnings_for(sys_before, sys_after),
        "verdict": "stay" if all(checks.values()) else "move",
    }


def summary(r: dict) -> str:
    m = r["memory_mb"]
    lines = [
        f"[{r['label']}] 서버 {r['host']} ({r['machine']}, CPU {r['cpu_count']}개, torch 스레드 {r['torch_threads']}, "
        f"Python {r['python']}, torch {r['torch']})",
        f"모델 로드 {r['load_sec']}초 / 프로세스 메모리 {m['process_after_load']['rss']}MB (최대 {m['process_after']['peak']}MB)",
        f"질문 임베딩 혼자 {r['query']['n']}회: p50 {r['query']['p50_ms']}ms · p95 {r['query']['p95_ms']}ms · "
        f"최대 {r['query']['max_ms']}ms (기준 p95 ≤ {int(P95_LIMIT_SEC * 1000)}ms)",
    ]
    if r["concurrent"]:
        c = r["concurrent"]
        lines.append(f"질문 임베딩 동시 {c['concurrency']}개씩 {c['n']}회: p50 {c['p50_ms']}ms · p95 {c['p95_ms']}ms · "
                     f"최대 {c['max_ms']}ms, 초당 {c['throughput_qps']}건 "
                     f"(기준 p95 ≤ {int(P95_CONCURRENT_LIMIT_SEC * 1000)}ms)")
    if r["passages"]:
        pz = r["passages"]
        lines.append(f"문서 임베딩 {pz['n']}개(평균 {pz['avg_chars']}자): {pz['sec']}초, 초당 {pz['per_sec']}개 → "
                     f"전체 {FULL_INDEX_CHUNKS}개 약 {pz['full_index_min_estimate']}분")
    lines.append(f"시스템 남은 메모리 {m['system_before']['available']} → 모델 올린 뒤 "
                 f"{m['system_after_load']['available']} → 끝 {m['system_after']['available']}MB / 스왑 사용 "
                 f"{m['system_before']['swap_used']} → {m['system_after']['swap_used']}MB")
    top = r["top_memory_before"]["by_name"]
    if top:
        lines.append("측정 전 메모리 많이 쓰던 것: " + ", ".join(f"{b['name']} {b['rss_mb']}MB" for b in top[:5]))
    lines += [f"주의: {w}" for w in r.get("warnings", [])]
    lines.append("판정: " + ("이 서버 유지 (기준 모두 통과)" if r["verdict"] == "stay"
                            else "ARM 서버로 옮김 — " + ", ".join(k for k, ok in r["checks"].items() if not ok)))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="KURE-v1 서버 실측 (절차: docs/data/rag_server_check.md)")
    ap.add_argument("--label", default="solo", help="결과 이름 (solo / with-backend 등)")
    ap.add_argument("--repeat", type=int, default=3, help="평가 질문 전체를 몇 번 반복할지")
    ap.add_argument("--concurrency", type=int, default=1, help="동시에 넣을 질문 수 (1이면 동시 측정 생략)")
    ap.add_argument("--passages", type=int, default=64,
                    help="문서 임베딩 속도를 잴 청크 수 (0이면 생략 — 백엔드와 같이 잴 때 CPU를 오래 잡지 않게)")
    ap.add_argument("--threads", type=int, default=None, help="torch 스레드 수 (백엔드와 같이 쓸 때 코어 절반 권장)")
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args(argv)
    r = run_bench(args.repeat, args.passages, args.threads, args.batch_size, args.concurrency, args.label)
    print(summary(r))
    text = json.dumps(r, ensure_ascii=False, indent=1)
    if args.json_out:
        args.json_out.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0 if r["verdict"] == "stay" else 2


if __name__ == "__main__":
    raise SystemExit(main())
