from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import GateTask, NotificationEvent, Opportunity, Source, User
from app.security import get_current_user
from app.serializers import gate_task, notification, opportunity_brief, source
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
        "sources": [source(s) for s in sources],
        "ai_quality": ai_quality.summary(db),
    }


@router.post("/notifications/read")
def mark_notifications_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    unread = db.execute(select(NotificationEvent).where(NotificationEvent.read == False)).scalars().all()  # noqa: E712
    for n in unread:
        n.read = True
    db.commit()
    return {"marked": len(unread)}
