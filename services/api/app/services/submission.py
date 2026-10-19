import csv
from datetime import datetime
from sqlalchemy import select

from app.config import storage_path
from app.models import (
    CompanyProfile,
    ComplianceItem,
    Document,
    License,
    Opportunity,
    Outcome,
    Proposal,
    SubmissionRecord,
)
from app.services import audit, notifications


def _record(db, opp) -> SubmissionRecord:
    sr = db.execute(select(SubmissionRecord).where(SubmissionRecord.opportunity_id == opp.id)).scalars().first()
    if not sr:
        sr = SubmissionRecord(opportunity_id=opp.id, status="DRAFT")
        db.add(sr)
        db.commit()
        db.refresh(sr)
    return sr


def _base_checklist(db, opp):
    items = []
    docs = db.execute(select(Document).where(Document.opportunity_id == opp.id)).scalars().all()
    items.append(
        {
            "item": "Tender documents downloaded and reviewed",
            "category": "documents",
            "mandatory": True,
            "status": "ready" if docs else "open",
            "owner": "proposal_engineer",
        }
    )
    items.append(
        {
            "item": f"Bid security arranged (PKR {opp.bid_security_amount or 'amount TBD'})",
            "category": "financial",
            "mandatory": True,
            "status": "open",
            "owner": "finance",
        }
    )
    items.append(
        {
            "item": f"Tender fee paid (PKR {opp.tender_fee or 'amount TBD'}) — portal challan if applicable",
            "category": "financial",
            "mandatory": True,
            "status": "open",
            "owner": "finance",
        }
    )
    items.append(
        {
            "item": "Portal registration and DSC/e-token validity confirmed",
            "category": "portal",
            "mandatory": opp.submission_mode == "e-submission",
            "status": "open",
            "owner": "bid_manager",
        }
    )
    items.append(
        {
            "item": "Signed forms, affidavits, undertakings and power of attorney",
            "category": "forms",
            "mandatory": True,
            "status": "open",
            "owner": "proposal_engineer",
        }
    )
    items.append(
        {
            "item": "Final priced BOQ / bill of quantities sealed and signed",
            "category": "commercial",
            "mandatory": True,
            "status": "open",
            "owner": "bid_manager",
        }
    )
    compliance = (
        db.execute(select(ComplianceItem).where(ComplianceItem.opportunity_id == opp.id)).scalars().all()
    )
    for c in compliance:
        if c.mandatory:
            items.append(
                {
                    "item": c.requirement[:180],
                    "category": f"requirement:{c.category}",
                    "mandatory": True,
                    "status": "ready" if c.status in ("COMPLIED", "WAIVED") else "open",
                    "owner": c.owner or "proposal_engineer",
                }
            )
    return items


def build_pack(db, opp):
    folder = storage_path() / "exports" / str(opp.id)
    folder.mkdir(parents=True, exist_ok=True)
    files = []

    proposal = db.execute(select(Proposal).where(Proposal.opportunity_id == opp.id)).scalars().first()
    if proposal:
        lines = [f"# {opp.title}", f"Buyer: {opp.buyer_name}", f"Reference: {opp.buyer_ref}", ""]
        for section in sorted(proposal.sections, key=lambda s: s.order_index):
            lines.append(f"## {section.title}")
            lines.append(section.content or "")
            if section.citations:
                lines.append("Citations: " + ", ".join(f"{c['type']}:{c['ref']}" for c in section.citations))
            lines.append("")
        pack_path = folder / "proposal_pack.md"
        pack_path.write_text("\n".join(lines), encoding="utf-8")
        files.append(pack_path.name)

    csv_path = folder / "compliance_matrix.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["requirement", "category", "mandatory", "status", "evidence_type", "evidence_ref", "owner"])
        for c in db.execute(select(ComplianceItem).where(ComplianceItem.opportunity_id == opp.id)).scalars().all():
            writer.writerow([c.requirement[:300], c.category, c.mandatory, c.status, c.evidence_type, c.evidence_ref, c.owner])
    files.append(csv_path.name)

    docs = db.execute(select(Document).where(Document.opportunity_id == opp.id)).scalars().all()
    docs_path = folder / "documents_index.txt"
    docs_path.write_text(
        "\n".join(f"- {d.filename} [{d.doc_type}] parsed={d.parsed}" for d in docs) or "No documents",
        encoding="utf-8",
    )
    files.append(docs_path.name)

    sr = _record(db, opp)
    sr.checklist = _base_checklist(db, opp)
    sr.pack_files = files
    sr.status = "PACK_BUILT"
    db.commit()
    open_items = sum(1 for i in sr.checklist if i["status"] == "open")
    audit.record(db, "submission.pack_built", opportunity_id=opp.id, detail={"files": files, "open_items": open_items})
    return {"files": files, "open": open_items}


