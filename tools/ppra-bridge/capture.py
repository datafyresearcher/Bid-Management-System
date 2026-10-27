"""Capture the PPRA Punjab tender listing and hand it to the BMS API.

eproc.punjab.gov.pk refuses connections from every datacenter network, so the
API can never read it directly — however patient the client and whichever
cloud region it runs in. But the portal answers the bid desk's own network
happily, and it answers a real browser: this script opens the listing in the
machine's installed Chrome, walks the pages, and posts the raw HTML to the
API's capture endpoint, where it runs through the same parser, normalizer and
scorer a live scan would use.

Setup, in tools/ppra-bridge:

    python -m venv .venv
    .venv/Scripts/pip install playwright httpx
    copy config.example.json config.json   (fill in the secret)

Run by hand:

    .venv/Scripts/python capture.py

The value for `secret` is the repository's BMS_CAPTURE_SECRET — the same value
the deploy pipeline gives the API.
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

CONFIG_PATH = Path(__file__).with_name("config.json")
LISTING_URL = "https://eproc.punjab.gov.pk/ActiveTenders.aspx"
GRID_SELECTOR = "table[id*='rdgrdManageTender']"
MAX_PAGES = 15


def log(message: str):
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {message}", flush=True)


def capture_pages() -> list[str]:
    """Read every page of the listing grid in a real Chrome."""
    from playwright.sync_api import sync_playwright

    pages: list[str] = []
    with sync_playwright() as p:
        # channel="chrome" drives the machine's installed Chrome — its TLS
        # handshake is a real browser's, which is what the portal's front
        # door accepts. No browser download is needed for this.
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        log("opening the listing")
        page.goto(LISTING_URL, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_selector(GRID_SELECTOR, timeout=60_000)
        page.wait_for_timeout(1500)
        pages.append(page.content())

        # The pager is a row of numbered postback links. Walk them in order;
        # a page that repeats what we already have means the end.
        while len(pages) < MAX_PAGES:
            wanted = str(len(pages) + 1)
            anchor = page.locator(f'a:text-is("{wanted}")').first
            try:
                if anchor.count() == 0:
                    break
            except Exception:
                break
            anchor.click()
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_selector(GRID_SELECTOR, timeout=60_000)
            page.wait_for_timeout(1200)
            html = page.content()
            if html == pages[-1]:
                break
            pages.append(html)
            log(f"captured page {len(pages)}")
        browser.close()
    return pages


def submit(pages: list[str], config: dict) -> dict:
    headers = {"X-Capture-Secret": config["secret"]}
    payload = {
        "code": config.get("source_code", "ppra_punjab"),
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
    try:
        pages = capture_pages()
    except Exception as exc:
        log(f"capture failed: {exc}")
        return 1
    log(f"captured {len(pages)} page(s); submitting")
    result = submit(pages, config)
    log(
        "submitted: {notices} notices, {new} new, {scored} scored, health {health}".format(
            **result
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
