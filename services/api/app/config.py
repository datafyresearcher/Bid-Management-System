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
    model_config = SettingsConfigDict(env_file=".env", env_prefix="BMS_", extra="ignore")

    database_url: str = "sqlite:///./bms.db"
    storage_dir: str = "./storage"

    llm_provider: str = "mock"
    llm_model: str = ""
    openrouter_api_key: str = Field(default="", validation_alias="OPENROUTER_API_KEY")
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", validation_alias="OPENAI_BASE_URL")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", validation_alias="OPENROUTER_BASE_URL"
    )

    fixtures: bool = True
    fixtures_path: str = Field(default="", validation_alias="BMS_FIXTURES_DIR")
    scan_interval_seconds: int = 3600
    scheduler_enabled: bool = False
    cors_origins: str = "http://localhost:3000"
    user_agent: str = "BMS-Bot/0.1 (+contact@ahte.example)"

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
