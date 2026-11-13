"""Add the RAG search index tables, rollback function and published-source view.

Settles the reviewed SQL draft v3 (docs/data/sql/rag_chunk_draft.sql, PR #11/#13/#39; the search part
is now docs/data/sql/rag_search.sql) as a migration, so the index can be loaded by app.jobs.load_rag_index without psql. Changes from the draft:

- rag_index_version.index_version is the *loaded* version: '<manifest index_version>.<binding>'.
  The binding is the published fingerprint each chunk was matched to. rag.index keeps its version
  when no chunk row changed, but a re-import can still give the same rows new fingerprints
  (validation/normalizer version bump). Such chunks would silently stop matching
  rag_source_active, so the loader loads them again under a new name instead of skipping.
  manifest_version and binding_sha256 keep both parts as columns.
- rag_source_active also returns row_sha256 (the source row hash the chunk was built from). The
  loader matches chunks through this view, so loading and search use one definition of
  "published".

No vector index on purpose: about 3.4k chunks per version, an exact scan is ~11 ms and never fights
the region filters. Add HNSW (vector_cosine_ops) with hnsw.iterative_scan when it grows past ~50k.

Revision ID: 20261114_03
Revises: 20261114_02
"""

import sqlalchemy as sa

from alembic import context, op

revision = "20261114_03"
down_revision = "20261114_02"
branch_labels = None
depends_on = None

DIM = 1024  # nlpai-lab/KURE-v1
# Frozen copies of the importer constants (app.jobs.import_*, agetech_data.*.revision.PROVIDER).
RECIPE_PROVIDER = "foodsafetykorea:COOKRCP01"
SEASONAL_PROVIDER = "data.go.kr:15168024"
WELFARE = {
    "welfare_central": ("ssis:NationalWelfareInformationsV001", "central_nationwide"),
    "welfare_local": ("ssis:LocalGovernmentWelfareInformations", "local"),
}


def _vector_type() -> str:
    # Qualify the type with the extension's schema, so the table works whatever the search_path
    # (tests migrate a fresh schema while the extension may already live in public).
    if context.is_offline_mode():
        return f"vector({DIM})"
    schema = op.get_bind().scalar(
        sa.text(
            "SELECT extnamespace::regnamespace::text FROM pg_extension WHERE extname = 'vector'"
        )
    )
    return f"{schema}.vector({DIM})"


