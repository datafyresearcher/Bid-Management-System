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
    .venv/Scripts/pip install playwright httpx curl_cffi pypdf
    copy config.example.json config.json   (fill in the secret)

Run by hand:

    .venv/Scripts/python capture.py

The scheduled task registered by register-task.ps1 runs this under the
venv's pythonw.exe instead, so no console window opens on the desktop.
pythonw has no stdout, which is why every log line goes to bridge.log.

The value for `secret` is the repository's BMS_CAPTURE_SECRET — the same value
the deploy pipeline gives the API. `sources` lists which portals to capture
(default: PPRA Punjab only).
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

CONFIG_PATH = Path(__file__).with_name("config.json")
LOG_PATH = Path(__file__).with_name("bridge.log")

MAX_PAGES = 15

# The largest document that may be carried over in one request. The API is
# deployed on a platform that caps the size of a request body, and the
# biggest bidding documents run past it. A file over this size is handed
# over as the text read from it instead.
MAX_UPLOAD_BYTES = 3_500_000


def log(message: str):
    """Log to bridge.log and, when a console exists, stdout as well.

    The log file is the log of record because the scheduled task runs this
    under pythonw.exe, where sys.stdout is None and print would raise.
    """
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {message}"
    try:
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 512 * 1024:
            LOG_PATH.replace(LOG_PATH.with_suffix(".log.old"))
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
    if sys.stdout is not None:
        print(line, flush=True)


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


def extract_text(content: bytes) -> str:
    """The text of a tender document, read here on the desk's machine.

    A file too large to carry over whole is handed over as its text, because
    what the analysis needs is the words, not the file. The portal's own copy
    stays one click away on the record, so nothing is lost by it.
    """
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    return "\n\f\n".join((page.extract_text() or "") for page in reader.pages)


TESSERACT_CANDIDATES = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)

# Below this many characters a PDF's text is treated as unreadable. A scanned
# page yields a stray header or nothing at all; a real page yields hundreds.
MIN_TEXT_CHARS_PER_PAGE = 120


def ocr_pdf(content: bytes) -> str:
    """The text of a scanned tender document, read with OCR.

    The authorities publish their notices as scans more often than they
    should — a two-page NIT whose every page is a photograph. A text reader
    gets a handful of characters out of it and the analysis is left with
    nothing, so the record honestly reports it could not read the document.
    The scan's own images, though, hold the words, and an OCR pass on this
    machine reads them back.

    Every page's embedded image is run through Tesseract. A page that yields
    an image too small to be a scan — a logo, a signature strip — is passed
    over. Small scans are enlarged first, because OCR accuracy falls away
    below roughly 1500 pixels of width.
    """
    import io

    import pytesseract
    from PIL import Image
    from pypdf import PdfReader

    for candidate in TESSERACT_CANDIDATES:
        if os.path.exists(candidate):
            pytesseract.pytesseract.tesseract_cmd = candidate
            break
    # Neither candidate exists — the binary may still be on the PATH. This
    # raises, with Tesseract's own error, when it is not.
    pytesseract.get_tesseract_version()

    reader = PdfReader(io.BytesIO(content))
    pages = []
    for page in reader.pages:
        page_text = []
        for image_info in page.images:
            image = Image.open(io.BytesIO(image_info.data))
            if image.width < 300:
                continue
            if image.width < 1500:
                ratio = 1500 / image.width
                image = image.resize((int(image.width * ratio), int(image.height * ratio)))
            page_text.append(pytesseract.image_to_string(image, lang="eng"))
        pages.append("\n".join(page_text))
    return "\n\f\n".join(pages)


def readable_text(content: bytes, name: str) -> str | None:
    """The text of a tender document, with scans read by OCR.

    Returns the text when the document can be read, or None when it cannot —
    the caller then hands the file over whole and lets the API's own reader
    deal with it. A PDF whose text comes back nearly empty is a scan, and the
    scan is OCR'd here, where the words are turned into text the analysis can
    read. The OCR'd text is what is carried over, so the record ends up with
    something to analyse either way.
    """
    if not name.lower().endswith(".pdf"):
        return None
    try:
        text = extract_text(content)
    except Exception as exc:
        log(f"{name} could not be read as a PDF: {exc}")
        return None
    from pypdf import PdfReader
    import io

    try:
        pages = max(1, len(PdfReader(io.BytesIO(content)).pages))
    except Exception:
        pages = 1
    if len(text.strip()) >= MIN_TEXT_CHARS_PER_PAGE * pages:
        return None  # a text PDF — the API's own reader handles it well
    log(f"{name} looks like a scan — its pages are being read with OCR")
    try:
        ocr_text = ocr_pdf(content)
    except Exception as exc:
        log(f"{name} could not be OCR'd: {exc}")
        return None
    if len(ocr_text.strip()) < MIN_TEXT_CHARS_PER_PAGE:
        log(f"{name} held nothing the OCR could read either")
        return ocr_text
    log(f"{name}: OCR read {len(ocr_text.strip())} characters out of the scan")
    return ocr_text


