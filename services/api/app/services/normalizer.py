import hashlib

from sqlalchemy import select

from app.models import CategoryMapping, Lead, Opportunity, RawSnapshot
from app.services import audit, notifications
from app.services.utils import detect_currency, normalize_key, parse_amount, parse_date, value_band

CATEGORY_KEYWORDS = {
    "Substations": ["substation", "grid station", "grid-station", "gss", "transformer"],
    "Transmission Lines": [
        "transmission line", "220kv", "132kv", "500kv", "tower", "conductor", "stringing", "t&p",
    ],
    "Renewable Energy": ["solar", "renewable", "wind", "pv plant", "photovoltaic"],
    "Civil Infrastructure": [
        "building", "civil works", "drain", "boundary wall", "control house", "foundation", "road",
        "street", "sewerage",
    ],
    "Transport Infrastructure": ["highway", "bridge", "interchange", "carriageway", "flyover"],
    "Supply / Goods": ["supply of", "procurement of", "equipment", "material", "cables", "insulator", "furniture"],
    "Services": ["services", "consultancy", "maintenance", "hiring of", "operations"],
}

TENDER_TYPE_KEYWORDS = {
    "Auction-Disposal": ["auction", "disposal", "scrap", "unserviceable"],
    "EOI": ["expression of interest", "eoi"],
    "PQ": ["pre-qualification", "prequalification", "pre qualification"],
    "RFP": ["request for proposal", "rfp", "proposal"],
    "Works": ["construction", "works", "installation", "erection", "extension", "rehabilitation"],
    "Goods": ["supply of", "procurement of", "purchase of"],
    "Services": ["services", "consultancy", "maintenance", "hiring of"],
}


def classify_category(db, source_code: str, source_category: str, title: str, description: str) -> str:
    if source_category:
        mapping = db.execute(
            select(CategoryMapping).where(
                CategoryMapping.source_code == source_code,
                CategoryMapping.source_category == source_category,
            )
        ).scalar_one_or_none()
        if mapping:
            return mapping.internal_category
    text = f"{title} {description}".lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(k in text for k in keywords):
            return category
    return "General"


def classify_tender_type(title: str, description: str) -> str:
    text = f"{title} {description}".lower()
    for tender_type in ["Auction-Disposal", "EOI", "PQ", "RFP"]:
        if any(k in text for k in TENDER_TYPE_KEYWORDS[tender_type]):
            return tender_type
    for tender_type in ["Works", "Goods", "Services"]:
        if any(k in text for k in TENDER_TYPE_KEYWORDS[tender_type]):
            return tender_type
    return "Works"


def detect_regime(text: str) -> tuple[str, str]:
    t = (text or "").lower()
    regime = "single-stage-one-envelope"
    if "two stage" in t or "two-stage" in t or "two envelope" in t or "two-envelope" in t:
        regime = "two-stage-two-envelope"
    elif "single stage" in t or "single-stage" in t:
        regime = "single-stage-one-envelope"
    family = ""
    if "fidic" in t:
        if "silver" in t or "epc/turnkey" in t or "epc turnkey" in t:
            family = "FIDIC Silver Book (EPC/Turnkey)"
        elif "yellow" in t or "plant and design-build" in t or "design-build" in t or "design and build" in t:
            family = "FIDIC Yellow Book (Plant & Design-Build)"
        elif "red book" in t or "conditions of contract for construction" in t:
            family = "FIDIC Red Book (Construction)"
        else:
            family = "FIDIC (edition unconfirmed)"
    if "pec" in t and "part-ii" in t:
        family = family or "PEC Standard Bidding Document (FIDIC-based)"
    if any(k in t for k in ["adb", "world bank", "islamic development bank", "isdb"]) and (
        "loan" in t or "financ" in t or "donor" in t
    ):
        family = family or "Donor SBD (MDB harmonised)"
    return regime, family


def build_dedup_key(buyer: str, ref: str, published_at) -> str:
    year = published_at.year if published_at else "na"
    return normalize_key(f"{buyer}|{ref}|{year}")[:380]


