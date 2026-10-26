import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import CategoryMapping, DecisionAudit, User
from app.security import require_roles
from app.serializers import iso
from app.security import hash_password
from app.services import ai_quality, audit, emailer

router = APIRouter(prefix="/api/admin", tags=["admin"])

ADMIN = require_roles("admin")


class UserIn(BaseModel):
    email: str
    name: str
    role: str = "viewer"
    password: str


class UserUpdateIn(BaseModel):
    name: str | None = None
    role: str | None = None
    active: bool | None = None
    password: str | None = None


class MappingIn(BaseModel):
    source_code: str
    source_category: str
    internal_category: str


@router.get("/users")
def list_users(user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    rows = db.execute(select(User).order_by(User.id)).scalars().all()
    return [{"id": u.id, "email": u.email, "name": u.name, "role": u.role, "active": u.active} for u in rows]


@router.post("/users")
def create_user(payload: UserIn, user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    email = payload.email.lower().strip()
    exists = db.execute(select(User).where(User.email == email)).scalars().first()
    if exists:
        raise HTTPException(status_code=400, detail="Email already registered")
    row = User(email=email, name=payload.name, role=payload.role, password_hash=hash_password(payload.password))
    db.add(row)
    db.commit()
    audit.record(db, "admin.user_created", actor=user.name, detail={"email": email, "role": payload.role})
    return {"id": row.id}


@router.put("/users/{user_id}")
def update_user(user_id: int, payload: UserUpdateIn, user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    row = db.get(User, user_id)
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.name is not None:
        row.name = payload.name
    if payload.role is not None:
        row.role = payload.role
    if payload.active is not None:
        row.active = payload.active
    if payload.password:
        row.password_hash = hash_password(payload.password)
    db.commit()
    audit.record(db, "admin.user_updated", actor=user.name, detail={"user_id": row.id})
    return {"id": row.id}


@router.get("/category-mappings")
def list_mappings(user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    rows = db.execute(select(CategoryMapping).order_by(CategoryMapping.source_code)).scalars().all()
    return [
        {"id": m.id, "source_code": m.source_code, "source_category": m.source_category, "internal_category": m.internal_category}
        for m in rows
    ]


@router.post("/category-mappings")
def add_mapping(payload: MappingIn, user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    exists = db.execute(
        select(CategoryMapping).where(
            CategoryMapping.source_code == payload.source_code,
            CategoryMapping.source_category == payload.source_category,
        )
    ).scalars().first()
    if exists:
        exists.internal_category = payload.internal_category
        db.commit()
        return {"id": exists.id, "updated": True}
    row = CategoryMapping(**payload.model_dump())
    db.add(row)
    db.commit()
    return {"id": row.id}


@router.delete("/category-mappings/{mapping_id}")
def delete_mapping(mapping_id: int, user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    row = db.get(CategoryMapping, mapping_id)
    if not row:
        raise HTTPException(status_code=404, detail="Mapping not found")
    db.delete(row)
    db.commit()
    return {"deleted": mapping_id}


@router.get("/ai-quality")
def ai_quality_summary(user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    return ai_quality.summary(db)


@router.get("/evaluation")
def run_evaluation(user: User = Depends(ADMIN)):
    """Run the gold-set evaluation and return per-field accuracy.

    Runs against a throwaway database, so it never touches operational data.
    """
    from app.services import evaluation

    report = evaluation.run_all()
    # The per-case detail is verbose; the summary is what the panel needs.
    report.pop("cases", None)
    return report


@router.get("/evaluation/report")
def evaluation_report(user: User = Depends(ADMIN)):
    """The same evaluation, rendered as a plain-text report."""
    from app.services import evaluation

    report = evaluation.run_all()
    return PlainTextResponse(evaluation.format_report(report))


@router.get("/audit")
def audit_log(limit: int = Query(default=100, le=500), opportunity_id: int | None = None, user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    query = select(DecisionAudit).order_by(DecisionAudit.created_at.desc()).limit(limit)
    if opportunity_id:
        query = query.where(DecisionAudit.opportunity_id == opportunity_id)
    rows = db.execute(query).scalars().all()
    return [
        {
            "id": r.id,
            "action": r.action,
            "actor": r.actor,
            "opportunity_id": r.opportunity_id,
            "gate_task_id": r.gate_task_id,
            "detail": r.detail,
            "created_at": iso(r.created_at),
        }
        for r in rows
    ]


@router.get("/audit/export")
def audit_export(user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    rows = db.execute(select(DecisionAudit).order_by(DecisionAudit.created_at)).scalars().all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "created_at", "action", "actor", "opportunity_id", "gate_task_id", "detail"])
    for r in rows:
        writer.writerow([r.id, r.created_at, r.action, r.actor, r.opportunity_id, r.gate_task_id, r.detail])
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_log.csv"},
    )


@router.get("/digest/preview")
def digest_preview(user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    """The brief as it would be sent, before it is sent.

    The way to check that the digest is worth reading is to read it — this
    returns exactly what the scheduled send would deliver, without mailing
    anyone.
    """
    from app.services import digest

    built = digest.build_digest(db)
    return {
        "ranked": len(built["ranked"]),
        "closing": len(built["closing"]),
        "waiting": built["waiting"],
        "overdue_gates": built["overdue_gates"],
        "pending_gates": built["pending_gates"],
        "new_since_last": built["new_since_last"],
        "text": digest.render_text(built),
    }


@router.post("/digest/send")
def digest_send(user: User = Depends(ADMIN), db: Session = Depends(get_db)):
    """Build and deliver the digest now.

    The scheduled send runs on the host's cron; this is how an administrator
    confirms the SMTP account works, or sends an extra brief on a busy day.
    """
    from app.services import digest

    if not emailer.configured():
        raise HTTPException(
            status_code=400,
            detail="Email is not configured on this deployment: set BMS_SMTP_HOST and BMS_SMTP_FROM.",
        )
    return digest.send_digest(db)
