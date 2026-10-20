"""Live reading from the federal EPMS portal (PPRA).

The EPMS active-tenders list is a server-rendered table: one `cb-rt-main` row
per tender, followed by a `cb-rt-detail` row carrying the organisation. No
authentication is needed for the public list, and nothing here logs in.
"""

import html as html_lib
import json
import re

from bs4 import BeautifulSoup

from app.connectors.base import BaseConnector
from app.services.utils import parse_amount, parse_date


def _clean(text: str) -> str:
    """Unescape entities, including the double-escaped ones the portal emits."""
    if not text:
        return ""
    text = html_lib.unescape(text)
    if "&" in text:
        text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()

# A tender reference as EPMS prints it, e.g. "TS0000013042E" or "P149046".
TENDER_NO_RE = re.compile(r"\b(TS\d{6,}E|P\d{5,})\b")

# Categories the portal uses on its own listings. The internal categoriser
# works off these.
SOURCE_CATEGORY_BY_STATUS = {
    "published": "Tender Notice",
    "published corrigendum": "Corrigendum",
    "bidding closed": "Tender Notice",
}


class EPMSFederalConnector(BaseConnector):
    adapter = "epms_federal"
    label = "Federal EPMS / EPADS portal"

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
                    "buyer_name": item.get("buyer_name") or item.get("agency", ""),
                    "buyer_ref": item.get("buyer_ref") or item.get("reference", ""),
                    "source_category": item.get("source_category") or item.get("category", ""),
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
        while page <= self.pages_allowed():
            left, estimate = self.scan_budget()
            if left < estimate:
                # Not enough time left for another page. Stop with what has
                # been read rather than be cut off part way through.
                break
            url = f"{self.base_url}?page={page}"
            html = client.get(url)
            self.note_request()
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
        """Turn one page of the active-tenders table into notices."""
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", class_="cb-rt") or soup.find("table")
        if not table:
            return []

        notices = []
        pending = None
        for row in table.find_all("tr"):
            classes = row.get("class") or []
            if "cb-rt-main" in classes:
                pending = self._parse_main_row(row)
            elif "cb-rt-detail" in classes and pending is not None:
                self._apply_detail_row(pending, row)
                notices.append(pending)
                pending = None
        return notices

    def _parse_main_row(self, row):
        cells = row.find_all("td")
        if len(cells) < 7:
            return None

        # Tender number lives in the "Tender No" cell, and again in the link
        # to the notice detail page.
        number_el = cells[2].select_one(".cb-rt-name") or cells[2].find("strong")
        tender_no = _clean(number_el.get_text(" ", strip=True)) if number_el else ""

        detail_link = None
        for a in cells[7].find_all("a", href=True) if len(cells) > 7 else []:
            if "tender-details" in a["href"]:
                detail_link = a["href"]
                break
        if not detail_link:
            for a in row.find_all("a", href=True):
                if "tender-details" in a["href"]:
                    detail_link = a["href"]
                    break
        if not detail_link:
            return None
        if not tender_no:
            match = TENDER_NO_RE.search(detail_link)
            tender_no = match.group(1) if match else detail_link.rstrip("/").split("/")[-1]

        # Title cell: the first strong is the title, the rest are notes.
        detail_cell = cells[3]
        strong = detail_cell.find("strong")
        title = _clean(strong.get_text(" ", strip=True)) if strong else _clean(detail_cell.get_text(" ", strip=True))
        notes = [
            _clean(s.get_text(" ", strip=True))
            for s in detail_cell.find_all("small")
            if s.get_text(" ", strip=True)
        ]
        category = ""
        for badge in detail_cell.find_all("span", class_="badge"):
            text = _clean(badge.get_text(" ", strip=True))
            if text and text not in notes:
                category = text
                break

        status = _clean(cells[4].get_text(" ", strip=True))
        advertised = _clean(cells[5].get_text(" ", strip=True))
        closing = _clean(cells[6].get_text(" ", strip=True))

        return {
            "native_id": tender_no,
            "url": self.abs_url(detail_link),
            "title": title,
            "buyer_name": "",
            "buyer_ref": tender_no,
            "portal_reference": tender_no,
            "source_category": category or SOURCE_CATEGORY_BY_STATUS.get(status.lower(), ""),
            "city": "",
            "area": self.source.area or "Federal",
            "estimated_value": None,
            "published_at": parse_date(advertised),
            "submission_deadline": parse_date(closing),
            "opening_at": None,
            "description": " ".join(notes[:3]),
            "status": status,
            # The portal marks a correction of a tender it already published.
            # It is the same tender, not a second one.
            "notice_status": "Corrigendum" if "corrigendum" in status.lower() else "Published",
            "_detail_fields": {},
        }

    def _apply_detail_row(self, notice, row):
        """Read the organisation card that follows a tender row."""
        fields = {}
        values = {}
        for label in row.select(".cb-rt-dl"):
            value = label.find_next_sibling(class_="cb-rt-dv")
            if value is None:
                continue
            key = label.get_text(" ", strip=True)
            fields[key] = value.get_text(" ", strip=True)
            values[key] = value
        notice["_detail_fields"] = fields

        org_node = values.get("Organization")
        if org_node is not None:
            # The card holds the organisation, the department and the city as
            # three separate elements. Reading them as one string repeats the
            # organisation twice and swallows the city.
            strong = org_node.find("strong")
            buyer = strong.get_text(" ", strip=True) if strong else ""
            buyer = _clean(buyer)
            department = ""
            for span in org_node.find_all("span"):
                text = span.get_text(" ", strip=True)
                if text and text != buyer:
                    department = _clean(text)
                    break
            city = ""
            for small in org_node.find_all("small"):
                text = _clean(small.get_text(" ", strip=True))
                if text:
                    city = re.sub(r"\s*-\s*Pakistan.*$", "", text).strip(" ,.-")
                    break
            notice["buyer_name"] = buyer or notice.get("buyer_name", "")
            notice["city"] = city
            if department and buyer:
                notice["buyer_name"] = f"{buyer} — {department}"

        for key, target in (
            ("Tender Fee", "tender_fee"),
            ("Estimated Cost", "estimated_value"),
            ("Security Amount", "bid_security_amount"),
        ):
            raw = fields.get(key, "")
            if raw:
                amount = parse_amount(raw)
                if amount is not None:
                    notice[target] = amount

    def fetch_detail(self, native_id):
        """Read one notice's detail page for the extra fields the list omits."""
        if self.fixture_mode or not native_id:
            return None
        url = f"{self.base_url.rstrip('/')}/tender-details/{native_id}"
        try:
            html = self.client().get(url)
        except Exception:
            return None
        return {"url": url, "html": html}
