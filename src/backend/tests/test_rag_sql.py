import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_public_data_import import corrections, snapshot

from app.jobs import import_public_data as importer
from app.models import Recipe, RecipeRevision

ROOT = Path(__file__).resolve().parents[3]
DRAFT = (ROOT / "docs/data/sql/rag_chunk_draft.sql").read_text(encoding="utf-8")


@pytest.fixture
def rag_db(pg_connection):
    schema = pg_connection.scalar(text("SELECT current_schema()"))
    assert schema.startswith("import_test_") and len(schema) == 44
    pg_connection.execute(text(f'SET search_path TO "{schema}", public'))
    # Run the published SQL literally, including PL/pgSQL percent syntax and example comments.
    pg_connection.connection.driver_connection.execute(DRAFT)
    pg_connection.commit()
    return pg_connection


def add_index(
    db,
    name,
    *,
    status="retired",
    activated=True,
    declared_count=1,
    chunk_model="test-model",
    source_fingerprint="0" * 64,
):
    db.execute(
        text(
            "INSERT INTO rag_index_version "
            "(index_version, embedding_model, chunk_count, manifest_sha256, data_versions, status, activated_at) "
            "VALUES (:name, 'test-model', :count, :digest, '{}', :status, :activated)"
        ),
        {
            "name": name,
            "count": declared_count,
            "digest": "0" * 64,
            "status": status,
            "activated": datetime.now(UTC) if activated else None,
        },
    )
    db.execute(
        text(
            "INSERT INTO rag_chunk "
            "(index_version, chunk_id, source_type, source_id, section, chunk_no, title, content, "
            "content_sha256, region_scope, data_version, source_record_sha256, embedding_model, embedding) "
            "VALUES (:name, 'recipe:1:all:1', 'recipe', '1', 'all', 1, 'title', 'content', :digest, "
            "'none', 'source-version', :fingerprint, :model, CAST(:embedding AS vector))"
        ),
        {
            "name": name,
            "digest": "0" * 64,
            "fingerprint": source_fingerprint,
            "model": chunk_model,
            "embedding": json.dumps([1] + [0] * 1023),
        },
    )


def active_versions(db):
    return list(
        db.scalars(
            text("SELECT index_version FROM rag_index_version WHERE status = 'active'")
        )
    )


@pytest.mark.parametrize(
    "target",
    [
        None,
        {"status": "loading"},
        {"status": "failed"},
        {"activated": False},
        {"declared_count": 2},
        {"chunk_model": "different-model"},
    ],
)
def test_invalid_rollback_preserves_current_index(rag_db, target):
    add_index(rag_db, "current", status="active")
    if target is not None:
        add_index(rag_db, "previous", **target)
    rag_db.commit()
    with pytest.raises(DBAPIError), rag_db.begin():
        rag_db.execute(
            text("SELECT rag_rollback_index(:previous)"), {"previous": "previous"}
        )
    assert active_versions(rag_db) == ["current"]


def test_valid_rollback_is_atomic_and_idempotent(rag_db):
    add_index(rag_db, "current", status="active")
    add_index(rag_db, "previous")
    rag_db.commit()
    with rag_db.begin():
        rag_db.execute(text("SELECT rag_rollback_index('previous')"))
    activated = rag_db.scalar(
        text(
            "SELECT activated_at FROM rag_index_version WHERE index_version = 'previous'"
        )
    )
    rag_db.commit()
    with rag_db.begin():
        rag_db.execute(text("SELECT rag_rollback_index('previous')"))
    assert active_versions(rag_db) == ["previous"]
    assert (
        rag_db.scalar(
            text("SELECT status FROM rag_index_version WHERE index_version = 'current'")
        )
        == "retired"
    )
    assert (
        rag_db.scalar(
            text(
                "SELECT activated_at FROM rag_index_version WHERE index_version = 'previous'"
            )
        )
        == activated
    )


def test_concurrent_rollbacks_keep_one_complete_active_version(rag_db):
    add_index(rag_db, "current", status="active")
    add_index(rag_db, "left")
    add_index(rag_db, "right")
    schema = rag_db.scalar(text("SELECT current_schema()"))
    assert schema.startswith("import_test_") and len(schema) == 44
    rag_db.commit()
    barrier = Barrier(2)

    def rollback(version):
        with rag_db.engine.connect() as connection:
            connection.execute(text(f'SET search_path TO "{schema}", public'))
            connection.commit()
            try:
                barrier.wait(timeout=10)
                with connection.begin():
                    connection.execute(
                        text("SELECT rag_rollback_index(:previous)"),
                        {"previous": version},
                    )
                return True
            finally:
                connection.rollback()
                connection.execute(text("SET search_path TO public"))
                connection.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(rollback, ["left", "right"])) == [True, True]
    active = active_versions(rag_db)
    assert len(active) == 1 and active[0] in {"left", "right"}


def test_source_view_rejects_old_chunks_after_same_raw_is_revalidated(
    rag_db, tmp_path, monkeypatch
):
    start = DRAFT.index("-- CREATE VIEW rag_source_active")
    end = DRAFT.index(";", start) + 1
    view_sql = "\n".join(
        line.removeprefix("-- ") for line in DRAFT[start:end].splitlines()
    )
    rag_db.exec_driver_sql(view_sql)
    rag_db.commit()
    path, correction_path = snapshot(tmp_path), corrections(tmp_path)
    initial = importer.prepare_import("recipes", path, corrections_path=correction_path)
    with Session(rag_db, expire_on_commit=False) as db:
        with db.begin():
            importer.apply_import(db, initial)
            recipe = db.scalar(select(Recipe))
            original = db.get(RecipeRevision, recipe.active_revision_id)
            original_raw = original.raw_sha256
            add_index(
                db, "current", status="active", source_fingerprint=original.fingerprint
            )
        query = text(
            "SELECT count(*) FROM rag_chunk c JOIN rag_source_active s "
            "ON s.source_type = c.source_type AND s.source_id = c.source_id "
            "AND s.record_sha256 = c.source_record_sha256"
        )
        with db.begin():
            assert db.scalar(query) == 1
        monkeypatch.setattr(importer, "RECIPE_VALIDATION_VERSION", "next-validation")
        updated = importer.prepare_import(
            "recipes", path, corrections_path=correction_path
        )
        with db.begin():
            importer.apply_import(db, updated)
            current = db.get(RecipeRevision, recipe.active_revision_id)
            assert current.raw_sha256 == original_raw
            assert current.fingerprint != original.fingerprint
            assert db.scalar(query) == 0
