from urllib.parse import urljoin

from app.config import fixtures_dir, settings


class BaseConnector:
    adapter = "base"
    label = "Base connector"

    # Per-scan overrides. A scan that has to fit inside a tight budget — the
    # first read of a freshly started deployment, for instance — can ask for
    # fewer pages, a shorter deadline and a shorter connect timeout without
    # changing the settings for every other scan.
    page_budget = None
    scan_seconds = None
    connect_timeout = None
    # How long one request to a portal may take. A read that has to fit a
    # tight window can ask for less, so that one slow portal cannot spend the
    # whole of it.
    request_timeout = None
    # How many times a failed request is retried. A read that has to fit a
    # tight window can ask for fewer, because a host that cannot be reached
    # costs the same however many times it is tried.
    retries = None

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

    # ------------------------------------------------------------------
    # Downloading a tender document
    # ------------------------------------------------------------------

    # The content types that are really a document. Everything else — HTML,
    # JSON, plain text — means the portal answered with a page rather than
    # with the file.
    DOCUMENT_CONTENT_TYPES = (
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        "application/zip",
        "application/x-rar",
        "application/octet-stream",
    )

    def download_document(self, url: str, filename: str = "") -> tuple[str, bytes] | None:
        """Fetch a tender document, or nothing at all.

        A portal that answers a request for a PDF with an HTML page is
        common: the site's single-page application serves its shell for every
        path, a login wall answers with a sign-in page, and an error page
        answers with a page saying there was an error. All three arrive with
        status 200 and a perfectly readable body, so a naive download files
        the shell as if it were the bidding document — and the bid team then
        analyses HTML instead of a tender.

        So the content type is checked before the bytes are accepted, and a
        body that is not a document is refused. `filename` is the name the
        document is filed under.
        """
        if not url:
            return None
        client = self.client()
        try:
            content, content_type = client.get_bytes(url)
        except Exception:
            return None
        if not self._is_document_body(content, content_type):
            return None
        name = filename or url.rsplit("/", 1)[-1] or "document.bin"
        return name, content

    @staticmethod
    def _is_document_body(content: bytes, content_type: str) -> bool:
        """Whether what came back is really a document.

        The content type is the primary signal, but a portal that serves
        `application/octet-stream` for everything is checked by its magic
        bytes as well, so a shell served as a download is still refused.
        """
        if not content:
            return False
        ctype = (content_type or "").split(";")[0].strip().lower()
        if ctype.startswith("text/html") or ctype in ("application/xhtml+xml", "text/plain"):
            return False
        if ctype and any(ctype.startswith(known) for known in BaseConnector.DOCUMENT_CONTENT_TYPES):
            # An octet-stream may still be a page. The magic bytes settle it.
            if ctype == "application/octet-stream" and content[:200].lstrip()[:1] == b"<":
                return False
            return True
        # No usable content type: fall back to the file's own signature.
        head = content[:8]
        if head.startswith(b"%PDF"):
            return True
        if head.startswith(b"PK\x03\x04"):
            return True
        if head.startswith(b"\xd0\xcf\x11\xe0"):
            return True
        if head.startswith(b"Rar!"):
            return True
        return False

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
            timeout=self.request_timeout or settings.live_request_timeout,
            min_interval=settings.live_min_interval,
            retries=self.retries if self.retries is not None else settings.live_retries,
            browser_ua=settings.live_browser_ua,
            connect_timeout=self.connect_timeout or settings.live_connect_timeout,
        )

    def pages_allowed(self) -> int:
        """How many listing pages this scan may walk."""
        if self.page_budget is not None:
            return max(1, int(self.page_budget))
        return settings.live_max_pages

    def scan_budget(self):
        """How long this source's read has left, and what one request costs.

        A read that runs past the budget of the process it is running in is
        cut off halfway through and loses everything it had gathered. The read
        therefore keeps an eye on the clock and stops before that, returning
        what it has managed to read.
        """
        import time

        started = getattr(self, "_scan_started", None)
        if started is None:
            started = time.monotonic()
            self._scan_started = started
        requests_made = getattr(self, "_scan_requests", 0)
        elapsed = time.monotonic() - started
        average = elapsed / requests_made if requests_made else 0.0
        # A request is costed above the average, so that a slow one still
        # finishes inside the budget.
        estimate = max(settings.live_min_interval, average) * 1.5
        limit = self.scan_seconds if self.scan_seconds is not None else settings.live_scan_deadline
        return limit - elapsed, estimate

    def note_request(self):
        """Note that a request was made, for the estimate above."""
        self._scan_requests = getattr(self, "_scan_requests", 0) + 1

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
