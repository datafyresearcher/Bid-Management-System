from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
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
from app.services import audit, shared_documents
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
    email: str = ""
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
    # A shared document is carried by every proposal; a locked one is the
    # master copy and can only be changed from here.
    shared: bool = True
    locked: bool = False
    category: str = "General"
    valid_until: str = ""


class SharedIn(BaseModel):
    title: str
    category: str = "General"
    type: str = "evidence"
    tags: str = ""
    content_text: str = ""
    shared: bool = True
    locked: bool = False
    approved: bool = True
    valid_until: str = ""


def _approved(db, model, row_id, approved):
    row = db.get(model, row_id)
    if not row:
        raise HTTPException(status_code=404, detail="Record not found")
    row.approved = approved
    db.commit()
    return {"id": row_id, "approved": approved}


def _get_row(db, model, row_id):
    """One knowledge-base record, or the 404 the reader deserves."""
    row = db.get(model, row_id)
    if not row:
        raise HTTPException(status_code=404, detail="Record not found")
    return row


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
        "email": company.email,
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


@router.put("/licenses/{row_id}")
def update_license(row_id: int, payload: LicenseIn, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    """Correct a licence. Only the fields the form manages are written —
    the issue and expiry dates a record may already carry are left alone,
    and so is its approval."""
    row = _get_row(db, License, row_id)
    row.number = payload.number
    row.category = payload.category
    row.fields = payload.fields
    db.commit()
    audit.record(db, "kb.license_updated", actor=user.name, detail={"id": row_id, "number": payload.number})
    return {"id": row_id}


@router.delete("/licenses/{row_id}")
def delete_license(row_id: int, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    row = _get_row(db, License, row_id)
    detail, row_id_done = {"number": row.number}, row.id
    db.delete(row)
    db.commit()
    audit.record(db, "kb.license_deleted", actor=user.name, detail={"id": row_id_done, **detail})
    return {"deleted": row_id_done}


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


@router.put("/financial-years/{row_id}")
def update_fy(row_id: int, payload: FYIn, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    """Correct a financial year. Bonding capacity, where a record carries
    one, is not part of the form and is left untouched."""
    row = _get_row(db, FinancialYear, row_id)
    row.fiscal_year = payload.fiscal_year
    row.turnover = payload.turnover
    row.net_worth = payload.net_worth
    row.profit = payload.profit
    row.auditor = payload.auditor
    db.commit()
    audit.record(db, "kb.fy_updated", actor=user.name, detail={"id": row_id, "fiscal_year": payload.fiscal_year})
    return {"id": row_id}


@router.delete("/financial-years/{row_id}")
def delete_fy(row_id: int, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    row = _get_row(db, FinancialYear, row_id)
    detail, row_id_done = {"fiscal_year": row.fiscal_year}, row.id
    db.delete(row)
    db.commit()
    audit.record(db, "kb.fy_deleted", actor=user.name, detail={"id": row_id_done, **detail})
    return {"deleted": row_id_done}


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


@router.put("/projects/{row_id}")
def update_project(row_id: int, payload: ProjectIn, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    """Correct a project record. The role it was performed in and its
    funding source are not part of the form and are left untouched."""
    row = _get_row(db, ProjectExperience, row_id)
    row.contract_no = payload.contract_no
    row.client = payload.client
    row.category = payload.category
    row.value = payload.value
    row.area = payload.area
    row.start_date = payload.start_date
    row.end_date = payload.end_date
    db.commit()
    audit.record(db, "kb.project_updated", actor=user.name, detail={"id": row_id, "contract_no": payload.contract_no})
    return {"id": row_id}


@router.delete("/projects/{row_id}")
def delete_project(row_id: int, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    row = _get_row(db, ProjectExperience, row_id)
    detail, row_id_done = {"contract_no": row.contract_no}, row.id
    db.delete(row)
    db.commit()
    audit.record(db, "kb.project_deleted", actor=user.name, detail={"id": row_id_done, **detail})
    return {"deleted": row_id_done}


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


@router.put("/personnel/{row_id}")
def update_personnel(row_id: int, payload: PersonnelIn, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    """Correct a person's record. Everything the form holds is written;
    certifications and key projects a record may carry are left alone."""
    row = _get_row(db, Personnel, row_id)
    row.name = payload.name
    row.position = payload.position
    row.pec_reg_no = payload.pec_reg_no
    row.years_experience = payload.years_experience
    row.availability = payload.availability
    db.commit()
    audit.record(db, "kb.personnel_updated", actor=user.name, detail={"id": row_id, "name": payload.name})
    return {"id": row_id}


@router.delete("/personnel/{row_id}")
def delete_personnel(row_id: int, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    row = _get_row(db, Personnel, row_id)
    detail, row_id_done = {"name": row.name}, row.id
    db.delete(row)
    db.commit()
    audit.record(db, "kb.personnel_deleted", actor=user.name, detail={"id": row_id_done, **detail})
    return {"deleted": row_id_done}


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


@router.put("/equipment/{row_id}")
def update_equipment(row_id: int, payload: EquipmentIn, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    """Correct a piece of equipment. Everything the form holds is written;
    a spec, year or location a record may carry is left alone."""
    row = _get_row(db, EquipmentItem, row_id)
    row.name = payload.name
    row.category = payload.category
    row.quantity = payload.quantity
    row.ownership = payload.ownership
    row.condition = payload.condition
    db.commit()
    audit.record(db, "kb.equipment_updated", actor=user.name, detail={"id": row_id, "name": payload.name})
    return {"id": row_id}


@router.delete("/equipment/{row_id}")
def delete_equipment(row_id: int, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    row = _get_row(db, EquipmentItem, row_id)
    detail, row_id_done = {"name": row.name}, row.id
    db.delete(row)
    db.commit()
    audit.record(db, "kb.equipment_deleted", actor=user.name, detail={"id": row_id_done, **detail})
    return {"deleted": row_id_done}


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


@router.put("/certificates/{row_id}")
def update_certificate(row_id: int, payload: CertificateIn, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    """Correct a certificate. Only the fields the form manages are written;
    a valid-from date a record may already carry is left alone."""
    row = _get_row(db, CompanyCertificate, row_id)
    row.name = payload.name
    row.issuer = payload.issuer
    row.number = payload.number
    row.expires_at = parse_date(payload.expires_at)
    db.commit()
    audit.record(db, "kb.certificate_updated", actor=user.name, detail={"id": row_id, "name": payload.name})
    return {"id": row_id}


@router.delete("/certificates/{row_id}")
def delete_certificate(row_id: int, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    row = _get_row(db, CompanyCertificate, row_id)
    detail, row_id_done = {"name": row.name}, row.id
    db.delete(row)
    db.commit()
    audit.record(db, "kb.certificate_deleted", actor=user.name, detail={"id": row_id_done, **detail})
    return {"deleted": row_id_done}


@router.get("/library")
def list_library(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(LibraryDocument)).scalars().all()
    # The text comes with the rows so a record can be corrected without
    # losing the words it already holds.
    return [{**shared_documents.document(r), "content_text": r.content_text or ""} for r in rows]


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


@router.put("/library/{row_id}")
def update_library(row_id: int, payload: LibraryIn, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    """Correct a reference document. Only the fields the library tab
    manages are written — a document that is also a shared document keeps
    its shared, locked, category and valid-until settings, which belong to
    the shared-documents tab."""
    row = _get_row(db, LibraryDocument, row_id)
    row.title = payload.title
    row.type = payload.type
    row.tags = payload.tags
    row.content_text = payload.content_text
    db.commit()
    audit.record(db, "kb.library_updated", actor=user.name, detail={"id": row_id, "title": payload.title})
    return {"id": row_id}


@router.delete("/library/{row_id}")
def delete_library(row_id: int, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    """Remove a document from the knowledge base. This is the knowledge
    base itself — the one place a locked shared document may be deleted."""
    row = _get_row(db, LibraryDocument, row_id)
    detail, row_id_done = {"title": row.title}, row.id
    db.delete(row)
    db.commit()
    audit.record(db, "kb.library_deleted", actor=user.name, detail={"id": row_id_done, **detail})
    return {"deleted": row_id_done}


# ----------------------------------------------------------------------
# Shared documents — the evidence every proposal carries
# ----------------------------------------------------------------------


@router.get("/shared")
def list_shared(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The shared documents, and the families they belong to."""
    return {
        "documents": shared_documents.list_documents(db, shared_only=True),
        "categories": shared_documents.CATEGORIES,
    }


@router.post("/shared")
def add_shared(payload: SharedIn, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    row = LibraryDocument(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    audit.record(db, "kb.shared_added", actor=user.name, detail={"title": payload.title, "category": payload.category})
    return shared_documents.document(row)


@router.put("/shared/{row_id}")
def update_shared(row_id: int, payload: SharedIn, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    row = db.get(LibraryDocument, row_id)
    if not row:
        raise HTTPException(status_code=404, detail="Shared document not found")
    for field, value in payload.model_dump().items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    audit.record(db, "kb.shared_updated", actor=user.name, detail={"id": row_id, "title": row.title})
    return shared_documents.document(row)


@router.post("/shared/{row_id}/file")
def upload_shared_file(
    row_id: int,
    file: UploadFile = File(...),
    user: User = Depends(WRITE_ROLES),
    db: Session = Depends(get_db),
):
    """Attach the file itself to a shared document."""
    row = db.get(LibraryDocument, row_id)
    if not row:
        raise HTTPException(status_code=404, detail="Shared document not found")
    content = file.file.read()
    if len(content) > shared_documents.MAX_UPLOAD:
        raise HTTPException(status_code=400, detail="File exceeds 30MB limit")
    shared_documents.save_file(db, row, file.filename or "document.bin", content)
    audit.record(
        db,
        "kb.shared_file_uploaded",
        actor=user.name,
        detail={"id": row_id, "title": row.title, "size": len(content)},
    )
    return shared_documents.document(row)


@router.get("/shared/{row_id}/download")
def download_shared(row_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Hand back the file a shared document was stored as."""
    row = db.get(LibraryDocument, row_id)
    if not row:
        raise HTTPException(status_code=404, detail="Shared document not found")
    if not row.file_path:
        raise HTTPException(status_code=404, detail="No file has been attached to this document")
    path = Path(row.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="The stored file is no longer on disk")
    return FileResponse(
        path,
        filename=path.name.split("_", 1)[-1] or path.name,
        media_type="application/octet-stream",
    )


@router.delete("/shared/{row_id}")
def delete_shared(row_id: int, user: User = Depends(WRITE_ROLES), db: Session = Depends(get_db)):
    """Remove a shared document from the knowledge base.

    A locked document can only be removed from here — that is the whole
    point of locking it.
    """
    row = db.get(LibraryDocument, row_id)
    if not row:
        raise HTTPException(status_code=404, detail="Shared document not found")
    title = row.title
    db.delete(row)
    db.commit()
    audit.record(db, "kb.shared_deleted", actor=user.name, detail={"id": row_id, "title": title})
    return {"id": row_id, "deleted": True}
