"""Live reading from NTDC.

NTDC's public site is an Angular application whose data comes from a public
JSON endpoint: `/ntdc/api/tenders`. No session or key is involved, and the
endpoint returns the whole tender history, so only recent records are taken.
"""

import json
import re

from app.connectors.base import BaseConnector
from app.services.utils import parse_date

# The endpoint returns every notice the organisation has ever published. These
# categories are results and supporting papers rather than live opportunities.
SKIP_CATEGORIES = {"evaluation results", "tors"}

# A tender reference as NTDC writes it in a notice title.
REFERENCE_PATTERNS = [
    re.compile(r"(?:TENDER|IFB|EOI|RFP)\s*(?:NO\.?|NUMBER|NO)\s*[:#\-]?\s*([A-Z0-9][A-Z0-9/\(\)\.\-]{3,44}?\d{4}(?:-\d{2})?)", re.I),
    re.compile(r"\b((?:[A-Z]{2,6}[-/]){1,4}[A-Z0-9\-]{2,12}/\d{4}(?:-\d{2})?)\b"),
    re.compile(r"\b((?:RFP|IFB|EOI|TS|LOT)-[A-Z0-9\-]{4,30})\b", re.I),
]


def extract_reference(title: str) -> str:
    """Pull the reference number a buyer published the notice under."""
    if not title:
        return ""
    for pattern in REFERENCE_PATTERNS:
        match = pattern.search(title)
        if match:
            return match.group(1).strip(" .:-")
    return ""


class NTDCConnector(BaseConnector):
    adapter = "ntdc"
    label = "NTDC tender notices (public JSON feed)"

    # The public feed behind the site's tender page. The page itself is an
    # Angular shell with no markup to read; this is where the notices live.
    API_URL = "https://ntdc.gov.pk/ntdc/api/tenders"
    # Where a notice document is served from.
    DOCUMENT_BASE = "https://ntdc.gov.pk/uploads"

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

        api_url = self.API_URL

        client = self.client()
        raw = client.get(api_url)
        self.last_raw = raw
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # The endpoint sometimes answers with a JSON array served as text.
            payload = json.loads(raw[raw.find("["):raw.rfind("]") + 1])
        return self.parse_feed(payload)

    def parse_feed(self, payload):
        """Turn the tender feed into notices.

        The endpoint returns every notice the organisation has ever published,
        so only the recent ones are taken and the categories that are results
        rather than opportunities are left out.
        """
        from app.config import settings
        from datetime import timedelta

        from app.services.utils import utcnow

        records = payload if isinstance(payload, list) else payload.get("data", [])

        cutoff = utcnow() - timedelta(days=settings.live_lookback_days)
        buyer = self.source.name or "National Transmission & Despatch Company (NTDC)"
        notices = []
        for record in records:
            category = (record.get("name") or "").strip()
            if category.lower() in SKIP_CATEGORIES:
                continue
            published = parse_date(record.get("published_on"))
            if published is None or published < cutoff:
                continue

            title = (record.get("title") or "").strip()
            document = record.get("path") or ""
            amendments = record.get("ammendments") or []
            description_parts = []
            if amendments:
                names = [a.get("title") for a in amendments if a.get("title")]
                if names:
                    description_parts.append("Amendments: " + "; ".join(names[:4]))

            notices.append(
                {
                    "native_id": f"ntdc-{record.get('id')}",
                    "url": self.document_url(document),
                    "title": title,
                    "buyer_name": buyer,
                    "buyer_ref": extract_reference(title) or f"NTDC-{record.get('id')}",
                    "portal_reference": extract_reference(title),
                    "source_category": category or "Tender Notice",
                    "city": "",
                    "area": self.source.area or "Federal",
                    "estimated_value": None,
                    "published_at": published,
                    # NTDC does not publish a closing date on the feed. The
                    # deadline comes out of the notice document at Gate 2.
                    "submission_deadline": None,
                    "opening_at": None,
                    "description": " ".join(description_parts),
                }
            )
        return notices

    def document_url(self, path: str) -> str:
        """Where a notice document is served from.

        The feed returns a site-root path such as "/bidding/IFB ....pdf"; the
        documents themselves live under the site's uploads directory.
        """
        if not path:
            return self.DOCUMENT_BASE
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if path.startswith("/"):
            return f"{self.DOCUMENT_BASE}{path}"
        return f"{self.DOCUMENT_BASE}/{path}"
