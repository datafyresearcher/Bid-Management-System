from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    if len(here.parents) > 3:
        return here.parents[3]
    return here.parents[-1]


REPO_ROOT = _repo_root()


class Settings(BaseSettings):
    # Load the repo-root .env (the one .env.example is copied to) and then the
    # local one, so a file next to the code wins over the shared default.
    # Both paths are needed because the API is started from services/api while
    # .env.example lives at the repository root.
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), ".env"),
        env_prefix="BMS_",
        extra="ignore",
    )

    database_url: str = "sqlite:///./bms.db"
    storage_dir: str = "./storage"
    # TLS mode used when the database is not PostgreSQL-on-Supabase but some
    # other host that still wants the connection encrypted.
    db_sslmode: str = "require"
    # How many database connections this instance keeps open. The connection
    # is pooled so that a write does not pay for a new TLS handshake every
    # time; a serverless instance only needs a handful.
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_timeout: int = 15
    # Seconds after which a pooled connection is retired. The pooler in front
    # of the database closes idle connections on its own schedule, and a
    # connection that was closed underneath us is replaced rather than
    # reused.
    db_pool_recycle: int = 280

    llm_provider: str = "mock"
    llm_model: str = ""
    # The whole budget for one model call, retries included. It has to be
    # shorter than the host's limit on a request, or a model that hangs would
    # use up the entire request on its own.
    llm_timeout_seconds: int = 25
    # Output budget for the scoring rationale. It has to leave room for the
    # model's own reasoning: a reasoning model spends its budget on thinking
    # before it answers, and if the cap lands first the answer never arrives.
    llm_score_max_tokens: int = 1000
    llm_max_retries: int = 2
    llm_temperature: float = 0.2
    llm_cache_enabled: bool = True
    llm_draft_workers: int = 4
    openrouter_api_key: str = Field(default="", validation_alias="OPENROUTER_API_KEY")
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", validation_alias="OPENAI_BASE_URL")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", validation_alias="OPENROUTER_BASE_URL"
    )

    fixtures: bool = True
    fixtures_path: str = Field(default="", validation_alias="BMS_FIXTURES_DIR")
    seed_on_startup: bool = False
    scan_interval_seconds: int = 3600
    scheduler_enabled: bool = False
    cors_origins: str = "http://localhost:3000"
    user_agent: str = "BMS-Bot/0.1 (+https://www.ahte.com.pk)"

    # --- Live portal reading -------------------------------------------
    # How long to wait on a single portal request. These are government sites
    # on slow links, and NTDC's own site in particular can take a minute.
    live_request_timeout: int = 60
    # Whether a live read presents a browser User-Agent. Several of these
    # portals refuse programmatic clients outright — NTDC answers 403 to a
    # bot User-Agent and 200 to a browser one — so a live read has to look
    # like the browser a bid manager would have used. Only public pages are
    # read, the request rate stays low, and nothing ever signs in.
    live_browser_ua: bool = True
    # Minimum seconds between two requests to the same portal. Public-sector
    # sites are not to be hammered, and the docs ask for one request per 3s.
    live_min_interval: float = 3.0
    # How many times a failed request is retried before the source is marked
    # degraded. Zero means a transient blip marks the source unhealthy.
    live_retries: int = 2
    # How many listing pages to walk per source in one scan. Keeps a scan
    # inside the time budget of a serverless function.
    live_max_pages: int = 3
    # How many notices per source are enriched with a detail-page read in a
    # single scan. Detail reads are the expensive part, so they are rationed.
    live_max_details: int = 2
    # Seconds a single source's read may spend on the network. A read stops
    # before this rather than being cut off halfway through, so the scan
    # returns what it managed to read instead of failing.
    live_scan_deadline: float = 32.0
    # Seconds allowed to open a connection to a portal. A host that cannot be
    # reached is not reached by waiting longer.
    live_connect_timeout: float = 10.0
    # Seconds a freshly started deployment may spend reading the portals
    # before it serves its first request, so that the dashboard is not empty.
    # The budget has to be big enough for every portal to get a turn: a portal
    # that is never read is a portal the dashboard knows nothing about.
    live_startup_budget: float = 30.0
    # Seconds one portal request may take during that first read. A portal
    # that is slow today must not spend the whole cold start on its own.
    live_startup_request_timeout: float = 20.0
    # Only notices published within this many days are taken from a portal
    # that publishes its whole history in one response. Without this a single
    # scan would import thousands of years-old records.
    live_lookback_days: int = 60
    # Whether live portal reads verify the portal's TLS certificate. On by
    # default; a portal whose certificate chain some inspection appliance
    # breaks can turn this off explicitly, and the logs say so every time it
    # is off.
    live_verify_tls: bool = True

    secret_key: str = "change-me-in-production"
    # A sign-in lasts a working week. The same desk opens the portal every
    # morning; a token that dies at lunchtime turns sign-in — and the browser's
    # "save password?" offer that comes with it — into a daily ritual.
    # Role and active status are re-checked against the database on every
    # request, so a longer-lived token cannot preserve stale permissions.
    token_ttl_hours: int = 168

    # --- Authentication hardening --------------------------------------
    # Password given to the seeded administrator when the knowledge base is
    # seeded in a live deployment. Empty means the demo password is only
    # ever used in fixtures mode; a deployment reading the live portals is
    # expected to have set a real one.
    admin_password: str = Field(default="", validation_alias=AliasChoices("BMS_ADMIN_PASSWORD", "ADMIN_PASSWORD"))
    # Failed sign-in attempts allowed from one identity before sign-ins are
    # refused for a while. The point is to make guessing a password slower
    # than the value of the guess.
    login_max_attempts: int = 10
    login_window_seconds: int = 300

    # --- Scheduled work (Vercel Cron) ----------------------------------
    # A serverless deployment has no process that wakes up on its own, so
    # the daily scan and digest are driven by a cron request. Vercel signs
    # that request with the CRON_SECRET set on the project; a deployment
    # without the secret refuses cron work rather than running it for
    # whoever asks.
    cron_secret: str = Field(default="", validation_alias=AliasChoices("BMS_CRON_SECRET", "CRON_SECRET"))

    # --- Outbound email -------------------------------------------------
    # The daily executive digest and screening alerts are delivered by SMTP
    # when these are set; without them the events stay in the dashboard
    # inbox only. Gmail app passwords, Mailgun and SES SMTP all fit here.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True
    digest_enabled: bool = True
    # Comma-separated recipients for the digest. When empty it goes to the
    # active admin, bid-manager and management accounts.
    digest_recipients: str = ""
    # The ranked brief keeps to the few tenders worth attention — a digest
    # that lists everything is an alert list, not a decision.
    digest_max_items: int = 10

    # --- Admin analytics bounds -----------------------------------------
    # AI quality analytics read the metrics of recent calls, not the whole
    # history; on a database reached over the network the difference is a
    # query that answers in milliseconds against one that does not.
    ai_metrics_window_days: int = 30

    # The whole time one request may take, including whatever the instance
    # had to do to get ready before serving it. Every phase of the work
    # draws from this one budget, so a request that starts slowly does less
    # rather than running past the end of its time.
    request_budget_seconds: int = 45

    score_archive_threshold: int = 40
    min_days_to_bid: int = 3
    # Seconds one scan may spend scoring the tenders it just captured. Scoring
    # a tender is what opens its review gate, so a capture that is not scored
    # leaves the review queue empty. The budget keeps a very large capture
    # from running past the end of the request that started it; the rest is
    # scored by the next pass.
    score_budget_seconds: int = 24
    # How many tenders are scored at the same time. Each one is scored on its
    # own, so a capture of a hundred tenders is finished in a fraction of the
    # time when the batch is spread over a few connections.
    score_workers: int = 4
    # Seconds the catch-up pass at start-up may spend scoring whatever the
    # last scan had left over. This is work done before the instance serves
    # anything, so it comes out of the first request's budget.
    startup_score_budget_seconds: int = 10
    # Seconds one tender's model call may take before it is abandoned. The
    # batch budget above is only checked between tenders, so without a limit
    # of its own a single slow answer would hold the whole request open for
    # the full timeout, retries included. A tender is only narrated when this
    # much of the batch budget is still free, so the rest of the batch keeps
    # moving and every tender still gets a score.
    score_item_seconds: int = 15
    # Seconds the "score everything waiting" action may spend. It has to leave
    # room for the request itself to return, so it is shorter than the host's
    # hard limit on a request.
    score_pending_budget_seconds: int = 40


settings = Settings()


def fixtures_dir() -> Path:
    if settings.fixtures_path:
        return Path(settings.fixtures_path)
    local = REPO_ROOT / "fixtures"
    if local.exists():
        return local
    container = Path("/fixtures")
    if container.exists():
        return container
    return local


def storage_path() -> Path:
    p = Path(settings.storage_dir)
    if not p.is_absolute():
        base = REPO_ROOT / "services" / "api"
        if not base.exists():
            base = Path.cwd()
        p = base / p
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        # A serverless instance runs on a read-only image with a writable
        # temporary directory. The files written there are lost when the
        # instance goes, but the text taken out of them is kept in the
        # database, so the analysis a document feeds still survives.
        import tempfile

        p = Path(tempfile.gettempdir()) / "bms-storage"
        p.mkdir(parents=True, exist_ok=True)
    for sub in ("documents", "raw", "exports", "uploads"):
        try:
            (p / sub).mkdir(exist_ok=True)
        except OSError:
            pass
    return p
