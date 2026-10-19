from datetime import datetime, timedelta

from sqlalchemy import select

from app.models import (
    ComplianceItem,
    ExtractedRequirement,
    GateTask,
    LibraryDocument,
    Opportunity,
    Proposal,
    User,
    WorkflowEvent,
)
from app.services import audit, notifications

APPROVE_DECISIONS = {"GO", "CONFIRMED", "APPROVED", "SUBMITTED", "YES"}
REJECT_DECISIONS = {"NO_GO", "NOT_CONFIRMED", "RETURNED", "NO", "BLOCKED"}
FINAL_STATES = {"WON", "LOST", "REJECTED", "ABANDONED", "SCREENED_OUT", "AUTO_ARCHIVED"}

GATE_OWNERS = {1: "bid_manager", 2: "proposal_engineer", 3: "proposal_engineer", 4: "management", 5: "bid_manager"}
GATE_SLA = {1: 24, 2: 48, 3: 48, 4: 24, 5: 12}


def transition(db, opp, to_state, trigger, actor="system", detail=""):
    from_state = opp.state
    opp.state = to_state
    if from_state != to_state:
        db.add(
            WorkflowEvent(
                opportunity_id=opp.id,
                from_state=from_state,
                to_state=to_state,
                trigger=trigger,
                actor=actor,
                detail=str(detail or "")[:500],
            )
        )
    db.commit()
    return opp


