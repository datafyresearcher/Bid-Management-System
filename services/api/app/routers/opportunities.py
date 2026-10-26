from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Opportunity, User
from app.security import get_current_user, require_roles
from app.serializers import opportunity_brief, opportunity_detail, outcome as outcome_serializer
from app.services import audit, documents, scorer, submission, workflow
from app.services.utils import detect_currency, parse_date, source_id_for_code, utcnow, value_band

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])

MAX_UPLOAD = 30 * 1024 * 1024


class OverrideIn(BaseModel):
    comment: str


class AbandonIn(BaseModel):
    reason_code: str = "manual"
    comment: str = ""


class OutcomeIn(BaseModel):
    result: str
    reason_code: str = ""
    comment: str = ""
    competitor_note: str = ""
    award_value: float | None = None


class ManualIn(BaseModel):
    title: str
    buyer_name: str = ""
    buyer_ref: str = ""
    description: str = ""
    category_internal: str = "General"
    area: str = ""
    city: str = ""
    estimated_value: float | None = None
    currency: str = ""
    published_at: str = ""
    clarification_deadline: str = ""
    submission_deadline: str = ""
    opening_at: str = ""
    source_label: str = "Manual entry"


@router.get("")
def list_opportunities(
    state: str = "",
    q: str = "",
    category: str = "",
    area: str = "",
    min_score: float | None = None,
    sort: str = "created",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = select(Opportunity)
    if state:
        states = [s.strip().upper() for s in state.split(",") if s.strip()]
        if states:
            query = query.where(Opportunity.state.in_(states))
    if q:
        like = f"%{q}%"
        query = query.where(or_(Opportunity.title.ilike(like), Opportunity.buyer_name.ilike(like), Opportunity.buyer_ref.ilike(like)))
    if category:
        query = query.where(Opportunity.category_internal == category)
    if area:
        query = query.where(Opportunity.area == area)
    if min_score is not None:
        query = query.where(Opportunity.score_total >= min_score)

    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
    if sort == "deadline":
        query = query.order_by(Opportunity.submission_deadline.is_(None), Opportunity.submission_deadline)
    elif sort == "score":
        query = query.order_by(Opportunity.score_total.desc())
    else:
        query = query.order_by(Opportunity.created_at.desc())
    items = db.execute(query.offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {"total": total, "page": page, "page_size": page_size, "items": [opportunity_brief(o) for o in items]}


@router.get("/{opp_id}")
def get_opportunity(opp_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    opp = db.get(Opportunity, opp_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return opportunity_detail(opp)


@router.post("/manual")
def create_manual(payload: ManualIn, user: User = Depends(require_roles("bid_manager", "proposal_engineer")), db: Session = Depends(get_db)):
    currency = payload.currency or detect_currency(f"{payload.title} {payload.description}")
    opp = Opportunity(
        dedup_key=f"manual-{utcnow().isoformat()}",
        country="PK",
        area=payload.area,
        city=payload.city,
        category_internal=payload.category_internal or "General",
        buyer_name=payload.buyer_name,
        buyer_ref=payload.buyer_ref,
        title=payload.title,
        description=payload.description,
        estimated_value=payload.estimated_value,
        currency=currency,
        value_band=value_band(payload.estimated_value, currency),
        published_at=parse_date(payload.published_at),
        clarification_deadline=parse_date(payload.clarification_deadline),
        submission_deadline=parse_date(payload.submission_deadline),
        opening_at=parse_date(payload.opening_at),
        source_kind="manual",
        state="NORMALIZED",
        source_refs=[{"source_code": "manual", "native_id": f"manual-{utcnow().isoformat()}", "url": ""}],
        source_id=source_id_for_code(db, "manual"),
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)
    audit.record(db, "opportunity.manual_created", actor=user.name, opportunity_id=opp.id, detail={"title": opp.title[:150]})
    return opportunity_detail(opp)


@router.post("/{opp_id}/score")
def score_opportunity(opp_id: int, user: User = Depends(require_roles("bid_manager")), db: Session = Depends(get_db)):
    opp = db.get(Opportunity, opp_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    score = scorer.run(db, opp)
    return {"score_total": score.total, "subscores": score.subscores, "hard_gate_result": score.hard_gates, "rationale": score.rationale, "state": opp.state}


@router.post("/score-pending")
def score_pending(user: User = Depends(require_roles("bid_manager")), db: Session = Depends(get_db)):
    """Score every captured tender that is still waiting for a score.

    A scan files the tenders it found but leaves the decision on each one to
    the bid manager. This takes all of them at once, so the review queue fills
    instead of staying empty until every tender has been scored by hand.

    The batch runs inside a budget, so this returns as soon as it has to.
    Whatever it did not reach is still waiting and is picked up by the next
    pass; the count it returns says how many were scored this time.
    """
    from app.services import jobs

    pending = (
        db.execute(select(Opportunity.id).where(Opportunity.state == "NORMALIZED"))
        .scalars()
        .all()
    )
    scored = jobs.score_new(
        db,
        list(pending),
        budget_seconds=settings.score_pending_budget_seconds,
    )
    audit.record(
        db,
        "opportunity.score_pending",
        actor=user.name,
        detail={"pending": len(pending), "scored": scored},
    )
    return {"pending": len(pending), "scored": scored}



@router.post("/{opp_id}/override")
def override_screening(opp_id: int, payload: OverrideIn, user: User = Depends(require_roles("bid_manager", "management")), db: Session = Depends(get_db)):
    opp = db.get(Opportunity, opp_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    if opp.state not in ("SCREENED_OUT", "AUTO_ARCHIVED"):
        raise HTTPException(status_code=400, detail="Override only applies to screened out or archived opportunities")
    scorer.override_screening(db, opp, actor=user.name, comment=payload.comment)
    return opportunity_brief(opp)


@router.post("/{opp_id}/abandon")
def abandon(opp_id: int, payload: AbandonIn, user: User = Depends(require_roles("bid_manager", "management")), db: Session = Depends(get_db)):
    opp = db.get(Opportunity, opp_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    workflow.abandon(db, opp, payload.reason_code, payload.comment, actor=user)
    return opportunity_brief(opp)


@router.post("/{opp_id}/outcome")
def record_outcome(opp_id: int, payload: OutcomeIn, user: User = Depends(require_roles("bid_manager", "management")), db: Session = Depends(get_db)):
    opp = db.get(Opportunity, opp_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    result = payload.result.upper()
    if result not in ("WON", "LOST", "REJECTED"):
        raise HTTPException(status_code=400, detail="Result must be WON, LOST or REJECTED")
    # An outcome can only exist for a bid that was actually submitted.
    # Without this guard a bid could be marked WON straight from screening,
    # which would silently poison the win-rate-by-score-band feedback loop.
    if opp.state not in ("SUBMITTED", "EVALUATION", "WON", "LOST", "REJECTED"):
        raise HTTPException(
            status_code=409,
            detail=f"Bid is in state {opp.state} — an outcome can only be recorded after submission (SUBMITTED or EVALUATION).",
        )
    outcome_row = submission.record_outcome(
        db,
        opp,
        result,
        reason_code=payload.reason_code,
        comment=payload.comment,
        competitor_note=payload.competitor_note,
        award_value=payload.award_value,
        actor=user,
    )
    return outcome_serializer(outcome_row)


@router.post("/{opp_id}/documents")
def upload_document(opp_id: int, file: UploadFile = File(...), user: User = Depends(require_roles("bid_manager", "proposal_engineer")), db: Session = Depends(get_db)):
    opp = db.get(Opportunity, opp_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    content = file.file.read()
    if len(content) > MAX_UPLOAD:
        raise HTTPException(status_code=400, detail="File exceeds 30MB limit")
    doc = documents.save_document(db, opp, file.filename or "upload.bin", content)
    return {"id": doc.id, "filename": doc.filename, "doc_type": doc.doc_type, "parsed": doc.parsed, "size": doc.size}


@router.post("/{opp_id}/analyze")
def analyze(opp_id: int, user: User = Depends(require_roles("bid_manager", "proposal_engineer")), db: Session = Depends(get_db)):
    opp = db.get(Opportunity, opp_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    result = workflow.reanalyze(db, opp)
    return result
