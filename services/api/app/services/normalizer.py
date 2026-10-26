import hashlib
import re

from sqlalchemy import select

from app.config import settings
from app.models import CategoryMapping, Lead, Opportunity, RawSnapshot
from app.services import audit, notifications
from app.services.utils import detect_currency, normalize_key, parse_amount, parse_date, value_band


def _keyword_hit(keyword: str, text: str) -> bool:
    """Whether a keyword appears in the text as a word of its own.

    A short code would otherwise match inside a longer word: "gss" sits inside
    "GSSSE", which would have a school meals tender filed under substations.
    """
    if keyword.isalnum() and len(keyword) <= 4:
        return re.search(rf"\b{re.escape(keyword)}\b", text, re.I) is not None
    return keyword in text

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


def classify_category(db, source_code: str, source_category: str, title: str, description: str, mappings=None) -> str:
    if source_category:
        mapping = None
        if mappings is not None:
            # The whole map for this source was read once for the batch.
            mapping = mappings.get(source_category)
        else:
            mapping = db.execute(
                select(CategoryMapping).where(
                    CategoryMapping.source_code == source_code,
                    CategoryMapping.source_category == source_category,
                )
            ).scalar_one_or_none()
            mapping = mapping.internal_category if mapping else None
        if mapping:
            return mapping
    text = f"{title} {description}".lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(_keyword_hit(k, text) for k in keywords):
            return category
    return "General"


def classify_tender_type(title: str, description: str) -> str:
    text = f"{title} {description}".lower()
    for tender_type in ["Auction-Disposal", "EOI", "PQ", "RFP"]:
        if any(_keyword_hit(k, text) for k in TENDER_TYPE_KEYWORDS[tender_type]):
            return tender_type
    for tender_type in ["Works", "Goods", "Services"]:
        if any(_keyword_hit(k, text) for k in TENDER_TYPE_KEYWORDS[tender_type]):
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


def _same_tender_record(db, source, notice: dict):
    """An existing record for the same tender, published under another notice.

    A corrigendum is the tender it corrects, published a second time. When the
    correction reaches us after the original notice has already been captured,
    the two have to end up as one record rather than two.

    The pairing is only made when it is unambiguous: exactly one record from
    the same source carries the same procurement name for the same department,
    and one of the two notices is a correction. Where the department has
    published several notices under that name, which of them the correction
    belongs to is not knowable, and the correction is kept as its own record.
    """
    title = (notice.get("title") or "").strip().upper()
    buyer = (notice.get("buyer_name") or "").strip()
    if not title or not buyer:
        return None

    is_corrigendum = (notice.get("notice_status") or "") == "Corrigendum"
    rows = (
        db.execute(
            select(Opportunity).where(
                Opportunity.source_id == source.id,
                Opportunity.buyer_name == buyer,
            )
        )
        .scalars()
        .all()
    )
    matches = [o for o in rows if (o.title or "").strip().upper() == title]
    if len(matches) != 1:
        return None
    existing = matches[0]
    if not (is_corrigendum or existing.notice_status == "Corrigendum"):
        return None
    return existing


