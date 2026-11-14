"""Load the RAG search index into rag_index_version / rag_chunk without psql; default is a dry run.

    cd src/backend
    uv run python -m app.jobs.load_rag_index            # check manifest + CSV only (no database)
    uv run python -m app.jobs.load_rag_index --apply    # load, bind to published rows, activate
    uv run python -m app.jobs.load_rag_index --verify   # is the active version this index, bound now?
    uv run python -m app.jobs.load_rag_index --rollback <index_version>

Input: data/processed/rag/manifest.json + rag_chunk.csv, written by agetech_data.rag.index and
agetech_data.rag.export (those need the RAG python with numpy; this job only reads text files).
Tables: Alembic 20261114_03 (docs/data/rag_index_contract.md 4).

--apply, in one transaction (the previous active version is searched until it commits):
  1. COPY the CSV into a temp table; its rows, index_version and model must match the manifest.
  2. Bind: a chunk gets the published fingerprint from rag_source_active when its source row hash
     (CSV source_row_sha256) equals the published row's row_sha256. Unbound chunks are not loaded
     (their record is unpublished, held or has changed since the index was built).
  3. Name = '<manifest index_version>.<first 12 hex of the binding digest>'. Same manifest and same
     fingerprints -> same name, so a rerun is a no-op; a re-import that only changed fingerprints
     gets a new name and is loaded again. A name that was active before is never re-activated
     automatically (it may have been rolled back from on purpose); --verify reports it, --rollback
     switches.
  4. Under the rag_rollback_index lock: insert as 'loading', check count and model, retire the
     active version, activate this one, delete retired versions except the latest one.
Exit codes: 0 ok (also already loaded), 1 failed or --verify found a difference.
"""

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from agetech_data import paths
from agetech_data.rag.export import COLUMNS, CSV_COLUMNS
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

STAGE = "rag_chunk_stage"
KEEP_RETIRED = 1  # the previous version stays for rollback
COPY_BLOCK = 1 << 20
# Columns compared by --verify (index_version differs by design; vectors compare as text).
COMPARED = [
    "embedding::text" if c == "embedding" else c
    for c in COLUMNS
    if c != "index_version"
]
# Raised by rag_rollback_index with a readable message (version name and reason).
ROLLBACK_ERRORS = {"22023", "23514"}


class LoadError(Exception):
    """A readable reason the index was not loaded (never contains connection details)."""


