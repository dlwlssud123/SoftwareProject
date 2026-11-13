"""app.jobs.load_rag_index: rag.export CSV -> rag_index_version / rag_chunk without psql."""

import csv
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from agetech_data.rag.export import CSV_COLUMNS
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from test_public_data_import import corrections, snapshot

from app.jobs import import_public_data as importer
from app.jobs import load_rag_index as loader
from app.models import Recipe, RecipeRevision

MODEL = "test-model@1"
SEARCH_SQL = Path(__file__).resolve().parents[3] / "docs/data/sql/rag_search.sql"
RECIPES = [
    {
        "RCP_SEQ": seq,
        "RCP_NM": name,
        "RCP_PARTS_DTLS": "소금 1g, 물 적당량",
        "MANUAL01": "1. 끓인다.",
        "INFO_ENG": "0",
        "INFO_NA": "0",
    }
    for seq, name in (("1", "검증 레시피"), ("2", "두번째 레시피"))
]


@pytest.fixture
def db(pg_connection):
    schema = pg_connection.scalar(text("SELECT current_schema()"))
    assert schema.startswith("import_test_") and len(schema) == 44
    pg_connection.execute(text(f'SET search_path TO "{schema}", public'))
    pg_connection.commit()
    return pg_connection


def import_recipes(conn, tmp_path, monkeypatch=None, validation=None):
    if validation is not None:
        monkeypatch.setattr(importer, "RECIPE_VALIDATION_VERSION", validation)
    plan = importer.prepare_import(
        "recipes",
        snapshot(tmp_path, rows=RECIPES),
        corrections_path=corrections(tmp_path),
    )
    with Session(conn, expire_on_commit=False) as session:
        with session.begin():
            importer.apply_import(session, plan)
            revisions = {
                recipe.source_id: session.get(RecipeRevision, recipe.active_revision_id)
                for recipe in session.scalars(select(Recipe))
            }
    return {k: (v.fingerprint, v.effective_sha256) for k, v in revisions.items()}


def unit(axis):
    return "[" + ",".join("1" if i == axis else "0" for i in range(1024)) + "]"


def chunk(
    source_type, source_id, row_sha256, *, version, model=MODEL, n=1, axis=0, **cells
):
    row = {
        "index_version": version,
        "chunk_id": f"{source_type}:{source_id}:all:{n}",
        "source_type": source_type,
        "source_id": source_id,
        "section": "all",
        "chunk_no": str(n),
        "title": f"title {source_id}",
        "content": f'본문 {source_id}, "따옴표"\n줄바꿈',
        "content_sha256": "c" * 64,
        "region_scope": "none",
        "ctpv": "",
        "sgg": "",
        "source_url": "",
        "source_checked_at": "2026-11-13T03:00:00+00:00",
        "source_modified": "",
        "period_end": "",
        "quality_status": "ok",
        "quality_flags": '{"allergen_analysis_complete"}',
        "allergens": '{"대두"}',
        "status": "active",
        "data_version": "recipes:abc",
        "source_row_sha256": row_sha256,
        "embedding_model": model,
        "embedding": unit(axis),
        "embedded_at": "2026-11-13T03:51:58+00:00",
    }
    return {**row, **cells}