class _BatchLookup:
    """The records a batch of notices is matched against, read once.

    A portal can publish a hundred notices between two scans. Matching each
    one against the database separately costs a round trip per notice, and a
    scan that cannot finish inside the time its request is allowed leaves the
    tenders behind. The records a notice is matched against are therefore read
    once for the whole batch, and the tenders the batch creates are written
    in one go.
    """

    def __init__(self, db, source, notices):
        self.db = db
        self.source = source
        self.by_dedup = {}
        self.by_buyer_title = {}
        self.categories = {}
        self.leads = []

        keys = []
        for notice in notices:
            key = build_dedup_key(
                notice.get("buyer_name", ""),
                notice.get("buyer_ref", ""),
                parse_date(notice.get("published_at")),
            )
            if key and not key.endswith("|na"):
                keys.append(key)
        if keys:
            for row in db.execute(select(Opportunity).where(Opportunity.dedup_key.in_(keys))).scalars().all():
                self.by_dedup[row.dedup_key] = row

        # Records already held for this source, indexed the way a corrigendum
        # is paired with the tender it corrects.
        for row in db.execute(select(Opportunity).where(Opportunity.source_id == source.id)).scalars().all():
            key = (row.buyer_name or "", (row.title or "").strip().upper())
            self.by_buyer_title.setdefault(key, []).append(row)

        for mapping in db.execute(select(CategoryMapping).where(CategoryMapping.source_code == source.code)).scalars().all():
            self.categories[mapping.source_category] = mapping.internal_category

        self.leads = db.execute(select(Lead).where(Lead.status == "Tracking")).scalars().all()

    def same_tender_record(self, notice: dict):
        """The record this notice belongs to, where it is a correction."""
        title = (notice.get("title") or "").strip().upper()
        buyer = (notice.get("buyer_name") or "").strip()
        if not title or not buyer:
            return None
        is_corrigendum = (notice.get("notice_status") or "") == "Corrigendum"
        matches = self.by_buyer_title.get((buyer, title), [])
        if len(matches) != 1:
            return None
        existing = matches[0]
        if not (is_corrigendum or existing.notice_status == "Corrigendum"):
            return None
        return existing

    def remember(self, opp: Opportunity, dedup_key: str):
        """Remember a tender this batch has just created."""
        if dedup_key and not dedup_key.endswith("|na"):
            self.by_dedup[dedup_key] = opp
        key = (opp.buyer_name or "", (opp.title or "").strip().upper())
        self.by_buyer_title.setdefault(key, []).append(opp)


def normalize_notices(db, source, notices) -> list:
    """Capture a whole listing of notices from one portal.

    The same work as `normalize_notice`, done for a batch. The records the
    notices are matched against are read once, the new tenders are written
    together, and the audit trail is written with them. That is what lets a
    scan finish inside the time the request it runs in is allowed, even when
    the portal published a hundred tenders since the last scan.
    """
    if not notices:
        return []
    lookup = _BatchLookup(db, source, notices)
    created = []
    for notice in notices:
        opp = _normalize_one(db, source, notice, lookup)
        if opp is not None:
            created.append(opp)
    # The tenders are written first, so that they carry their own identity,
    # and the audit trail and the leads that follow them are written with it.
    db.commit()
    for opp in created:
        if opp.state != "NORMALIZED":
            continue
        audit.record(
            db,
            "opportunity.normalized",
            opportunity_id=opp.id,
            detail={"source": source.code, "native_id": _native_id_of(opp), "category": opp.category_internal},
            commit=False,
        )
        link_tracking_leads(db, opp, lookup.leads)
    db.commit()
    return created


def _native_id_of(opp: Opportunity) -> str:
    for ref in opp.source_refs or []:
        if isinstance(ref, dict) and ref.get("native_id"):
            return str(ref.get("native_id"))
    return ""


def normalize_notice(db, source, notice: dict) -> Opportunity:
    return _normalize_one(db, source, notice, None)


