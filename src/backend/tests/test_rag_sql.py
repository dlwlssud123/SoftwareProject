"""RAG tables from Alembic 20261114_03: rollback function, published-source view, migration round trip."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import pytest
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_public_data_import import corrections, snapshot

from alembic import command
from app.jobs import import_public_data as importer
from app.models import Recipe, RecipeRevision

ALEMBIC_INI = Path(__file__).parents[1] / "alembic.ini"


@pytest.fixture
def rag_db(pg_connection):
    schema = pg_connection.scalar(text("SELECT current_schema()"))
    assert schema.startswith("import_test_") and len(schema) == 44
    # public too: the vector extension (and its <=> operator) may live there.
    pg_connection.execute(text(f'SET search_path TO "{schema}", public'))
    pg_connection.commit()
    return pg_connection


def version_name(manifest_version):
    binding = hashlib.sha256(manifest_version.encode()).hexdigest()
    return f"{manifest_version}.{binding[:12]}", binding


def add_index(
    db,
    manifest_version,
    *,
    status="retired",
    activated=True,
    declared_count=1,
    chunk_model="test-model",
    source_fingerprint="0" * 64,
):
    name, binding = version_name(manifest_version)
    db.execute(
        text(
            "INSERT INTO rag_index_version (index_version, manifest_version, binding_sha256, "
            "embedding_model, chunk_count, manifest_sha256, data_versions, status, activated_at) "
            "VALUES (:name, :manifest, :binding, 'test-model', :count, :digest, '{}', :status, "
            ":activated)"
        ),
        {
            "name": name,
            "manifest": manifest_version,
            "binding": binding,
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
    return name


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
        {"status": "loading", "activated": False},
        {"status": "failed", "activated": False},
        {"declared_count": 2},
        {"chunk_model": "different-model"},
    ],
)
def test_invalid_rollback_preserves_current_index(rag_db, target):
    current = add_index(rag_db, "current", status="active")
    previous = (
        add_index(rag_db, "previous", **target)
        if target is not None
        else version_name("previous")[0]
    )
    rag_db.commit()
    with pytest.raises(DBAPIError), rag_db.begin():
        rag_db.execute(
            text("SELECT rag_rollback_index(:previous)"), {"previous": previous}
        )
    assert active_versions(rag_db) == [current]


def test_table_checks_keep_versions_consistent(rag_db):
    # an activated status needs activated_at, and the name must be '<manifest>.<binding 12>'
    with pytest.raises(DBAPIError), rag_db.begin():
        add_index(rag_db, "x", status="retired", activated=False)
    with pytest.raises(DBAPIError), rag_db.begin():
        rag_db.execute(
            text(
                "INSERT INTO rag_index_version (index_version, manifest_version, binding_sha256, "
                "embedding_model, chunk_count, manifest_sha256, data_versions) "
                "VALUES ('free-name', 'm', :b, 'model', 1, :b, '[]')"
            ),
            {"b": "a" * 64},
        )
    with pytest.raises(DBAPIError), rag_db.begin():
        add_index(rag_db, "one", status="active")
        add_index(rag_db, "two", status="active")


def test_valid_rollback_is_atomic_and_idempotent(rag_db):
    current = add_index(rag_db, "current", status="active")
    previous = add_index(rag_db, "previous")
    rag_db.commit()
    with rag_db.begin():
        rag_db.execute(text("SELECT rag_rollback_index(:v)"), {"v": previous})
    activated = rag_db.scalar(
        text("SELECT activated_at FROM rag_index_version WHERE index_version = :v"),
        {"v": previous},
    )
    rag_db.commit()
    with rag_db.begin():
        rag_db.execute(text("SELECT rag_rollback_index(:v)"), {"v": previous})
    assert active_versions(rag_db) == [previous]
    status, again = rag_db.execute(
        text(
            "SELECT (SELECT status FROM rag_index_version WHERE index_version = :c), "
            "(SELECT activated_at FROM rag_index_version WHERE index_version = :p)"
        ),
        {"c": current, "p": previous},
    ).one()
    assert status == "retired" and again == activated


def test_concurrent_rollbacks_keep_one_complete_active_version(rag_db):
    add_index(rag_db, "current", status="active")
    left, right = add_index(rag_db, "left"), add_index(rag_db, "right")
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
        assert list(pool.map(rollback, [left, right])) == [True, True]
    active = active_versions(rag_db)
    assert len(active) == 1 and active[0] in {left, right}


def test_source_view_rejects_old_chunks_after_same_raw_is_revalidated(
    rag_db, tmp_path, monkeypatch
):
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
        # the view also returns the row hash the loader binds chunks by
        with db.begin():
            row = db.execute(
                text(
                    "SELECT record_sha256, row_sha256 FROM rag_source_active "
                    "WHERE source_type = 'recipe' AND source_id = '1'"
                )
            ).one()
        assert tuple(row) == (original.fingerprint, original.effective_sha256)
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


def test_migration_downgrade_drops_rag_objects_and_upgrade_restores_them(rag_db):
    def objects():
        return rag_db.execute(
            text(
                "SELECT to_regclass('rag_index_version') IS NOT NULL, "
                "to_regclass('rag_chunk') IS NOT NULL, to_regclass('rag_source_active') IS NOT NULL, "
                "to_regprocedure('rag_rollback_index(text)') IS NOT NULL"
            )
        ).one()

    config = Config(str(ALEMBIC_INI))
    config.attributes["connection"] = rag_db
    assert tuple(objects()) == (True, True, True, True)
    command.downgrade(config, "20261114_02")
    rag_db.commit()
    assert tuple(objects()) == (False, False, False, False)
    # the extension stays (docker/initdb creates it; other objects may use it)
    assert rag_db.scalar(
        text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
    )
    command.upgrade(config, "head")
    rag_db.commit()
    assert tuple(objects()) == (True, True, True, True)