def write_index(path, version, rows, count=None):
    path.mkdir(parents=True, exist_ok=True)
    manifest = {
        "index_version": version,
        "model_id": MODEL,
        "count": len(rows) if count is None else count,
        "data_versions": ["recipes:abc"],
    }
    (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with (path / "rag_chunk.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def recipe_index(path, version, hashes, extra=()):
    rows = [
        chunk("recipe", k, row, version=version)
        for k, (_, row) in sorted(hashes.items())
    ]
    return write_index(path, version, [*rows, *extra])


def versions(conn):
    found = {
        r.index_version: r.status
        for r in conn.execute(
            text("SELECT index_version, status FROM rag_index_version")
        )
    }
    conn.commit()
    return found


# Each job call runs its own transaction, like a fresh engine.connect() in main().
def apply(conn, plan):
    conn.commit()
    return loader.apply_load(conn, plan)


def verify(conn, plan):
    conn.commit()
    return loader.verify_load(conn, plan)


def rollback(conn, version):
    conn.commit()
    return loader.rollback_to(conn, version)


def test_prepare_checks_the_csv_belongs_to_the_manifest(tmp_path):
    rows = [chunk("recipe", "1", "a" * 64, version="V")]
    plan = loader.prepare(write_index(tmp_path / "ok", "V", rows))
    assert (plan.rows, plan.by_source_type, plan.model) == (1, {"recipe": 1}, MODEL)
    with pytest.raises(loader.LoadError, match="has 1 rows, manifest V has 2"):
        loader.prepare(write_index(tmp_path / "count", "V", rows, count=2))
    with pytest.raises(loader.LoadError, match="not the export of manifest"):
        loader.prepare(write_index(tmp_path / "other", "W", rows))
    other_model = [chunk("recipe", "1", "a" * 64, version="V", model="other@2")]
    with pytest.raises(loader.LoadError, match="not the export of manifest"):
        loader.prepare(write_index(tmp_path / "model", "V", other_model))
    (tmp_path / "ok" / "rag_chunk.csv").write_text("a,b\n", encoding="utf-8")
    with pytest.raises(loader.LoadError, match="columns differ"):
        loader.prepare(tmp_path / "ok")
    with pytest.raises(loader.LoadError, match="manifest.json is missing"):
        loader.prepare(tmp_path / "nothing")


def test_main_dry_run_reads_files_only(tmp_path, capsys):
    index = write_index(tmp_path, "V", [chunk("recipe", "1", "a" * 64, version="V")])
    assert loader.main(["--index", str(index)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True and out["rows"] == 1
    assert loader.main(["--index", str(tmp_path / "missing")]) == 1
    assert "manifest.json is missing" in capsys.readouterr().err


def test_apply_binds_published_rows_activates_and_reruns_as_no_op(db, tmp_path):
    hashes = import_recipes(db, tmp_path)
    stale = chunk("recipe", "3", "f" * 64, version="V1")  # not published
    seasonal = chunk("seasonal", "m11-1", "e" * 64, version="V1")  # not imported
    plan = loader.prepare(
        recipe_index(tmp_path / "rag", "V1", hashes, [stale, seasonal])
    )
    result = apply(db, plan)
    name = result["index_version"]
    assert (
        result["status"] == "activated" and name.startswith("V1.") and len(name) == 15
    )
    assert result["loaded"] == 2 and result["previous_active"] is None
    assert result["chunks"] == {
        "recipe": {"in_index": 3, "loaded": 2},
        "seasonal": {"in_index": 1, "loaded": 0},
    }
    stored = db.execute(
        text(
            "SELECT source_id, source_record_sha256, content, allergens, embedding_model "
            "FROM rag_chunk WHERE index_version = :v ORDER BY source_id"
        ),
        {"v": name},
    ).all()
    assert [(r.source_id, r.source_record_sha256) for r in stored] == [
        (k, hashes[k][0]) for k in ("1", "2")
    ]
    assert stored[0].content == '본문 1, "따옴표"\n줄바꿈' and stored[0].allergens == [
        "대두"
    ]
    meta = db.execute(
        text("SELECT * FROM rag_index_version WHERE index_version = :v"), {"v": name}
    ).one()
    assert (meta.manifest_version, meta.chunk_count, meta.status) == ("V1", 2, "active")
    assert meta.binding_sha256.startswith(name[3:]) and meta.data_versions == [
        "recipes:abc"
    ]
    assert db.scalar(text("SELECT to_regclass('rag_chunk_stage')")) is None

    again = apply(db, plan)
    assert (again["status"], again["index_version"], again["active"]) == (
        "already_active",
        name,
        name,
    )
    assert versions(db) == {name: "active"}

    verified = verify(db, plan)
    assert verified["verified"] is True and verified["searchable"] == 2


def test_new_fingerprints_with_same_rows_load_a_new_version(db, tmp_path, monkeypatch):
    # rag.index keeps its version when no chunk row changed; a re-import with a new validation
    # version still gives the recipes new fingerprints -> must load again, not skip
    first_hashes = import_recipes(db, tmp_path)
    plan = loader.prepare(recipe_index(tmp_path / "rag", "V1", first_hashes))
    first = apply(db, plan)["index_version"]
    second_hashes = import_recipes(db, tmp_path, monkeypatch, validation="next")
    assert {k: v[1] for k, v in second_hashes.items()} == {
        k: v[1] for k, v in first_hashes.items()
    }
    stale = verify(db, plan)
    assert stale["verified"] is False and stale["searchable"] == 0
    assert stale["active"] == first and stale["expected"] != first

    result = apply(db, plan)
    second = result["index_version"]
    assert (
        result["status"] == "activated" and second.startswith("V1.") and second != first
    )
    assert result["previous_active"] == first and result["pruned"] == []
    assert versions(db) == {first: "retired", second: "active"}
    assert verify(db, plan)["searchable"] == 2

    # rolling back keeps the rolled-back-from version retired on the next run
    rolled = rollback(db, first)
    assert (rolled["previous_active"], rolled["active"]) == (second, first)
    kept = apply(db, plan)
    assert kept["status"] == "previously_activated" and kept["active"] == first
    assert versions(db) == {first: "active", second: "retired"}


def test_activation_keeps_only_the_previous_version(db, tmp_path):
    hashes = import_recipes(db, tmp_path)
    names = []
    for i in range(1, 4):
        plan = loader.prepare(recipe_index(tmp_path / f"rag{i}", f"V{i}", hashes))
        result = apply(db, plan)
        names.append(result["index_version"])
    assert result["pruned"] == [names[0]]
    assert versions(db) == {names[1]: "retired", names[2]: "active"}
    assert db.scalar(text("SELECT count(*) FROM rag_chunk")) == 4  # cascade


def test_failures_keep_the_previous_active_version(db, tmp_path):
    hashes = import_recipes(db, tmp_path)
    plan = loader.prepare(recipe_index(tmp_path / "rag", "V1", hashes))
    active = apply(db, plan)["index_version"]

    unpublished = loader.prepare(
        write_index(
            tmp_path / "none", "V2", [chunk("recipe", "1", "0" * 64, version="V2")]
        )
    )
    with pytest.raises(loader.LoadError, match="no chunk matches a published record"):
        apply(db, unpublished)

    changed = loader.prepare(recipe_index(tmp_path / "changed", "V3", hashes))
    recipe_index(
        tmp_path / "changed", "V3", {"1": hashes["1"]}
    )  # rewritten after prepare
    with pytest.raises(loader.LoadError, match="CSV changed while loading"):
        apply(db, changed)

    assert versions(db) == {active: "active"}
    assert verify(db, plan)["verified"] is True


def test_concurrent_loads_of_the_same_index_activate_once(db, tmp_path):
    hashes = import_recipes(db, tmp_path)
    plan = loader.prepare(recipe_index(tmp_path / "rag", "V1", hashes))
    schema = db.scalar(text("SELECT current_schema()"))
    assert schema.startswith("import_test_") and len(schema) == 44
    db.commit()
    barrier = Barrier(2)

    def load(_):
        with db.engine.connect() as connection:
            connection.execute(text(f'SET search_path TO "{schema}", public'))
            connection.commit()
            try:
                barrier.wait(timeout=10)
                return loader.apply_load(connection, plan)["status"]
            finally:
                connection.rollback()
                connection.execute(text("SET search_path TO public"))
                connection.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(load, range(2)))
    assert statuses == ["activated", "already_active"]
    assert list(versions(db).values()) == ["active"]


def test_documented_search_sql_runs_on_the_migrated_tables(db, tmp_path):
    hashes = import_recipes(db, tmp_path)
    rows = [
        # recipe 1: two chunks, the second closer to the question -> one hit per recipe
        chunk("recipe", "1", hashes["1"][1], version="V1", axis=0),
        chunk("recipe", "1", hashes["1"][1], version="V1", n=2, axis=1),
        # recipe 2: no soy, but allergen analysis not complete -> dropped when filtering
        chunk(
            "recipe",
            "2",
            hashes["2"][1],
            version="V1",
            axis=2,
            allergens="{}",
            quality_flags="{}",
        ),
    ]
    apply(db, loader.prepare(write_index(tmp_path / "rag", "V1", rows)))
    query = SEARCH_SQL.read_text(encoding="utf-8")
    start = query.index("SELECT chunk_id")
    statement = text(query[start : query.index(";", start)])

    def search(**params):
        values = {
            "q": "[" + ",".join(["0.6", "0.8"] + ["0"] * 1022) + "]",
            "embedding_model": MODEL,
            "source_types": ["recipe", "seasonal"],
            "ctpv": "대구광역시",
            "sgg": "남구",
            "allergies": [],
            **params,
        }
        found = [
            (r.chunk_id, round(r.similarity, 3)) for r in db.execute(statement, values)
        ]
        db.commit()
        return found

    assert search() == [("recipe:1:all:2", 0.8), ("recipe:2:all:1", 0.0)]
    assert search(allergies=["대두"]) == []  # 1 has soy, 2 is not fully analysed
    assert search(allergies=["새우"]) == [("recipe:1:all:2", 0.8)]
    assert search(source_types=["welfare_central", "welfare_local"]) == []
    assert search(embedding_model="other-model") == []
