from sqlalchemy import select

from app.llm import provider as llm
from app.llm import prompts
from app.models import (
    CompanyCertificate,
    CompanyProfile,
    EquipmentItem,
    ExtractedRequirement,
    FinancialYear,
    LibraryDocument,
    License,
    Personnel,
    ProjectExperience,
    Proposal,
    ProposalSection,
)
from app.services import audit

SECTION_SPECS = [
    ("cover_letter", "Cover Letter"),
    ("company_profile", "Company Profile"),
    ("technical_approach", "Technical Approach"),
    ("methodology", "Methodology & Work Plan"),
    ("personnel", "Key Personnel"),
    ("equipment", "Plant & Equipment"),
    ("past_performance", "Past Performance"),
    ("compliance_statement", "Compliance Statement"),
    ("commercial_notes", "Commercial Notes"),
]

GAPS = []


def _kb(db):
    return {
        "company": db.execute(select(CompanyProfile)).scalars().first(),
        "license": db.execute(select(License).where(License.approved == True)).scalars().first(),  # noqa: E712
        "fys": db.execute(select(FinancialYear).where(FinancialYear.approved == True)).scalars().all(),  # noqa: E712
        "projects": db.execute(select(ProjectExperience).where(ProjectExperience.approved == True)).scalars().all(),  # noqa: E712
        "personnel": db.execute(select(Personnel).where(Personnel.approved == True)).scalars().all(),  # noqa: E712
        "equipment": db.execute(select(EquipmentItem).where(EquipmentItem.approved == True)).scalars().all(),  # noqa: E712
        "certificates": db.execute(select(CompanyCertificate).where(CompanyCertificate.approved == True)).scalars().all(),  # noqa: E712
        "library": db.execute(select(LibraryDocument).where(LibraryDocument.approved == True)).scalars().all(),  # noqa: E712
    }


def _requirements(db, opp):
    return (
        db.execute(select(ExtractedRequirement).where(ExtractedRequirement.opportunity_id == opp.id))
        .scalars()
        .all()
    )


def _deterministic_sections(opp, kb, requirements, gaps):
    company = kb["company"]
    license_row = kb["license"]
    projects = kb["projects"]
    personnel = kb["personnel"]
    equipment = kb["equipment"]
    certificates = kb["certificates"]
    fys = kb["fys"]

    citations = []
    sections = {}

    company_name = company.name if company else "The Company"
    sections["cover_letter"] = (
        f"To: {opp.buyer_name or 'The Employer'}\n"
        f"Subject: {opp.title}\n"
        f"Reference: {opp.buyer_ref or 'N/A'}\n\n"
        f"{company_name} is pleased to submit its proposal in response to the captioned tender. "
        f"We confirm our PEC licence {license_row.category if license_row else '[GAP: PEC licence not in KB]'} "
        f"(No. {license_row.number if license_row else 'N/A'}) and our acceptance of the tender terms.\n\n"
        f"Bid security of PKR {opp.bid_security_amount or '[GAP: bid security amount not extracted]'} "
        f"is furnished as {opp.bid_security_form or '[GAP: bid security form not extracted]'}."
    )
    if company:
        citations.append({"type": "company", "ref": company.name})
    if license_row:
        citations.append({"type": "license", "ref": license_row.number})

    if company:
        latest_fy = fys[-1] if fys else None
        sections["company_profile"] = (
            f"{company.legal_name or company.name} — {company.summary}\n"
            f"Registration: SECP {company.secp or 'N/A'}, NTN {company.ntn or 'N/A'} ({company.tax_status}).\n"
            f"PEC Licence: {license_row.category if license_row else '[GAP: licence]'} "
            f"({', '.join(license_row.fields or []) if license_row and license_row.fields else 'fields N/A'}).\n"
            f"Latest audited turnover: PKR {int(latest_fy.turnover):,} ({latest_fy.fiscal_year}) "
            f"per {latest_fy.auditor or 'auditor N/A'}."
            if latest_fy
            else f"{company.legal_name or company.name} — {company.summary}\n[GAP: audited financials not in KB]"
        )
        citations.append({"type": "company", "ref": "profile"})
        if latest_fy:
            citations.append({"type": "financial", "ref": latest_fy.fiscal_year})
    else:
        sections["company_profile"] = "[GAP: company profile not loaded in KB]"
        gaps.append("company_profile")

    scope_reqs = [r.text for r in requirements if r.category in ("technical", "compliance")][:6]
    approach_lines = [
        "Our understanding of the scope: " + (opp.description[:400] or opp.title),
        "Execution strategy: mobilisation of our own tower/stringing resources, NTP-driven schedule with monthly progress monitoring, "
        "and compliance with the employer's QA/QC requirements.",
    ]
    if scope_reqs:
        approach_lines.append("Key scope requirements tracked from tender documents:")
        approach_lines.extend(f"- {s[:220]}" for s in scope_reqs)
    sections["technical_approach"] = "\n".join(approach_lines)

    method_lines = [
        "Work plan: survey & design review, procurement of materials, foundation works, tower erection, stringing, testing & commissioning.",
        "Resource deployment aligns with the submitted personnel and equipment schedules; site organisation includes a project manager, "
        "QA/QC engineer and HSE officer.",
        "Interface management with the employer and third parties is handled through weekly coordination meetings and formal correspondence.",
    ]
    sections["methodology"] = "\n".join(method_lines)

    if personnel:
        lines = [f"- {p.name} — {p.position} ({p.years_experience} yrs, PEC {p.pec_reg_no or 'N/A'})" for p in personnel[:8]]
        sections["personnel"] = "Key personnel proposed:\n" + "\n".join(lines)
        citations.extend({"type": "personnel", "ref": p.name} for p in personnel[:5])
    else:
        sections["personnel"] = "[GAP: no approved personnel in KB]"
        gaps.append("personnel")

    if equipment:
        lines = [f"- {e.name} ({e.ownership}, {e.quantity} unit(s), {e.condition})" for e in equipment[:10]]
        sections["equipment"] = "Plant & equipment available:\n" + "\n".join(lines)
        citations.extend({"type": "equipment", "ref": e.name} for e in equipment[:5])
    else:
        sections["equipment"] = "[GAP: no approved equipment in KB]"
        gaps.append("equipment")

    if projects:
        lines = []
        for p in projects[:8]:
            client = p.client or "Client"
            lines.append(f"- {p.contract_no or 'Contract'} — {client} ({p.category or 'scope'}), PKR {int(p.value or 0):,}, {p.start_date}-{p.end_date}, role {p.role}")
        sections["past_performance"] = "Relevant completed contracts:\n" + "\n".join(lines)
        citations.extend({"type": "project", "ref": p.contract_no} for p in projects[:6])
    else:
        sections["past_performance"] = "[GAP: no approved project experience in KB]"
        gaps.append("past_performance")

    cert_lines = [f"- {c.name} ({c.issuer or 'issuer'}) {c.number or ''}" for c in certificates[:8]]
    matrix = [f"- [{r.category}] {r.text[:200]}" for r in requirements[:30]]
    sections["compliance_statement"] = (
        "Compliance commitments and certificates:\n"
        + ("\n".join(cert_lines) if cert_lines else "[GAP: certificates not in KB]")
        + "\n\nRequirements register (complied / noted):\n"
        + ("\n".join(matrix) if matrix else "- To be completed after document analysis")
    )
    if not certificates:
        gaps.append("certificates")

    commercial = [
        f"Bid security: PKR {opp.bid_security_amount or '[verify]'} ({opp.bid_security_form or 'form TBD'})",
        f"Tender fee: PKR {opp.tender_fee or '[verify]'}",
        "Prices: as per BOQ submitted separately (no price adjustment assumptions noted unless clarified).",
        "Validity: as required by the tender; extensions handled via formal request.",
    ]
    sections["commercial_notes"] = "\n".join(commercial)
    return sections, citations


