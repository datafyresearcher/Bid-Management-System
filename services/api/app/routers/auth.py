import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User
from app.security import create_token, get_current_user, verify_password
from app.serializers import user_brief

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


# Failed sign-ins, by client and account. The point of the limit is not to
# stop a determined attacker — it is to make guessing a password slower than
# the value of the guess, and to make the attempt visible in the logs.
# Counted in-process: a deployment runs a handful of instances, so the
# effective limit is a few times the configured one, which is still an order
# of magnitude below what a password-guessing run needs.
_attempts: dict[str, list[float]] = {}
_attempts_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    """The caller's address, as the platform reports it.

    The API runs behind Vercel's edge, so the socket address is the edge's;
    the forwarded header carries the client that actually sent the request.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _attempt_key(request: Request, email: str) -> str:
    return f"{_client_ip(request)}|{email.lower().strip()}"


def _is_limited(key: str) -> tuple[bool, int]:
    """Whether this identity is refused right now, and for how long."""
    window = settings.login_window_seconds
    now = time.monotonic()
    with _attempts_lock:
        stamps = [t for t in _attempts.get(key, []) if now - t < window]
        _attempts[key] = stamps
        if len(stamps) >= settings.login_max_attempts:
            oldest = min(stamps)
            return True, max(1, int(window - (now - oldest)))
    return False, 0


def _record_failure(key: str) -> None:
    with _attempts_lock:
        _attempts.setdefault(key, []).append(time.monotonic())
        # The map only ever grows by identities that fail to sign in, so it
        # is pruned now and then rather than allowed to grow without end.
        if len(_attempts) > 10_000:
            cutoff = time.monotonic() - settings.login_window_seconds
            for k in [k for k, v in _attempts.items() if not v or v[-1] < cutoff]:
                _attempts.pop(k, None)


def _clear_failures(key: str) -> None:
    with _attempts_lock:
        _attempts.pop(key, None)


def _secret_ok() -> bool:
    """Whether tokens can be signed without relying on the default key.

    A deployment that reads the live portals is a deployment that holds real
    tender data. Signing its sessions with a key that is printed in the
    repository would let anyone forge an administrator identity, so sign-in
    is refused — loudly, and with the fix in the message — until a real key
    is set. Fixtures/demo mode keeps working out of the box.
    """
    if settings.fixtures:
        return True
    return settings.secret_key != "change-me-in-production"


@router.post("/login")
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    if not _secret_ok():
        raise HTTPException(
            status_code=503,
            detail="Server not configured for production: set BMS_SECRET_KEY before signing in.",
        )
    key = _attempt_key(request, payload.email)
    limited, retry_after = _is_limited(key)
    if limited:
        raise HTTPException(
            status_code=429,
            detail="Too many failed sign-ins. Try again shortly.",
            headers={"Retry-After": str(retry_after)},
        )
    user = db.execute(select(User).where(User.email == payload.email.lower().strip())).scalars().first()
    if not user or not user.active or not verify_password(payload.password, user.password_hash):
        _record_failure(key)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    _clear_failures(key)
    return {"token": create_token(user), "user": user_brief(user)}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return user_brief(user)