def _welfare_select(source_type: str) -> str:
    provider, scope = WELFARE[source_type]
    return f"""
SELECT '{source_type}'::text, w.source_id::text, v.fingerprint::text, v.content_sha256::text
  FROM welfare_services w
  JOIN welfare_revisions v ON v.id = w.active_revision_id AND v.service_id = w.id
 WHERE w.provider = '{provider}' AND w.scope = '{scope}'
   AND w.publication_status = 'published'
   AND v.detail_state = 'ready' AND v.quality_status <> 'hold'"""


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    vector = _vector_type()
    op.execute(
        """
CREATE TABLE rag_index_version (
    index_version     text         PRIMARY KEY,
    manifest_version  text         NOT NULL,
    binding_sha256    char(64)     NOT NULL,
    embedding_model   text         NOT NULL,
    chunk_count       integer      NOT NULL CHECK (chunk_count > 0),
    manifest_sha256   char(64)     NOT NULL,
    data_versions     jsonb        NOT NULL,
    status            text         NOT NULL DEFAULT 'loading'
                      CHECK (status IN ('loading', 'active', 'retired', 'failed')),
    created_at        timestamptz  NOT NULL DEFAULT now(),
    activated_at      timestamptz,
    CHECK (index_version = manifest_version || '.' || left(binding_sha256, 12)),
    CHECK (status NOT IN ('active', 'retired') OR activated_at IS NOT NULL)
)"""
    )
    op.execute(
        "CREATE UNIQUE INDEX rag_index_version_one_active ON rag_index_version ((status)) "
        "WHERE status = 'active'"
    )
    op.execute(
        f"""
CREATE TABLE rag_chunk (
    index_version     text         NOT NULL REFERENCES rag_index_version (index_version) ON DELETE CASCADE,
    chunk_id          text         NOT NULL,
    source_type       text         NOT NULL
                      CHECK (source_type IN ('welfare_central', 'welfare_local', 'recipe', 'seasonal')),
    source_id         text         NOT NULL,
    section           text         NOT NULL,
    chunk_no          smallint     NOT NULL,
    title             text         NOT NULL,
    content           text         NOT NULL,
    content_sha256    char(64)     NOT NULL,
    region_scope      text         NOT NULL
                      CHECK (region_scope IN ('national', 'province', 'district', 'none')),
    ctpv              text,
    sgg               text,
    source_url        text,
    source_checked_at timestamptz,
    source_modified   date,
    period_end        date,
    quality_status    text         NOT NULL DEFAULT 'ok' CHECK (quality_status IN ('ok', 'flagged')),
    quality_flags     text[]       NOT NULL DEFAULT '{{}}',
    allergens         text[]       NOT NULL DEFAULT '{{}}',
    status            text         NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'retracted')),
    data_version      text         NOT NULL,
    source_record_sha256 char(64)  NOT NULL,
    embedding_model   text         NOT NULL,
    embedding         {vector}     NOT NULL,
    embedded_at       timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (index_version, chunk_id),
    CHECK (region_scope <> 'district' OR (ctpv IS NOT NULL AND sgg IS NOT NULL)),
    CHECK (region_scope <> 'province' OR (ctpv IS NOT NULL AND sgg IS NULL)),
    CHECK (region_scope NOT IN ('national', 'none') OR (ctpv IS NULL AND sgg IS NULL))
)"""
    )
    op.execute(
        "CREATE INDEX rag_chunk_source_idx ON rag_chunk (index_version, source_type, source_id)"
    )
    op.execute(
        "CREATE INDEX rag_chunk_region_idx ON rag_chunk (index_version, ctpv, sgg) "
        "WHERE status = 'active'"
    )
    comments = {
        "TABLE rag_index_version": "One loaded RAG index: a rag.index manifest bound to the published source fingerprints. At most one is active.",
        "COLUMN rag_index_version.index_version": "'<manifest_version>.<first 12 hex of binding_sha256>'",
        "COLUMN rag_index_version.manifest_version": "rag.index manifest.json index_version (UTC, e.g. 20261113T035158Z)",
        "COLUMN rag_index_version.binding_sha256": "sha256 of sorted 'chunk_id<TAB>source_record_sha256' lines of the loaded chunks",
        "COLUMN rag_index_version.chunk_count": "Chunks actually loaded (bound to a published source); checked on activation and rollback",
        "TABLE rag_chunk": "Search chunks of one index version. Only rows whose source_record_sha256 equals rag_source_active.record_sha256 may be used as evidence.",
        "COLUMN rag_chunk.source_record_sha256": "Fingerprint of the published DB revision this chunk was built from (seasonal: content_sha256)",
        "COLUMN rag_chunk.embedding": "KURE-v1 passage vector, L2-normalised; compare with <=> (cosine) and the same embedding_model only",
        "COLUMN rag_chunk.allergens": "Allergen names detected, flagged or undetermined; check quality_flags allergen_analysis_complete before excluding",
    }
    for target, comment in comments.items():
        quoted = comment.replace("'", "''")
        op.execute(f"COMMENT ON {target} IS '{quoted}'")

    op.execute(
        """
CREATE FUNCTION rag_rollback_index(previous_version text) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    target rag_index_version%ROWTYPE;
    actual_count bigint;
    mixed_models boolean;
BEGIN
    -- Same lock as the loader: search SELECTs go on, writers wait for the transaction.
    LOCK TABLE rag_index_version, rag_chunk IN EXCLUSIVE MODE;
    SELECT * INTO target FROM rag_index_version WHERE index_version = previous_version;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Rollback index version does not exist: %', previous_version
            USING ERRCODE = '22023';
    END IF;
    IF target.status NOT IN ('active', 'retired') OR target.activated_at IS NULL THEN
        RAISE EXCEPTION 'Rollback requires a previously activated version: %', previous_version
            USING ERRCODE = '22023';
    END IF;
    SELECT count(*), bool_or(embedding_model IS DISTINCT FROM target.embedding_model)
      INTO actual_count, mixed_models
      FROM rag_chunk WHERE index_version = previous_version;
    IF actual_count <> target.chunk_count OR coalesce(mixed_models, false) THEN
        RAISE EXCEPTION 'Rollback index count or model is invalid: %', previous_version
            USING ERRCODE = '23514';
    END IF;
    IF target.status = 'active' THEN
        RETURN;
    END IF;
    UPDATE rag_index_version SET status = 'retired' WHERE status = 'active';
    UPDATE rag_index_version SET status = 'active', activated_at = now()
      WHERE index_version = previous_version;
END;
$$"""
    )

    op.execute(
        f"""
CREATE VIEW rag_source_active (source_type, source_id, record_sha256, row_sha256) AS
{_welfare_select("welfare_central")}
UNION ALL
{_welfare_select("welfare_local")}
UNION ALL
SELECT 'recipe'::text, r.source_id::text, v.fingerprint::text, v.effective_sha256::text
  FROM recipes r
  JOIN recipe_revisions v ON v.id = r.active_revision_id AND v.recipe_id = r.id
 WHERE r.provider = '{RECIPE_PROVIDER}' AND v.quality_status <> 'hold'
UNION ALL
SELECT 'seasonal'::text, f.source_id::text, f.content_sha256::text, f.content_sha256::text
  FROM seasonal_foods f
 WHERE f.provider = '{SEASONAL_PROVIDER}' AND f.is_published AND f.detail_status = 'ok'"""
    )
    op.execute(
        "COMMENT ON VIEW rag_source_active IS 'Published source records RAG may cite: "
        "record_sha256 = published fingerprint (join rag_chunk.source_record_sha256), "
        "row_sha256 = source row hash the loader matches chunks by'"
    )


def downgrade() -> None:
    # The vector extension stays: docker/initdb creates it and other objects may use it.
    op.execute("DROP VIEW rag_source_active")
    op.execute("DROP FUNCTION rag_rollback_index(text)")
    op.execute("DROP TABLE rag_chunk")
    op.execute("DROP TABLE rag_index_version")