def generate(db, opp):
    kb = _kb(db)
    requirements = _requirements(db, opp)
    gaps = []
    sections, citations = _deterministic_sections(opp, kb, requirements, gaps)

    provider = llm.get_provider()
    llm_used = False
    if provider.enabled:
        for key, title in SECTION_SPECS:
            base = sections.get(key, "")
            if not base or base.startswith("[GAP"):
                continue
            prompt_input = (
                f"Tender: {opp.title}\nBuyer: {opp.buyer_name}\nSection: {title}\n"
                f"Grounding material:\n{base}\n\nRequirements context:\n"
                + "\n".join(r.text[:200] for r in requirements[:12])
            )
            result = provider.chat(prompts.DRAFT_V1["system"], prompts.fence_untrusted(prompt_input), max_tokens=700)
            llm.record_metric(db, "draft", result, opportunity_id=opp.id)
            if result.valid and result.text.strip():
                sections[key] = result.text.strip()
                llm_used = True

    proposal = db.execute(select(Proposal).where(Proposal.opportunity_id == opp.id)).scalars().first()
    if not proposal:
        proposal = Proposal(opportunity_id=opp.id, status="DRAFT")
        db.add(proposal)
        db.commit()
        db.refresh(proposal)

    existing = {s.key: s for s in proposal.sections}
    stored = 0
    for index, (key, title) in enumerate(SECTION_SPECS):
        content = sections.get(key, "")
        status = "GAPS" if "[[GAP" in content or "[GAP" in content else "DRAFTED"
        section = existing.get(key)
        if section:
            section.content = content
            section.status = status
            section.citations = citations if key in ("company_profile", "personnel", "equipment", "past_performance") else []
            section.order_index = index
        else:
            db.add(
                ProposalSection(
                    proposal_id=proposal.id,
                    key=key,
                    title=title,
                    content=content,
                    status=status,
                    citations=citations if key in ("company_profile", "personnel", "equipment", "past_performance") else [],
                    order_index=index,
                )
            )
        stored += 1
    proposal.status = "DRAFT"
    db.commit()
    audit.record(db, "proposal.generated", opportunity_id=opp.id, detail={"sections": stored, "gaps": gaps, "llm": llm_used})
    return {"sections": stored, "gaps": gaps}
