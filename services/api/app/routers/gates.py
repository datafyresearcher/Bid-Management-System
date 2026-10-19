from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

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


@router.get("")
def list_gates(status: str = "PENDING,OVERDUE", role: str = "", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(GateTask).order_by(GateTask.due_at)
    statuses = [s.strip().upper() for s in status.split(",") if s.strip()]
    if statuses:
        query = query.where(GateTask.status.in_(statuses))
    if role:
        query = query.where(GateTask.owner_role == role)
    elif user.role not in ("admin", "management"):
        query = query.where((GateTask.owner_role == user.role) | (GateTask.owner_user_id == user.id))
    tasks = db.execute(query).scalars().all()
    return [gate_task(g) for g in tasks]


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