def _normalize_one(db, source, notice: dict, lookup=None):
    published = parse_date(notice.get("published_at"))
    dedup_key = build_dedup_key(notice.get("buyer_name", ""), notice.get("buyer_ref", ""), published)
    existing = None
    if dedup_key and not dedup_key.endswith("|na"):
        if lookup is not None:
            existing = lookup.by_dedup.get(dedup_key)
        else:
            existing = db.execute(select(Opportunity).where(Opportunity.dedup_key == dedup_key)).scalar_one_or_none()
    # A correction of a tender that is already on file is that tender, not a
    # second one.
    paired = False
    if existing is None:
        if lookup is not None:
            existing = lookup.same_tender_record(notice)
        else:
            existing = _same_tender_record(db, source, notice)
        paired = existing is not None

    source_ref = {
        "source_id": source.id,
        "source_code": source.code,
        "native_id": notice.get("native_id"),
        "url": notice.get("url"),
        # The reference the authority published the notice under, when the
        # portal states one, and the notice document itself.
        "reference": notice.get("portal_reference") or notice.get("buyer_ref", ""),
        "document_url": notice.get("document_url", ""),
        # Whether this record came off the live portal or out of a saved
        # capture of one, so the dashboard can tell the two apart.
        "mode": "saved-capture" if settings.fixtures else "live",
    }

    if existing:
        # Copy the refs into fresh dicts. Mutating the loaded dicts in place
        # would change the old value too, and the update would never be flushed.
        refs = [dict(r) for r in (existing.source_refs or [])]
        status = (notice.get("notice_status") or "").strip()
        # A corrigendum is more specific than a plain publication. Once a
        # tender is known to carry one, a later scan of the original notice
        # does not undo that, nor does it replace the correction's document.
        keep_corrigendum = existing.notice_status == "Corrigendum" and status != "Corrigendum"
        matched = False
        for i, r in enumerate(refs):
            if r.get("source_code") == source.code and r.get("native_id") == source_ref["native_id"]:
                # Same notice seen again. Keep the stored reference current —
                # portals move pages and the canonical URL changes over time.
                if source_ref.get("url") and r.get("url") != source_ref["url"] and not keep_corrigendum:
                    refs[i] = {**r, "url": source_ref["url"]}
                matched = True
                break
        if not matched:
            refs.append(source_ref)
        existing.source_refs = refs
        if existing.source_id is None:
            existing.source_id = source.id
        # A corrigendum can move a deadline that was already recorded. The
        # later date wins, because it is the one the authority published last.
        deadline = parse_date(notice.get("submission_deadline"))
        if deadline and (existing.submission_deadline is None or deadline > existing.submission_deadline):
            existing.submission_deadline = deadline
        if paired and published and (existing.published_at is None or published < existing.published_at):
            # The tender was first published with the original notice, which
            # may only be reaching us now.
            existing.published_at = published
        if status and status != existing.notice_status and not keep_corrigendum:
            existing.notice_status = status
        if lookup is None:
            db.commit()
        return existing

    title = notice.get("title", "").strip()
    description = notice.get("description", "")
    combined = f"{title} {description}"
    currency = detect_currency(combined)
    estimated_value = parse_amount(notice.get("estimated_value"))
    regime, family = detect_regime(combined)
    category = classify_category(
        db,
        source.code,
        notice.get("source_category", ""),
        title,
        description,
        mappings=lookup.categories if lookup is not None else None,
    )
    # When the portal states the procurement type itself, that is used rather
    # than a guess from the wording of the title.
    tender_type = (notice.get("tender_type") or "").strip() or classify_tender_type(title, description)

    opp = Opportunity(
        dedup_key=dedup_key,
        country=getattr(source, "country", "PK"),
        area=notice.get("area", "") or getattr(source, "area", ""),
        city=notice.get("city", ""),
        category_internal=category,
        category_source=notice.get("source_category", ""),
        tender_type=tender_type,
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
        notice_status=(notice.get("notice_status") or "").strip() or "Published",
        state="NORMALIZED",
        source_refs=[source_ref],
        source_id=source.id,
    )
    db.add(opp)
    if lookup is not None:
        # The tender is written with the rest of the batch, but it is
        # remembered straight away so that a second notice in the same batch
        # is matched against it rather than becoming a duplicate.
        lookup.remember(opp, dedup_key)
        return opp
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


def link_tracking_leads(db, opp: Opportunity, leads=None):
    # The leads waiting for a published tender are read once for a batch, so
    # that a hundred new tenders do not ask the same question a hundred times.
    if leads is None:
        leads = db.execute(select(Lead).where(Lead.status == "Tracking")).scalars().all()
    for lead in leads:
        if not _lead_matches(lead, opp):
            continue
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
