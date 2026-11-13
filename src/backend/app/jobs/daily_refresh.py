"""Daily public-data refresh in one command, recorded in job_runs (kind 'public_data_daily').

    cd src/backend
    uv run python -m app.jobs.daily_refresh                  # collect -> import -> map -> RAG
    uv run python -m app.jobs.daily_refresh --dry-run        # print the steps and commands only
    uv run python -m app.jobs.daily_refresh --skip-refresh   # re-import the current snapshots (retry)
    RAG_PYTHON=/path/to/python-with-embed-extra uv run python -m app.jobs.daily_refresh

Steps (each one is the existing command, run as its own process so a failure or the embedding
model's memory does not leak into the next step):

  refresh                agetech_data.refresh (all sources; a failed source keeps its last good snapshot)
  import_welfare         app.jobs.import_welfare --apply          (central + local, one transaction)
  import_public_data     app.jobs.import_public_data --apply      (recipes + foods)
  import_meal_facilities app.jobs.import_meal_facilities --apply
  import_seasonal        app.jobs.import_seasonal --apply         (links against active DB recipes)
  map_recipe_foods       app.jobs.map_recipe_foods --apply        (after recipes and foods)
  welfare_build          agetech_data.welfare.build --no-report   (RAG input; never rewrites tracked docs)
  recipes_contract       agetech_data.recipes.contract --input <recipes snapshot> --no-sample --corrections
                         (corrected rows = DB recipe_revisions.effective, so the 4 corrected recipes get chunks)
  rag_index              agetech_data.rag.index                   (RAG python: needs numpy + sentence-transformers)
  rag_export             agetech_data.rag.export                  (RAG python: index -> rag_chunk.csv)
  rag_load               app.jobs.load_rag_index --apply          (bind to published rows, activate; no psql)
  rag_load_verify        app.jobs.load_rag_index --verify         (with --verify)

Rules:
- Every import is idempotent (same snapshot -> already imported), so the whole command can be rerun.
- A step is *skipped*, not failed, when it has to wait: an import whose snapshot is not complete yet
  (welfare details still pending under the daily quota, seasonal details failed), RAG steps without an
  embedding environment. Skips carry a reason code. The RAG tables come with the migrations.
- Later steps still run after a failure, except steps that need it. RAG steps run only when this run
  imported welfare and recipes successfully, so a new index version always matches the published rows.
- The run is failed if any step failed; job_runs.error_code is the first failed step.

Concurrency: a session advisory lock allows one daily run at a time (exit 3 if another holds it).
'running' rows of this kind left by a killed run are marked failed with error_code 'interrupted'.
A worker may create a 'queued' (or 'failed', for a retry) row and pass --job-id; otherwise a row is
created. Per-step results go to data/processed/daily_refresh_status.json (+ one line per run in
daily_refresh_log.jsonl, last output of each step in data/processed/daily_refresh/<step>.log).
Exit codes: 0 succeeded, 1 failed, 2 bad --job-id, 3 another run holds the lock.
"""

import argparse
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agetech_data import paths
from agetech_data.refresh.sources import SOURCES
from agetech_data.settings import load_secret, redact
from sqlalchemy import insert, select, text, update
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import SQLAlchemyError

from app.models import JobRun

KIND = "public_data_daily"
# One daily run at a time. Different from the import lock (6711061156) that each import takes itself.
RUN_LOCK = 6711061157
STATUS_SCHEMA = 1
BACKEND_DIR = Path(__file__).resolve().parents[2]
HOUR = 3600
TAIL_CHARS = 1500
JOBS = JobRun.__table__
# Exit 0 only when the interpreter can build embeddings (rag.index / rag.export import these).
RAG_ENV_CHECK = (
    "import importlib.util as u, sys; "
    "sys.exit(0 if all(u.find_spec(m) for m in ('numpy', 'sentence_transformers')) else 3)"
)


@dataclass(frozen=True)
class Step:
    name: str
    args: tuple[str, ...]  # after the interpreter
    runtime: str = "backend"  # backend | rag
    cwd: Path = BACKEND_DIR
    needs: tuple[str, ...] = ()  # skipped unless these steps were ok in this run
    snapshots: tuple[Path, ...] = ()  # skipped while any of these is not complete
    timeout: int = HOUR


