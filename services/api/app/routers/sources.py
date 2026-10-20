from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Source, User
from app.security import get_current_user, require_roles
from app.serializers import source as source_serializer
from app.services import audit, jobs

router = APIRouter(prefix="/api/sources", tags=["sources"])


class SourceIn(BaseModel):
    code: str
    name: str
    country: str = "PK"
    area: str = ""
    type: str = "portal"
    adapter: str = "fixture_json"
    url: str = ""
    authority: str = ""
    tier: str = ""
    access: str = "public"
    listing_url: str = ""
    schedule_hours: int = 24
    enabled: bool = True


class SourceUpdateIn(BaseModel):
    name: str | None = None
    country: str | None = None
    area: str | None = None
    type: str | None = None
    adapter: str | None = None
    url: str | None = None
    authority: str | None = None
    tier: str | None = None
    access: str | None = None
    listing_url: str | None = None
    schedule_hours: int | None = None
    enabled: bool | None = None
    approved: bool | None = None


@router.get("")
def list_sources(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Source).order_by(Source.code)).scalars().all()
    return [source_serializer(s) for s in rows]


@router.get("/adapters")
def adapters(user: User = Depends(get_current_user)):
    from app.connectors.registry import ADAPTER_CATALOG

    return ADAPTER_CATALOG


@router.post("")
def create_source(payload: SourceIn, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    exists = db.execute(select(Source).where(Source.code == payload.code)).scalars().first()
    if exists:
        raise HTTPException(status_code=400, detail="Source code already exists")
    row = Source(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    audit.record(db, "source.created", actor=user.name, detail={"code": row.code, "adapter": row.adapter})
    return source_serializer(row)


@router.put("/{source_id}")
def update_source(source_id: int, payload: SourceUpdateIn, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    row = db.get(Source, source_id)
    if not row:
        raise HTTPException(status_code=404, detail="Source not found")
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(row, field, value)
    db.commit()
    audit.record(db, "source.updated", actor=user.name, detail={"source_id": row.id})
    return source_serializer(row)


@router.post("/{source_id}/scan")
def scan_source(source_id: int, user: User = Depends(require_roles("bid_manager")), db: Session = Depends(get_db)):
    row = db.get(Source, source_id)
    if not row:
        raise HTTPException(status_code=404, detail="Source not found")
    try:
        result = jobs.run_source(db, row)
    except Exception as exc:
        jobs.record_scan_failure(db, row, exc)
        raise HTTPException(status_code=502, detail=f"Scan failed: {exc}")
    return result


@router.post("/{source_id}/test-fetch")
def test_fetch(source_id: int, user: User = Depends(require_roles("admin", "bid_manager")), db: Session = Depends(get_db)):
    from app.connectors.registry import get_connector

    row = db.get(Source, source_id)
    if not row:
        raise HTTPException(status_code=404, detail="Source not found")
    connector = get_connector(row)
    if not connector:
        raise HTTPException(status_code=400, detail=f"No adapter registered for '{row.adapter}'")
    try:
        notices = connector.fetch_listing() or []
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Fetch failed: {exc}")
    return {
        "count": len(notices),
        "samples": [
            {
                "native_id": n.get("native_id"),
                "title": (n.get("title") or "")[:180],
                "buyer": n.get("buyer_name"),
                "deadline": n.get("submission_deadline"),
                "value": n.get("estimated_value"),
            }
            for n in notices[:5]
        ],
    }
