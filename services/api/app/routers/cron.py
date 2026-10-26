"""Scheduled work, driven by an HTTP request.

A serverless deployment has no process that wakes up on its own, so the
things a running system would do on a timer — reading the portals, keeping
the SLA clocks honest, sending the daily digest — are done here, when the
host's scheduler asks.

The route is guarded by the deployment's cron secret. Vercel's scheduler
signs its calls with the ``CRON_SECRET`` set on the project; anything else
that finds the URL is refused. A deployment that has no secret configured
refuses cron work outright rather than running it for whoever asks.
"""

import logging

from fastapi import APIRouter, HTTPException, Request

from app import runtime
from app.config import settings

logger = logging.getLogger("bms.cron")

router = APIRouter(prefix="/api/cron", tags=["cron"])


def _authorized(request: Request) -> bool:
    expected = (settings.cron_secret or "").strip()
    if not expected:
        # Fail closed: an unsigned scheduler is an open invitation to make
        # the deployment read portals and send mail on demand.
        return False
    # Vercel's scheduler signs the call with the secret as a bearer token.
    # The x-vercel-cron header only marks an invocation as cron-shaped and is
    # trivially forgeable, so it never grants access on its own.
    header = request.headers.get("authorization", "")
    return header.startswith("Bearer ") and header[len("Bearer "):].strip() == expected


@router.get("/tick")
def tick(request: Request):
    if not _authorized(request):
        if not settings.cron_secret:
            raise HTTPException(
                status_code=503,
                detail="Scheduled work is not configured: set CRON_SECRET on the deployment.",
            )
        raise HTTPException(status_code=403, detail="Not authorized")

    from app.db import SessionLocal
    from app.services import digest, jobs

    db = SessionLocal()
    result = {"scan": {}, "watchdogs": {}, "digest": {}, "scored": 0}
    try:
        # Every phase draws from the request budget the middleware set, so a
        # slow portal leaves less time for the rest rather than pushing the
        # request past the host's limit.
        result["scan"] = jobs.run_scan(db)
        result["watchdogs"] = jobs.watchdogs(db)
        left = runtime.remaining()
        budget = settings.score_pending_budget_seconds
        if left is not None:
            budget = max(0.0, min(budget, left - 5.0))
        if budget > 2.0:
            result["scored"] = jobs.score_pending(db, budget_seconds=budget)
        result["digest"] = digest.send_digest(db)
        return result
    except Exception:
        logger.exception("cron tick failed")
        raise
    finally:
        db.close()
