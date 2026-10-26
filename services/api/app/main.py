import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware

from app import runtime
from app.config import settings
from app.db import init_db
from app.routers import admin, auth, cron, dashboard, gates, kb, leads, opportunities, proposals, sources

logging.basicConfig(level=logging.INFO)

DEFAULT_SECRET = "change-me-in-production"


@asynccontextmanager
async def lifespan(app):
    started = time.monotonic()
    init_db()
    # The database, the knowledge base, the portals and the review queue are
    # all brought up to date on every start. The database is shared between
    # instances, so each step checks what is already there before it does
    # the work again.
    from app.bootstrap import ensure_seeded

    ensure_seeded()
    task = None
    stop_event = None
    if settings.scheduler_enabled:
        from app.services import jobs

        stop_event = asyncio.Event()
        task = asyncio.create_task(jobs.scheduler_loop(stop_event))
    _log_configuration()
    # Whatever the start-up cost was, it comes out of the budget of the
    # request this instance is about to serve.
    runtime.set_startup_seconds(time.monotonic() - started)
    yield
    if stop_event:
        stop_event.set()
    if task:
        try:
            await asyncio.wait_for(task, timeout=5)
        except Exception:
            pass


def _log_configuration():
    """Say how this instance is configured, once, at start-up.

    Everything logged here is already visible on the health endpoint; the
    point is that a misconfiguration — a default signing key on a live
    deployment, a database on a throwaway disk — is visible in the logs of
    the deployment that has the problem, without anyone having to probe.
    """
    log = logging.getLogger("bms.startup")
    backend = "postgresql" if settings.database_url.startswith("postgres") else "sqlite"
    log.info(
        "API starting: fixtures=%s llm=%s db=%s scheduler=%s",
        settings.fixtures,
        settings.llm_provider,
        backend,
        settings.scheduler_enabled,
    )
    if not settings.fixtures and settings.secret_key == DEFAULT_SECRET:
        log.critical(
            "BMS_SECRET_KEY is the default while reading live portals. "
            "Sessions are forgeable with the key printed in the repository. "
            "Set BMS_SECRET_KEY before going live; sign-in is refused until then."
        )
    if not settings.fixtures and backend == "sqlite":
        log.warning(
            "Live data is being written to SQLite on this instance's own disk. "
            "Everything a scan writes is lost when the instance goes. "
            "Set BMS_DATABASE_URL to a shared PostgreSQL."
        )
    if not settings.fixtures and not settings.cron_secret:
        log.warning(
            "No CRON_SECRET is configured: scheduled scans and the daily "
            "digest are refused. Set CRON_SECRET on the deployment to enable them."
        )


app = FastAPI(title="AI Bid Management System", version="0.1.0", lifespan=lifespan)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_budget(request, call_next):
    """Give every request one deadline, and record it for the work to follow.

    The host this runs on stops a request after a fixed time. Every part of
    the work — reading a portal, writing the capture, scoring it, asking the
    model to explain it — draws from what is left of that time, so a request
    that started slowly does less rather than running out mid-way.
    """
    started = time.monotonic()
    request_id = uuid.uuid4().hex[:12]
    overhead = runtime.claim_startup_seconds()
    budget = max(5.0, float(settings.request_budget_seconds) - overhead)
    runtime.set_deadline(time.monotonic() + budget)
    response = await call_next(request)
    # One line per request. On a serverless host the platform keeps the logs
    # of the invocation; in a container they are the API's own. Slow requests
    # are what a bid manager reports as "the dashboard is slow today" — the
    # duration says whether it was the instance starting or the work itself.
    duration_ms = int((time.monotonic() - started) * 1000)
    logging.getLogger("bms.access").info(
        '%s "%s %s" %s %sms',
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response

for module in (auth, dashboard, opportunities, gates, leads, kb, sources, admin, proposals, cron):
    app.include_router(module.router)


@app.get("/api/health")
def health(authorization: str = Header(default="")):
    """Liveness, and a little configuration.

    Unauthenticated callers — the platform's checks, the CI smoke test —
    get the status and the fixtures flag, which is what the smoke test
    asserts on. Database contents and LLM configuration are only reported
    to a signed-in administrator: they describe the deployment's internals
    and nobody else needs them.
    """
    minimal = {"status": "ok", "fixtures": settings.fixtures}
    payload = None
    if authorization.startswith("Bearer "):
        from app.security import decode_token

        payload = decode_token(authorization[len("Bearer "):])
    if not payload:
        return minimal
    from app.db import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        user = db.get(User, payload.get("uid"))
        if not user or not user.active or user.role != "admin":
            return minimal
    finally:
        db.close()
    from app.llm import provider as llm

    return {
        "status": "ok",
        "provider": settings.llm_provider,
        "fixtures": settings.fixtures,
        "database": _database_status(),
        "llm": llm.provider_status(),
    }


def _database_status():
    """Report where the results are actually being kept.

    The dashboard and the review queue both read from the database, so it is
    worth being able to see at a glance that it is reachable and shared,
    rather than a file on one machine's disk.
    """
    from sqlalchemy import text

    from app.db import IS_POSTGRES, engine

    backend = "postgresql" if IS_POSTGRES else "sqlite"
    status = {"backend": backend, "shared": IS_POSTGRES}
    try:
        with engine.connect() as conn:
            status["opportunities"] = conn.execute(
                text("select count(*) from opportunities")
            ).scalar()
            status["pending_gates"] = conn.execute(
                text("select count(*) from gate_tasks where status = 'PENDING'")
            ).scalar()
    except Exception as exc:
        status["error"] = str(exc)[:200]
    return status