@dataclass(frozen=True)
class Result:
    returncode: int
    stdout: str
    stderr: str


class JobRunError(Exception):
    pass


def build_steps(
    *,
    refresh: bool = True,
    sources: list[str] | None = None,
    verify: bool = False,
    rag: bool = True,
) -> list[Step]:
    steps: list[Step] = []
    if refresh:
        source_args = ("--source", *sources) if sources else ()
        steps.append(
            Step(
                "refresh",
                ("-m", "agetech_data.refresh", *source_args),
                timeout=4 * HOUR,
            )
        )
    imports = [
        ("import_welfare", (paths.WELFARE_CENTRAL_RAW, paths.WELFARE_LOCAL_RAW)),
        ("import_public_data", (paths.RECIPES_ALL_RAW, paths.NUTRITION_RAW)),
        ("import_meal_facilities", (paths.FREE_MEAL_RAW,)),
        ("import_seasonal", (paths.SEASONAL_RAW,)),
        ("map_recipe_foods", ()),
    ]
    for name, snapshots in imports:
        steps.append(
            Step(name, ("-m", f"app.jobs.{name}", "--apply"), snapshots=snapshots)
        )
    if verify:
        for name, _ in imports:
            steps.append(
                Step(
                    f"{name}_verify",
                    ("-m", f"app.jobs.{name}", "--verify"),
                    needs=(name,),
                )
            )
    if rag:
        steps += [
            Step("welfare_build", ("-m", "agetech_data.welfare.build", "--no-report")),
            Step(
                "recipes_contract",
                (
                    "-m",
                    "agetech_data.recipes.contract",
                    "--input",
                    str(paths.RECIPES_ALL_RAW),
                    "--no-sample",
                    # RAG chunks must match the published rows (DB recipe_revisions.effective)
                    "--corrections",
                    str(paths.RECIPE_CORRECTIONS),
                    "--output-json",
                    str(paths.RECIPES_API_ALL),
                ),
            ),
            Step(
                "rag_index",
                ("-m", "agetech_data.rag.index"),
                runtime="rag",
                needs=(
                    "import_welfare",
                    "import_public_data",
                    "welfare_build",
                    "recipes_contract",
                ),
                timeout=3 * HOUR,
            ),
            Step(
                "rag_export",
                ("-m", "agetech_data.rag.export"),
                runtime="rag",
                needs=("rag_index",),
            ),
            Step(
                "rag_load",
                ("-m", "app.jobs.load_rag_index", "--apply"),
                needs=("rag_export",),
            ),
        ]
        if verify:
            steps.append(
                Step(
                    "rag_load_verify",
                    ("-m", "app.jobs.load_rag_index", "--verify"),
                    needs=("rag_load",),
                )
            )
    return steps


