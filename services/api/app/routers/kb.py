from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    CompanyCertificate,
    CompanyProfile,
    EquipmentItem,
    FinancialYear,
    License,
    LibraryDocument,
    Personnel,
    ProjectExperience,
    User,
)
from app.security import get_current_user, require_roles
from app.services import audit
from app.services.utils import parse_date

router = APIRouter(prefix="/api/kb", tags=["knowledge-base"])

WRITE_ROLES = require_roles("bid_manager")


class ApproveIn(BaseModel):
    approved: bool = True


class CompanyIn(BaseModel):
    name: str
    legal_name: str = ""
    secp: str = ""
    ntn: str = ""
    tax_status: str = "Active"
    address: str = ""
    website: str = ""
    summary: str = ""
    blacklisted: bool = False


class LicenseIn(BaseModel):
    number: str = ""
    category: str = "C-A"
    fields: list[str] = []
    issued_at: str = ""
    expires_at: str = ""


class FYIn(BaseModel):
    fiscal_year: str
    turnover: float = 0
    net_worth: float = 0
    profit: float = 0
    currency: str = "PKR"
    auditor: str = ""
    bonding_capacity: float | None = None
    approved: bool = True


class ProjectIn(BaseModel):
    contract_no: str = ""
    client: str = ""
    scope: str = ""
    category: str = ""
    value: float | None = None
    currency: str = "PKR"
    area: str = ""
    start_date: str = ""
    end_date: str = ""
    role: str = "Sole"
    funding_source: str = ""
    certificate_ref: str = ""
    keywords: str = ""
    approved: bool = True


class PersonnelIn(BaseModel):
    name: str
    position: str = ""
    pec_reg_no: str = ""
    years_experience: int = 0
    education: str = ""
    key_projects: str = ""
    certifications: list[str] = []
    availability: str = "Available"
    approved: bool = True


class EquipmentIn(BaseModel):
    name: str
    category: str = ""
    spec: str = ""
    quantity: int = 1
    ownership: str = "Owned"
    year: int | None = None
    condition: str = "Good"
    location: str = ""
    approved: bool = True


class CertificateIn(BaseModel):
    name: str
    issuer: str = ""
    number: str = ""
    valid_from: str = ""
    expires_at: str = ""
    approved: bool = True


class LibraryIn(BaseModel):
    title: str
    type: str = "policy"
    tags: str = ""
    content_text: str = ""
    approved: bool = True


def _approved(db, model, row_id, approved):
    row = db.get(model, row_id)
    if not row:
        raise HTTPException(status_code=404, detail="Record not found")
    row.approved = approved
    db.commit()
    return {"id": row_id, "approved": approved}


@router.get("/summary")
def kb_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    def counts(model):
        total = db.execute(select(func.count(model.id))).scalar() or 0
        approved = db.execute(select(func.count(model.id)).where(model.approved == True)).scalar() or 0  # noqa: E712
        return {"total": total, "approved": approved}

    return {
        "company": bool(db.execute(select(CompanyProfile)).scalars().first()),
        "licenses": counts(License),
        "financial_years": counts(FinancialYear),
        "projects": counts(ProjectExperience),
        "personnel": counts(Personnel),
        "equipment": counts(EquipmentItem),
        "certificates": counts(CompanyCertificate),
        "library": counts(LibraryDocument),
    }


