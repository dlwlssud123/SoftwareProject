import dataclasses
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.jobs import daily_refresh as dr

DEFAULT_ORDER = [
    "refresh",
    "import_welfare",
    "import_public_data",
    "import_meal_facilities",
    "import_seasonal",
    "map_recipe_foods",
    "welfare_build",
    "recipes_contract",
    "rag_index",
    "rag_export",
    "rag_load",
]


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 13, 1, 0, tzinfo=UTC)

    def __call__(self):
        self.now += timedelta(seconds=1)
        return self.now


class FakeRunner:
    """Answers by step: argv[2] is the module for python steps, psql steps start with 'psql'."""

    def __init__(self, fail=(), embed=True, refresh_status=None):
        self.fail, self.embed, self.refresh_status = set(fail), embed, refresh_status
        self.calls = []

    def __call__(self, argv, cwd, env, timeout):
        self.calls.append((argv, cwd, env))
        if argv[1] == "-c":
            return dr.Result(0 if self.embed else 3, "", "")
        name = "rag_load" if argv[0] == "psql" else argv[2].split(".")[-1]
        if name in self.fail:
            return dr.Result(
                1, "", f"{name} failed. password=sekretpw key=abcdef123456"
            )
        if name == "refresh" and self.refresh_status is not None:
            self.refresh_status.write_text(
                json.dumps(
                    {
                        "sources": {
                            "recipes": {
                                "last_attempt_at": "2026-11-13T01:00:01+00:00",
                                "last_status": "ok",
                                "item_count": 1156,
                                "changes": {"added": 0, "removed": 0, "changed": 2},
                            },
                            "nutrition": {
                                "last_attempt_at": "2026-10-31T00:00:00+00:00"
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            return dr.Result(0, "[recipes] 정상\n완료: 정상 1 / 실패 0\n", "")
        if name == "rag_load":
            return dr.Result(0, "COMMIT\n판본 V 활성 (청크 2878 개)\n", "")
        return dr.Result(0, json.dumps({"already_imported": False, "rows": 3}), "log")


def snapshot(path, complete=True, **details):
    path.write_text(
        json.dumps({"meta": {"complete": complete, "details": details}, "items": []}),
        encoding="utf-8",
    )
    return path


def local_steps(tmp_path, **build):
    """Default steps with snapshots in tmp_path (all complete) and rag_load running there."""
    out = []
    for step in dr.build_steps(**build):
        snaps = tuple(
            snapshot(tmp_path / f"{step.name}_{i}.json")
            for i, _ in enumerate(step.snapshots)
        )
        cwd = tmp_path if step.runtime == "psql" else step.cwd
        out.append(dataclasses.replace(step, snapshots=snaps, cwd=cwd))
    return out


def run(steps, runner, tmp_path, **kw):
    options = {
        "runner": runner,
        "python": "py",
        "rag_python": "ragpy",
        "psql": "psql",
        "env": {"E": "1"},
        "psql_env": {"PGPASSWORD": "x"},
        "rag_tables": lambda: True,
        "scrub": lambda s: s.replace("sekretpw", "***").replace("abcdef123456", "***"),
        "clock": Clock(),
        "output_dir": tmp_path / "out",
        "refresh_status": tmp_path / "refresh_status.json",
    }
    options.update(kw)
    return dr.execute(steps, **options)


def by_name(rows):
    return {r["name"]: r for r in rows}


def test_build_steps_order_and_options():
    assert [s.name for s in dr.build_steps()] == DEFAULT_ORDER
    steps = {s.name: s for s in dr.build_steps()}
    # RAG inputs are rebuilt without touching tracked docs/samples
    assert "--no-report" in steps["welfare_build"].args
    assert "--no-sample" in steps["recipes_contract"].args
    assert set(steps["rag_index"].needs) == {
        "import_welfare",
        "import_public_data",
        "welfare_build",
        "recipes_contract",
    }
    assert steps["rag_index"].runtime == steps["rag_export"].runtime == "rag"
    assert [s.name for s in dr.build_steps(refresh=False, rag=False)] == DEFAULT_ORDER[
        1:6
    ]
    refresh = dr.build_steps(sources=["recipes", "seasonal_foods"])[0]
    assert refresh.args[-3:] == ("--source", "recipes", "seasonal_foods")
    verify = [
        s for s in dr.build_steps(verify=True, rag=False) if s.name.endswith("_verify")
    ]
    assert [s.needs for s in verify] == [(n,) for n in DEFAULT_ORDER[1:6]]
    assert all(s.args[-1] == "--verify" for s in verify)


def test_all_steps_ok_with_summaries_and_logs(tmp_path):
    runner = FakeRunner(refresh_status=tmp_path / "refresh_status.json")
    rows = by_name(run(local_steps(tmp_path), runner, tmp_path))
    assert [r["status"] for r in rows.values()] == ["ok"] * len(DEFAULT_ORDER)
    assert dr.outcome(list(rows.values())) == ("succeeded", None)
    # refresh: per-source result of this run only (nutrition was attempted earlier)
    assert rows["refresh"]["summary"] == {
        "recipes": {
            "status": "ok",
            "items": 1156,
            "changes": {"added": 0, "removed": 0, "changed": 2},
            "error": None,
        }
    }
    assert rows["import_welfare"]["summary"] == {"already_imported": False, "rows": 3}
    assert rows["rag_load"]["summary"] == "판본 V 활성 (청크 2878 개)"
    calls = {c[0][2] if c[0][0] != "psql" else "psql": c for c in runner.calls}
    assert calls["agetech_data.rag.index"][0][0] == "ragpy"
    assert calls["app.jobs.import_seasonal"][0][0] == "py"
    psql_argv, psql_cwd, psql_env = calls["psql"]
    assert psql_argv[-2:] == ["-f", "load_index.sql"] and psql_cwd == tmp_path
    assert psql_env == {"PGPASSWORD": "x"}
    assert (
        (tmp_path / "out" / "import_welfare.log")
        .read_text(encoding="utf-8")
        .startswith("$ py -m app.jobs.import_welfare --apply")
    )


def test_incomplete_snapshot_waits_and_rag_keeps_previous_version(tmp_path):
    steps = local_steps(tmp_path)
    welfare = next(s for s in steps if s.name == "import_welfare")
    snapshot(welfare.snapshots[1], complete=False, remaining=12)
    runner = FakeRunner()
    rows = by_name(run(steps, runner, tmp_path))
    assert rows["import_welfare"]["status"] == "skipped"
    assert rows["import_welfare"]["reason"] == "incomplete_snapshot"
    assert rows["import_welfare"]["details_remaining"] == 12
    rag_index = rows["rag_index"]
    assert (rag_index["status"], rag_index["reason"], rag_index["detail"]) == (
        "skipped",
        "needs_not_ok",
        "import_welfare",
    )
    assert rows["rag_export"]["status"] == rows["rag_load"]["status"] == "skipped"
    assert (
        rows["import_public_data"]["status"]
        == rows["map_recipe_foods"]["status"]
        == "ok"
    )
    assert dr.outcome(list(rows.values())) == ("succeeded", None)
    ran = [c[0][2] for c in runner.calls if c[0][0] != "psql" and c[0][1] == "-m"]
    assert "app.jobs.import_welfare" not in ran and "agetech_data.rag.index" not in ran


def test_failure_continues_and_first_failure_is_error_code(tmp_path):
    runner = FakeRunner(fail={"import_public_data", "import_meal_facilities"})
    rows = run(local_steps(tmp_path), runner, tmp_path)
    named = by_name(rows)
    assert named["import_public_data"]["status"] == "failed"
    assert named["import_public_data"]["exit_code"] == 1
    assert "***" in named["import_public_data"]["error"]
    assert "sekretpw" not in json.dumps(rows) and "abcdef123456" not in json.dumps(rows)
    log = (tmp_path / "out" / "import_public_data.log").read_text(encoding="utf-8")
    assert "sekretpw" not in log and "abcdef123456" not in log
    # later independent steps still ran; RAG waits for a run that imported recipes
    assert (
        named["import_seasonal"]["status"]
        == named["map_recipe_foods"]["status"]
        == "ok"
    )
    assert named["rag_index"]["reason"] == "needs_not_ok"
    assert dr.outcome(rows) == ("failed", "import_public_data")


def test_rag_steps_wait_for_embed_env_psql_and_tables(tmp_path):
    rows = by_name(run(local_steps(tmp_path), FakeRunner(embed=False), tmp_path))
    assert rows["rag_index"]["reason"] == "no_embed_env"
    assert rows["rag_export"]["reason"] == rows["rag_load"]["reason"] == "needs_not_ok"
    rows = by_name(run(local_steps(tmp_path), FakeRunner(), tmp_path, psql=None))
    assert (
        rows["rag_export"]["status"] == "ok" and rows["rag_load"]["reason"] == "no_psql"
    )
    rows = by_name(
        run(local_steps(tmp_path), FakeRunner(), tmp_path, rag_tables=lambda: False)
    )
    assert rows["rag_load"]["reason"] == "no_rag_tables"
    assert dr.outcome(list(rows.values())) == ("succeeded", None)


def test_scrubber_and_child_environment(monkeypatch):
    monkeypatch.setenv("FOODSAFETY_API_KEY", "abcdef123456")
    url = "postgresql+psycopg://app:sekretpw@db.internal:5433/valueflow"
    scrub = dr.secrets_scrubber(url)
    leaked = f"connect {url} failed; serviceKey=abcdef123456 pw=sekretpw"
    assert "sekretpw" not in scrub(leaked) and "abcdef123456" not in scrub(leaked)
    env, psql_env = dr.child_environment(url)
    assert env["DATABASE_URL"] == url and env["PYTHONIOENCODING"] == "utf-8"
    assert {
        k: psql_env[k]
        for k in ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE")
    } == {
        "PGHOST": "db.internal",
        "PGPORT": "5433",
        "PGUSER": "app",
        "PGPASSWORD": "sekretpw",
        "PGDATABASE": "valueflow",
    }


def test_snapshot_wait_only_for_readable_incomplete_snapshots(tmp_path):
    assert dr.snapshot_wait(snapshot(tmp_path / "ok.json")) is None
    wait = dr.snapshot_wait(snapshot(tmp_path / "s.json", complete=False, failed=2))
    assert wait["reason"] == "incomplete_snapshot" and wait["details_failed"] == 2
    # missing or broken files are the import's error to report, not a wait
    assert dr.snapshot_wait(tmp_path / "missing.json") is None
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    assert dr.snapshot_wait(tmp_path / "broken.json") is None


def test_dry_run_prints_plan_without_database(capsys):
    assert dr.main(["--dry-run", "--skip-refresh", "--no-rag"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert [s["name"] for s in plan["steps"]] == DEFAULT_ORDER[1:6]
    assert plan["steps"][0]["waits_for_complete"] == [
        "data/raw/welfare/central_elderly.json",
        "data/raw/welfare/local_elderly.json",
    ]
    with pytest.raises(SystemExit):
        dr.main(["--dry-run", "--skip-refresh", "--source", "recipes"])


# --- job_runs on PostgreSQL --------------------------------------------------------------------
def two_steps():
    return [
        dr.Step("import_welfare", ("-m", "app.jobs.import_welfare", "--apply")),
        dr.Step("map_recipe_foods", ("-m", "app.jobs.map_recipe_foods", "--apply")),
    ]


def daily(conn, tmp_path, runner, **kw):
    return dr.run_daily(
        conn,
        kw.pop("steps", two_steps()),
        status_path=tmp_path / "status.json",
        log_path=tmp_path / "log.jsonl",
        clock=Clock(),
        progress=lambda line: None,
        runner=runner,
        python="py",
        rag_python="py",
        psql=None,
        env={},
        psql_env={},
        scrub=lambda s: s,
        **kw,
    )


def job_rows(conn):
    jobs = dr.JOBS
    return conn.execute(
        select(
            jobs.c.id,
            jobs.c.status,
            jobs.c.attempts,
            jobs.c.error_code,
            jobs.c.started_at,
            jobs.c.finished_at,
        ).where(jobs.c.kind == dr.KIND)
    ).all()


def test_postgres_run_records_job_runs_status_file_and_log(tmp_path, pg_connection):
    assert daily(pg_connection, tmp_path, FakeRunner()) == 0
    [row] = job_rows(pg_connection)
    assert (row.status, row.attempts, row.error_code) == ("succeeded", 1, None)
    assert row.started_at < row.finished_at
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["job_run_id"] == str(row.id) and status["status"] == "succeeded"
    assert [s["status"] for s in status["steps"]] == ["ok", "ok"]

    assert daily(pg_connection, tmp_path, FakeRunner(fail={"import_welfare"})) == 1
    failed = [r for r in job_rows(pg_connection) if r.status == "failed"]
    assert [(r.attempts, r.error_code) for r in failed] == [(1, "import_welfare")]
    lines = (tmp_path / "log.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["status"] for line in lines] == ["succeeded", "failed"]
    # the run lock is released after each run
    assert pg_connection.execute(
        text("SELECT pg_try_advisory_lock(:k)"), {"k": dr.RUN_LOCK}
    ).scalar()
    pg_connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": dr.RUN_LOCK})
    pg_connection.commit()


def test_postgres_job_id_from_worker_and_stale_running_rows(tmp_path, pg_connection):
    jobs = dr.JOBS
    queued, stale, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    pg_connection.execute(
        jobs.insert(),
        [
            {"id": queued, "kind": dr.KIND, "status": "queued", "attempts": 0},
            {"id": stale, "kind": dr.KIND, "status": "running", "attempts": 1},
            {"id": other, "kind": "something_else", "status": "running", "attempts": 1},
        ],
    )
    pg_connection.commit()
    assert daily(pg_connection, tmp_path, FakeRunner(), job_id=queued) == 0
    rows = {r.id: r for r in pg_connection.execute(select(jobs)).all()}
    assert (rows[queued].status, rows[queued].attempts) == ("succeeded", 1)
    assert (rows[stale].status, rows[stale].error_code) == ("failed", "interrupted")
    assert rows[other].status == "running"  # other kinds are not ours to touch
    # a finished row cannot be reused; a failed one can be retried
    assert daily(pg_connection, tmp_path, FakeRunner(), job_id=queued) == 2
    assert daily(pg_connection, tmp_path, FakeRunner(), job_id=stale) == 0
    retried = pg_connection.execute(select(jobs).where(jobs.c.id == stale)).one()
    assert (retried.status, retried.attempts, retried.error_code) == (
        "succeeded",
        2,
        None,
    )


def test_postgres_second_run_waits_for_the_lock(tmp_path, pg_connection):
    with pg_connection.engine.connect() as holder:
        assert holder.execute(
            text("SELECT pg_try_advisory_lock(:k)"), {"k": dr.RUN_LOCK}
        ).scalar()
        holder.commit()
        runner = FakeRunner()
        assert daily(pg_connection, tmp_path, runner) == 3
        assert runner.calls == [] and job_rows(pg_connection) == []
        holder.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": dr.RUN_LOCK})
        holder.commit()


def test_postgres_rag_tables_check(pg_connection):
    assert dr.rag_tables_exist(pg_connection) is False
    pg_connection.execute(text("CREATE TABLE rag_index_version (index_version text)"))
    pg_connection.execute(text("CREATE TABLE rag_chunk (index_version text)"))
    pg_connection.commit()
    assert dr.rag_tables_exist(pg_connection) is True