def run_process(argv: list[str], cwd: Path, env: dict, timeout: int) -> Result:
    try:
        done = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return Result(done.returncode, done.stdout, done.stderr)
    except subprocess.TimeoutExpired as expired:

        def as_text(value) -> str:
            if isinstance(value, bytes):
                return value.decode("utf-8", "replace")
            return value or ""

        return Result(
            -1,
            as_text(expired.stdout),
            as_text(expired.stderr) + f"\ntimed out after {timeout}s",
        )
    except OSError as error:
        return Result(
            -2, "", f"could not start {Path(argv[0]).name} ({type(error).__name__})"
        )


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(paths.REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def snapshot_wait(path: Path) -> dict | None:
    """A readable snapshot whose meta says it is not complete -> wait (skip) instead of failing.

    Missing or unreadable files are not waits: the import runs and reports its own error.
    """
    try:
        meta = json.loads(path.read_bytes()).get("meta") or {}
    except (OSError, ValueError, AttributeError):
        return None
    if meta.get("complete") is True:
        return None
    details = meta.get("details") or {}
    wait = {
        "reason": "incomplete_snapshot",
        "detail": f"{_rel(path)} is not complete yet",
    }
    for key in ("remaining", "failed"):
        if isinstance(details.get(key), int):
            wait[f"details_{key}"] = details[key]
    return wait


def _compact(value, depth: int = 0):
    if isinstance(value, dict):
        return (
            {k: _compact(v, depth + 1) for k, v in value.items()}
            if depth < 3
            else "{…}"
        )
    if isinstance(value, list):
        return [_compact(v, depth + 1) for v in value[:10]] + (
            ["…"] if len(value) > 10 else []
        )
    if isinstance(value, str) and len(value) > 200:
        return value[:200] + "…"
    return value


def output_summary(stdout: str):
    """The JSON object a step printed last (imports, rag.index), else its last output line."""
    out = stdout.strip()
    if not out:
        return None
    for start in (0, out.rfind("\n{") + 1):
        if out[start:].startswith("{"):
            try:
                return _compact(json.loads(out[start:]))
            except ValueError:
                pass
    return out.splitlines()[-1][:300]


def refresh_summary(status_path: Path, since: str) -> dict | None:
    """Per-source result of the refresh step, from the refresh status file."""
    try:
        sources = (
            json.loads(status_path.read_text(encoding="utf-8")).get("sources") or {}
        )
    except (OSError, ValueError):
        return None
    out = {}
    for name, entry in sources.items():
        if (entry.get("last_attempt_at") or "") < since:
            continue
        changes = entry.get("changes") or {}
        out[name] = {
            "status": entry.get("last_status"),
            "items": entry.get("item_count"),
            "changes": {k: changes.get(k) for k in ("added", "removed", "changed")},
            "error": entry.get("last_error"),
        }
    return out


def _tail(text_: str) -> str:
    text_ = text_.strip()
    return text_ if len(text_) <= TAIL_CHARS else "…" + text_[-TAIL_CHARS:]


def execute(
    steps: list[Step],
    *,
    runner: Callable[[list[str], Path, dict, int], Result],
    python: str,
    rag_python: str,
    env: dict,
    scrub: Callable[[str], str],
    clock: Callable[[], datetime],
    output_dir: Path | None = None,
    refresh_status: Path = paths.REFRESH_STATUS,
    on_step: Callable[[list[dict]], None] = lambda rows: None,
    progress: Callable[[str], None] = lambda line: None,
) -> list[dict]:
    rows: list[dict] = []
    done: dict[str, str] = {}
    rag_env: list[dict | None] = []  # checked once, when the first RAG step comes

    def wait_reason(step: Step) -> dict | None:
        not_ok = [n for n in step.needs if n in done and done[n] != "ok"]
        if not_ok:
            return {"reason": "needs_not_ok", "detail": ", ".join(not_ok)}
        for snapshot in step.snapshots:
            wait = snapshot_wait(snapshot)
            if wait:
                return wait
        if step.runtime == "rag":
            if not rag_env:
                check = runner([rag_python, "-c", RAG_ENV_CHECK], BACKEND_DIR, env, 120)
                rag_env.append(
                    None
                    if check.returncode == 0
                    else {
                        "reason": "no_embed_env",
                        "detail": "RAG python lacks numpy/sentence-transformers (set --rag-python or RAG_PYTHON)",
                    }
                )
            return rag_env[0]
        return None

    for number, step in enumerate(steps, 1):
        started = clock()
        row = {"name": step.name, "started_at": _iso(started)}
        wait = wait_reason(step)
        if wait:
            row.update(status="skipped", **wait)
        else:
            argv = [rag_python if step.runtime == "rag" else python, *step.args]
            result = runner(argv, step.cwd, env, step.timeout)
            stdout, stderr = scrub(result.stdout), scrub(result.stderr)
            ok = result.returncode == 0
            row.update(status="ok" if ok else "failed", exit_code=result.returncode)
            summary = (
                refresh_summary(refresh_status, row["started_at"])
                if step.name == "refresh"
                else output_summary(stdout)
            )
            if summary is not None:
                row["summary"] = summary
            if not ok:
                row["error"] = _tail(stderr or stdout)
            if output_dir is not None:
                output_dir.mkdir(parents=True, exist_ok=True)
                shown = " ".join([Path(argv[0]).name, *step.args])
                (output_dir / f"{step.name}.log").write_text(
                    f"$ {shown}\n(exit {result.returncode})\n--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}\n",
                    encoding="utf-8",
                )
        row["duration_sec"] = round((clock() - started).total_seconds(), 1)
        done[step.name] = row["status"]
        rows.append(row)
        on_step(rows)
        note = f" — {row['reason']}" if row["status"] == "skipped" else ""
        progress(
            f"[{number}/{len(steps)}] {step.name}: {row['status']} ({row['duration_sec']}s){note}"
        )
    return rows


def outcome(rows: list[dict]) -> tuple[str, str | None]:
    failed = [r["name"] for r in rows if r["status"] == "failed"]
    return ("failed", failed[0][:64]) if failed else ("succeeded", None)


# --- job_runs ---------------------------------------------------------------------------------
def claim_run(conn: Connection, job_id: uuid.UUID | None, now: datetime) -> uuid.UUID:
    """Mark stale 'running' rows interrupted (we hold the run lock) and start this run's row."""
    stale = [JOBS.c.kind == KIND, JOBS.c.status == "running"]
    if job_id is not None:
        stale.append(JOBS.c.id != job_id)
    conn.execute(
        update(JOBS)
        .where(*stale)
        .values(status="failed", error_code="interrupted", finished_at=now)
    )
    if job_id is not None:
        row = conn.execute(
            select(JOBS.c.kind, JOBS.c.status).where(JOBS.c.id == job_id)
        ).one_or_none()
        if row is None or row.kind != KIND or row.status not in ("queued", "failed"):
            conn.rollback()
            raise JobRunError(
                f"--job-id must be a queued or failed '{KIND}' job_runs row"
            )
        conn.execute(
            update(JOBS)
            .where(JOBS.c.id == job_id)
            .values(
                status="running",
                attempts=JOBS.c.attempts + 1,
                started_at=now,
                finished_at=None,
                error_code=None,
            )
        )
        run_id = job_id
    else:
        run_id = uuid.uuid4()
        conn.execute(
            insert(JOBS).values(
                id=run_id,
                kind=KIND,
                status="running",
                attempts=1,
                started_at=now,
                next_run_at=now,
            )
        )
    conn.commit()
    return run_id


def finish_run(
    conn: Connection,
    run_id: uuid.UUID,
    status: str,
    error_code: str | None,
    now: datetime,
) -> None:
    conn.execute(
        update(JOBS)
        .where(JOBS.c.id == run_id)
        .values(status=status, error_code=error_code, finished_at=now)
    )
    conn.commit()


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    tmp.replace(path)


def run_daily(
    conn: Connection,
    steps: list[Step],
    *,
    job_id: uuid.UUID | None = None,
    status_path: Path = paths.DAILY_REFRESH_STATUS,
    log_path: Path = paths.DAILY_REFRESH_LOG,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    progress: Callable[[str], None] = lambda line: print(
        line, file=sys.stderr, flush=True
    ),
    **execute_options,
) -> int:
    if not conn.execute(
        text("SELECT pg_try_advisory_lock(:key)"), {"key": RUN_LOCK}
    ).scalar():
        conn.rollback()
        progress("Another daily refresh holds the run lock; nothing was run.")
        return 3
    conn.commit()
    try:
        started = clock()
        try:
            run_id = claim_run(conn, job_id, started)
        except JobRunError as error:
            progress(str(error))
            return 2
        status = {
            "schema_version": STATUS_SCHEMA,
            "kind": KIND,
            "job_run_id": str(run_id),
            "status": "running",
            "started_at": _iso(started),
            "finished_at": None,
            "error_code": None,
            "planned": [s.name for s in steps],
            "steps": [],
        }
        _write_json(status_path, status)

        def record(rows: list[dict]) -> None:
            status["steps"] = rows
            _write_json(status_path, status)

        try:
            rows = execute(
                steps,
                clock=clock,
                on_step=record,
                progress=progress,
                **execute_options,
            )
        except BaseException:
            # Ctrl-C or a bug in this runner: leave a finished row behind, then re-raise.
            status.update(
                status="failed", error_code="interrupted", finished_at=_iso(clock())
            )
            _write_json(status_path, status)
            try:
                finish_run(conn, run_id, "failed", "interrupted", clock())
            except SQLAlchemyError:
                pass
            raise
        result, error_code = outcome(rows)
        finished = clock()
        finish_run(conn, run_id, result, error_code, finished)
        status.update(
            status=result,
            error_code=error_code,
            finished_at=_iso(finished),
            duration_sec=round((finished - started).total_seconds(), 1),
        )
        _write_json(status_path, status)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as log:
            line = {
                k: status[k]
                for k in (
                    "job_run_id",
                    "started_at",
                    "finished_at",
                    "status",
                    "error_code",
                )
            }
            line["steps"] = {r["name"]: r["status"] for r in rows}
            log.write(json.dumps(line, ensure_ascii=False) + "\n")
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0 if result == "succeeded" else 1
    finally:
        conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": RUN_LOCK})
        conn.commit()


# --- command line -----------------------------------------------------------------------------
def secrets_scrubber(database_url: str) -> Callable[[str], str]:
    """Hide the database URL/password and the public-data API keys if a step ever prints them."""
    url = make_url(database_url)
    keys = {name for source in SOURCES.values() for name in source.key_names}
    secrets = [
        database_url,
        url.password or "",
        *(load_secret(name) for name in sorted(keys)),
    ]
    secrets = [s for s in secrets if len(s) >= 6]
    return lambda value: redact(value, *secrets)


def child_environment(database_url: str) -> dict:
    # Every step imports into the same database this run records job_runs in.
    return dict(
        os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", DATABASE_URL=database_url
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Daily public-data refresh (collect -> import -> map -> RAG), recorded in job_runs"
    )
    parser.add_argument(
        "--source", nargs="+", choices=list(SOURCES), help="refresh only these sources"
    )
    parser.add_argument(
        "--skip-refresh", action="store_true", help="import the current snapshots only"
    )
    parser.add_argument(
        "--no-rag", action="store_true", help="stop after the DB imports"
    )
    parser.add_argument(
        "--verify", action="store_true", help="re-check every import after applying"
    )
    parser.add_argument(
        "--rag-python",
        help="interpreter with the embed extra (default: $RAG_PYTHON or this one)",
    )
    parser.add_argument(
        "--job-id",
        type=uuid.UUID,
        help="queued/failed job_runs row created by a worker",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the steps and commands; run nothing",
    )
    args = parser.parse_args(argv)
    if args.skip_refresh and args.source:
        parser.error("--source needs the refresh step (drop --skip-refresh)")

    steps = build_steps(
        refresh=not args.skip_refresh,
        sources=args.source,
        verify=args.verify,
        rag=not args.no_rag,
    )
    rag_python = args.rag_python or os.environ.get("RAG_PYTHON") or sys.executable
    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "kind": KIND,
                    "python": sys.executable,
                    "rag_python": rag_python,
                    "steps": [
                        {
                            "name": s.name,
                            "runtime": s.runtime,
                            "args": list(s.args),
                            "cwd": _rel(s.cwd),
                            "needs": list(s.needs),
                            "waits_for_complete": [_rel(p) for p in s.snapshots],
                        }
                        for s in steps
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    from app.core.config import get_settings
    from app.core.database import engine

    database_url = get_settings().database_url.get_secret_value()
    env = child_environment(database_url)
    try:
        conn = engine.connect()
    except SQLAlchemyError:
        # Driver messages can include connection details; never print exception strings.
        print(
            "Daily refresh could not connect to the database; nothing was run.",
            file=sys.stderr,
        )
        return 1
    with conn:
        try:
            return run_daily(
                conn,
                steps,
                job_id=args.job_id,
                runner=run_process,
                python=sys.executable,
                rag_python=rag_python,
                env=env,
                scrub=secrets_scrubber(database_url),
                output_dir=paths.DAILY_REFRESH_OUTPUT_DIR,
            )
        except SQLAlchemyError:
            print(
                "Daily refresh lost the database while recording job_runs; check the last status file.",
                file=sys.stderr,
            )
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
