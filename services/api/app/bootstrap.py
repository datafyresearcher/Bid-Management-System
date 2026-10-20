import logging
import sys
import time
from pathlib import Path

logger = logging.getLogger("bms.bootstrap")


def ensure_seeded():
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    try:
        import seed

        seed.main()
    except Exception:
        logger.exception("Startup seed failed")
    try:
        populate_from_portals()
    except Exception:
        logger.exception("Startup portal read failed")


def populate_from_portals():
    """Read the portals when a deployment starts with an empty database.

    A serverless instance starts with nothing, and a dashboard that announces
    live reading while showing no tenders is not much use. This reads the
    portals within a small budget, so that the first request a person makes
    already has real tenders behind it.

    The budget is deliberately small — one page per source, a short deadline,
    a short connect timeout — because the read happens inside the first
    request, and a portal that cannot be reached must not hold that request
    up. What is read is committed source by source, so what was read is kept
    even if the budget runs out half way.
    """
    from app.config import settings

    if settings.fixtures:
        # The demo pipeline has already filled the database.
        return

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Opportunity, Source
    from app.services import jobs

    db = SessionLocal()
    try:
        if db.execute(select(Opportunity.id).limit(1)).scalar_one_or_none():
            # This instance already holds tenders; there is nothing to read.
            return
        sources = db.execute(
            select(Source).where(Source.type == "portal", Source.enabled == True)  # noqa: E712
        ).scalars().all()
        read_within_budget(db, sources)
    finally:
        db.close()


def read_within_budget(db, sources, budget=None):
    """Read the given sources until the budget is spent.

    The federal portals answer quickly from anywhere. Punjab's answers only
    from inside Pakistan, so it comes last and is often not reached within
    the budget.
    """
    from app.config import settings
    from app.services import jobs

    limit = budget if budget is not None else settings.live_startup_budget
    started = time.monotonic()
    for source in sorted(sources, key=lambda s: (s.tier != "P1", s.code)):
        left = limit - (time.monotonic() - started)
        if left < 6:
            logger.info("Startup read stopped after %.0fs", time.monotonic() - started)
            break
        try:
            jobs.run_source(db, source, page_budget=1, scan_seconds=6, connect_timeout=4)
        except Exception:
            logger.warning("Startup read of %s failed", source.code)
