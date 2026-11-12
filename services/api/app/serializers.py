from datetime import datetime

from app.services.utils import utcnow
from app.source_registry import BRIDGE_FED_SOURCES

# The states a tender ends in. A tender in one of these is finished whatever
# its deadline says, so it is not treated as merely out of date.
FINAL_STATES = {"WON", "LOST", "REJECTED", "ABANDONED", "SCREENED_OUT", "AUTO_ARCHIVED"}

# The states where the bid itself has been decided. These are closed, not
# merely out of date — the bid room reads them differently, and they are
# kept out of the "past deadline" section, which is for tenders that were
# still live when their date passed.
DECIDED_STATES = {"WON", "LOST", "REJECTED", "ABANDONED"}


def deadline_status(o) -> str:
    """Whether the bidding window is still open.

    `open` — the tender can still be bid, or nothing is known about when it
    closes. `expired` — the submission deadline has passed, so the tender
    can no longer be bid. `closed` — the bid was decided: won, lost,
    rejected or given up.

    A tender that was screened out on merit is judged by its deadline like
    any other. If its date has passed, it belongs in the past-deadline
    section, because that is what the bidding team asked for: a tender
    whose window has shut should not be left looking live.
    """
    if o.state in DECIDED_STATES:
        return "closed"
    if o.submission_deadline is None:
        return "open"
    if o.submission_deadline < utcnow():
        return "expired"
    return "open"


def iso(dt):
    if isinstance(dt, datetime):
        return dt.isoformat()
    return dt


def user_brief(user):
    if not user:
        return None
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role}


def gate_task(g, include_opportunity=True):
    data = {
        "id": g.id,
        "opportunity_id": g.opportunity_id,
        "gate": g.gate,
        "title": g.title,
        "owner_role": g.owner_role,
        "owner_user_id": g.owner_user_id,
        "status": g.status,
        "sla_hours": g.sla_hours,
        "due_at": iso(g.due_at),
        "decision": g.decision,
        "reason_code": g.reason_code,
        "comment": g.comment,
        "decided_by": g.decided_by,
        "decided_at": iso(g.decided_at),
        "inputs_snapshot": g.inputs_snapshot,
        "created_at": iso(g.created_at),
    }
    if include_opportunity and g.opportunity:
        data["opportunity"] = {
            "id": g.opportunity.id,
            "title": g.opportunity.title,
            "buyer_name": g.opportunity.buyer_name,
            "state": g.opportunity.state,
            "submission_deadline": iso(g.opportunity.submission_deadline),
            "score_total": g.opportunity.score_total,
            "source": source_attribution(g.opportunity),
        }
    return data


def opportunity_brief(o):
    return {
        "id": o.id,
        "title": o.title,
        "buyer_name": o.buyer_name,
        "buyer_ref": o.buyer_ref,
        "country": o.country,
        "area": o.area,
        "city": o.city,
        "category_internal": o.category_internal,
        "tender_type": o.tender_type,
        "procurement_regime": o.procurement_regime,
        "contract_family": o.contract_family,
        "estimated_value": o.estimated_value,
        "currency": o.currency,
        "value_band": o.value_band,
        "published_at": iso(o.published_at),
        "submission_deadline": iso(o.submission_deadline),
        "opening_at": iso(o.opening_at),
        "state": o.state,
        "deadline_status": deadline_status(o),
        "score_total": o.score_total,
        "hard_gate_result": o.hard_gate_result,
        "ai_rationale": o.ai_rationale,
        "bid_summary": o.bid_summary,
        "ai_confidence": o.ai_confidence,
        "extraction_grade": o.extraction_grade,
        "documents_status": o.documents_status,
        "notice_status": o.notice_status,
        "source_refs": o.source_refs or [],
        "source": source_attribution(o),
        "lead_id": o.lead_id,
        "abandoned_reason": o.abandoned_reason,
        "created_at": iso(o.created_at),
        "updated_at": iso(o.updated_at),
    }


