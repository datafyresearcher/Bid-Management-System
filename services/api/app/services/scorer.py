from datetime import datetime, timedelta

from sqlalchemy import select

from app.config import settings
from app.llm import provider as llm
from app.llm import prompts
from app.models import CompanyProfile, GateTask, License, ProjectExperience, Score
from app.services import audit, notifications
from app.services.utils import normalize_key, sanitize_inline, utcnow

PEC_RANK = {"C-A": 5, "NO LIMIT": 5, "C-B": 4, "C-1": 3, "C-2": 2, "C-3": 1, "C-4": 0}

SCOPE_KEYWORDS = [
    "substation", "grid station", "transmission line", "tower", "220kv", "132kv", "500kv",
    "conductor", "stringing", "foundation", "control house", "bus bar", "bay",
]

BUYER_ALIASES = [
    ("ntdc", ["national transmission", "ntdc"]),
    ("wapda", ["wapda", "water and power"]),
    ("hesco", ["hesco", "hyderabad electric"]),
    ("gepco", ["gepco", "gujranwala electric"]),
    ("lesco", ["lesco", "lahore electric"]),
    ("mepco", ["mepco", "multan electric"]),
]


class ScoringContext:
    """The company's own record, read once for a whole batch of tenders.

    The profile, the licence, the track record and the latest financial year
    are the same for every tender that is scored together. Reading them once
    for the batch instead of once per tender is the difference between a
    capture that finishes in seconds and one that spends all of its time
    waiting for the database.
    """

    def __init__(self, company, license_row, projects, latest_fy):
        self.company = company
        self.license = license_row
        self.projects = projects
        self.latest_fy = latest_fy


def load_context(db) -> ScoringContext:
    from sqlalchemy import desc

    from app.models import FinancialYear

    company = db.execute(select(CompanyProfile)).scalars().first()
    license_row = db.execute(select(License).where(License.approved == True)).scalars().first()  # noqa: E712
    projects = db.execute(select(ProjectExperience).where(ProjectExperience.approved == True)).scalars().all()  # noqa: E712
    latest_fy = db.execute(select(FinancialYear).order_by(desc(FinancialYear.fiscal_year))).scalars().first()
    return ScoringContext(company, license_row, projects, latest_fy)