def open_gate(db, opp, gate, title, owner_role=None, sla_hours=None, inputs=None):
    pending = (
        db.execute(
            select(GateTask).where(GateTask.opportunity_id == opp.id, GateTask.status == "PENDING")
        )
        .scalars()
        .first()
    )
    if pending:
        return pending
    owner_role = owner_role or GATE_OWNERS.get(gate, "bid_manager")
    sla_hours = sla_hours or GATE_SLA.get(gate, 24)
    owner = (
        db.execute(select(User).where(User.role == owner_role, User.active == True))  # noqa: E712
        .scalars()
        .first()
    )
    task = GateTask(
        opportunity_id=opp.id,
        gate=gate,
        title=title[:300],
        owner_role=owner_role,
        owner_user_id=owner.id if owner else None,
        sla_hours=sla_hours,
        due_at=datetime.utcnow() + timedelta(hours=sla_hours),
        inputs_snapshot=inputs or {},
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    transition(db, opp, f"GATE{gate}", f"gate{gate}_opened", detail=title[:200])
    notifications.notify(
        db,
        "gate",
        f"Gate {gate} pending: {title[:100]}",
        f"Owner role: {owner_role} | SLA {sla_hours}h",
        severity="warning" if sla_hours <= 24 else "info",
        opportunity_id=opp.id,
    )
    return task


def decide_gate(db, task, decision, actor=None, comment="", reason_code=""):
    decision = (decision or "").upper().replace("-", "_")
    task.decision = decision
    task.comment = comment or ""
    task.reason_code = reason_code or ""
    task.decided_by = actor.id if actor else None
    task.decided_at = datetime.utcnow()
    task.status = "APPROVED" if decision in APPROVE_DECISIONS else "REJECTED"
    db.commit()

    audit.record(
        db,
        f"gate{task.gate}.decision",
        actor=actor.name if actor else "system",
        opportunity_id=task.opportunity_id,
        gate_task_id=task.id,
        detail={"decision": decision, "comment": comment, "reason_code": reason_code},
    )

    opp = db.get(Opportunity, task.opportunity_id)
    if not opp:
        return task

    if task.gate == 1:
        if decision in APPROVE_DECISIONS:
            run_analysis(db, opp)
        elif decision in REJECT_DECISIONS:
            abandon(db, opp, reason_code or "no_go", comment, actor)
        else:
            reopen(db, task, opp, "Unrecognised decision — gate reopened")
    elif task.gate == 2:
        if decision in APPROVE_DECISIONS:
            start_drafting(db, opp)
        elif decision in REJECT_DECISIONS:
            abandon(db, opp, reason_code or "not_confirmed", comment, actor)
        else:
            reopen(db, task, opp, "Unrecognised decision — gate reopened")
    elif task.gate == 3:
        if decision in APPROVE_DECISIONS:
            assemble(db, opp, actor)
        elif decision in REJECT_DECISIONS:
            request_revision(db, opp, comment, actor)
        else:
            reopen(db, task, opp, "Unrecognised decision — gate reopened")
    elif task.gate == 4:
        if decision in APPROVE_DECISIONS:
            mark_ready(db, opp, actor)
        elif decision in REJECT_DECISIONS:
            request_revision(db, opp, comment, actor)
        else:
            reopen(db, task, opp, "Unrecognised decision — gate reopened")
    elif task.gate == 5:
        if decision in APPROVE_DECISIONS:
            from app.services import submission

            submission.mark_submitted(db, opp, actor, comment)
        else:
            notifications.notify(
                db,
                "submission",
                f"Submission not confirmed: {opp.title[:90]}",
                comment or "Gate 5 closed without submission confirmation — reopen when submitted.",
                severity="warning",
                opportunity_id=opp.id,
            )
    return task


def reopen(db, task, opp, note):
    task.status = "PENDING"
    task.decision = ""
    task.decided_at = None
    db.commit()
    notifications.notify(db, "gate", f"Gate {task.gate} reopened: {task.title[:90]}", note, severity="info", opportunity_id=opp.id)


def abandon(db, opp, reason_code, comment="", actor=None):
    opp.abandoned_reason = (reason_code or "abandoned")[:200]
    transition(db, opp, "ABANDONED", "abandoned", actor=actor.name if actor else "system", detail=comment or reason_code)
    _close_pending_gates(db, opp, comment)
    notifications.notify(
        db,
        "abandoned",
        f"Abandoned: {opp.title[:90]}",
        f"{reason_code or 'abandoned'} — {comment}".strip(" —"),
        severity="info",
        opportunity_id=opp.id,
    )


def request_revision(db, opp, comment, actor=None):
    proposal = db.execute(select(Proposal).where(Proposal.opportunity_id == opp.id)).scalars().first()
    if proposal:
        proposal.status = "REVISION"
        db.commit()
    transition(db, opp, "DRAFTING", "revision_requested", actor=actor.name if actor else "system", detail=comment)
    _close_pending_gates(db, opp, comment)
    notifications.notify(
        db,
        "gate",
        f"Revision requested: {opp.title[:90]}",
        comment,
        severity="warning",
        opportunity_id=opp.id,
    )


def _close_pending_gates(db, opp, comment=""):
    pending = (
        db.execute(
            select(GateTask).where(GateTask.opportunity_id == opp.id, GateTask.status.in_(["PENDING", "OVERDUE"]))
        )
        .scalars()
        .all()
    )
    for task in pending:
        task.status = "CANCELLED"
        task.comment = comment or "Superseded"
        db.commit()


def run_analysis(db, opp):
    from app.services import documents, extractor, risk

    transition(db, opp, "DOCS_FETCHED", "gate1_go", detail="Fetching tender documents")
    documents.fetch_for_opportunity(db, opp)
    extractor.run(db, opp)
    risk.run(db, opp)
    _build_compliance(db, opp)
    transition(db, opp, "ANALYZED", "analysis_complete", detail="Requirements, risks and compliance matrix ready")
    open_gate(
        db,
        opp,
        gate=2,
        title=f"Eligibility & requirements check — {opp.title[:100]}",
        owner_role="proposal_engineer",
        sla_hours=GATE_SLA[2],
        inputs={"eligibility": _eligibility(db, opp), "requirements": _requirement_counts(db, opp)},
    )


def reanalyze(db, opp):
    from app.services import extractor, risk

    documents_result = None
    extractor_result = extractor.run(db, opp)
    risk_flags = risk.run(db, opp)
    compliance_added = _build_compliance(db, opp)
    documents_result = {"compliance_added": compliance_added, "requirements": extractor_result.get("requirements"), "risk_flags": len(risk_flags)}
    audit.record(db, "opportunity.reanalyzed", opportunity_id=opp.id, detail=documents_result)
    return documents_result


def start_drafting(db, opp):
    from app.services import drafter

    transition(db, opp, "DRAFTING", "gate2_confirmed")
    result = drafter.generate(db, opp)
    open_gate(
        db,
        opp,
        gate=3,
        title=f"Draft review — {opp.title[:110]}",
        owner_role="proposal_engineer",
        sla_hours=GATE_SLA[3],
        inputs={"sections": result.get("sections", 0), "gaps": result.get("gaps", [])},
    )


def assemble(db, opp, actor=None):
    from app.services import submission

    proposal = db.execute(select(Proposal).where(Proposal.opportunity_id == opp.id)).scalars().first()
    if proposal:
        proposal.status = "APPROVED"
        db.commit()
    transition(db, opp, "ASSEMBLY", "gate3_approved", actor=actor.name if actor else "system")
    pack = submission.build_pack(db, opp)
    open_gate(
        db,
        opp,
        gate=4,
        title=f"Final approval — {opp.title[:110]}",
        owner_role="management",
        sla_hours=GATE_SLA[4],
        inputs={"pack_files": pack.get("files", []), "checklist_open": pack.get("open", 0)},
    )


def mark_ready(db, opp, actor=None):
    from app.services import submission

    submission.prepare(db, opp)
    transition(db, opp, "READY_TO_SUBMIT", "gate4_approved", actor=actor.name if actor else "system")
    open_gate(
        db,
        opp,
        gate=5,
        title=f"Submission confirmation — {opp.title[:100]}",
        owner_role="bid_manager",
        sla_hours=GATE_SLA[5],
        inputs={"submission_mode": opp.submission_mode, "deadline": str(opp.submission_deadline)},
    )


def _build_compliance(db, opp):
    requirements = (
        db.execute(select(ExtractedRequirement).where(ExtractedRequirement.opportunity_id == opp.id))
        .scalars()
        .all()
    )
    existing = {
        (c.requirement or "")[:80]
        for c in db.execute(select(ComplianceItem).where(ComplianceItem.opportunity_id == opp.id)).scalars().all()
    }
    library = db.execute(select(LibraryDocument).where(LibraryDocument.approved == True)).scalars().all()  # noqa: E712
    added = 0
    for req in requirements:
        if (req.text or "")[:80] in existing:
            continue
        evidence_type, evidence_ref = "none", ""
        words = [w for w in (req.text or "").lower().split() if len(w) > 4][:6]
        for doc in library:
            hay = f"{doc.title} {doc.tags or ''}".lower()
            if words and sum(1 for w in words if w in hay) >= 2:
                evidence_type, evidence_ref = "library", doc.title
                break
        db.add(
            ComplianceItem(
                opportunity_id=opp.id,
                requirement=req.text,
                category=req.category,
                anchor=req.anchor,
                evidence_type=evidence_type,
                evidence_ref=evidence_ref,
                status="TBD",
                mandatory=req.mandatory,
            )
        )
        added += 1
    db.commit()
    return added


def _requirement_counts(db, opp):
    requirements = (
        db.execute(select(ExtractedRequirement).where(ExtractedRequirement.opportunity_id == opp.id))
        .scalars()
        .all()
    )
    counts = {}
    for req in requirements:
        counts[req.category] = counts.get(req.category, 0) + 1
    return counts


def _eligibility(db, opp):
    from app.models import FinancialYear, License

    from app.services.scorer import PEC_RANK

    notes = []
    pec_ok = True
    license_row = db.execute(select(License).where(License.approved == True)).scalars().first()  # noqa: E712
    company_rank = PEC_RANK.get((license_row.category or "").upper(), 0) if license_row else 0
    required = (opp.pec_category_required or "").upper()
    if required and required in PEC_RANK and company_rank < PEC_RANK[required]:
        pec_ok = False
        notes.append(f"PEC {required} required vs held {license_row.category if license_row else 'none'}")

    turnover_ok = True
    thresholds = opp.qualification_thresholds or {}
    required_turnover = thresholds.get("turnover")
    if required_turnover:
        fy = db.execute(select(FinancialYear).order_by(FinancialYear.fiscal_year.desc())).scalars().first()
        if not fy or (fy.turnover or 0) < required_turnover:
            turnover_ok = False
            notes.append(f"Turnover {required_turnover} exceeds evidence {fy.turnover if fy else 0}")

    deadline_ok = True
    if opp.submission_deadline:
        days_left = (opp.submission_deadline - datetime.utcnow()).days
        if days_left < 0:
            deadline_ok = False
            notes.append("Deadline has passed")
        elif days_left < 7:
            notes.append(f"Only {days_left} day(s) to deadline")
    return {
        "pec_ok": pec_ok,
        "turnover_ok": turnover_ok,
        "deadline_ok": deadline_ok,
        "notes": notes,
    }
