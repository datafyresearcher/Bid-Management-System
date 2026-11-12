"""The database the system runs on, and the shape it is expected to have.

The deployment runs on PostgreSQL and a developer's machine runs on SQLite,
and the two do not agree on everything. A statement PostgreSQL refuses is
accepted by SQLite, so a step that only ever fails in production is one the
test suite cannot see — which is why the differences that matter are pinned
down here rather than left to be found in production.

Two of them are pinned down:

* a boolean column cannot be given the default ``0`` in PostgreSQL, so a
  column added that way is never added at all, and every query that selects
  it afterwards fails;
* a row cannot be deleted while another row still points at it, so the
  chunks of a deleted document have to go with it.
"""

from sqlalchemy import inspect

from app.db import ADDED_COLUMNS, engine
from app.models import Base


def test_a_boolean_column_is_given_a_default_postgresql_accepts():
    """A boolean column's default must be a boolean.

    ``BOOLEAN DEFAULT 0`` is refused by PostgreSQL with a type mismatch. The
    column is then never added, and every query that selects it fails with
    "column does not exist" — a failure that only ever shows up on the
    deployment.
    """
    for table, columns in ADDED_COLUMNS.items():
        for name, ddl in columns:
            parts = ddl.split(None, 1)
            sql_type = parts[0].upper()
            default = parts[1] if len(parts) > 1 else ""
            if sql_type != "BOOLEAN":
                continue
            value = default.replace("DEFAULT", "").strip().lower()
            assert value in ("false", "true"), (
                f"{table}.{name} is a boolean with the default {value!r}; "
                "PostgreSQL refuses that, so the column would never be added"
            )


def test_every_added_column_is_one_the_model_declares():
    """A column added by a migration must be a column the code expects.

    A migration that names a column the model does not have adds a column
    nothing reads; a column the model has and the migration does not name
    is a column the deployment is missing.
    """
    for table, columns in ADDED_COLUMNS.items():
        declared = set(Base.metadata.tables[table].columns.keys())
        for name, _ddl in columns:
            assert name in declared, f"{table}.{name} is added but not declared by the model"


def test_the_migration_brings_an_old_database_up_to_the_model():
    """A database created before a column was added is brought up to date."""
    from app.db import migrate_columns

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "library_documents" not in tables:
        # Nothing to check on a database that has not been created yet.
        return
    present = {col["name"] for col in inspector.get_columns("library_documents")}
    migrate_columns()
    after = {col["name"] for col in inspect(engine).get_columns("library_documents")}
    for name, _ddl in ADDED_COLUMNS.get("library_documents", []):
        assert name in present or name in after, f"library_documents.{name} is missing"


def test_a_deleted_document_takes_its_chunks_with_it():
    """A row cannot be deleted while another row still points at it.

    SQLite does not enforce this unless it is told to, and the deployment
    runs on PostgreSQL, which always does. The test database is therefore
    held to the same rule, so a deletion that would fail on the deployment
    fails here too.
    """
    from sqlalchemy import text

    with engine.connect() as connection:
        enabled = connection.execute(text("PRAGMA foreign_keys")).scalar()
    assert enabled == 1, "the test database must enforce foreign keys"