def push_documents(config: dict) -> dict:
    """Fetch the tender documents the cloud cannot reach, and hand them over.

    The portal refuses connections from datacenter networks, so the documents
    it publishes can only be fetched from a machine the portal answers — this
    one. The bid manager approves a tender in the cloud, the record is marked
    as waiting for its document, and this run fetches it and brings it over.

    The document is fetched with a browser's TLS handshake, because a plain
    client is turned away at the handshake itself.
    """
    headers = {"X-Capture-Secret": config["secret"]}
    api_url = config["api_url"].rstrip("/")

    try:
        response = httpx.get(
            f"{api_url}/api/sources/documents-pending", headers=headers, timeout=60
        )
        if response.status_code != 200:
            log(f"could not ask for the pending documents: HTTP {response.status_code}")
            return {"tenders": 0, "documents": 0, "failed": 0}
        pending = response.json()
    except Exception as exc:
        log(f"could not ask for the pending documents: {exc}")
        return {"tenders": 0, "documents": 0, "failed": 0}

    if not pending:
        log("no tender is waiting for a document")
        return {"tenders": 0, "documents": 0, "failed": 0}

    from curl_cffi import requests as curl_requests

    brought = 0
    failed = 0
    for item in pending:
        for document in item.get("documents") or []:
            url = document.get("url") or ""
            if not url:
                continue
            name = document.get("filename") or url.rsplit("/", 1)[-1]
            try:
                response = curl_requests.get(url, impersonate="chrome124", timeout=180)
                if response.status_code >= 400:
                    raise RuntimeError(f"HTTP {response.status_code}")
                content = response.content
                if not content:
                    raise RuntimeError("empty response")
            except Exception as exc:
                log(f"could not fetch {name}: {exc}")
                failed += 1
                continue

            # A request body is capped, and the largest bidding documents run
            # past what may be carried over in one piece. What the analysis
            # reads is the text, so an oversized file is handed over as the
            # text read from it — with the address it was read from, so the
            # record knows the document has been dealt with.
            #
            # And a scan is read here whatever its size. The authorities
            # publish notices as photographs more often than they should: a
            # PDF handed over whole reads as nothing on the API's side, and
            # the record is left honestly reporting it could not read the
            # document. The words are in the scan, and the OCR reads them
            # back — so the text is carried over instead of the image.
            if len(content) > MAX_UPLOAD_BYTES:
                text = readable_text(content, name)
                if text is None:
                    try:
                        text = extract_text(content)
                    except Exception as exc:
                        log(f"{name} is too large to carry over and its text could not be read: {exc}")
                        failed += 1
                        continue
                content = text.encode("utf-8")
                name = f"{name.rsplit('.', 1)[0]}.txt"
                log(f"{name} was too large to carry over whole — its text was carried over instead")
            elif name.lower().endswith(".pdf"):
                text = readable_text(content, name)
                if text is not None:
                    content = text.encode("utf-8")
                    name = f"{name.rsplit('.', 1)[0]}.txt"

            try:
                response = httpx.post(
                    f"{api_url}/api/sources/capture/document",
                    headers=headers,
                    data={
                        "opportunity_id": str(item.get("opportunity_id")),
                        "filename": name,
                        "kind": document.get("kind") or "bidding document",
                        "source_url": url,
                    },
                    files={"file": (name, content, "application/pdf")},
                    timeout=300,
                )
            except Exception as exc:
                log(f"could not hand over {name}: {exc}")
                failed += 1
                continue

            if response.status_code != 200:
                log(f"the API refused {name}: HTTP {response.status_code} {response.text[:200]}")
                failed += 1
                continue

            body = response.json()
            brought += 1
            log(
                "tender {id}: {name} brought over — bid security {amount} at {percent}%, "
                "implied BOQ {boq}".format(
                    id=item.get("opportunity_id"),
                    name=name,
                    amount=body.get("bid_security_amount"),
                    percent=body.get("bid_security_percent"),
                    boq=body.get("estimated_boq_value"),
                )
            )

    log(f"documents: {brought} brought over, {failed} could not be fetched")
    return {"tenders": len(pending), "documents": brought, "failed": failed}


def main() -> int:
    if not CONFIG_PATH.exists():
        log("config.json is missing — copy config.example.json and fill it in.")
        return 1
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    sources = config.get("sources") or ["ppra_punjab"]
    unknown = [code for code in sources if code not in CAPTURES]
    if unknown:
        log(f"no capture routine for: {', '.join(unknown)}")
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

    # The documents themselves, for the tenders the bid team has approved and
    # whose portal cannot be reached from the cloud.
    try:
        result = push_documents(config)
        log(
            "documents: {tenders} tender(s) waiting, {documents} brought over, {failed} failed".format(
                **result
            )
        )
    except Exception as exc:
        log(f"the document step failed: {exc}")
        failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
