import asyncio
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from sqlalchemy import select

from app import runtime
from app.config import settings
from app.db import SessionLocal
from app.models import GateTask, NotificationEvent, Opportunity, Source
from app.services import notifications
from app.services.utils import utcnow
logger = logging.getLogger("bms.jobs")

ACTIVE_STATES = {
    "NEW", "NORMALIZED", "SCORED", "GATE1", "DOCS_FETCHED", "ANALYZED", "GATE2",
    "DRAFTING", "GATE3", "ASSEMBLY", "GATE4", "READY_TO_SUBMIT", "GATE5",
}


def _item_deadline(batch_deadline):
    """The deadline for one tender's model call.

    A batch budget on its own is not enough. The budget is checked between
    tenders, so a single model call that hangs would still hold the request
    open for the full timeout — and with retries on top of that, long past
    the end of the request that started it. Each tender therefore gets its
    own, shorter deadline, and the batch budget still applies on top.
    """
    item = time.monotonic() + settings.score_item_seconds
    if batch_deadline is None:
        return item
    return min(item, batch_deadline)


def _narrate_now(batch_deadline):
    """Is there room in the batch for a model call on the next tender?

    The score of a tender does not need the model — only the written
    explanation does. So when the batch is running out of time the tender is
    still scored and still opens its gate; it just gets the deterministic
    explanation. On a free-tier model, where a single answer can take the
    better part of twenty seconds, that is the difference between a review
    queue that fills and one that does not.
    """
    if batch_deadline is None:
        return True
    return (batch_deadline - time.monotonic()) >= settings.score_item_seconds


def _score_parallel(opportunity_ids, budget_seconds, workers):
    """Score a batch across a few connections at the same time.

    Each tender is scored on its own, so a batch can be spread over a few
    connections and finished in a fraction of the time. The database is
    reached over the network, and a tender scored on its own spends most of
    that time waiting for the database rather than doing work.
    """
    from app.services import scorer

    deadline = time.monotonic() + budget_seconds if budget_seconds else None
    ids = list(opportunity_ids)
    total = {"scored": 0}
    guard = threading.Lock()

    def worker(chunk):
        session = SessionLocal()
        scored_here = 0
        try:
            ctx = scorer.load_context(session)
            for opp_id in chunk:
                if deadline is not None and time.monotonic() > deadline:
                    break
                opp = session.get(Opportunity, opp_id)
                if opp is None:
                    continue
                try:
                    narrate = _narrate_now(deadline)
                    scorer.run(
                        session,
                        opp,
                        ctx=ctx,
                        deadline=_item_deadline(deadline) if narrate else None,
                        narrate=narrate,
                    )
                    scored_here += 1
                except Exception:
                    logger.exception("scoring failed for opportunity %s", opp_id)
                    session.rollback()
        finally:
            session.close()
        with guard:
            total["scored"] += scored_here

    chunks = [ids[i::workers] for i in range(workers)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(worker, chunks))
    return total["scored"]


