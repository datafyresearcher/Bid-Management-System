from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.connectors.http_client import is_connection_failure
from app.db import get_db
from app.models import GateTask, NotificationEvent, Opportunity, Source, User
from app.security import get_current_user
from app.serializers import gate_task, iso, notification, opportunity_brief, source
from app.services import ai_quality
from app.services.utils import utcnow

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

ACTIVE_STATES = [
    "NORMALIZED", "SCORED", "GATE1", "DOCS_FETCHED", "ANALYZED", "GATE2",
    "DRAFTING", "GATE3", "ASSEMBLY", "GATE4", "READY_TO_SUBMIT", "GATE5", "SUBMITTED", "EVALUATION",
]

# Dead ends. These are counted on their own tile, never inside "active".
CLOSED_STATES = ["SCREENED_OUT", "AUTO_ARCHIVED"]

# Final outcomes, reported separately from active work.
OUTCOME_STATES = ["SUBMITTED", "EVALUATION"]


@router.get("")
def summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    state_rows = db.execute(select(Opportunity.state, func.count(Opportunity.id)).group_by(Opportunity.state)).all()
    state_counts = {row[0]: row[1] for row in state_rows}

    # The tile counts are computed here, once, from one definition of "active".
    # The frontend renders these numbers rather than re-deriving them, so the
    # two can never disagree.
    active_count = sum(state_counts.get(state, 0) for state in ACTIVE_STATES)
    screened_out_count = sum(state_counts.get(state, 0) for state in CLOSED_STATES)
    submitted_count = sum(state_counts.get(state, 0) for state in OUTCOME_STATES)

    gate_query = select(GateTask).where(GateTask.status.in_(["PENDING", "OVERDUE"])).order_by(GateTask.due_at)
    if user.role not in ("admin", "management"):
        gate_query = gate_query.where((GateTask.owner_role == user.role) | (GateTask.owner_user_id == user.id))
    pending_gates = db.execute(gate_query).scalars().all()

    notifications_rows = (
        db.execute(select(NotificationEvent).order_by(NotificationEvent.created_at.desc()).limit(15)).scalars().all()
    )

    soon = utcnow() + timedelta(days=7)
    closing = (
        db.execute(
            select(Opportunity)
            .where(
                Opportunity.state.in_(ACTIVE_STATES),
                Opportunity.submission_deadline != None,  # noqa: E711
                Opportunity.submission_deadline <= soon,
                Opportunity.submission_deadline > utcnow(),
            )
            .order_by(Opportunity.submission_deadline)
            .limit(10)
        )
        .scalars()
        .all()
    )

    top = (
        db.execute(
            select(Opportunity)
            .where(Opportunity.state.in_(ACTIVE_STATES), Opportunity.score_total != None)  # noqa: E711
            .order_by(Opportunity.score_total.desc())
            .limit(8)
        )
        .scalars()
        .all()
    )

    sources = db.execute(select(Source).order_by(Source.code)).scalars().all()

    # How many records each source actually contributed. This is what makes the
    # source panel auditable rather than decorative.
    record_counts = dict(
        db.execute(
            select(Opportunity.source_id, func.count(Opportunity.id))
            .where(Opportunity.source_id != None)  # noqa: E711
            .group_by(Opportunity.source_id)
        ).all()
    )
    source_rows = []
    for s in sources:
        row = source(s)
        row["records"] = record_counts.get(s.id, 0)
        source_rows.append(row)

    # What the feed is actually doing, so the banner can tell the truth about
    # it rather than only announcing which mode is switched on. A system set
    # to read live portals has not read anything until a portal has answered.
    portals = [s for s in sources if s.type == "portal"]
    failed = [s for s in portals if s.health == "error"]
    # A portal that was read from the live site is one that answered. A portal
    # whose last read failed was not read, whatever mode the attempt was in.
    read_live = [
        s for s in portals
        if (s.last_scan_stats or {}).get("mode") == "live" and s.health != "error"
    ]
    never_read = [s for s in portals if not s.last_scan_at]
    last_scan = max((s.last_scan_at for s in portals if s.last_scan_at), default=None)
    # A portal this host cannot reach at all is not the same thing as one that
    # answered and failed. The first will not be fixed by pressing Scan again;
    # saying so is the difference between an honest banner and a false promise.
    unreachable = [
        s for s in failed
        if is_connection_failure((s.last_scan_stats or {}).get("error", ""))
    ]

    # Records carry the mode of the read that captured them, so what is on
    # screen can be counted by where it came from.
    ref_rows = db.execute(select(Opportunity.source_refs)).scalars().all()
    live_records = sum(
        1 for refs in ref_rows if refs and any(isinstance(r, dict) and r.get("mode") == "live" for r in refs)
    )
    total_records = db.execute(select(func.count(Opportunity.id))).scalar_one()

    feed_status = {
        "mode": "saved-capture" if settings.fixtures else "live",
        "portals_total": len(portals),
        "portals_read_live": len(read_live),
        "portals_failed": len(failed),
        "portals_never_read": len(never_read),
        "portals_unreachable": len(unreachable),
        "failed_names": [s.name for s in failed],
        "unreachable_names": [s.name for s in unreachable],
        "last_scan_at": iso(last_scan),
        "records_total": total_records,
        "records_live": live_records,
        "records_other": total_records - live_records,
        # A feed that has not spoken to a portal in over a day is not "live"
        # in any sense a reader should act on.
        "stale": last_scan is None or (utcnow() - last_scan) > timedelta(hours=24),
    }

    return {
        "state_counts": state_counts,
        "active_count": active_count,
        "screened_out_count": screened_out_count,
        "submitted_count": submitted_count,
        "pending_gates": [gate_task(g, include_opportunity=True) for g in pending_gates[:20]],
        "pending_gates_total": len(pending_gates),
        "notifications": [notification(n) for n in notifications_rows],
        "closing_soon": [opportunity_brief(o) for o in closing],
        "top_opportunities": [opportunity_brief(o) for o in top],
        "sources": source_rows,
        # Whether the connectors are pulling from the live portals or from
        # saved captures of them. Surfaced so nobody mistakes a capture for a
        # live pull.
        "feed_mode": "saved-capture" if settings.fixtures else "live",
        "feed_status": feed_status,
        "ai_quality": ai_quality.summary(db),
    }


@router.post("/notifications/read")
def mark_notifications_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    unread = db.execute(select(NotificationEvent).where(NotificationEvent.read == False)).scalars().all()  # noqa: E712
    for n in unread:
        n.read = True
    db.commit()
    return {"marked": len(unread)}
