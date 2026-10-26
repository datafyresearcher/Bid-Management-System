"""AI quality and outcome feedback.

This is the loop that was missing: recorded bid outcomes are joined back to the
score that predicted them, so you can see whether the scoring model actually
separates winning bids from losing ones — and which knowledge-base gaps are
costing you work.

Nothing here is a vanity metric. Each number answers an operational question:

* ``llm_by_task``          — is the model healthy, fast, and returning valid output?
* ``score_band_performance`` — does a higher score actually mean more wins?
* ``calibration``          — are won and lost bids scored as differently as they behave?
* ``override_rate``        — how often do humans disagree with the screening?
* ``extraction_grades``    — how much of the analysis rests on missing evidence?
* ``knowledge_gaps``       — which KB artifacts are missing from real proposals?
"""

from sqlalchemy import func, select

from app.llm import provider as llm
from app.models import (
    AIMetric,
    DecisionAudit,
    ExtractedRequirement,
    GateTask,
    Opportunity,
    Outcome,
    ProposalSection,
    Score,
)

SCORE_BANDS = [(0, 40, "<40"), (40, 55, "40-54"), (55, 70, "55-69"), (70, 100, "70+")]


def _bucket(total):
    for low, high, label in SCORE_BANDS:
        if low <= total < high or (high == 100 and total <= 100):
            return label
    return "unknown"


def summary(db) -> dict:
    from datetime import timedelta

    from app.config import settings
    from app.services.utils import utcnow

    by_task = {}
    # Model quality is a question about the recent past — how the calls made
    # lately have behaved. Reading the whole history answers a different
    # question at a cost that grows forever: on a database over the network,
    # a year of scans is a query that does not come back inside a request.
    metrics = (
        db.execute(
            select(AIMetric).where(
                AIMetric.created_at >= utcnow() - timedelta(days=settings.ai_metrics_window_days)
            )
        )
        .scalars()
        .all()
    )
    for m in metrics:
        bucket = by_task.setdefault(
            m.task,
            {
                "calls": 0, "invalid": 0, "tokens": 0, "latency_ms": 0,
                "simulated": 0, "cached": 0, "errors": 0,
            },
        )
        bucket["calls"] += 1
        bucket["invalid"] += 0 if m.output_valid else 1
        bucket["tokens"] += m.tokens_estimate or 0
        bucket["latency_ms"] += m.latency_ms or 0
        bucket["simulated"] += 1 if m.simulated else 0
        bucket["cached"] += 1 if m.cached else 0
        bucket["errors"] += 1 if (m.error or "") else 0
    for bucket in by_task.values():
        bucket["avg_latency_ms"] = round(bucket["latency_ms"] / bucket["calls"], 1) if bucket["calls"] else 0
        bucket["valid_rate"] = round((bucket["calls"] - bucket["invalid"]) / bucket["calls"], 3) if bucket["calls"] else 0

    # Which model actually answered. A router that picks the model per call —
    # OpenRouter's free router does — makes "openrouter/free" a name for a
    # queue of models rather than a model at all, and the only way to see what
    # is really serving the traffic is to count the answers.
    by_model = {}
    for m in metrics:
        if m.simulated:
            continue
        entry = by_model.setdefault(
            m.model or "unknown",
            {"calls": 0, "invalid": 0, "tokens": 0, "latency_ms": 0, "errors": 0},
        )
        entry["calls"] += 1
        entry["invalid"] += 0 if m.output_valid else 1
        entry["tokens"] += m.tokens_estimate or 0
        entry["latency_ms"] += m.latency_ms or 0
        entry["errors"] += 1 if (m.error or "") else 0
    for entry in by_model.values():
        entry["avg_latency_ms"] = round(entry["latency_ms"] / entry["calls"], 1) if entry["calls"] else 0
        entry["valid_rate"] = round((entry["calls"] - entry["invalid"]) / entry["calls"], 3) if entry["calls"] else 0
    by_model = dict(sorted(by_model.items(), key=lambda kv: -kv[1]["calls"]))

    score_count = db.execute(select(func.count(Score.id))).scalar() or 0
    override_count = (
        db.execute(select(func.count(DecisionAudit.id)).where(DecisionAudit.action == "screening.override")).scalar() or 0
    )
    gate_rows = db.execute(select(GateTask.decision, func.count(GateTask.id)).group_by(GateTask.decision)).all()
    gate_decisions = {row[0] or "PENDING": row[1] for row in gate_rows}
    returned = sum(v for k, v in gate_decisions.items() if k in ("RETURNED", "NO_GO", "NOT_CONFIRMED"))
    approved = sum(v for k, v in gate_decisions.items() if k in ("GO", "CONFIRMED", "APPROVED", "SUBMITTED"))

    return {
        "llm_by_task": by_task,
        "llm_by_model": by_model,
        "provider": llm.provider_status(),
        "scores_total": score_count,
        "screening_overrides": override_count,
        "override_rate": round(override_count / score_count, 3) if score_count else 0,
        "gate_decisions": gate_decisions,
        "gate_returns": returned,
        "gate_approvals": approved,
        "gate_approval_rate": round(approved / (approved + returned), 3) if (approved + returned) else 0,
        **outcome_feedback(db),
        **extraction_quality(db),
        **knowledge_gaps(db),
    }