def run(db, opp, ctx=None, deadline=None, narrate=True) -> Score:
    """Score one tender.

    ``deadline`` is an absolute ``time.monotonic()`` value handed to the model
    call so a slow answer cannot hold the request open past its budget. The
    score itself never depends on the model: only the narrative does.

    ``narrate=False`` skips the model entirely and writes the deterministic
    rationale. That is the difference between a tender that is scored and a
    tender that is only waiting for a slow model to answer it, and on a
    free-tier model the difference is large.
    """
    if ctx is None:
        ctx = load_context(db)
    company = ctx.company
    license_row = ctx.license
    projects = ctx.projects

    failures = []
    warnings = []

    if company and company.blacklisted:
        failures.append({"gate": "blacklist", "reason": "Company marked blacklisted/debarred"})

    company_rank = 0
    if license_row:
        company_rank = PEC_RANK.get((license_row.category or "").upper(), 3)
    required_category = (opp.pec_category_required or "").strip().upper()
    if required_category and required_category in PEC_RANK and company_rank < PEC_RANK[required_category]:
        failures.append(
            {
                "gate": "pec_category",
                "reason": f"Required PEC {required_category} exceeds company licence {license_row.category if license_row else 'none'}",
            }
        )

    if opp.specialization and license_row and license_row.fields:
        fields_text = " ".join(license_row.fields).lower()
        spec = opp.specialization.lower()
        if not any(w in fields_text for w in spec.split() if len(w) > 3):
            warnings.append({"gate": "specialization", "reason": f"Specialization '{opp.specialization}' not evidenced in licence fields"})

    if opp.submission_deadline:
        days_left = (opp.submission_deadline - utcnow()).days
        if days_left < settings.min_days_to_bid:
            failures.append({"gate": "deadline", "reason": f"Only {days_left} day(s) to deadline"})

    if opp.tender_type in ("Auction-Disposal",):
        failures.append({"gate": "strategy", "reason": "Auction/disposal is outside strategy scope"})

    subscores = _subscores(opp, projects, ctx.latest_fy)
    total = round(sum(v["score"] for v in subscores.values()), 1)
    passed = len(failures) == 0

    rationale = _rationale(
        db, opp, subscores, total, failures, warnings, projects,
        deadline=deadline, narrate=narrate,
    )

    score = Score(
        opportunity_id=opp.id,
        total=total,
        subscores=subscores,
        hard_gates={"passed": passed, "failures": failures, "warnings": warnings},
        rationale=rationale,
        provider=llm.get_provider().name,
        prompt_version=prompts.SCORE_RATIONALE_V1["version"],
    )
    db.add(score)

    opp.score_total = total
    opp.hard_gate_result = {"passed": passed, "failures": failures, "warnings": warnings}
    opp.ai_rationale = rationale
    opp.ai_confidence = _confidence(opp, projects, subscores, warnings)
    db.commit()

    audit.record(
        db,
        "opportunity.scored",
        opportunity_id=opp.id,
        detail={"total": total, "passed": passed, "failures": failures},
    )

    from app.services import workflow

    if not passed:
        workflow.transition(db, opp, "SCREENED_OUT", "hard_gate_failed", detail="; ".join(f["reason"] for f in failures))
        notifications.notify(
            db,
            "screen_out",
            f"Screened out: {opp.title[:80]}",
            "; ".join(f["reason"] for f in failures),
            severity="info",
            opportunity_id=opp.id,
        )
    elif total < settings.score_archive_threshold:
        workflow.transition(db, opp, "AUTO_ARCHIVED", "below_threshold", detail=f"score {total}")
    else:
        # Re-scoring a bid that is already sitting in a gate must not pull it
        # back out of that gate. Keep the workflow state consistent with the
        # gate that is actually open.
        pending_gate = (
            db.execute(
                select(GateTask)
                .where(GateTask.opportunity_id == opp.id, GateTask.status.in_(["PENDING", "OVERDUE"]))
            )
            .scalars()
            .first()
        )
        if pending_gate:
            if opp.state != f"GATE{pending_gate.gate}":
                workflow.transition(db, opp, f"GATE{pending_gate.gate}", "rescored", detail=f"score {total}")
            # The snapshot is what the reviewer reads, so it has to describe
            # the score that is actually in front of them. Leaving the old
            # one behind would put a stale rationale next to a fresh score.
            pending_gate.inputs_snapshot = {
                "score": total,
                "subscores": subscores,
                "rationale": rationale,
                "failures": failures,
            }
            db.commit()
        else:
            workflow.transition(db, opp, "SCORED", "scoring_complete", detail=f"score {total}")
        workflow.open_gate(
            db,
            opp,
            gate=1,
            title=f"Go/No-Go — {opp.title[:120]}",
            owner_role="bid_manager",
            sla_hours=24 if not _urgent(opp) else 4,
            inputs={"score": total, "subscores": subscores, "rationale": rationale, "failures": failures},
        )
    return score


def _urgent(opp) -> bool:
    if not opp.submission_deadline:
        return False
    return (opp.submission_deadline - utcnow()) < timedelta(days=7)


def _subscores(opp, projects, latest_fy=None):
    text = normalize_key(f"{opp.title} {opp.description}")
    category = opp.category_internal

    category_projects = [p for p in projects if (p.category or "") == category]
    keyword_hits = sum(1 for k in SCOPE_KEYWORDS if k in text)
    keyword_ratio = min(1.0, keyword_hits / 6)
    scope = 30 * (0.55 * (1.0 if category_projects else 0.25) + 0.45 * keyword_ratio)

    buyer_key = None
    buyer_norm = normalize_key(opp.buyer_name)
    for canonical, aliases in BUYER_ALIASES:
        if any(a in buyer_norm for a in aliases):
            buyer_key = canonical
            break
    buyer_aliases = next((aliases for canonical, aliases in BUYER_ALIASES if canonical == buyer_key), [])
    buyer_projects = [
        p for p in projects if any(a in normalize_key(p.client) for a in buyer_aliases)
    ]
    n = len(buyer_projects)
    buyer = 15 if n >= 3 else 10 if n >= 1 else 4

    geography = 8
    if opp.area and any((p.area or "") == opp.area for p in projects):
        geography = 10

    value = 7
    if opp.estimated_value:
        fy = latest_fy
        turnover = fy.turnover if fy else None
        if turnover:
            amount = opp.estimated_value if opp.currency == "PKR" else opp.estimated_value * 280
            ratio = amount / turnover
            value = 15 if 0.05 <= ratio <= 0.5 else 10 if ratio <= 1.0 else 6 if ratio <= 2.0 else 3

    margin = 6
    thresholds = opp.qualification_thresholds or {}
    if thresholds:
        margin = 15
        required_similar = thresholds.get("similar_work_count")
        if required_similar:
            available = len([p for p in projects if (p.category or "") == category])
            if available < required_similar:
                margin = max(3, margin - 6 * (required_similar - available))
        required_turnover = thresholds.get("turnover")
        if required_turnover:
            fy = latest_fy
            if not fy or fy.turnover < required_turnover:
                margin = max(3, margin - 6)
    else:
        margin = 9 if category_projects else 6

    strategy = 9
    if opp.tender_type == "Works":
        strategy += 2
    if any(k in text for k in ["adb", "world bank", "donor", "loan"]):
        strategy += 3
    if opp.procurement_regime == "two-stage-two-envelope":
        strategy += 1
    strategy = min(15, strategy)

    return {
        "scope": {"score": round(scope, 1), "max": 30},
        "buyer": {"score": buyer, "max": 15},
        "value": {"score": value, "max": 15},
        "geography": {"score": geography, "max": 10},
        "margin": {"score": margin, "max": 15},
        "strategy": {"score": strategy, "max": 15},
    }


