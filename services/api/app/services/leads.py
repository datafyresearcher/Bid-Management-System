import json

from sqlalchemy import select

from app.config import fixtures_dir
from app.models import Lead, Opportunity
from app.services import audit, notifications
from app.services.normalizer import build_dedup_key, classify_category
from app.services.utils import detect_currency, normalize_key, parse_date, source_id_for_code, value_band

LEAD_STATUSES = ["Signal", "Qualified", "Tracking", "Converted", "Dropped"]

# A lead carries either a source registry code (email_plan) or a confidence
# tier (L1/L2/L9). Tier codes describe how sure we are, not where the signal
# came from, so they are mapped onto the registry row that actually published
# the signal.
LEAD_SOURCE_CODES = {
    "L1": "annual_plan",
    "L2": "annual_plan",
    "L9": "manual",
}


def lead_source_code(lead) -> str:
    """Registry source code for a lead."""
    code = (lead.source_code or "").strip()
    if code in ("email_plan", "annual_plan", "manual"):
        return code
    return LEAD_SOURCE_CODES.get(code, "manual")


def import_fixture_leads(db) -> int:
    path = fixtures_dir() / "leads_annual_plan.json"
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    items = payload if isinstance(payload, list) else payload.get("leads", [])
    created = 0
    for item in items:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        exists = db.execute(select(Lead).where(Lead.title == title)).scalars().first()
        if exists:
            continue
        db.add(
            Lead(
                source_code=item.get("source_code", "L2"),
                source_label=item.get("source_label", "Annual procurement plan"),
                buyer=item.get("buyer", ""),
                title=title,
                description=item.get("description", ""),
                category_internal=item.get("category_internal") or classify_category(db, "fixture", "", title, ""),
                area=item.get("area", ""),
                expected_window=item.get("expected_window", ""),
                estimated_value=item.get("estimated_value"),
                currency=item.get("currency", "PKR"),
                confidence_tier=item.get("confidence_tier", "Medium"),
                confidence_note=item.get("confidence_note", ""),
                status=item.get("status", "Signal"),
                evidence=item.get("evidence") or {"fixture": path.name},
            )
        )
        created += 1
    db.commit()
    if created:
        notifications.notify(db, "lead", f"{created} budget signals imported", "From annual procurement plan fixtures", severity="info")
    return created


def create_manual(db, payload: dict) -> Lead:
    lead = Lead(
        source_code=payload.get("source_code", "L9"),
        source_label=payload.get("source_label", "Manual entry"),
        buyer=payload.get("buyer", ""),
        title=payload.get("title", "").strip() or "Untitled signal",
        description=payload.get("description", ""),
        category_internal=payload.get("category_internal", "General"),
        area=payload.get("area", ""),
        expected_window=payload.get("expected_window", ""),
        estimated_value=payload.get("estimated_value"),
        currency=payload.get("currency", "PKR"),
        confidence_tier=payload.get("confidence_tier", "Medium"),
        confidence_note=payload.get("confidence_note", ""),
        status="Signal",
        evidence=payload.get("evidence") or {"manual": True},
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    audit.record(db, "lead.created", detail={"lead_id": lead.id, "title": lead.title[:120]})
    return lead


def update_status(db, lead, status, actor=None):
    status = status.capitalize()
    if status not in LEAD_STATUSES:
        status = "Signal"
    lead.status = status
    db.commit()
    audit.record(db, "lead.status", actor=actor.name if actor else "system", detail={"lead_id": lead.id, "status": status})
    return lead


def convert_to_opportunity(db, lead, actor=None) -> Opportunity:
    if lead.converted_opportunity_id:
        existing = db.get(Opportunity, lead.converted_opportunity_id)
        if existing:
            return existing

    published = parse_date(lead.expected_window) if lead.expected_window else None
    source_code = lead_source_code(lead)
    opp = Opportunity(
        dedup_key=build_dedup_key(lead.buyer, f"lead-{lead.id}", published),
        country="PK",
        area=lead.area or "",
        category_internal=lead.category_internal or "General",
        category_source=lead.source_label or "",
        buyer_name=lead.buyer or "",
        buyer_ref=f"LEAD-{lead.id}",
        title=lead.title,
        description=lead.description or "",
        estimated_value=lead.estimated_value,
        currency=lead.currency or detect_currency(lead.title),
        value_band=value_band(lead.estimated_value, lead.currency or "PKR"),
        state="NORMALIZED",
        source_kind="lead",
        source_refs=[{"source_code": source_code, "native_id": f"lead-{lead.id}", "url": ""}],
        source_id=source_id_for_code(db, source_code),
        lead_id=lead.id,
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)

    lead.status = "Converted"
    lead.converted_opportunity_id = opp.id
    db.commit()

    from app.services import scorer

    scorer.run(db, opp)
    audit.record(db, "lead.converted.manual", actor=actor.name if actor else "system", opportunity_id=opp.id, detail={"lead_id": lead.id})
    notifications.notify(
        db,
        "lead",
        f"Lead converted and scored: {lead.title[:80]}",
        f"Score {opp.score_total} — state {opp.state}",
        severity="info",
        opportunity_id=opp.id,
    )
    return opp
