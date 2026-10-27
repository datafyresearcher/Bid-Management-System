"""Shared HTTP client for live portal reads.

Two things make government portals awkward to fetch, and both are handled
here rather than in each connector:

* **TLS fingerprinting.** Some portals (PPRA Punjab's Active Procurement, for
  one) complete the handshake and then drop the connection unless the client
  looks like a real browser. `curl_cffi` reproduces Chrome's TLS signature, so
  a read looks like the browser a bid manager would have used.
* **Politeness.** These are public-sector sites. Requests are spaced out, the
  User-Agent identifies us, and a failing portal is retried a small number of
  times rather than hammered.

Everything here is read-only. Nothing in this module logs in, and nothing
stores portal credentials.
"""

import logging
import time

logger = logging.getLogger("bms.http")

# A browser-grade client, when one is available. `curl_cffi` impersonates
# Chrome's TLS fingerprint, which is what gets past portals that drop
# non-browser clients mid-handshake.
try:  # pragma: no cover - availability depends on the environment
    from curl_cffi import requests as _curl_requests

    HAS_CURL_CFFI = True
except Exception:  # pragma: no cover
    _curl_requests = None
    HAS_CURL_CFFI = False

import httpx


class FetchError(RuntimeError):
    """A portal could not be read."""


# The phrases a failed connection produces. They are the difference between a
# portal that answered and said no, and a portal that cannot be reached from
# here at all — the first may be worth another try, the second will not answer
# however long we wait.
CONNECTION_MARKERS = (
    "could not connect",
    "failed to connect",
    "connection refused",
    "connection timed out",
    "could not resolve host",
    "couldn't resolve host",
    "name or service not known",
    "temporary failure in name resolution",
    "no route to host",
    "network is unreachable",
)


def is_connection_failure(text) -> bool:
    """Whether a failure was a host that could not be reached."""
    value = str(text).lower()
    return any(marker in value for marker in CONNECTION_MARKERS)


def _is_connection_failure(exc: Exception) -> bool:
    """Whether the host could not be reached at all.

    A portal that answered and refused is a different matter from a portal
    that cannot be reached from here — the first may be worth another try,
    the second will not answer however long we wait.
    """
    return is_connection_failure(exc)


class LiveClient:
    """A polite, retrying reader for public portal pages."""

    def __init__(
        self,
        user_agent: str = "",
        timeout: float = 45.0,
        min_interval: float = 1.5,
        retries: int = 2,
        impersonate: bool = True,
        browser_ua: bool = True,
        connect_timeout: float = 10.0,
        verify_tls: bool | None = None,
    ):
        self.user_agent = user_agent or "AHTE-BMS/0.1 (bid desk; contact admin@ahte.local)"
        self.timeout = timeout
        # A host that cannot be reached at all is not going to be reached by
        # waiting longer. This is the time allowed to open the connection,
        # and it is kept short so an unreachable portal is reported as such
        # quickly instead of stalling a scan.
        self.connect_timeout = connect_timeout
        self.min_interval = min_interval
        self.retries = max(0, retries)
        self.impersonate = impersonate and HAS_CURL_CFFI
        # Certificates are verified unless a deployment turns that off for a
        # portal whose chain an inspection appliance breaks. It is off only
        # when someone said so in the environment, and the logs say so every
        # time a client is built that way.
        from app.config import settings

        self.verify = settings.live_verify_tls if verify_tls is None else verify_tls
        if not self.verify:
            logger.warning("TLS verification is OFF for portal reads (BMS_LIVE_VERIFY_TLS=false)")
        # With browser impersonation the request has to carry the browser's
        # own User-Agent, or the portal refuses it. Overriding it with our own
        # string is what earns a 403 from NTDC.
        self.browser_ua = browser_ua
        self._last_request_at = 0.0

    def _wait(self):
        """Space requests out so a portal is never hit in a burst."""
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request_at = time.monotonic()

    def get(self, url: str, headers: dict | None = None) -> str:
        """Fetch a page and return its text. Raises FetchError on failure."""
        return self._request("GET", url, headers=headers)

    def post(self, url: str, data: dict, headers: dict | None = None) -> str:
        """Submit a form and return the response text.

        Some portals page through an ASP.NET WebForms grid, where moving to
        the next page is a form post rather than a URL.
        """
        return self._request("POST", url, data=data, headers=headers)

    def _request(self, method: str, url: str, data: dict | None = None, headers: dict | None = None) -> str:
        base_headers = {}
        if not (self.impersonate and self.browser_ua):
            # Only send our own identity when we are not impersonating a
            # browser — see the note on `browser_ua`.
            base_headers = {
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        if headers:
            base_headers.update(headers)

        last_error = None
        connection_failures = 0
        for attempt in range(self.retries + 1):
            self._wait()
            try:
                if self.impersonate:
                    # curl_cffi names the redirect flag `allow_redirects`.
                    response = _curl_requests.request(
                        method,
                        url,
                        impersonate="chrome124",
                        headers=base_headers,
                        data=data,
                        timeout=(self.connect_timeout, self.timeout),
                        allow_redirects=True,
                        verify=self.verify,
                    )
                else:
                    with httpx.Client(
                        timeout=httpx.Timeout(self.timeout, connect=self.connect_timeout),
                        follow_redirects=True,
                        headers=base_headers,
                        verify=self.verify,
                    ) as client:
                        response = client.request(method, url, data=data)
                if response.status_code >= 400:
                    raise FetchError(f"HTTP {response.status_code} for {url}")
                return _decode(response)
            except Exception as exc:
                last_error = exc
                if not _is_connection_failure(exc):
                    # The portal answered, and said no. Repeating the request
                    # will not change the answer.
                    break
                connection_failures += 1
                if connection_failures > 2:
                    # Three connection attempts is the ceiling. The portal we
                    # read most — PPRA Punjab's e-procurement — accepts
                    # connections from Pakistan but drops foreign ones
                    # intermittently, so a couple of tries genuinely turn a
                    # failed scan into a good one; beyond that, a host that
                    # still will not open is not answering and should not be
                    # hammered.
                    break
                if attempt < self.retries:
                    backoff = 2 ** attempt
                    logger.warning("Fetch failed (%s); retrying in %ss", exc, backoff)
                    time.sleep(backoff)
        raise FetchError(f"could not read {url}: {last_error}")


def _decode(response) -> str:
    """Decode a response, preferring UTF-8.

    These portals serve UTF-8, but the client guesses latin-1 when the
    response carries no charset — and latin-1 turns a curly apostrophe into
    three mojibake characters. UTF-8 is tried strictly first; the response's
    own charset is only used when the bytes are genuinely not UTF-8.
    """
    raw = response.content
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass

    charset = None
    try:
        charset = response.encoding
    except Exception:
        charset = None
    if charset:
        try:
            return raw.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            pass
    return raw.decode("utf-8", errors="replace")
