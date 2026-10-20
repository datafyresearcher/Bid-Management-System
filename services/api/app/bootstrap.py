import logging
import sys
import time
from pathlib import Path

logger = logging.getLogger("bms.bootstrap")

# The connect timeout the cold start allows. A source is only attempted when
# at least this much of the budget is left, because a host that cannot be
# reached is only discovered by trying to open a connection to it.
CONNECT_ATTEMPT_COST = 4.0


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
    from inside Pakistan, so it comes last — but it is still read, because a
    portal that cannot be reached has to be recorded as such rather than left
    looking healthy and unread.

    The budget is shared out fairly: each source gets a slice of what is
    left, so a slow portal cannot starve the one after it. A host that does
    not answer fails on the connect timeout, which costs a few seconds and
    tells the dashboard the truth about that portal.
    """
    from app.config import settings
    from app.services import jobs

    limit = budget if budget is not None else settings.live_startup_budget
    started = time.monotonic()
    ordered = sorted(sources, key=lambda s: (s.tier != "P1", s.code))
    for index, source in enumerate(ordered):
        left = limit - (time.monotonic() - started)
        if left < CONNECT_ATTEMPT_COST:
            # Not even a connection attempt fits in what is left.
            logger.info("Startup read stopped after %.0fs", time.monotonic() - started)
            break
        remaining = len(ordered) - index
        slice_seconds = max(3.0, min(6.0, left / remaining))
        try:
            jobs.run_source(
                db,
                source,
                page_budget=1,
                scan_seconds=slice_seconds,
                connect_timeout=4,
                # A host that cannot be reached costs the same however many
                # times it is tried, so the cold start does not wait for it.
                retries=0,
            )
        except Exception as exc:
            # Record the failure. A portal this deployment cannot reach has to
            # be recorded as unread, or it looks healthy on the register and
            # the dashboard invites a Scan that can never succeed.
            logger.warning("Startup read of %s failed", source.code)
            jobs.record_scan_failure(db, source, exc)
