from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Opportunity, Proposal, ProposalSection, SubmissionRecord, User
from app.security import get_current_user, require_roles
from app.serializers import proposal as proposal_serializer, submission as submission_serializer
from app.services import drafter, submission

router = APIRouter(prefix="/api/proposals", tags=["proposals"])


class SectionIn(BaseModel):
    content: str
    status: str | None = None


class ChecklistIn(BaseModel):
    index: int
    status: str


def _get_proposal(db, opp_id: int) -> Proposal:
    proposal = db.execute(select(Proposal).where(Proposal.opportunity_id == opp_id)).scalars().first()
    if not proposal:
        raise HTTPException(status_code=404, detail="No proposal drafted yet")
    return proposal


@router.get("/{opp_id}")
def get_proposal(opp_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return proposal_serializer(_get_proposal(db, opp_id))


@router.post("/{opp_id}/generate")
def generate(opp_id: int, user: User = Depends(require_roles("bid_manager", "proposal_engineer")), db: Session = Depends(get_db)):
    opp = db.get(Opportunity, opp_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    result = drafter.generate(db, opp)
    return result


@router.put("/sections/{section_id}")
def update_section(section_id: int, payload: SectionIn, user: User = Depends(require_roles("bid_manager", "proposal_engineer")), db: Session = Depends(get_db)):
    section = db.get(ProposalSection, section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    section.content = payload.content
    if payload.status:
        section.status = payload.status
    elif "GAP" in payload.content:
        section.status = "GAPS"
    else:
        section.status = "EDITED"
    db.commit()
    return {"id": section.id, "status": section.status}


@router.post("/{opp_id}/export")
def export_pack(opp_id: int, user: User = Depends(require_roles("bid_manager", "proposal_engineer")), db: Session = Depends(get_db)):
    opp = db.get(Opportunity, opp_id)
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return submission.build_pack(db, opp)


@router.get("/{opp_id}/submission")
def get_submission(opp_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    record = db.execute(select(SubmissionRecord).where(SubmissionRecord.opportunity_id == opp_id)).scalars().first()
    return submission_serializer(record) or {}


@router.put("/{opp_id}/submission/checklist")
def update_checklist(opp_id: int, payload: ChecklistIn, user: User = Depends(require_roles("bid_manager", "proposal_engineer")), db: Session = Depends(get_db)):
    record = db.execute(select(SubmissionRecord).where(SubmissionRecord.opportunity_id == opp_id)).scalars().first()
    if not record or not record.checklist:
        raise HTTPException(status_code=404, detail="Checklist not built yet")
    if payload.index < 0 or payload.index >= len(record.checklist):
        raise HTTPException(status_code=400, detail="Invalid checklist index")
    entries = [dict(item) for item in record.checklist]
    entries[payload.index]["status"] = payload.status
    record.checklist = entries
    db.commit()
    return submission_serializer(record)