def prepare(db, opp):
    sr = _record(db, opp)
    if sr.status in ("DRAFT", "PACK_BUILT"):
        build_pack(db, opp)
        sr = _record(db, opp)
    sr.status = "READY"
    sr.portal_note = (
        f"Submission mode: {opp.submission_mode}. Print the pack, arrange bid security instrument and fee challan, "
        f"upload documents to the portal before the deadline {opp.submission_deadline}. "
        "Keep the submission receipt / stamped copy as proof."
    )
    db.commit()
    audit.record(db, "submission.ready", opportunity_id=opp.id)
    notifications.notify(
        db,
        "submission",
        f"Ready to submit: {opp.title[:90]}",
        f"Mode: {opp.submission_mode}; deadline {opp.submission_deadline}",
        severity="warning",
        opportunity_id=opp.id,
    )
    return sr


def mark_submitted(db, opp, actor=None, comment=""):
    from app.services import workflow

    sr = _record(db, opp)
    sr.status = "SUBMITTED"
    sr.submitted_at = datetime.utcnow()
    if comment:
        sr.portal_note = (sr.portal_note + "\n" + comment).strip()
    db.commit()
    workflow.transition(db, opp, "SUBMITTED", "submission_confirmed", actor=actor.name if actor else "system", detail=comment)
    audit.record(db, "submission.confirmed", actor=actor.name if actor else "system", opportunity_id=opp.id, detail={"comment": comment})
    notifications.notify(
        db,
        "submission",
        f"Submitted: {opp.title[:90]}",
        "Outcome watch started — record result after opening.",
        severity="info",
        opportunity_id=opp.id,
    )
    return sr


def record_outcome(db, opp, result, reason_code="", comment="", competitor_note="", award_value=None, actor=None):
    from app.services import workflow

    result = result.upper()
    outcome = db.execute(select(Outcome).where(Outcome.opportunity_id == opp.id)).scalars().first()
    if not outcome:
        outcome = Outcome(opportunity_id=opp.id, result=result)
        db.add(outcome)
    outcome.result = result
    outcome.reason_code = reason_code
    outcome.comment = comment
    outcome.competitor_note = competitor_note
    outcome.award_value = award_value
    outcome.recorded_by = actor.id if actor else None
    db.commit()

    workflow.transition(db, opp, result, "outcome_recorded", actor=actor.name if actor else "system", detail=comment or reason_code)
    audit.record(db, "outcome.recorded", actor=actor.name if actor else "system", opportunity_id=opp.id, detail={"result": result, "reason": reason_code})
    notifications.notify(
        db,
        "outcome",
        f"Outcome {result}: {opp.title[:90]}",
        comment or reason_code,
        severity="info",
        opportunity_id=opp.id,
    )
    return outcome


def kb_gaps_summary(db):
    company = db.execute(select(CompanyProfile)).scalars().first()
    license_row = db.execute(select(License).where(License.approved == True)).scalars().first()  # noqa: E712
    gaps = []
    if not company:
        gaps.append("company profile")
    if not license_row:
        gaps.append("approved PEC licence")
    return gaps
