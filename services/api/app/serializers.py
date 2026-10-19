from datetime import datetime


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
        "score_total": o.score_total,
        "hard_gate_result": o.hard_gate_result,
        "ai_rationale": o.ai_rationale,
        "ai_confidence": o.ai_confidence,
        "extraction_grade": o.extraction_grade,
        "documents_status": o.documents_status,
        "notice_status": o.notice_status,
        "source_refs": o.source_refs or [],
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
            "tender_fee": o.tender_fee,
            "submission_mode": o.submission_mode,
            "checklist": o.checklist,
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
        "schedule_hours": s.schedule_hours,
        "enabled": s.enabled,
        "approved": s.approved,
        "health": s.health,
        "last_scan_at": iso(s.last_scan_at),
        "last_scan_stats": s.last_scan_stats,
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