def score_new(db, opportunity_ids, budget_seconds=None, workers=None):
    """Score freshly captured tenders so the review gates open on their own.

    A scan used to leave every new tender sitting in NORMALIZED, waiting for
    somebody to press Score on each one. Nothing reached the review queue, so
    the gate queue read "no pending gates" even though a scan had just run.
    Scoring the capture closes that gap: a tender that clears the hard gates
    opens Gate 1, and one that does not is screened out with the reason
    recorded against it.

    A tender that fails to score is left where it was rather than taking the
    rest of the capture down with it. The budget stops a very large capture
    from running past the end of the request that started it; whatever is
    left over is picked up by the next pass.
    """
    from app.services import scorer

    if not opportunity_ids:
        return 0
    workers = workers if workers is not None else settings.score_workers
    # Whatever is left of the request is what this batch may spend.
    left = runtime.remaining()
    if left is not None:
        budget_seconds = min(budget_seconds, left) if budget_seconds else left
    if workers > 1 and len(opportunity_ids) > 1:
        return _score_parallel(opportunity_ids, budget_seconds, workers)

    deadline = time.monotonic() + budget_seconds if budget_seconds else None
    scored = 0
    # The company's own record is read once for the whole batch rather than
    # once per tender. It does not change while the batch runs.
    ctx = scorer.load_context(db)
    for position, opp_id in enumerate(opportunity_ids):
        if deadline is not None and time.monotonic() > deadline:
            logger.info(
                "Scoring stopped at the budget with %s tender(s) still waiting",
                len(opportunity_ids) - position,
            )
            break
        opp = db.get(Opportunity, opp_id)
        if opp is None:
            continue
        try:
            narrate = _narrate_now(deadline)
            scorer.run(
                db,
                opp,
                ctx=ctx,
                deadline=_item_deadline(deadline) if narrate else None,
                narrate=narrate,
            )
            scored += 1
        except Exception:
            logger.exception("scoring failed for opportunity %s", opp_id)
            db.rollback()
    db.commit()
    return scored


def score_pending(db, budget_seconds=None, workers=None):
    """Score every captured tender that is still waiting for a score.

    This is the catch-up pass. A scan scores what it captured, and whatever
    did not fit inside the budget is scored here, so the review queue fills up
    instead of waiting for somebody to press Score on every tender by hand.
    """
    pending = (
        db.execute(select(Opportunity.id).where(Opportunity.state == "NORMALIZED"))
        .scalars()
        .all()
    )
    if not pending:
        return 0
    left = runtime.remaining()
    if left is not None:
        budget_seconds = min(budget_seconds, left) if budget_seconds else left
    return score_new(db, list(pending), budget_seconds=budget_seconds, workers=workers)


def run_source(db, source, page_budget=None, scan_seconds=None, connect_timeout=None, retries=None, request_timeout=None) -> dict:
    """Read one source and file what it found.

    The budgets are per-scan overrides. A read that has to fit inside a tight
    window — the first read of a freshly started deployment, for instance —
    can ask for fewer pages and a shorter deadline without changing the
    settings for every other scan.
    """
    from app.connectors.registry import get_connector
    from app.services import normalizer

    started = time.monotonic()
    connector = get_connector(source)
    if not connector:
        source.health = "no_adapter"
        db.commit()
        return {"error": "no_adapter"}
    if page_budget is not None:
        connector.page_budget = page_budget
    if scan_seconds is not None:
        connector.scan_seconds = scan_seconds
    # The read and the scoring that follows it share one budget. A read that
    # used most of the request's time leaves the scoring a short one, which
    # is the right answer: the capture is already recorded, and the scoring
    # of it is picked up by the next pass.
    left = runtime.remaining()
    if left is not None:
        # The connector falls back to the configured deadline when it has no
        # deadline of its own, so use the same fallback here.
        current = connector.scan_seconds if connector.scan_seconds is not None else settings.live_scan_deadline
        connector.scan_seconds = max(5.0, min(current, left))
    if connect_timeout is not None:
        connector.connect_timeout = connect_timeout
    if retries is not None:
        connector.retries = retries
    if request_timeout is not None:
        connector.request_timeout = request_timeout

    notices = connector.fetch_listing() or []
    raw = getattr(connector, "last_raw", None)
    if raw:
        normalizer.store_snapshot(db, source, None, source.url, raw, kind="listing", meta={"adapter": source.adapter})

    before_ids = set(db.execute(select(Opportunity.id)).scalars().all())
    # The whole listing is captured in one pass, so a portal that published a
    # hundred tenders since the last scan does not cost a hundred round trips.
    normalizer.normalize_notices(db, source, notices)
    after_ids = set(db.execute(select(Opportunity.id)).scalars().all())
    new_ids = after_ids - before_ids
    created = len(new_ids)

    # A portal that answers but yields nothing has changed shape under us.
    # That is a drift signal, not a healthy scan, so it is not recorded as one.
    if notices:
        source.health = "ok"
    else:
        source.health = "degraded"
    source.last_scan_at = utcnow()
    source.last_scan_stats = {
        "notices": len(notices),
        "new": created,
        "updated": max(0, len(notices) - created),
        # Be explicit about whether this capture came off the live portal or
        # from a saved copy of one. The dashboard shows this to the user.
        "mode": "saved-capture" if connector.fixture_mode else "live",
        "seconds": round(time.monotonic() - started, 1),
    }
    db.commit()

    # Scoring happens after the capture is committed, so a tender that reaches
    # the review queue is already recorded even if the scoring is interrupted.
    budget = settings.score_budget_seconds
    left = runtime.remaining()
    if left is not None:
        budget = max(0.0, min(budget, left))
    scored = score_new(db, sorted(new_ids), budget_seconds=budget)
    if scored:
        source.last_scan_stats["scored"] = scored
        db.commit()

    if created:
        notifications.notify(
            db,
            "scan",
            f"{created} new tender(s) from {source.name}",
            f"Source {source.code} scanned: {len(notices)} notices processed.",
            severity="info",
        )
    _email_new_passing(db, source, sorted(new_ids))
    return {"notices": len(notices), "new": created, "scored": scored}


