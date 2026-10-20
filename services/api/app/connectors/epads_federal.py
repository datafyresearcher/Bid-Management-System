"""Live reading from EPADS, the federal e-Pak Acquisition and Disposal System.

EPADS publishes its open opportunities as a server-rendered table. The table
carries the title, the procuring agency, the agency's own reference number and
the publication date.

The notice detail page is rendered by JavaScript and exposes no reference in
its markup, so the closing date is not taken from here. Rather than guess at
it, the deadline is left empty and picked up later from the notice document.
"""

import json
import re

from bs4 import BeautifulSoup

from app.connectors.base import BaseConnector
from app.services.utils import parse_date

# The agency's own reference, e.g. "P146307".
REFERENCE_RE = re.compile(r"\b(P\d{4,})\b")

# "Closing On: 19h 33m Left" — a countdown, not a date.
CLOSING_RE = re.compile(r"Closing On:\s*([0-9dhms ]+Left)", re.I)

PUBLISHED_RE = re.compile(r"Published On:\s*([A-Za-z]+,\s*[A-Za-z]+\s+\d{1,2},\s*\d{4}[^C]*)", re.I)


def _clean_department(text: str) -> str:
    """Collapse the department name when the portal prints it twice.

    EPADS renders "Export-Import Bank of Pakistan (EXIM Bank) (Export-Import
    Bank of Pakistan (EXIM Bank))" — the same name once for display and once
    inside the tooltip.
    """
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return ""
    length = len(text)
    for cut in range(length // 2, 0, -1):
        head = text[:cut].strip()
        tail = text[cut:].strip().lstrip("(").rstrip(")").strip()
        if tail and tail == head:
            return head
    return text


class EPADSFederalConnector(BaseConnector):
    adapter = "epads_federal"
    label = "Federal EPADS (e-Pak Acquisition and Disposal System)"

    def fetch_listing(self):
        if self.fixture_mode:
            return self._from_fixture()
        return self._from_live()

    # -- fixture -------------------------------------------------------

    def _from_fixture(self):
        path = self.fixture_path("listings.json")
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.last_raw = json.dumps(payload)
        items = payload if isinstance(payload, list) else payload.get("notices", [])
        notices = []
        for item in items:
            notices.append(
                {
                    "native_id": item.get("native_id") or item.get("id") or "",
                    "url": item.get("url", self.base_url),
                    "title": item.get("title", ""),
                    "buyer_name": item.get("buyer_name", ""),
                    "buyer_ref": item.get("buyer_ref", ""),
                    "source_category": item.get("source_category", ""),
                    "city": item.get("city", ""),
                    "area": item.get("area", self.source.area or "Federal"),
                    "estimated_value": item.get("estimated_value"),
                    "published_at": item.get("published_at"),
                    "submission_deadline": item.get("submission_deadline"),
                    "opening_at": item.get("opening_at"),
                    "description": item.get("description", ""),
                }
            )
        return notices

    # -- live ----------------------------------------------------------

    def _from_live(self):
        from app.config import settings

        client = self.client()
        notices = []
        seen = set()
        page = 1
        while page <= settings.live_max_pages:
            url = self.base_url if page == 1 else f"{self.base_url}?page={page}"
            html = client.get(url)
            self.last_raw = html
            page_notices = self.parse_listing(html)
            if not page_notices:
                break
            added = 0
            for notice in page_notices:
                if notice["native_id"] in seen:
                    continue
                seen.add(notice["native_id"])
                notices.append(notice)
                added += 1
            if not added:
                break
            page += 1
        return notices

    def parse_listing(self, html: str):
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", class_="cb") or soup.find("table")
        if not table:
            return []

        notices = []
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) != 5:
                continue
            if not cells[0].get_text(strip=True).isdigit():
                continue

            title_cell = cells[1]
            link = None
            for a in title_cell.find_all("a", href=True):
                if "/opportunities/" in a["href"]:
                    link = a["href"]
                    break
            if link is None:
                continue

            # The cell is structured: a link holding the title, a span holding
            # the procuring agency, and a badge holding the reference. The
            # visible text is truncated, so the full values are read from the
            # tooltip attributes.
            tooltip = title_cell.select_one('[data-bs-toggle="tooltip"][title]')
            full_title = tooltip.get("title") if tooltip else ""
            title = full_title or title_cell.get_text(" ", strip=True)

            agency = ""
            for span in title_cell.find_all("span"):
                if span is tooltip:
                    continue
                tip = span.get("title") or ""
                if tip:
                    agency = tip.strip()
                    break

            reference = ""
            for badge in title_cell.select("span.badge"):
                text = badge.get_text(" ", strip=True)
                if text and REFERENCE_RE.match(text):
                    reference = text
                    break
            if not reference:
                match = REFERENCE_RE.search(title_cell.get_text(" ", strip=True))
                if match:
                    reference = match.group(1)

            status_text = cells[2].get_text(" ", strip=True)
            published = ""
            pmatch = PUBLISHED_RE.search(status_text)
            if pmatch:
                published = pmatch.group(1)
            closing_note = ""
            cmatch = CLOSING_RE.search(status_text)
            if cmatch:
                closing_note = cmatch.group(1).strip()

            procedure = cells[3].get_text(" ", strip=True)
            category = procedure.split(" Single Stage")[0].split(" Two Stage")[0].strip()

            identifier = link.rstrip("/").split("/")[-1]
            notices.append(
                {
                    "native_id": f"epads-{identifier}",
                    "url": self.abs_url(link),
                    "title": title.strip(),
                    "buyer_name": _clean_department(agency),
                    "buyer_ref": reference or f"EPADS/{identifier}",
                    "portal_reference": reference,
                    "source_category": category,
                    "city": "",
                    "area": self.source.area or "Federal",
                    "estimated_value": None,
                    "published_at": parse_date(published),
                    # EPADS publishes a countdown rather than a closing date,
                    # and the detail page renders its dates in JavaScript. The
                    # deadline is left empty rather than estimated.
                    "submission_deadline": None,
                    "opening_at": None,
                    "description": " ".join(x for x in [procedure, closing_note] if x),
                }
            )
        return notices
