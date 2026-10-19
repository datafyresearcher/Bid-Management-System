import base64
import hashlib
import hmac
import json
import os
import time

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User

ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_b64, dk_b64 = stored.split("$", 1)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(dk_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def create_token(user: User) -> str:
    payload = {
        "uid": user.id,
        "role": user.role,
        "name": user.name,
        "email": user.email,
        "exp": time.time() + settings.token_ttl_hours * 3600,
    }
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    sig = hmac.new(settings.secret_key.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return raw + "." + sig


def decode_token(token: str):
    try:
        raw, sig = token.split(".", 1)
        expected = hmac.new(settings.secret_key.encode(), raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(raw.encode()))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


def get_current_user(authorization: str = Header(default=""), db: Session = Depends(get_db)) -> User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    payload = decode_token(authorization.replace("Bearer ", "", 1))
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.get(User, payload["uid"])
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


def require_roles(*roles: str):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if roles and user.role != "admin" and user.role not in roles:
            raise HTTPException(status_code=403, detail=f"Requires role: {'/'.join(roles)}")
        return user

    return dependency
