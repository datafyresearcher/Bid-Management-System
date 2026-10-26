from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import GateTask, User
from app.security import get_current_user
from app.serializers import gate_task
from app.services import workflow

router = APIRouter(prefix="/api/gates", tags=["gates"])


class DecideIn(BaseModel):
    decision: str
    comment: str = ""
    reason_code: str = ""


def _filtered_query(status: str, role: str, user: User):
    """The gates a person is allowed to see, before any paging."""
    query = select(GateTask).order_by(GateTask.due_at)
    statuses = [s.strip().upper() for s in status.split(",") if s.strip()]
    if statuses:
        query = query.where(GateTask.status.in_(statuses))
    if role:
        query = query.where(GateTask.owner_role == role)
    elif user.role not in ("admin", "management"):
        query = query.where((GateTask.owner_role == user.role) | (GateTask.owner_user_id == user.id))
    return query


@router.get("")
def list_gates(
    status: str = "PENDING,OVERDUE",
    role: str = "",
    limit: int = 100,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = _filtered_query(status, role, user)
    # The opportunities are loaded in one go rather than one at a time. A
    # queue that holds hundreds of gates would otherwise ask the database the
    # same question once per gate, and the page would time out.
    query = query.options(selectinload(GateTask.opportunity))
    query = query.offset(max(0, offset)).limit(max(1, min(limit, 300)))
    tasks = db.execute(query).scalars().all()
    return [gate_task(g) for g in tasks]


@router.get("/count")
def count_gates(
    status: str = "PENDING,OVERDUE",
    role: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """How many gates there are in the view, not just the page.

    A queue of several hundred gates is not something anybody reads off one
    screen, so the page that shows them has to say how many are behind it.
    """
    query = _filtered_query(status, role, user)
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
    return {"total": total, "status": status, "role": role}


@router.get("/{gate_id}")
def get_gate(gate_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.get(GateTask, gate_id)
    if not task:
        raise HTTPException(status_code=404, detail="Gate task not found")
    return gate_task(task)


@router.post("/{gate_id}/decide")
def decide(gate_id: int, payload: DecideIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = db.get(GateTask, gate_id)
    if not task:
        raise HTTPException(status_code=404, detail="Gate task not found")
    if task.status not in ("PENDING", "OVERDUE"):
        raise HTTPException(status_code=400, detail=f"Gate already {task.status}")
    allowed = {task.owner_role, "admin", "management"}
    if user.role not in allowed:
        raise HTTPException(status_code=403, detail=f"Gate owned by role {task.owner_role}")
    workflow.decide_gate(db, task, payload.decision, actor=user, comment=payload.comment, reason_code=payload.reason_code)
    db.refresh(task)
    return gate_task(task)
