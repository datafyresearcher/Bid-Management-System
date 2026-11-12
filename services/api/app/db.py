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

if settings.database_url.startswith("sqlite"):
    # SQLite does not enforce foreign keys unless it is told to, and the
    # deployment runs on PostgreSQL, which always does. A row deleted while
    # another still points at it is refused by the deployment and quietly
    # allowed here, so the two would not agree — and the difference would
    # only ever show up in production. SQLite is therefore held to the same
    # rule as the database the system actually runs on.
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _enforce_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

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
#
# The defaults are written the way PostgreSQL writes them. A boolean column
# cannot be given the default `0` there — the database refuses the statement
# with a type mismatch, the column is never added, and every query that
# selects it afterwards fails with "column does not exist". That is not a
# warning a deployment can be left to get past: the column the code expects
# is simply not there.
ADDED_COLUMNS = {
    "ai_metrics": [
        ("simulated", "BOOLEAN DEFAULT false"),
        ("cached", "BOOLEAN DEFAULT false"),
        ("error", "VARCHAR(200) DEFAULT ''"),
        ("attempts", "INTEGER DEFAULT 1"),
    ],
    "opportunities": [
        ("ai_confidence", "FLOAT"),
        ("extraction_grade", "VARCHAR(20) DEFAULT ''"),
        ("source_id", "INTEGER"),
        ("bid_summary", "JSON"),
        ("bid_security_percent", "FLOAT"),
        ("estimated_boq_value", "FLOAT"),
        ("boq_estimate_note", "VARCHAR(300) DEFAULT ''"),
    ],
    "library_documents": [
        ("shared", "BOOLEAN DEFAULT false"),
        ("locked", "BOOLEAN DEFAULT false"),
        ("category", "VARCHAR(80) DEFAULT 'General'"),
        ("valid_until", "VARCHAR(40) DEFAULT ''"),
    ],
    "proposals": [
        ("included_kb_docs", "JSON"),
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
    "documents": [
        ("source_url", "VARCHAR(600) DEFAULT ''"),
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


def backfill_ntdc_notice_links():
    """Point every NTDC tender's notice link at the tender itself.

    NTDC publishes no page per notice — its tenders page is a single-page
    application that opens each tender in a dialog — so the tender is a file,
    and that file is the only addressable link to it. The records captured
    before that was understood carried the tenders listing as their notice
    link, which is why clicking "Open notice" for an NTDC tender opened the
    NTDC website instead of the tender.

    The document link is already captured against each record, so this
    rewrites the notice links in place and every tender already on file opens
    its own document without waiting for the next scan.
    """
    from sqlalchemy import select

    from app.connectors.ntdc import NTDCConnector, encode_path
    from app.models import Opportunity

    listing = NTDCConnector.LISTING_URL
    base = NTDCConnector.DOCUMENT_BASE
    uploads = base + "/uploads"
    session = SessionLocal()
    try:
        rows = session.execute(select(Opportunity.id, Opportunity.source_refs)).all()
        updates = []
        for opp_id, refs in rows:
            if not isinstance(refs, list) or not refs:
                continue
            updated = []
            dirty = False
            for ref in refs:
                if not isinstance(ref, dict) or ref.get("source_code") != "ntdc":
                    updated.append(ref)
                    continue
                document = ref.get("document_url") or ""
                if document.rstrip("/") in {base.rstrip("/"), listing.rstrip("/")} - {""}:
                    # A capture that fell back to the portal's own address
                    # carries no document. It must not be offered as one.
                    document = ""
                if document.startswith(base):
                    target = base + encode_path(document[len(base):])
                elif document:
                    target = document
                elif (ref.get("url") or "").startswith(uploads):
                    # The captures made before the document link was stored
                    # carried the broken "/uploads" path as the notice link.
                    # That path does not exist, and because the site answers
                    # every unknown path with its application shell, the link
                    # answered 200 with a web page instead of the tender. The
                    # rest of the path is the site-root path, so the real file
                    # can be recovered from it.
                    target = base + encode_path(ref["url"][len(uploads):])
                else:
                    # No document was captured against this notice, so there
                    # is nothing better to point at. Whatever the record
                    # carries is left as it is: rewriting it here would throw
                    # away what the capture knew, and choosing the listing is
                    # the connector's job, not this one's.
                    target = ref.get("url") or listing
                if ref.get("url") != target:
                    ref = dict(ref)
                    ref["url"] = target
                    dirty = True
                updated.append(ref)
            if dirty:
                updates.append({"id": opp_id, "source_refs": updated})
        if updates:
            # Written in one batch rather than one statement at a time. On a
            # serverless instance a cold start is the wrong place to spend
            # thousands of round trips to a database on another continent.
            session.bulk_update_mappings(Opportunity, updates)
            session.commit()
            logger.info("Pointed %s NTDC notice links at their own tender", len(updates))
        return len(updates)
    except Exception as exc:
        logger.warning("NTDC notice link backfill skipped: %s", exc)
        session.rollback()
        return 0
    finally:
        session.close()


def backfill_derived_document_links():
    """Give every tender on file the document link its own id already determines.

    Some authorities publish the bidding document under a path built out of
    the notice's own id. Where that is the case, the link is known from the
    record alone — no request to the portal is needed to find it, and every
    tender on file can be given it without waiting for the next scan to walk
    past it again.

    A record that already carries a link is left exactly as it is. This only
    ever fills in a link that is missing.
    """
    from sqlalchemy import select

    from app.connectors.registry import get_connector
    from app.models import Opportunity, Source

    session = SessionLocal()
    try:
        connectors = {}
        for source in session.execute(select(Source)).scalars().all():
            connector = get_connector(source)
            if connector is not None:
                connectors[source.id] = connector
        if not connectors:
            return 0

        rows = session.execute(select(Opportunity.id, Opportunity.source_refs)).all()
        updates = []
        for opp_id, refs in rows:
            if not isinstance(refs, list) or not refs:
                continue
            updated = []
            dirty = False
            for ref in refs:
                if not isinstance(ref, dict):
                    updated.append(ref)
                    continue
                connector = connectors.get(ref.get("source_id"))
                if connector is None or ref.get("document_url"):
                    updated.append(ref)
                    continue
                try:
                    derived = connector.document_url_for(ref.get("native_id") or "") or ""
                except Exception:
                    derived = ""
                if derived:
                    ref = dict(ref)
                    ref["document_url"] = derived
                    dirty = True
                updated.append(ref)
            if dirty:
                updates.append({"id": opp_id, "source_refs": updated})
        if updates:
            session.bulk_update_mappings(Opportunity, updates)
            session.commit()
            logger.info("Gave %s tenders the document link their id determines", len(updates))
        return len(updates)
    except Exception as exc:
        logger.warning("Derived document link backfill skipped: %s", exc)
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
    backfill_ntdc_notice_links()
    backfill_derived_document_links()