def normalize_notice(db, source, notice: dict) -> Opportunity:
    published = parse_date(notice.get("published_at"))
    dedup_key = build_dedup_key(notice.get("buyer_name", ""), notice.get("buyer_ref", ""), published)
    existing = None
    if dedup_key and not dedup_key.endswith("|na"):
        existing = db.execute(select(Opportunity).where(Opportunity.dedup_key == dedup_key)).scalar_one_or_none()

    source_ref = {
        "source_id": source.id,
        "source_code": source.code,
        "native_id": notice.get("native_id"),
        "url": notice.get("url"),
    }

    if existing:
        refs = list(existing.source_refs or [])
        if not any(r.get("source_code") == source.code and r.get("native_id") == source_ref["native_id"] for r in refs):
            refs.append(source_ref)
            existing.source_refs = refs
        db.commit()
        return existing

    title = notice.get("title", "").strip()
    description = notice.get("description", "")
    combined = f"{title} {description}"
    currency = detect_currency(combined)
    estimated_value = parse_amount(notice.get("estimated_value"))
    regime, family = detect_regime(combined)
    category = classify_category(db, source.code, notice.get("source_category", ""), title, description)

    opp = Opportunity(
        dedup_key=dedup_key,
        country=getattr(source, "country", "PK"),
        area=notice.get("area", "") or getattr(source, "area", ""),
        city=notice.get("city", ""),
        category_internal=category,
        category_source=notice.get("source_category", ""),
        tender_type=classify_tender_type(title, description),
        procurement_regime=regime,
        contract_family=family,
        source_kind=getattr(source, "type", "portal"),
        buyer_name=notice.get("buyer_name", ""),
        buyer_ref=notice.get("buyer_ref", ""),
        title=title or "Untitled tender",
        description=description,
        estimated_value=estimated_value,
        currency=currency,
        value_band=value_band(estimated_value, currency),
        published_at=published,
        clarification_deadline=parse_date(notice.get("clarification_deadline")),
        submission_deadline=parse_date(notice.get("submission_deadline")),
        opening_at=parse_date(notice.get("opening_at")),
        notice_status="Published",
        state="NORMALIZED",
        source_refs=[source_ref],
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)

    audit.record(
        db,
        "opportunity.normalized",
        opportunity_id=opp.id,
        detail={"source": source.code, "native_id": notice.get("native_id"), "category": category},
    )
    link_tracking_leads(db, opp)
    return opp


def link_tracking_leads(db, opp: Opportunity):
    leads = db.execute(select(Lead).where(Lead.status == "Tracking")).scalars().all()
    for lead in leads:
        if _lead_matches(lead, opp):
            lead.status = "Converted"
            lead.converted_opportunity_id = opp.id
            opp.lead_id = lead.id
            db.commit()
            notifications.notify(
                db,
                "lead",
                f"Lead converted: {lead.title[:80]}",
                f"Lead #{lead.id} matched published tender — {opp.title[:120]}",
                severity="info",
                opportunity_id=opp.id,
            )
            audit.record(db, "lead.converted", opportunity_id=opp.id, detail={"lead_id": lead.id})
            return


def _lead_matches(lead: Lead, opp: Opportunity) -> bool:
    if lead.status != "Tracking":
        return False
    buyer_a = normalize_key(lead.buyer)
    buyer_b = normalize_key(opp.buyer_name)
    if buyer_a and buyer_b and buyer_a[:12] != buyer_b[:12] and buyer_a not in buyer_b and buyer_b not in buyer_a:
        return False
    if lead.category_internal not in ("", "General") and lead.category_internal != opp.category_internal:
        return False
    tokens = [t for t in normalize_key(lead.title).split() if len(t) > 3]
    if not tokens:
        return buyer_a and buyer_a in buyer_b
    opp_text = normalize_key(f"{opp.title} {opp.description}")
    hits = sum(1 for t in set(tokens) if t in opp_text)
    return hits >= max(1, len(set(tokens)) // 4)


def snapshot_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()


def store_snapshot(db, source, native_id, url, content, kind="listing", meta=None) -> RawSnapshot:
    snap = RawSnapshot(
        source_id=source.id,
        native_id=native_id,
        url=url,
        kind=kind,
        content_hash=snapshot_hash(content or ""),
        content=content,
        meta=meta or {},
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return snap
