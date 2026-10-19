from sqlalchemy import func, select

from app.models import AIMetric, DecisionAudit, GateTask, Score


def summary(db) -> dict:
    by_task = {}
    metrics = db.execute(select(AIMetric)).scalars().all()
    for m in metrics:
        bucket = by_task.setdefault(m.task, {"calls": 0, "invalid": 0, "tokens": 0, "latency_ms": 0})
        bucket["calls"] += 1
        bucket["invalid"] += 0 if m.output_valid else 1
        bucket["tokens"] += m.tokens_estimate or 0
        bucket["latency_ms"] += m.latency_ms or 0
    for bucket in by_task.values():
        bucket["avg_latency_ms"] = round(bucket["latency_ms"] / bucket["calls"], 1) if bucket["calls"] else 0

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
        "scores_total": score_count,
        "screening_overrides": override_count,
        "override_rate": round(override_count / score_count, 3) if score_count else 0,
        "gate_decisions": gate_decisions,
        "gate_returns": returned,
        "gate_approvals": approved,
        "gate_approval_rate": round(approved / (approved + returned), 3) if (approved + returned) else 0,
    }
