from app.models import DecisionAudit

SYSTEM_ACTOR = "system"


def record(db, action: str, actor: str = SYSTEM_ACTOR, opportunity_id=None, gate_task_id=None, detail=None):
    entry = DecisionAudit(
        action=action,
        actor=actor,
        opportunity_id=opportunity_id,
        gate_task_id=gate_task_id,
        detail=detail or {},
    )
    db.add(entry)
    db.commit()
    return entry
