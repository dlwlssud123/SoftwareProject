from alembic import context
from app import models  # noqa: F401 - register all tables
from app.core.base import Base
from app.core.database import engine

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    # Existing extension tables or unrelated application tables must remain untouched.
    return not (type_ == "table" and reflected and compare_to is None)


def include_name(name, type_, parent_names):
    # Same rule, applied before reflection: tables without a model (the raw-SQL RAG tables of
    # 20261114_03 with pgvector columns, extension tables) are not reflected at all, so
    # autogenerate/check neither warns about their types nor proposes dropping them.
    return type_ != "table" or name in target_metadata.tables


if context.is_offline_mode():
    context.configure(
        dialect_name="postgresql",
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()
else:

    def run_online(connection):
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            include_name=include_name,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()

    external_connection = context.config.attributes.get("connection")
    if external_connection is not None:
        run_online(external_connection)
    else:
        with engine.connect() as connection:
            run_online(connection)
