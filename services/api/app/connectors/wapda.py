"""Live reading from WAPDA.

WAPDA publishes its tender notices as ordinary WordPress posts. The listing
page is server-rendered, so the notices can be read directly — no browser
automation and no session.
"""

import json
import re

from bs4 import BeautifulSoup

from app.connectors.base import BaseConnector
from app.services.utils import parse_date

# The listing renders each notice as a post with a title link and a date.
POST_TITLE_CLASS = "wp-block-post-title"

# The WordPress query variable behind the listing's pagination.
PAGE_QUERY = "query-4-page"

# A tender reference as WAPDA writes it, e.g. "WAPDA TENDER NO-30". The word
# boundary matters: without it "Tender Notice" is read as "Tender No.".
REFERENCE_RE = re.compile(
    r"\b(?:WAPDA\s*)?TENDER\s*(?:NO\.?|NUMBER)\b\.?\s*[:#\-]?\s*([A-Z0-9][A-Z0-9/\(\)\.\-]{2,40})",
    re.I,
)


class WAPDAConnector(BaseConnector):
    adapter = "wapda"
    label = "WAPDA tender notices"

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
            # The listing keeps its trailing slash; the pager query hangs off it.
            root = self.base_url + "/"
            url = root if page == 1 else f"{root}?{PAGE_QUERY}={page}"
            html = client.get(url)
            self.last_raw = html
            page_notices = self.parse_listing(html)
            if not page_notices:
                break
            added = 0
            for notice in page_notices:
                if notice["url"] in seen:
                    continue
                seen.add(notice["url"])
                notices.append(notice)
                added += 1
            if not added:
                break
            page += 1
        return notices

    def parse_listing(self, html: str):
        soup = BeautifulSoup(html, "html.parser")
        buyer = self.source.name or "Pakistan Water and Power Development Authority (WAPDA)"
        notices = []
        for post in soup.select("li.wp-block-post"):
            heading = post.select_one(f"h4.{POST_TITLE_CLASS} a")
            if heading is None:
                continue
            title = heading.get_text(" ", strip=True)
            link = heading.get("href") or ""
            if not title or not link:
                continue

            published = ""
            for node in post.find_all(["time", "span", "div"]):
                classes = " ".join(node.get("class") or [])
                if re.search(r"date|time", classes, re.I):
                    candidate = node.get_text(" ", strip=True)
                    if candidate:
                        published = candidate
                        break
            if not published:
                published = post.get_text(" ", strip=True)

            reference = ""
            match = REFERENCE_RE.search(title)
            if match:
                reference = match.group(1).strip(" .:-")

            # The notice's own address is the one identifier the listing gives
            # every notice, so it stands in when the title prints no number.
            slug = link.rstrip("/").split("/")[-1]

            notices.append(
                {
                    "native_id": f"wapda-{slug}",
                    "url": self.abs_url(link),
                    "title": title,
                    "buyer_name": buyer,
                    "buyer_ref": reference or f"WAPDA/{slug}",
                    "portal_reference": reference,
                    "source_category": "Tender Notice",
                    "city": "",
                    "area": self.source.area or "Federal",
                    "estimated_value": None,
                    "published_at": parse_date(published),
                    # The closing date is on the notice document, not the list.
                    "submission_deadline": None,
                    "opening_at": None,
                    "description": "",
                }
            )
        return notices