def opportunity_detail(o):
    data = opportunity_brief(o)
    data.update(
        {
            "description": o.description,
            "category_source": o.category_source,
            "clarification_deadline": iso(o.clarification_deadline),
            "pec_category_required": o.pec_category_required,
            "specialization": o.specialization,
            "prequal_required": o.prequal_required,
            "qualification_thresholds": o.qualification_thresholds,
            "bid_security_amount": o.bid_security_amount,
            "bid_security_form": o.bid_security_form,
            "bid_security_percent": o.bid_security_percent,
            "estimated_boq_value": o.estimated_boq_value,
            "boq_estimate_note": o.boq_estimate_note,
            "tender_fee": o.tender_fee,
            "submission_mode": o.submission_mode,
            "checklist": o.checklist,
            # The direct link to the bidding document on the authority's own
            # site, and the clarifications and amendments published with it.
            # The link is there whether or not the file was downloaded, so
            # the bid team can always reach the document.
            "document_link": document_link(o),
            "related_documents": related_documents(o),
            "documents": [document(d) for d in o.documents],
            "requirements": [requirement(r) for r in o.requirements],
            "risk_flags": [risk(r) for r in o.risk_flags],
            "compliance": [compliance(c) for c in o.compliance_items],
            "gates": [gate_task(g, include_opportunity=False) for g in o.gate_tasks],
            "timeline": [
                {
                    "from_state": e.from_state,
                    "to_state": e.to_state,
                    "trigger": e.trigger,
                    "actor": e.actor,
                    "detail": e.detail,
                    "created_at": iso(e.created_at),
                }
                for e in sorted(o.workflow_events, key=lambda x: x.created_at)
            ],
        }
    )
    return data


def document_link(o) -> str:
    """The direct link to the bidding document on the authority's site.

    This is the fallback when the file could not be downloaded, and it is
    kept on the record whatever happened to the download.
    """
    for ref in o.source_refs or []:
        if not isinstance(ref, dict):
            continue
        url = ref.get("document_url") or ""
        if url:
            return url
    return ""


def related_documents(o) -> list:
    """The clarifications, amendments and addenda published with the tender.

    Deduplicated across the notices the record was captured from, because a
    tender seen on more than one notice must not offer the same
    clarification twice.
    """
    seen = set()
    out = []
    for ref in o.source_refs or []:
        if not isinstance(ref, dict):
            continue
        for related in ref.get("related_documents") or []:
            if not isinstance(related, dict):
                continue
            url = related.get("url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            out.append(
                {
                    "title": related.get("title") or "Related document",
                    "url": url,
                    "date": related.get("date") or "",
                    "kind": related.get("kind") or "related",
                }
            )
    return out


def document(d):
    return {
        "id": d.id,
        "filename": d.filename,
        "doc_type": d.doc_type,
        "size": d.size,
        "pages": d.pages,
        "parsed": d.parsed,
        "parse_status": d.parse_status,
        "created_at": iso(d.created_at),
    }


def requirement(r):
    return {
        "id": r.id,
        "category": r.category,
        "text": r.text,
        "anchor": r.anchor,
        "mandatory": r.mandatory,
    }


def risk(r):
    return {
        "id": r.id,
        "severity": r.severity,
        "category": r.category,
        "title": r.title,
        "detail": r.detail,
        "anchor": r.anchor,
        "suggested_action": r.suggested_action,
    }


def compliance(c):
    return {
        "id": c.id,
        "requirement": c.requirement,
        "category": c.category,
        "anchor": c.anchor,
        "evidence_type": c.evidence_type,
        "evidence_ref": c.evidence_ref,
        "status": c.status,
        "owner": c.owner,
        "notes": c.notes,
        "mandatory": c.mandatory,
    }


def lead(l):
    return {
        "id": l.id,
        "source_code": l.source_code,
        "source_label": l.source_label,
        "buyer": l.buyer,
        "title": l.title,
        "description": l.description,
        "category_internal": l.category_internal,
        "area": l.area,
        "expected_window": l.expected_window,
        "estimated_value": l.estimated_value,
        "currency": l.currency,
        "confidence_tier": l.confidence_tier,
        "confidence_note": l.confidence_note,
        "status": l.status,
        "evidence": l.evidence,
        "converted_opportunity_id": l.converted_opportunity_id,
        "created_at": iso(l.created_at),
    }


