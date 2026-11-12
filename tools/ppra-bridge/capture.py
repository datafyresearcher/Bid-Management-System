"""Capture the portals the cloud cannot reach and hand them to the BMS API.

Two of the authorized portals — eproc.punjab.gov.pk (PPRA Punjab) and
wapda.gov.pk (WAPDA) — refuse connections from datacenter networks as a
class: the cloud scan times out or is reset at the TLS open, from every
region. But the portals answer the bid desk's own network happily, and they
answer a real browser. This script opens each listing in the machine's
installed Chrome, walks the pages, and posts the raw HTML to the API's
capture endpoint, where it runs through the same parser, normalizer and
scorer a live scan would use.

Setup, in tools/ppra-bridge:

    python -m venv .venv
    .venv/Scripts/pip install playwright httpx
    copy config.example.json config.json   (fill in the secret)

Run by hand:

    .venv/Scripts/python capture.py

The value for `secret` is the repository's BMS_CAPTURE_SECRET — the same value
the deploy pipeline gives the API. `sources` lists which portals to capture
(default: PPRA Punjab only).
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

CONFIG_PATH = Path(__file__).with_name("config.json")

MAX_PAGES = 15


def log(message: str):
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {message}", flush=True)


def pager_link(page, wanted: str):
    """The pager's link for a page number.

    The number sits inside a span inside the anchor, so an exact-text match on
    the anchor itself never finds it — the text engine assigns the text to the
    innermost element that holds it. A walk that looked for the anchor by its
    own text therefore found nothing, and stopped after the first page, so the
    portal's tenders past the front of the grid were never captured.
    """
    for selector in (
        f'a:has(span:text-is("{wanted}"))',
        f'a:has(span:text-is("{wanted} "))',
        f'a >> text="{wanted}"',
    ):
        locator = page.locator(selector).first
        if locator.count():
            return locator
    return None


def capture_ppra(page) -> list[str]:
    """Read every page of the PPRA Punjab listing grid in a real browser."""
    LISTING_URL = "https://eproc.punjab.gov.pk/ActiveTenders.aspx"
    GRID_SELECTOR = "table[id*='rdgrdManageTender']"

    pages: list[str] = []
    log("opening the PPRA Punjab listing")
    page.goto(LISTING_URL, wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_selector(GRID_SELECTOR, timeout=60_000)
    page.wait_for_timeout(1500)
    pages.append(page.content())

    # The pager is a row of numbered postback links. Walk them in order;
    # a page that repeats what we already have means the end.
    while len(pages) < MAX_PAGES:
        wanted = str(len(pages) + 1)
        anchor = pager_link(page, wanted)
        if anchor is None:
            break
        previous = pages[-1]
        try:
            anchor.click(timeout=20_000)
        except Exception as exc:
            log(f"could not open page {wanted}: {exc}")
            break
        page.wait_for_selector(GRID_SELECTOR, timeout=60_000)
        # The postback replaces the grid, and it does not always land within a
        # fixed pause, so the new page is waited for rather than assumed.
        html = page.content()
        for _ in range(40):
            if html != previous:
                break
            page.wait_for_timeout(500)
            html = page.content()
        if html == previous:
            break
        pages.append(html)
        log(f"captured page {len(pages)}")
    return pages


def capture_wapda(page) -> list[str]:
    """Read the WAPDA tender listing, which is a server-rendered WordPress page.

    The pager hangs a plain query variable off the listing URL — no postbacks,
    so each page is one navigation. A page that repeats the notices we already
    have (or has none) means the end.
    """
    LISTING_URL = "https://wapda.gov.pk/wapda-tenders/"
    POST_LINKS = "li.wp-block-post h4.wp-block-post-title a"
    WAPDA_MAX_PAGES = 5

    pages: list[str] = []
    seen: set[str] = set()
    for page_number in range(1, WAPDA_MAX_PAGES + 1):
        url = LISTING_URL if page_number == 1 else f"{LISTING_URL}?query-4-page={page_number}"
        log(f"opening WAPDA listing page {page_number}")
        page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(1500)
        links = page.eval_on_selector_all(POST_LINKS, "els => els.map(e => e.href)")
        if not links or not [l for l in links if l not in seen]:
            break
        seen.update(links)
        pages.append(page.content())
    return pages


# One capture routine per bridge-fed source, keyed by the source code the API
# knows. Listed in app/source_registry.py as BRIDGE_FED_SOURCES.
CAPTURES = {
    "ppra_punjab": capture_ppra,
    "wapda": capture_wapda,
}


def submit(pages: list[str], config: dict, source_code: str) -> dict:
    headers = {"X-Capture-Secret": config["secret"]}
    payload = {
        "code": source_code,
        "pages": pages,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    last_error = None
    for attempt in range(3):
        try:
            response = httpx.post(
                f"{config['api_url'].rstrip('/')}/api/sources/capture",
                json=payload,
                headers=headers,
                timeout=120,
            )
            if response.status_code == 200:
                return response.json()
            last_error = f"HTTP {response.status_code}: {response.text[:300]}"
        except Exception as exc:
            last_error = str(exc)
        log(f"submit failed ({attempt + 1}/3): {last_error}")
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"could not submit the capture: {last_error}")


def main() -> int:
    if not CONFIG_PATH.exists():
        print("config.json is missing — copy config.example.json and fill it in.")
        return 1
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    sources = config.get("sources") or ["ppra_punjab"]
    unknown = [code for code in sources if code not in CAPTURES]
    if unknown:
        print(f"no capture routine for: {', '.join(unknown)}")
        return 1

    from playwright.sync_api import sync_playwright

    failures = 0
    with sync_playwright() as p:
        # channel="chrome" drives the machine's installed Chrome — its TLS
        # handshake is a real browser's, which is what these portals accept.
        # No browser download is needed for this.
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        for code in sources:
            try:
                pages = CAPTURES[code](page)
                if not pages:
                    raise RuntimeError("nothing could be captured")
                log(f"{code}: captured {len(pages)} page(s); submitting")
                result = submit(pages, config, code)
                log(
                    "{source}: {notices} notices, {new} new, {scored} scored, health {health}".format(
                        **result
                    )
                )
            except Exception as exc:
                log(f"{code} failed: {exc}")
                failures += 1
        browser.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
