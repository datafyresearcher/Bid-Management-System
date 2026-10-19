from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Lead, Source, User
from app.security import get_current_user, require_roles
from app.serializers import lead as lead_serializer
from app.services import leads as leads_service
from app.connectors import email_inbox

router = APIRouter(prefix="/api/leads", tags=["leads"])


class LeadIn(BaseModel):
    title: str
    buyer: str = ""
    description: str = ""
    category_internal: str = "General"
    area: str = ""
    expected_window: str = ""
    estimated_value: float | None = None
    currency: str = "PKR"
    confidence_tier: str = "Medium"
    confidence_note: str = ""
    source_code: str = "L9"
    source_label: str = "Manual entry"
    evidence: dict | None = None


class StatusIn(BaseModel):
    status: str


@router.get("")
def list_leads(status: str = "", q: str = "", page: int = 1, page_size: int = 50, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(Lead)
    if status:
        statuses = [s.strip().capitalize() for s in status.split(",") if s.strip()]
        if statuses:
            query = query.where(Lead.status.in_(statuses))
    if q:
        like = f"%{q}%"
        query = query.where(or_(Lead.title.ilike(like), Lead.buyer.ilike(like)))
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
    items = db.execute(query.order_by(Lead.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {"total": total, "items": [lead_serializer(item) for item in items]}


@router.post("")
def create_lead(payload: LeadIn, user: User = Depends(require_roles("bid_manager", "proposal_engineer")), db: Session = Depends(get_db)):
    lead = leads_service.create_manual(db, payload.model_dump())
    return lead_serializer(lead)


@router.post("/{lead_id}/status")
def update_status(lead_id: int, payload: StatusIn, user: User = Depends(require_roles("bid_manager", "proposal_engineer")), db: Session = Depends(get_db)):
    lead_row = db.get(Lead, lead_id)
    if not lead_row:
        raise HTTPException(status_code=404, detail="Lead not found")
    leads_service.update_status(db, lead_row, payload.status, actor=user)
    return lead_serializer(lead_row)


@router.post("/{lead_id}/convert")
def convert(lead_id: int, user: User = Depends(require_roles("bid_manager")), db: Session = Depends(get_db)):
    lead_row = db.get(Lead, lead_id)
    if not lead_row:
        raise HTTPException(status_code=404, detail="Lead not found")
    opp = leads_service.convert_to_opportunity(db, lead_row, actor=user)
    return {"opportunity_id": opp.id, "state": opp.state, "score_total": opp.score_total}


@router.post("/import/annual-plan")
def import_annual_plan(user: User = Depends(require_roles("bid_manager", "proposal_engineer")), db: Session = Depends(get_db)):
    created = leads_service.import_fixture_leads(db)
    return {"created": created}


@router.post("/import/email/{source_code}")
def import_email(source_code: str, user: User = Depends(require_roles("bid_manager", "proposal_engineer")), db: Session = Depends(get_db)):
    source = db.execute(select(Source).where(Source.code == source_code)).scalars().first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    created = email_inbox.import_leads(db, source)
    return {"created": created}