def outcome_feedback(db) -> dict:
    """Join recorded outcomes back to the score that predicted them."""
    rows = db.execute(
        select(Outcome.result, Outcome.reason_code, Opportunity.score_total, Opportunity.id)
        .join(Opportunity, Opportunity.id == Outcome.opportunity_id)
    ).all()

    result = {
        "outcomes_total": len(rows),
        "outcomes_won": 0,
        "outcomes_lost": 0,
        "outcomes_rejected": 0,
        "win_rate": 0.0,
        "score_band_performance": [],
        "calibration": {},
        "loss_reasons": [],
    }
    if not rows:
        return result

    won_scores, lost_scores = [], []
    bands = {}
    reasons = {}
    for outcome_result, reason_code, score_total, opp_id in rows:
        outcome_result = (outcome_result or "").upper()
        score = float(score_total or 0)
        if outcome_result == "WON":
            result["outcomes_won"] += 1
            won_scores.append(score)
        elif outcome_result == "LOST":
            result["outcomes_lost"] += 1
            lost_scores.append(score)
        elif outcome_result == "REJECTED":
            result["outcomes_rejected"] += 1
        label = _bucket(score)
        entry = bands.setdefault(label, {"band": label, "wins": 0, "losses": 0, "decided": 0})
        entry["decided"] += 1
        if outcome_result == "WON":
            entry["wins"] += 1
        elif outcome_result == "LOST":
            entry["losses"] += 1
        if outcome_result in ("LOST", "REJECTED") and reason_code:
            reasons[reason_code] = reasons.get(reason_code, 0) + 1

    decided = result["outcomes_won"] + result["outcomes_lost"]
    result["win_rate"] = round(result["outcomes_won"] / decided, 3) if decided else 0.0

    ordered = {label: bands[label] for _, _, label in SCORE_BANDS if label in bands}
    for entry in ordered.values():
        entry["win_rate"] = round(entry["wins"] / entry["decided"], 3) if entry["decided"] else 0.0
    result["score_band_performance"] = list(ordered.values())

    if won_scores or lost_scores:
        result["calibration"] = {
            "avg_score_won": round(sum(won_scores) / len(won_scores), 1) if won_scores else None,
            "avg_score_lost": round(sum(lost_scores) / len(lost_scores), 1) if lost_scores else None,
            "separation": (
                round(sum(won_scores) / len(won_scores) - sum(lost_scores) / len(lost_scores), 1)
                if won_scores and lost_scores
                else None
            ),
        }
    result["loss_reasons"] = [
        {"reason": reason, "count": count} for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1])
    ]
    return result


def extraction_quality(db) -> dict:
    """How trustworthy is the document analysis on each opportunity?"""
    grades = db.execute(
        select(Opportunity.extraction_grade, func.count(Opportunity.id))
        .where(Opportunity.extraction_grade != "", Opportunity.extraction_grade != None)  # noqa: E711
        .group_by(Opportunity.extraction_grade)
    ).all()
    confidences = db.execute(
        select(Opportunity.ai_confidence)
        .where(Opportunity.ai_confidence != None)  # noqa: E711
    ).all()
    values = [float(c[0]) for c in confidences if c[0] is not None]
    return {
        "extraction_grades": {grade: count for grade, count in grades},
        "avg_extraction_confidence": round(sum(values) / len(values), 3) if values else None,
        "extraction_confidence_samples": len(values),
    }


def knowledge_gaps(db) -> dict:
    """Which company evidence is missing from proposals that were actually drafted?"""
    gap_sections = db.execute(
        select(ProposalSection.key, func.count(ProposalSection.id))
        .where(ProposalSection.status == "GAPS")
        .group_by(ProposalSection.key)
    ).all()
    total_sections = db.execute(select(func.count(ProposalSection.id))).scalar() or 0
    gap_total = sum(count for _, count in gap_sections)
    return {
        "proposal_sections_total": total_sections,
        "proposal_sections_with_gaps": gap_total,
        "gap_rate": round(gap_total / total_sections, 3) if total_sections else 0.0,
        "gaps_by_section": [
            {"section": key, "count": count}
            for key, count in sorted(gap_sections, key=lambda kv: -kv[1])
        ],
    }


def requirement_coverage(db) -> dict:
    """How many requirements were captured per analysed opportunity."""
    rows = db.execute(
        select(Opportunity.id, func.count(ExtractedRequirement.id))
        .join(ExtractedRequirement, ExtractedRequirement.opportunity_id == Opportunity.id)
        .group_by(Opportunity.id)
    ).all()
    counts = [count for _, count in rows]
    return {
        "opportunities_with_requirements": len(counts),
        "avg_requirements": round(sum(counts) / len(counts), 1) if counts else 0.0,
    }
