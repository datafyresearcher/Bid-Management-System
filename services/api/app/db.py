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
        ("source_id", "INTEGER"),
    ],
    "sources": [
        ("authority", "VARCHAR(250) DEFAULT ''"),
        ("tier", "VARCHAR(8) DEFAULT ''"),
        ("access", "VARCHAR(40) DEFAULT 'public'"),
        ("listing_url", "VARCHAR(500) DEFAULT ''"),
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


def sync_source_registry():
    """Apply the authorized source registry to the database.

    The registry holds the authoritative portal URLs and the authority behind
    each one. It is applied on every start, not only during seeding, so a
    running instance never keeps serving a stale or dead portal link.
    """
    from app.source_registry import sync_source_registry as apply_registry

    session = SessionLocal()
    try:
        return apply_registry(session)
    except Exception as exc:
        logger.warning("Source registry sync skipped: %s", exc)
        session.rollback()
        return (0, 0)
    finally:
        session.close()


def backfill_opportunity_sources():
    """Point every opportunity at the source registry row it was captured from.

    Records written before the source registry was linked only carry the source
    code inside the `source_refs` JSON blob. Resolving that to a real row keeps
    the dashboard attribution truthful without re-scanning any portal.
    """
    from sqlalchemy import select

    from app.models import Opportunity, Source

    session = SessionLocal()
    try:
        codes = {s.code: s.id for s in session.execute(select(Source)).scalars().all()}
        if not codes:
            return 0
        rows = session.execute(select(Opportunity.id, Opportunity.source_id, Opportunity.source_refs)).all()
        linked = 0
        for opp_id, source_id, refs in rows:
            if source_id or not refs:
                continue
            if not isinstance(refs, list) or not refs:
                continue
            first = refs[0]
            if not isinstance(first, dict):
                continue
            code = first.get("source_code")
            if not code or code not in codes:
                continue
            opp = session.get(Opportunity, opp_id)
            if opp is not None:
                opp.source_id = codes[code]
                linked += 1
        if linked:
            session.commit()
            logger.info("Backfilled source_id on %s opportunities", linked)
        return linked
    except Exception as exc:
        logger.warning("Opportunity source backfill skipped: %s", exc)
        session.rollback()
        return 0
    finally:
        session.close()


def init_db():
    from app import models

    Base.metadata.create_all(bind=engine)
    migrate_columns()
    # Order matters: the registry must exist before opportunities can be
    # pointed at a source row.
    sync_source_registry()
    backfill_opportunity_sources()
