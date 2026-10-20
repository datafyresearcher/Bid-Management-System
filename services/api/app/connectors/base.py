from urllib.parse import urljoin

from app.config import fixtures_dir, settings


class BaseConnector:
    adapter = "base"
    label = "Base connector"

    def __init__(self, source):
        self.source = source
        # Notices are read from the authority's listing page; the portal home
        # page is only the fallback for sources that publish at a single URL.
        self.listing_url = (getattr(source, "listing_url", "") or source.url or "").rstrip("/")
        self.base_url = self.listing_url
        self.fixture_mode = settings.fixtures
        self.last_raw = None

    def fixture_path(self, *parts):
        return fixtures_dir().joinpath(self.source.code, *parts)

    def fetch_listing(self):
        raise NotImplementedError

    def fetch_detail(self, native_id):
        return None

    def fetch_documents(self, native_id, ref=None):
        """The documents a notice points at.

        `ref` is the stored per-notice reference, which carries the portal's
        own document link when one was captured.
        """
        return None

    def _headers(self):
        return {"User-Agent": settings.user_agent}

    # ------------------------------------------------------------------
    # Live reading
    # ------------------------------------------------------------------

    def client(self):
        """A polite, retrying reader for the live portal.

        Created per scan so the request spacing starts fresh.
        """
        from app.connectors.http_client import LiveClient

        return LiveClient(
            user_agent=settings.user_agent,
            timeout=settings.live_request_timeout,
            min_interval=settings.live_min_interval,
            retries=settings.live_retries,
            browser_ua=settings.live_browser_ua,
        )

    def abs_url(self, url: str, base: str = "") -> str:
        """Resolve a portal-relative link against the source's listing page.

        Portals link their documents relative to the site root rather than to
        the listing page, so the link is resolved the way a browser would:
        against the listing URL, treating it as the page it is.
        """
        if not url:
            return ""
        if url.startswith("http://") or url.startswith("https://"):
            return url
        root = (base or self.base_url)
        if not root:
            return url
        return urljoin(root, url)