def _email_new_passing(db, source, new_ids):
    """One email for the tenders from this capture that cleared screening.

    The digest is the daily habit; this is the same-day alert — a tender that
    passed the hard gates and opened its review gate is the thing a bid
    manager would want to know about before lunch, not tomorrow morning.
    Batched per capture so a busy portal day is one message, not forty.
    """
    if not new_ids:
        return
    from app.config import settings as _settings
    from app.services import digest as digest_service
    from app.services import emailer

    if not emailer.configured():
        return
    passing = (
        db.execute(
            select(Opportunity).where(
                Opportunity.id.in_(new_ids),
                # A capture opens Gate 1 on the tenders that cleared screening;
                # those further down the pipeline came from an earlier capture.
                Opportunity.state.in_(("GATE1", "DOCS_FETCHED", "ANALYZED", "GATE2", "DRAFTING", "GATE3", "ASSEMBLY", "GATE4", "READY_TO_SUBMIT", "GATE5")),
            )
        )
        .scalars()
        .all()
    )
    if not passing:
        return
    lines = [f"{len(passing)} new tender(s) from {source.name} cleared screening:", ""]
    for o in passing:
        deadline = o.submission_deadline.strftime("%Y-%m-%d") if o.submission_deadline else "—"
        lines.append(f"  [{o.score_total:.0f}/100] {o.title[:100]}")
        lines.append(f"          {o.buyer_name} · deadline {deadline}")
    lines.append("")
    lines.append("Open the review queue to start Gate 1 on the ones worth pursuing.")
    to = digest_service.recipients(db)
    if to:
        emailer.send_email(to, f"AHTE BMS — {len(passing)} new tender(s) cleared screening", "\n".join(lines))


def record_scan_failure(db, source, exc):
    """Record that a read of a portal did not happen.

    A portal that could not be read has to be recorded as such. Leaving it
    looking healthy — or merely unread — tells the user that another press of
    the Scan button would fix it, which is not true of a host this
    deployment cannot reach at all.
    """
    source.health = "error"
    source.last_scan_at = utcnow()
    source.last_scan_stats = {
        "error": str(exc)[:300],
        "mode": "saved-capture" if settings.fixtures else "live",
    }
    db.commit()


def run_scan(db=None):
    own = db is None
    if own:
        db = SessionLocal()
    stats = {"sources": 0, "new": 0, "updated": 0, "errors": 0, "skipped": 0}
    try:
        sources = (
            db.execute(select(Source).where(Source.enabled == True, Source.approved == True))  # noqa: E712
            .scalars()
            .all()
        )
        for source in sources:
            if source.type != "portal":
                stats["skipped"] += 1
                continue
            stats["sources"] += 1
            try:
                result = run_source(db, source)
                stats["new"] += result.get("new", 0)
                stats["updated"] += max(0, result.get("notices", 0) - result.get("new", 0))
            except Exception as exc:
                logger.exception("scan failed for %s", source.code)
                record_scan_failure(db, source, exc)
                stats["errors"] += 1
        return stats
    finally:
        if own:
            db.close()