@router.get("/gaps")
def kb_gaps(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Which company evidence is missing or not yet approved."""
    from app.services import submission

    gaps, present = submission.kb_gaps_summary(db)
    return {"gaps": gaps, "present": present, "complete": not gaps}


@router.get("/company")
def get_company(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    company = db.execute(select(CompanyProfile)).scalars().first()
    if not company:
        return {}
    return {
        "id": company.id,
        "name": company.name,
        "legal_name": company.legal_name,
        "secp": company.secp,
        "ntn": company.ntn,
        "tax_status": company.tax_status,
        "address": company.address,
        "website": company.website,
        "summary": company.summary,
        "blacklisted": company.blacklisted,
    }


@router.put("/company")
def upsert_company(payload: CompanyIn, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    company = db.execute(select(CompanyProfile)).scalars().first()
    if not company:
        company = CompanyProfile(name=payload.name)
        db.add(company)
    for field, value in payload.model_dump().items():
        setattr(company, field, value)
    db.commit()
    audit.record(db, "kb.company_updated", actor=user.name)
    return {"id": company.id}


@router.get("/licenses")
def list_licenses(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(License)).scalars().all()
    return [{"id": r.id, "number": r.number, "category": r.category, "fields": r.fields or [], "approved": r.approved} for r in rows]


@router.post("/licenses")
def add_license(payload: LicenseIn, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    row = License(
        number=payload.number,
        category=payload.category,
        fields=payload.fields,
        issued_at=parse_date(payload.issued_at),
        expires_at=parse_date(payload.expires_at),
        approved=True,
    )
    db.add(row)
    db.commit()
    audit.record(db, "kb.license_added", actor=user.name, detail={"number": payload.number, "category": payload.category})
    return {"id": row.id}


@router.post("/licenses/{row_id}/approve")
def approve_license(row_id: int, payload: ApproveIn, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    return _approved(db, License, row_id, payload.approved)


@router.get("/financial-years")
def list_fys(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(FinancialYear)).scalars().all()
    return [
        {
            "id": r.id,
            "fiscal_year": r.fiscal_year,
            "turnover": r.turnover,
            "net_worth": r.net_worth,
            "profit": r.profit,
            "auditor": r.auditor,
            "bonding_capacity": r.bonding_capacity,
            "approved": r.approved,
        }
        for r in rows
    ]


@router.post("/financial-years")
def add_fy(payload: FYIn, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    row = FinancialYear(**payload.model_dump())
    db.add(row)
    db.commit()
    audit.record(db, "kb.fy_added", actor=user.name, detail={"fiscal_year": payload.fiscal_year})
    return {"id": row.id}


@router.post("/financial-years/{row_id}/approve")
def approve_fy(row_id: int, payload: ApproveIn, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    return _approved(db, FinancialYear, row_id, payload.approved)


@router.get("/projects")
def list_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(ProjectExperience)).scalars().all()
    return [
        {
            "id": r.id,
            "contract_no": r.contract_no,
            "client": r.client,
            "scope": r.scope,
            "category": r.category,
            "value": r.value,
            "area": r.area,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "role": r.role,
            "approved": r.approved,
        }
        for r in rows
    ]


@router.post("/projects")
def add_project(payload: ProjectIn, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    row = ProjectExperience(**payload.model_dump())
    db.add(row)
    db.commit()
    audit.record(db, "kb.project_added", actor=user.name, detail={"contract_no": payload.contract_no})
    return {"id": row.id}


@router.post("/projects/{row_id}/approve")
def approve_project(row_id: int, payload: ApproveIn, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    return _approved(db, ProjectExperience, row_id, payload.approved)


@router.get("/personnel")
def list_personnel(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Personnel)).scalars().all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "position": r.position,
            "pec_reg_no": r.pec_reg_no,
            "years_experience": r.years_experience,
            "availability": r.availability,
            "approved": r.approved,
        }
        for r in rows
    ]


@router.post("/personnel")
def add_personnel(payload: PersonnelIn, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    row = Personnel(**payload.model_dump())
    db.add(row)
    db.commit()
    audit.record(db, "kb.personnel_added", actor=user.name, detail={"name": payload.name})
    return {"id": row.id}


@router.post("/personnel/{row_id}/approve")
def approve_personnel(row_id: int, payload: ApproveIn, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    return _approved(db, Personnel, row_id, payload.approved)


@router.get("/equipment")
def list_equipment(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(EquipmentItem)).scalars().all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "category": r.category,
            "spec": r.spec,
            "quantity": r.quantity,
            "ownership": r.ownership,
            "condition": r.condition,
            "approved": r.approved,
        }
        for r in rows
    ]


@router.post("/equipment")
def add_equipment(payload: EquipmentIn, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    row = EquipmentItem(**payload.model_dump())
    db.add(row)
    db.commit()
    audit.record(db, "kb.equipment_added", actor=user.name, detail={"name": payload.name})
    return {"id": row.id}


@router.post("/equipment/{row_id}/approve")
def approve_equipment(row_id: int, payload: ApproveIn, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    return _approved(db, EquipmentItem, row_id, payload.approved)


@router.get("/certificates")
def list_certificates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(CompanyCertificate)).scalars().all()
    return [
        {"id": r.id, "name": r.name, "issuer": r.issuer, "number": r.number, "expires_at": r.expires_at, "approved": r.approved}
        for r in rows
    ]


@router.post("/certificates")
def add_certificate(payload: CertificateIn, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    row = CompanyCertificate(
        name=payload.name,
        issuer=payload.issuer,
        number=payload.number,
        valid_from=payload.valid_from,
        expires_at=parse_date(payload.expires_at),
        approved=payload.approved,
    )
    db.add(row)
    db.commit()
    audit.record(db, "kb.certificate_added", actor=user.name, detail={"name": payload.name})
    return {"id": row.id}


@router.post("/certificates/{row_id}/approve")
def approve_certificate(row_id: int, payload: ApproveIn, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    return _approved(db, CompanyCertificate, row_id, payload.approved)


@router.get("/library")
def list_library(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(LibraryDocument)).scalars().all()
    return [
        {"id": r.id, "title": r.title, "type": r.type, "tags": r.tags, "approved": r.approved}
        for r in rows
    ]


@router.post("/library")
def add_library(payload: LibraryIn, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    row = LibraryDocument(**payload.model_dump())
    db.add(row)
    db.commit()
    audit.record(db, "kb.library_added", actor=user.name, detail={"title": payload.title})
    return {"id": row.id}


@router.post("/library/{row_id}/approve")
def approve_library(row_id: int, payload: ApproveIn, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    return _approved(db, LibraryDocument, row_id, payload.approved)
