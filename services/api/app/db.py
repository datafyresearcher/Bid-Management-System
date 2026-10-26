import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

logger = logging.getLogger("bms.db")

# The application runs in two places. On a developer machine it talks to a
# local SQLite file; when it is deployed it talks to PostgreSQL on Supabase.
# The two need different engines, so the difference is decided once here.
#
# Why PostgreSQL for the deployment: a serverless instance is a throwaway
# container with a throwaway disk. A SQLite file written by one request is
# gone by the next one, so a scan's results — and the review gates that scan
# opened — vanished between two clicks. A managed PostgreSQL database is
# shared by every instance, so what a scan writes is still there for the next
# request to read.
IS_POSTGRES = settings.database_url.startswith("postgres")

connect_args = {}
engine_kwargs = {"future": True}

if IS_POSTGRES:
    # The connection is pooled, not thrown away. A sessionless pool would close
    # the connection every time a transaction commits, so every write would
    # pay for a fresh DNS lookup and TLS handshake — which, to a database on
    # another continent, is far more expensive than the write itself.
    engine_kwargs["pool_size"] = settings.db_pool_size
    engine_kwargs["max_overflow"] = settings.db_max_overflow
    engine_kwargs["pool_timeout"] = settings.db_pool_timeout
    engine_kwargs["pool_recycle"] = settings.db_pool_recycle
    # A dropped connection is detected on checkout rather than surfacing as a
    # failed query halfway through a scan.
    engine_kwargs["pool_pre_ping"] = True
    connect_args = {
        # psycopg's automatic prepared statements are not safe behind a
        # transaction-mode pooler, so they are switched off.
        "prepare_threshold": None,
    }
    if "sslmode" not in settings.database_url:
        connect_args["sslmode"] = settings.db_sslmode
elif settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(settings.database_url, connect_args=connect_args, **engine_kwargs)
# Objects keep their values after a commit instead of being expired and read
# back. The application writes a row and then reads it again in the same
# request more often than not, and on a database that is reached over the
# network each of those reads is a round trip worth not paying.
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True
)



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
    "company_profile": [
        ("email", "VARCHAR(200) DEFAULT ''"),
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

    try:
        # Asking the database which tables it already has costs one question.
        # Letting `create_all` work that out table by table costs one
        # question per table, which on a database reached over the network is
        # a noticeable part of a cold start.
        existing = set(inspect(engine).get_table_names())
        missing = [table for name, table in Base.metadata.tables.items() if name not in existing]
        if missing:
            Base.metadata.create_all(bind=engine, tables=missing, checkfirst=False)
    except Exception as exc:
        # Two serverless instances can start at the same moment and both try
        # to create the same table. The loser of that race sees "already
        # exists", which means the schema is there and nothing is broken.
        logger.info("Schema creation reported: %s", exc)
    migrate_columns()
    # Order matters: the registry must exist before opportunities can be
    # pointed at a source row.
    sync_source_registry()
    backfill_opportunity_sources()