def _notified_recently(db, ntype, prefix, hours=20) -> bool:
    since = utcnow() - timedelta(hours=hours)
    rows = (
        db.execute(
            select(NotificationEvent).where(
                NotificationEvent.type == ntype,
                NotificationEvent.created_at >= since,
                NotificationEvent.title.like(f"{prefix}%"),
            )
        )
        .scalars()
        .all()
    )
    return bool(rows)


def watchdogs(db=None):
    from app.services import workflow

    own = db is None
    if own:
        db = SessionLocal()
    result = {"overdue_gates": 0, "deadline_warnings": 0, "moved_to_evaluation": 0}
    try:
        now = utcnow()
        overdue = (
            db.execute(select(GateTask).where(GateTask.status == "PENDING", GateTask.due_at < now))
            .scalars()
            .all()
        )
        for task in overdue:
            task.status = "OVERDUE"
            db.commit()
            notifications.notify(
                db,
                "sla",
                f"SLA overdue: {task.title[:90]}",
                f"Gate {task.gate} overdue since {task.due_at} — escalate to {task.owner_role}",
                severity="warning",
                opportunity_id=task.opportunity_id,
            )
            result["overdue_gates"] += 1

        soon = now + timedelta(hours=72)
        closing = (
            db.execute(
                select(Opportunity).where(
                    Opportunity.state.in_(list(ACTIVE_STATES)),
                    Opportunity.submission_deadline != None,  # noqa: E711
                    Opportunity.submission_deadline <= soon,
                    Opportunity.submission_deadline > now,
                )
            )
            .scalars()
            .all()
        )
        for opp in closing:
            prefix = f"#{opp.id} "
            if _notified_recently(db, "deadline", prefix):
                continue
            notifications.notify(
                db,
                "deadline",
                f"{prefix}Closing soon: {opp.title[:80]}",
                f"Deadline {opp.submission_deadline} — state {opp.state}",
                severity="warning",
                opportunity_id=opp.id,
            )
            result["deadline_warnings"] += 1

        opened = (
            db.execute(
                select(Opportunity).where(
                    Opportunity.state == "SUBMITTED",
                    Opportunity.opening_at != None,  # noqa: E711
                    Opportunity.opening_at < now,
                )
            )
            .scalars()
            .all()
        )
        for opp in opened:
            workflow.transition(db, opp, "EVALUATION", "opening_passed", detail="Awaiting result — record outcome")
            notifications.notify(
                db,
                "outcome",
                f"Record outcome: {opp.title[:80]}",
                "Bids opened — capture result, competitor notes and feedback in the bid room.",
                severity="info",
                opportunity_id=opp.id,
            )
            result["moved_to_evaluation"] += 1
        return result
    finally:
        if own:
            db.close()


async def scheduler_loop(stop_event=None):
    """Scan the portals on an interval, and keep the SLA clocks honest.

    On a serverless instance the function is torn down between requests, so a
    scan at start-up would only make the first request slow — and a scan that
    outlives the function is a scan that never finishes. There the first
    cycle waits for its interval instead, and the scan is driven by the Scan
    button, which a person is waiting for.
    """
    timeout = settings.scan_interval_seconds
    if os.environ.get("VERCEL"):
        if stop_event is not None:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=timeout)
                return
            except asyncio.TimeoutError:
                pass
        else:
            await asyncio.sleep(timeout)
    while True:
        try:
            run_scan()
            watchdogs()
        except Exception:
            logger.exception("scheduler cycle failed")
        if stop_event is not None:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=timeout)
                return
            except asyncio.TimeoutError:
                continue
        await asyncio.sleep(timeout)
