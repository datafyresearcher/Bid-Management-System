from app.config import fixtures_dir, settings


class BaseConnector:
    adapter = "base"
    label = "Base connector"

    def __init__(self, source):
        self.source = source
        self.base_url = (source.url or "").rstrip("/")
        self.fixture_mode = settings.fixtures
        self.last_raw = None

    def fixture_path(self, *parts):
        return fixtures_dir().joinpath(self.source.code, *parts)

    def fetch_listing(self):
        raise NotImplementedError

    def fetch_detail(self, native_id):
        return None

    def fetch_documents(self, native_id):
        return None

    def _headers(self):
        return {"User-Agent": settings.user_agent}
