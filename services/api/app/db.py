import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

logger = logging.getLogger("bms.db")

connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Columns added after the first release. `create_all` only creates missing
# tables, it never alters existing ones, so an upgraded database keeps the old
# shape without these steps. Each entry maps a table to the columns it must
# have, with the SQL type and default to apply.
ADDED_COLUMNS = {
    "ai_metrics": [
        ("simulated", "BOOLEAN DEFAULT 0"),
        ("cached", "BOOLEAN DEFAULT 0"),
        ("error", "VARCHAR(200) DEFAULT ''"),
        ("attempts", "INTEGER DEFAULT 1"),
    ],
    "opportunities": [
        ("ai_confidence", "FLOAT"),
        ("extraction_grade", "VARCHAR(20) DEFAULT ''"),
    ],
}


def migrate_columns():
    """Add any missing columns to existing tables. Safe to run on every start."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table, columns in ADDED_COLUMNS.items():
        if table not in existing_tables:
            continue
        present = {col["name"] for col in inspector.get_columns(table)}
        for name, ddl in columns:
            if name in present:
                continue
            try:
                with engine.begin() as conn:
                    conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {ddl}'))
                logger.info("Migrated: added %s.%s", table, name)
            except Exception as exc:
                logger.warning("Could not add %s.%s: %s", table, name, exc)


def init_db():
    from app import models

    Base.metadata.create_all(bind=engine)
    migrate_columns()