def source(s):
    return {
        "id": s.id,
        "code": s.code,
        "name": s.name,
        "country": s.country,
        "area": s.area,
        "type": s.type,
        "adapter": s.adapter,
        "url": s.url,
        # Provenance — who publishes this data and how we are allowed to read it.
        "authority": s.authority,
        "tier": s.tier,
        "access": s.access,
        # How this deployment reads the portal: directly from the cloud, or
        # through the bid desk's capture bridge because the portal refuses
        # datacenter connections.
        "read_via": "bridge" if s.code in BRIDGE_FED_SOURCES else "cloud",
        "listing_url": s.listing_url,
        "schedule_hours": s.schedule_hours,
        "enabled": s.enabled,
        "approved": s.approved,
        "health": s.health,
        "last_scan_at": iso(s.last_scan_at),
        "last_scan_stats": s.last_scan_stats,
    }


def source_attribution(o):
    """Where a single record came from, ready to show to the user.

    Combines the source registry row (authority, official URL) with the
    per-notice reference captured from the portal, so a reader can trace a
    tender back to the publication it was taken from.
    """
    refs = [r for r in (o.source_refs or []) if isinstance(r, dict)]
    src = getattr(o, "source", None)
    if not refs and src is None:
        return None

    primary = refs[0] if refs else {}
    portal_url = src.url if src else ""
    listing_url = src.listing_url if src else ""

    def carries_a_document(ref):
        """Whether this notice points at a document rather than at a page.

        A notice that published no file has none, and a capture that fell
        back to the portal's own address has none either — neither is a
        document, and neither may be offered as one.
        """
        doc = (ref.get("document_url") or "").strip()
        if not doc:
            return False
        places = {p.rstrip("/") for p in (portal_url, listing_url) if p}
        return doc.rstrip("/") not in places

    # A tender published under more than one notice keeps every one of them.
    # The reference the authority published it under comes from the first, but
    # the link that opens the tender comes from the first one that actually
    # carries a document — otherwise the tender opens on whichever notice
    # happened to be captured first, even where that notice had no file.
    document_ref = next((r for r in refs if carries_a_document(r)), primary)
    notice_url = document_ref.get("url") or primary.get("url") or ""
    document_url = document_ref.get("document_url") or ""
    if document_url.rstrip("/") in {p.rstrip("/") for p in (portal_url, listing_url) if p}:
        document_url = ""
    # The reference the authority published the notice under, when the portal
    # states one. Otherwise the capture's own id.
    reference = primary.get("reference") or primary.get("native_id") or ""

    extra = []
    for ref in refs[1:]:
        extra.append(
            {
                "reference": ref.get("reference") or ref.get("native_id") or "",
                "notice_url": ref.get("url") or "",
                "source_code": ref.get("source_code") or "",
            }
        )

    return {
        "code": primary.get("source_code") or (src.code if src else ""),
        "name": src.name if src else "",
        "authority": src.authority if src else "",
        "tier": src.tier if src else "",
        "access": src.access if src else "",
        "type": src.type if src else "",
        "health": src.health if src else "",
        "portal_url": portal_url,
        "listing_url": listing_url,
        "notice_url": notice_url,
        "document_url": document_url,
        "related_documents": related_documents(o),
        "reference": reference,
        "last_scan_at": iso(src.last_scan_at) if src else None,
        "scan_mode": (src.last_scan_stats or {}).get("mode", "") if src else "",
        "additional_refs": extra,
    }


def notification(n):
    return {
        "id": n.id,
        "type": n.type,
        "severity": n.severity,
        "title": n.title,
        "body": n.body,
        "opportunity_id": n.opportunity_id,
        "read": n.read,
        "created_at": iso(n.created_at),
    }


def proposal(p):
    return {
        "id": p.id,
        "opportunity_id": p.opportunity_id,
        "status": p.status,
        "version": p.version,
        "updated_at": iso(p.updated_at),
        "sections": [
            {
                "id": s.id,
                "key": s.key,
                "title": s.title,
                "content": s.content,
                "status": s.status,
                "citations": s.citations or [],
                "order_index": s.order_index,
            }
            for s in sorted(p.sections, key=lambda x: x.order_index)
        ],
    }


def submission(sr):
    if not sr:
        return None
    return {
        "id": sr.id,
        "status": sr.status,
        "checklist": sr.checklist,
        "pack_files": sr.pack_files,
        "portal_note": sr.portal_note,
        "submitted_at": iso(sr.submitted_at),
        "blocked_reason": sr.blocked_reason,
    }


def outcome(o):
    if not o:
        return None
    return {
        "result": o.result,
        "reason_code": o.reason_code,
        "comment": o.comment,
        "competitor_note": o.competitor_note,
        "award_value": o.award_value,
        "created_at": iso(o.created_at),
    }