def _latest_fy(db):
    from sqlalchemy import desc

    from app.models import FinancialYear

    return db.execute(select(FinancialYear).order_by(desc(FinancialYear.fiscal_year))).scalars().first()


def _rationale(db, opp, subscores, total, failures, warnings, projects, deadline=None, narrate=True) -> str:
    """Write the human-facing rationale for a score.

    The score itself is always deterministic. This function only narrates it.
    Tender-derived text is attacker-controlled, so it is sanitised and fenced
    before it reaches the model.
    """
    provider = llm.get_provider()
    if provider.enabled and narrate:
        summary = (
            f"Tender: {sanitize_inline(opp.title, 200)}\n"
            f"Buyer: {sanitize_inline(opp.buyer_name, 120)}\n"
            f"Category: {opp.category_internal}\n"
            f"Value: {opp.estimated_value} {opp.currency}\n"
            f"Deadline: {opp.submission_deadline}\n"
            f"Subscores: {subscores}\n"
            f"Total: {total}\n"
            f"Warnings: {warnings}\n"
            f"Company projects: {[(p.contract_no, p.client, p.category) for p in projects[:10]]}\n"
            f"{prompts.fence_untrusted(f'{opp.title} {opp.description}', 'TENDER NOTICE')}"
        )
        result = provider.chat(
            prompts.SCORE_RATIONALE_V1["system"],
            prompts.fence_untrusted(summary, "SCORING INPUT"),
            max_tokens=settings.llm_score_max_tokens,
            task="score",
            deadline=deadline,
        )
        llm.record_metric(db, "score", result, opportunity_id=opp.id)
        if result.valid and result.text.strip():
            return result.text.strip()

    label = "Strong" if total >= 70 else "Moderate" if total >= 55 else "Weak"
    parts = [
        f"{label} fit ({total}/100).",
        f"Scope match {subscores['scope']['score']}/30 against {len(projects)} approved projects in KB.",
        f"Buyer familiarity {subscores['buyer']['score']}/15 with {opp.buyer_name or 'this buyer'}.",
    ]
    if subscores["margin"]["score"] < 9:
        parts.append("Qualification margin is thin — verify experience certificates and turnover before committing.")
    if warnings:
        parts.append("Warnings: " + "; ".join(w["reason"] for w in warnings[:2]) + ".")
    return " ".join(parts)


def _confidence(opp, projects, subscores, warnings) -> float:
    """How much of this score rests on real evidence rather than absence.

    A high score produced by empty knowledge-base rows is not a reliable
    signal, so the bid room shows this alongside the number.
    """
    signals = [
        bool(projects),
        bool(opp.buyer_name),
        bool(opp.submission_deadline),
        bool(opp.estimated_value),
        bool(opp.category_internal and opp.category_internal != "General"),
        bool(opp.qualification_thresholds),
        subscores.get("margin", {}).get("score", 0) >= 9,
        subscores.get("scope", {}).get("score", 0) >= 18,
    ]
    base = sum(1 for s in signals if s) / len(signals)
    penalty = 0.05 * len(warnings)
    return round(max(0.0, min(1.0, base - penalty)), 3)


def override_screening(db, opp, actor: str, comment: str):
    from app.services import workflow

    audit.record(
        db,
        "screening.override",
        actor=actor,
        opportunity_id=opp.id,
        detail={"comment": comment, "previous": opp.hard_gate_result},
    )
    workflow.transition(db, opp, "SCORED", "human_override", actor=actor, detail=comment)
    workflow.open_gate(
        db,
        opp,
        gate=1,
        title=f"Go/No-Go (override) — {opp.title[:110]}",
        owner_role="bid_manager",
        sla_hours=24,
        inputs={"override": True, "comment": comment, "score": opp.score_total},
    )
