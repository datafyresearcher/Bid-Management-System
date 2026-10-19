import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import init_db
from app.routers import admin, auth, dashboard, gates, kb, leads, opportunities, proposals, sources

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app):
    init_db()
    if settings.seed_on_startup:
        from app.bootstrap import ensure_seeded

        ensure_seeded()
    task = None
    stop_event = None
    if settings.scheduler_enabled:
        from app.services import jobs

        stop_event = asyncio.Event()
        task = asyncio.create_task(jobs.scheduler_loop(stop_event))
    yield
    if stop_event:
        stop_event.set()
    if task:
        try:
            await asyncio.wait_for(task, timeout=5)
        except Exception:
            pass


app = FastAPI(title="AI Bid Management System", version="0.1.0", lifespan=lifespan)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (auth, dashboard, opportunities, gates, leads, kb, sources, admin, proposals):
    app.include_router(module.router)


@app.get("/api/health")
def health():
    from app.llm import provider as llm

    return {
        "status": "ok",
        "provider": settings.llm_provider,
        "fixtures": settings.fixtures,
        "llm": llm.provider_status(),
    }
