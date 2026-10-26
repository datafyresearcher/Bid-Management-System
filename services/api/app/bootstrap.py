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
    """Bring a freshly started deployment up to a usable state.

    Three things happen here, in this order:

    * the knowledge base is seeded, because the scorer reads the company's
      licence and track record to decide whether a tender is even worth
      looking at;
    * the portals are read, but only when there is nothing to read yet — the
      database is shared, so a second instance does not re-read what the
      first one already captured;
    * whatever the last scan left waiting for a score is scored, so the
      review queue fills on its own.
    """
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from app.config import settings

    if settings.seed_on_startup:
        try:
            import seed

            # The schema was already brought up by the application before it
            # got here, so it is not checked a second time.
            seed.main(init=False)
        except Exception:
            logger.exception("Startup seed failed")
    try:
        apply_admin_password()
    except Exception:
        logger.exception("Administrator password rotation failed")
    try:
        populate_from_portals()
    except Exception:
        logger.exception("Startup portal read failed")
    try:
        score_leftovers()
    except Exception:
        logger.exception("Startup scoring pass failed")


def apply_admin_password():
    """Rotate the administrator's password when BMS_ADMIN_PASSWORD says so.

    Runs even when seeding is off, because the rotation is how an operator
    changes or recovers the admin password on a live deployment: set the
    variable, redeploy, sign in with the new password.
    """
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from app.config import settings
    from app.db import SessionLocal

    if not settings.admin_password:
        return False
    import seed

    db = SessionLocal()
    try:
        return seed.apply_admin_password(db)
    finally:
        db.close()


def score_leftovers():
    """Score whatever the last capture left waiting.

    A scan scores the tenders it captured, but a large capture can run out of
    its scoring budget before it reaches the end of the list. This picks up
    the rest, so tenders that were captured but never scored do not sit in
    the inbox with an empty review queue above them.
    """
    from app.config import settings
    from app.db import SessionLocal
    from app.services import jobs

    db = SessionLocal()
    try:
        scored = jobs.score_pending(db, budget_seconds=settings.startup_score_budget_seconds)
        if scored:
            logger.info("Startup scored %s tender(s) left over from an earlier capture", scored)
        return scored
    finally:
        db.close()


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

    Every portal is given a turn, and a portal that cannot be reached is
    recorded as such rather than left looking healthy and unread. Two things
    make that possible:

    * **Punjab is read first.** It is the only portal whose host may not
      answer at all from here, and a host that does not answer is discovered
      by trying to open a connection to it — which costs a few seconds. The
      federal portals answer quickly from anywhere, so they can afford to
      wait their turn.
    * **The budget is shared out fairly.** Each source gets a slice of what is
      left, so a slow portal cannot starve the one after it, and one request
      is bounded, so a portal that is slow today cannot spend the whole cold
      start on its own.
    """
    from app.config import settings
    from app.services import jobs

    limit = budget if budget is not None else settings.live_startup_budget
    started = time.monotonic()
    ordered = sorted(sources, key=lambda s: (s.tier or "", s.code))
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
                request_timeout=settings.live_startup_request_timeout,
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