@dataclass
class Plan:
    index_dir: Path
    csv_path: Path
    manifest: dict
    manifest_sha256: str
    rows: int = 0
    by_source_type: dict = field(default_factory=dict)

    @property
    def manifest_version(self) -> str:
        return self.manifest["index_version"]

    @property
    def model(self) -> str:
        return self.manifest["model_id"]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(COPY_BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare(index_dir: Path, csv_path: Path | None = None) -> Plan:
    """Read the manifest and check the CSV belongs to it (header, rows, version, model)."""
    manifest_path = index_dir / "manifest.json"
    csv_path = csv_path or index_dir / "rag_chunk.csv"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        version, model, count = (
            manifest["index_version"],
            manifest["model_id"],
            int(manifest["count"]),
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise LoadError(
            f"{manifest_path.name} is missing or unreadable — run agetech_data.rag.index first"
        ) from error
    plan = Plan(index_dir, csv_path, manifest, _sha256_file(manifest_path))
    try:
        with csv_path.open(encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            if next(reader, None) != CSV_COLUMNS:
                raise LoadError(
                    f"{csv_path.name} columns differ from agetech_data.rag.export — export it again"
                )
            at = {name: i for i, name in enumerate(CSV_COLUMNS)}
            counts: dict[str, int] = {}
            for row in reader:
                if (
                    len(row) != len(CSV_COLUMNS)
                    or row[at["index_version"]] != version
                    or row[at["embedding_model"]] != model
                ):
                    raise LoadError(
                        f"{csv_path.name} is not the export of manifest {version} — export it again"
                    )
                source_type = row[at["source_type"]]
                counts[source_type] = counts.get(source_type, 0) + 1
    except OSError as error:
        raise LoadError(
            f"{csv_path.name} is missing — run agetech_data.rag.export first"
        ) from error
    plan.rows, plan.by_source_type = sum(counts.values()), dict(sorted(counts.items()))
    if plan.rows != count:
        raise LoadError(
            f"{csv_path.name} has {plan.rows} rows, manifest {version} has {count} — export it again"
        )
    return plan


# --- database -----------------------------------------------------------------------------------
def stage(conn: Connection, plan: Plan) -> dict:
    """COPY the CSV into a temp table and bind chunks to published fingerprints (same transaction)."""
    conn.execute(
        text(
            f"CREATE TEMP TABLE {STAGE} (LIKE rag_chunk INCLUDING DEFAULTS) ON COMMIT DROP"
        )
    )
    conn.execute(
        text(
            f"ALTER TABLE {STAGE} ALTER COLUMN source_record_sha256 DROP NOT NULL, "
            "ADD COLUMN source_row_sha256 char(64) NOT NULL"
        )
    )
    raw = conn.connection.driver_connection
    with raw.cursor() as cursor:
        with cursor.copy(
            f"COPY {STAGE} ({', '.join(CSV_COLUMNS)}) FROM STDIN "
            "WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')"
        ) as copy:
            with plan.csv_path.open("rb") as handle:
                while block := handle.read(COPY_BLOCK):
                    copy.write(block)
    rows, foreign = conn.execute(
        text(
            f"SELECT count(*), count(*) FILTER (WHERE index_version <> :v OR embedding_model <> :m) "
            f"FROM {STAGE}"
        ),
        {"v": plan.manifest_version, "m": plan.model},
    ).one()
    if rows != plan.rows or foreign:
        raise LoadError(
            "the CSV changed while loading (rows, version or model differ) — nothing was loaded"
        )
    # One definition of "published" for loading and search: the rag_source_active view.
    conn.execute(
        text(
            f"UPDATE {STAGE} s SET source_record_sha256 = a.record_sha256 "
            "FROM rag_source_active a "
            "WHERE a.source_type = s.source_type AND a.source_id = s.source_id "
            "AND a.row_sha256 = s.source_row_sha256"
        )
    )
    by_type = {
        r.source_type: {"in_index": r.in_index, "loaded": r.loaded}
        for r in conn.execute(
            text(
                f"SELECT source_type, count(*) AS in_index, count(source_record_sha256) AS loaded "
                f"FROM {STAGE} GROUP BY source_type ORDER BY source_type"
            )
        )
    }
    bound, binding = conn.execute(
        text(
            "SELECT count(*), encode(sha256(convert_to(coalesce(string_agg("
            "chunk_id || chr(9) || source_record_sha256, chr(10) ORDER BY chunk_id COLLATE \"C\"), ''), "
            f"'UTF8')), 'hex') FROM {STAGE} WHERE source_record_sha256 IS NOT NULL"
        )
    ).one()
    if not bound:
        raise LoadError(
            "no chunk matches a published record — import the sources first; nothing was loaded"
        )
    return {
        "index_version": f"{plan.manifest_version}.{binding[:12]}",
        "binding_sha256": binding,
        "loaded": bound,
        "chunks": by_type,
    }


def _versions(conn: Connection) -> list[dict]:
    return [
        {
            "index_version": r.index_version,
            "status": r.status,
            "chunks": r.chunk_count,
            "activated_at": r.activated_at.isoformat() if r.activated_at else None,
        }
        for r in conn.execute(
            text(
                "SELECT index_version, status, chunk_count, activated_at FROM rag_index_version "
                "ORDER BY created_at DESC, index_version"
            )
        )
    ]


def _active(conn: Connection) -> str | None:
    return conn.scalar(
        text("SELECT index_version FROM rag_index_version WHERE status = 'active'")
    )


def apply_load(conn: Connection, plan: Plan) -> dict:
    with conn.begin() as transaction:
        bound = stage(conn, plan)
        name = bound["index_version"]
        result = {"manifest_version": plan.manifest_version, **bound}
        # Writers (other loads, rollbacks, cleanup) wait; search SELECTs keep running.
        conn.execute(text("LOCK TABLE rag_index_version, rag_chunk IN EXCLUSIVE MODE"))
        previous = _active(conn)
        existing = conn.execute(
            text(
                "SELECT status FROM rag_index_version WHERE index_version = :name "
                "AND status IN ('active', 'retired')"
            ),
            {"name": name},
        ).scalar()
        if existing:
            transaction.rollback()
            return {
                **result,
                "status": "already_active"
                if existing == "active"
                else "previously_activated",
                "active": previous,
                **(
                    {}
                    if existing == "active"
                    else {
                        "note": "this binding was active before (maybe rolled back from); not re-activated automatically, switch with --rollback"
                    }
                ),
            }
        # A version left 'loading'/'failed' by an older loader is replaced by this load.
        conn.execute(
            text(
                "DELETE FROM rag_index_version WHERE index_version = :name "
                "AND status IN ('loading', 'failed')"
            ),
            {"name": name},
        )
        conn.execute(
            text(
                "INSERT INTO rag_index_version (index_version, manifest_version, binding_sha256, "
                "embedding_model, chunk_count, manifest_sha256, data_versions, status) VALUES "
                "(:name, :manifest_version, :binding, :model, :count, :manifest_sha256, "
                "CAST(:data_versions AS jsonb), 'loading')"
            ),
            {
                "name": name,
                "manifest_version": plan.manifest_version,
                "binding": bound["binding_sha256"],
                "model": plan.model,
                "count": bound["loaded"],
                "manifest_sha256": plan.manifest_sha256,
                "data_versions": json.dumps(
                    plan.manifest.get("data_versions", []), ensure_ascii=False
                ),
            },
        )
        rest = [c for c in COLUMNS if c != "index_version"]
        conn.execute(
            text(
                f"INSERT INTO rag_chunk (index_version, {', '.join(rest)}) "
                f"SELECT :name, {', '.join(rest)} FROM {STAGE} WHERE source_record_sha256 IS NOT NULL"
            ),
            {"name": name},
        )
        count, same_model = conn.execute(
            text(
                "SELECT count(*), coalesce(bool_and(embedding_model = :model), false) "
                "FROM rag_chunk WHERE index_version = :name"
            ),
            {"name": name, "model": plan.model},
        ).one()
        if count != bound["loaded"] or not same_model:
            raise LoadError(
                "inserted chunks differ from the staged count or model — not activated"
            )
        conn.execute(
            text(
                "UPDATE rag_index_version SET status = 'retired' WHERE status = 'active'"
            )
        )
        conn.execute(
            text(
                "UPDATE rag_index_version SET status = 'active', activated_at = now() "
                "WHERE index_version = :name"
            ),
            {"name": name},
        )
        pruned = list(
            conn.scalars(
                text(
                    "DELETE FROM rag_index_version WHERE status IN ('retired', 'failed') "
                    "AND index_version NOT IN (SELECT index_version FROM rag_index_version "
                    "WHERE status = 'retired' ORDER BY activated_at DESC NULLS LAST, index_version "
                    "LIMIT :keep) RETURNING index_version"
                ),
                {"keep": KEEP_RETIRED},
            )
        )
        result.update(
            status="activated", previous_active=previous, pruned=sorted(pruned)
        )
    return result


def verify_load(conn: Connection, plan: Plan) -> dict:
    """Read-only in effect (rolled back): is the active version exactly this index bound now?"""
    with conn.begin() as transaction:
        bound = stage(conn, plan)
        name = bound["index_version"]
        active = _active(conn)
        result = {
            "manifest_version": plan.manifest_version,
            "expected": name,
            "active": active,
            "loaded_expected": bound["loaded"],
        }
        problems = []
        if active != name:
            problems.append(
                "active version is not this index bound to the current published rows"
            )
        else:
            stored, differing = conn.execute(
                text(
                    "SELECT (SELECT chunk_count FROM rag_index_version WHERE index_version = :name), "
                    f"(SELECT count(*) FROM ((SELECT {', '.join(COMPARED)} FROM rag_chunk "
                    f"WHERE index_version = :name EXCEPT SELECT {', '.join(COMPARED)} FROM {STAGE} "
                    f"WHERE source_record_sha256 IS NOT NULL) UNION ALL (SELECT {', '.join(COMPARED)} "
                    f"FROM {STAGE} WHERE source_record_sha256 IS NOT NULL EXCEPT SELECT "
                    f"{', '.join(COMPARED)} FROM rag_chunk WHERE index_version = :name)) d)"
                ),
                {"name": name},
            ).one()
            if stored != bound["loaded"] or differing:
                problems.append(f"{differing} chunk rows differ from the index files")
        result["searchable"] = conn.scalar(
            text(
                "SELECT count(*) FROM rag_chunk c "
                "JOIN rag_index_version v ON v.index_version = c.index_version AND v.status = 'active' "
                "JOIN rag_source_active s ON s.source_type = c.source_type AND s.source_id = c.source_id "
                "AND s.record_sha256 = c.source_record_sha256 WHERE c.status = 'active'"
            )
        )
        result["versions"] = _versions(conn)
        transaction.rollback()
    result["verified"] = not problems
    if problems:
        result["problems"] = problems
    return result


def rollback_to(conn: Connection, version: str) -> dict:
    with conn.begin():
        before = _active(conn)
        conn.execute(text("SELECT rag_rollback_index(:version)"), {"version": version})
        result = {
            "status": "rolled_back",
            "previous_active": before,
            "active": _active(conn),
        }
    with conn.begin():
        result["versions"] = _versions(conn)
    return result


# --- command line -------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--index", type=Path, default=paths.RAG_INDEX_DIR)
    parser.add_argument(
        "--csv", type=Path, help="rag.export CSV (default: <index>/rag_chunk.csv)"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--rollback", metavar="INDEX_VERSION")
    mode.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.rollback:
            plan = None
        else:
            plan = prepare(args.index, args.csv)
        if not (args.apply or args.verify or args.rollback):
            result = {
                "dry_run": True,
                "manifest_version": plan.manifest_version,
                "model": plan.model,
                "rows": plan.rows,
                "by_source_type": plan.by_source_type,
                "note": "chunks are bound to published DB rows on --apply",
            }
        else:
            from app.core.database import engine

            with engine.connect() as conn:
                if args.apply:
                    result = apply_load(conn, plan)
                elif args.verify:
                    result = verify_load(conn, plan)
                else:
                    result = rollback_to(conn, args.rollback)
    except LoadError as error:
        print(f"RAG index load failed: {error}", file=sys.stderr)
        return 1
    except DBAPIError as error:
        state = getattr(error.orig, "sqlstate", None)
        if args.rollback and state in ROLLBACK_ERRORS:
            # rag_rollback_index's own message (version name and reason only).
            print(
                f"Rollback refused: {error.orig.diag.message_primary}", file=sys.stderr
            )
        else:
            print(
                "RAG index load failed in the database (migrated to head? sources imported?). "
                "Transaction was not committed; the previous active version is still searched.",
                file=sys.stderr,
            )
        return 1
    except SQLAlchemyError:
        # Driver messages can include connection details; never print exception strings.
        print(
            "RAG index load could not use the database. Transaction was not committed.",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("verified", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
