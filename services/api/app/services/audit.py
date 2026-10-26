from app.models import DecisionAudit

SYSTEM_ACTOR = "system"


def record(db, action: str, actor: str = SYSTEM_ACTOR, opportunity_id=None, gate_task_id=None, detail=None, commit: bool = True):
    """Write an entry to the audit trail.

    `commit=False` leaves the entry to be written with the rest of the work
    in hand. A batch that captures a hundred tenders writes a hundred entries
    that way, and reaches the database in one go instead of a hundred times.
    """
    entry = DecisionAudit(
        action=action,
        actor=actor,
        opportunity_id=opportunity_id,
        gate_task_id=gate_task_id,
        detail=detail or {},
    )
    db.add(entry)
    if commit:
        db.commit()
    return entry
