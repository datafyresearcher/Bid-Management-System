import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import GateTask, NotificationEvent, Opportunity, Source
from app.services import notifications

logger = logging.getLogger("bms.jobs")

ACTIVE_STATES = {
    "NEW", "NORMALIZED", "SCORED", "GATE1", "DOCS_FETCHED", "ANALYZED", "GATE2",
    "DRAFTING", "GATE3", "ASSEMBLY", "GATE4", "READY_TO_SUBMIT", "GATE5",
}


def run_source(db, source) -> dict:
    from app.connectors.registry import get_connector
    from app.services import normalizer

    connector = get_connector(source)
    if not connector:
        source.health = "no_adapter"
        db.commit()
        return {"error": "no_adapter"}

    notices = connector.fetch_listing() or []
    raw = getattr(connector, "last_raw", None)
    if raw:
        normalizer.store_snapshot(db, source, None, source.url, raw, kind="listing", meta={"adapter": source.adapter})

    before_ids = set(db.execute(select(Opportunity.id)).scalars().all())
    for notice in notices:
        normalizer.normalize_notice(db, source, notice)
    after_ids = set(db.execute(select(Opportunity.id)).scalars().all())
    created = len(after_ids - before_ids)

    source.health = "ok"
    source.last_scan_at = datetime.utcnow()
    source.last_scan_stats = {"notices": len(notices), "new": created, "updated": max(0, len(notices) - created)}
    db.commit()

    if created:
        notifications.notify(
            db,
            "scan",
            f"{created} new tender(s) from {source.name}",
            f"Source {source.code} scanned: {len(notices)} notices processed.",
            severity="info",
        )
    return {"notices": len(notices), "new": created}


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
                source.health = "error"
                source.last_scan_at = datetime.utcnow()
                source.last_scan_stats = {"error": str(exc)[:300]}
                db.commit()
                stats["errors"] += 1
        return stats
    finally:
        if own:
            db.close()


def _notified_recently(db, ntype, prefix, hours=20) -> bool:
    since = datetime.utcnow() - timedelta(hours=hours)
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
        now = datetime.utcnow()
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
    while True:
        try:
            run_scan()
            watchdogs()
        except Exception:
            logger.exception("scheduler cycle failed")
        timeout = settings.scan_interval_seconds
        if stop_event is not None:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=timeout)
                return
            except asyncio.TimeoutError:
                continue
        await asyncio.sleep(timeout)
