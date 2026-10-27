from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Opportunity, Source, User
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


class CaptureIn(BaseModel):
    code: str
    # The raw HTML of each listing page, in order, exactly as the portal
    # served it to the browser that captured it.
    pages: list[str]
    captured_at: str = ""


@router.post("/capture")
def capture_listing(
    payload: CaptureIn,
    x_capture_secret: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Ingest listing pages captured off-portal by the bid desk's machine.

    One portal (PPRA Punjab) refuses connections from every datacenter
    network, so this deployment can never read it directly — however patient
    the client and whichever region it runs in. The bridge closes that gap:
    the desk's own browser fetches the pages from a network the portal
    answers, and this endpoint runs them through exactly the same parser,
    normalizer and scorer a live scan would. The capture is stored whole as
    the source's latest snapshot, so provenance is kept and the parse stays
    auditable.

    Authenticated by the capture secret rather than a user account, because
    the machine doing the capturing is the desk's, not a person's. An
    unconfigured or wrong secret reads as a missing route rather than a
    forbidden one, so the door leaves no trace for strangers to knock on.
    """
    import hmac

    from app import runtime
    from app.config import settings
    from app.connectors.registry import get_connector
    from app.services import normalizer
    from app.services.utils import utcnow

    if not settings.capture_secret or not hmac.compare_digest(
        x_capture_secret, settings.capture_secret
    ):
        raise HTTPException(status_code=404, detail="Not found")

    row = db.execute(select(Source).where(Source.code == payload.code)).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Unknown source code: {payload.code}")
    connector = get_connector(row)
    if not connector:
        raise HTTPException(status_code=400, detail=f"No adapter registered for '{row.adapter}'")

    parse = getattr(connector, "parse_grid", None) or getattr(connector, "parse_listing", None)
    if parse is None:
        raise HTTPException(status_code=400, detail=f"Adapter '{row.adapter}' cannot parse captured HTML")

    pages = [p for p in payload.pages if p and p.strip()]
    if not pages:
        raise HTTPException(status_code=400, detail="No pages in capture")

    started = utcnow()
    notices, seen = [], set()
    for page in pages:
        for notice in parse(page) or []:
            native_id = notice.get("native_id")
            if native_id and native_id not in seen:
                seen.add(native_id)
                notices.append(notice)
    if hasattr(connector, "_merge_corrigenda"):
        # Pair corrigenda with their originals where the listing itself makes
        # the pair clear. The detail-page resolution a live scan also does is
        # deliberately skipped: it reads the portal back, and this portal is
        # the one this deployment cannot read.
        notices = connector._merge_corrigenda(notices)

    normalizer.store_snapshot(
        db,
        row,
        None,
        row.listing_url or row.url,
        pages[0],
        kind="listing",
        meta={"adapter": row.adapter, "mode": "bridge", "pages": len(pages), "captured_at": payload.captured_at},
    )

    before_ids = set(db.execute(select(Opportunity.id)).scalars().all())
    normalizer.normalize_notices(db, row, notices)
    after_ids = set(db.execute(select(Opportunity.id)).scalars().all())
    new_ids = after_ids - before_ids
    created = len(new_ids)

    # A capture whose parser found nothing means the portal changed shape —
    # recorded as degraded rather than healthy, like a live scan would be.
    row.health = "ok" if notices else "degraded"
    row.last_scan_at = utcnow()
    row.last_scan_stats = {
        "notices": len(notices),
        "new": created,
        "updated": max(0, len(notices) - created),
        "mode": "bridge",
        "pages": len(pages),
        "seconds": round((utcnow() - started).total_seconds(), 1),
    }
    db.commit()
    audit.record(
        db,
        "source.captured",
        actor="capture bridge",
        detail={"code": row.code, "notices": len(notices), "new": created, "pages": len(pages)},
    )

    budget = settings.score_budget_seconds
    left = runtime.remaining()
    if left is not None:
        budget = max(0.0, min(budget, left))
    scored = jobs.score_new(db, sorted(new_ids), budget_seconds=budget)
    return {
        "source": row.code,
        "notices": len(notices),
        "new": created,
        "updated": max(0, len(notices) - created),
        "scored": scored,
        "pages": len(pages),
        "health": row.health,
    }


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
