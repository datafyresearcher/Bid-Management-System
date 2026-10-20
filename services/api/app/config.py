from pathlib import Path

from pydantic import Field
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

    llm_provider: str = "mock"
    llm_model: str = ""
    llm_timeout_seconds: int = 60
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
    user_agent: str = "BMS-Bot/0.1 (+contact@ahte.example)"

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
    live_startup_budget: float = 20.0
    # Only notices published within this many days are taken from a portal
    # that publishes its whole history in one response. Without this a single
    # scan would import thousands of years-old records.
    live_lookback_days: int = 60

    secret_key: str = "change-me-in-production"
    token_ttl_hours: int = 12

    score_archive_threshold: int = 40
    min_days_to_bid: int = 3


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
    p.mkdir(parents=True, exist_ok=True)
    (p / "documents").mkdir(exist_ok=True)
    (p / "raw").mkdir(exist_ok=True)
    (p / "exports").mkdir(exist_ok=True)
    (p / "uploads").mkdir(exist_ok=True)
    return p
