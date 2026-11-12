"""Live reading from NTDC.

NTDC's public site is an Angular application whose data comes from a public
JSON endpoint: `/ntdc/api/tenders`. No session or key is involved, and the
endpoint returns the whole tender history, so only recent records are taken.
"""

import json
import re
from urllib.parse import quote

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


def encode_path(path: str) -> str:
    """Percent-encode a published file path so the link cannot be truncated.

    NTDC's file names carry spaces, brackets and the occasional '#'. Left
    raw, the '#' would cut the link short at the fragment and the rest of the
    file name would never be sent to the server, so the link would open the
    wrong thing — or nothing at all.

    The '%' is kept as a safe character so a path that is already encoded is
    not encoded a second time.
    """
    if not path:
        return ""
    return quote(path, safe="/%")


def extract_reference(title: str) -> str:
    """Pull the reference number a buyer published the notice under."""
    if not title:
        return ""
    for pattern in REFERENCE_PATTERNS:
        match = pattern.search(title)
        if match:
            return match.group(1).strip(" .:-")
    return ""


# The families of document a buyer publishes against a tender. The title
# NTDC gives the file says which family it is, and the bid team needs to know
# whether they are looking at a change to the scope or a question and answer.
RELATED_KINDS = [
    ("clarification", ("clarification", "clarifications", "query", "queries", "q&a", "pre-bid", "prebid", "pre bid")),
    ("amendment", ("amendment", "amendments", "addendum", "addenda")),
    ("corrigendum", ("corrigendum", "corrigenda", "revision", "revised")),
    ("evaluation", ("evaluation", "evalution", "result", "award")),
]


def classify_related(title: str) -> str:
    """Which family of document a related file belongs to."""
    text = (title or "").lower()
    for kind, keywords in RELATED_KINDS:
        if any(keyword in text for keyword in keywords):
            return kind
    return "related"


class NTDCConnector(BaseConnector):
    adapter = "ntdc"
    label = "NTDC tender notices (public JSON feed)"

    # The public feed behind the site's tender page. The page itself is an
    # Angular shell with no markup to read; this is where the notices live.
    API_URL = "https://ntdc.gov.pk/ntdc/api/tenders"
    # The tenders listing a reader can open and search. The site is a
    # single-page application, so this path is a route in its bundle rather
    # than a server-rendered page — but it is the real page, and it is where
    # a person goes to look for a tender by its reference.
    LISTING_URL = "https://ntdc.gov.pk/tendors"
    # Where a notice document is served from.
    #
    # The feed returns a site-root path such as "/bidding/IFB ....pdf", and
    # the file is served from the site root itself. It used to be read as
    # living under "/uploads", which is wrong: that path does not exist, and
    # because the site answers every unknown path with its single-page
    # application shell, the link answered 200 with an HTML page. A bid
    # team clicking it got a web page rather than the bidding document, and
    # nothing looked broken.
    DOCUMENT_BASE = "https://ntdc.gov.pk"

    def __init__(self, source):
        super().__init__(source)
        # Every tender the portal still publishes, indexed by its own id.
        # Filled by parse_feed from the whole feed, so a tender that is on
        # file can be pointed at its file even once it has aged out of the
        # window the notices are taken from.
        self.document_index = {}

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
            document = item.get("document_url", "")
            notices.append(
                {
                    "native_id": item.get("native_id") or item.get("id") or "",
                    # The same rule as the live feed: the notice link opens the
                    # tender's own file, and falls back to the listing when
                    # the capture carries no file.
                    "url": item.get("url") or self.notice_url(document),
                    "document_url": document,
                    "related_documents": item.get("related_documents", []) or [],
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

        The whole feed is also indexed by native id, so a tender that is
        already on file can be pointed at its own file even after it has
        aged out of the window the notices are taken from. The portal keeps
        the tender's file for years; only the window that decides what is
        *new* moves.
        """
        from app.config import settings
        from datetime import timedelta

        from app.services.utils import utcnow

        records = payload if isinstance(payload, list) else payload.get("data", [])

        self.document_index = {}
        for record in records:
            if not isinstance(record, dict):
                continue
            native_id = f"ntdc-{record.get('id')}"
            path = record.get("path") or ""
            self.document_index[native_id] = {
                "document_url": self.document_url(path),
                "related_documents": self.related_documents(record),
            }

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
            related = self.related_documents(record)
            description_parts = []
            if related:
                names = [r.get("title") for r in related if r.get("title")]
                if names:
                    description_parts.append("Amendments: " + "; ".join(names[:4]))

            notices.append(
                {
                    "native_id": f"ntdc-{record.get('id')}",
                    # The link that opens this tender. NTDC has no page per
                    # notice, so it points at the tender's own file.
                    "url": self.notice_url(document),
                    # The bidding document itself, which is what the bid team
                    # actually needs to open.
                    "document_url": self.document_url(document),
                    # The clarifications, amendments and addenda the buyer
                    # published against this tender.
                    "related_documents": related,
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
                    # deadline comes out of the notice document at Stage 2.
                    "submission_deadline": None,
                    "opening_at": None,
                    "description": " ".join(description_parts),
                }
            )
        return notices

    def related_documents(self, record: dict) -> list:
        """The clarifications, amendments and addenda for one notice.

        The feed carries them against the notice they belong to, each with
        its own title, file and date. They are kept as structured entries
        rather than being flattened into the description, because the bid
        team has to be able to open each one — an amendment that changes a
        deadline is not the same as a site notice attached to a tender.
        """
        out = []
        for item in record.get("ammendments") or []:
            if not isinstance(item, dict):
                continue
            path = item.get("path") or ""
            if not path:
                continue
            title = (item.get("title") or "").strip()
            out.append(
                {
                    "title": title or "Amendment",
                    "url": self.document_url(path),
                    "date": item.get("date") or "",
                    "kind": classify_related(title),
                    "source_id": item.get("id"),
                }
            )
        return out

    def fetch_documents(self, native_id, ref=None):
        """The bidding document, and every clarification published with it.

        The document link is kept on the stored reference, so the tender
        record can always point at the file on the authority's own site even
        when the download itself is not possible.
        """
        if not native_id:
            return None

        if self.fixture_mode:
            return self._documents_from_fixture(native_id)

        ref = ref or {}
        documents = []

        document_url = ref.get("document_url") or ""
        if document_url:
            fetched = self.download_document(document_url)
            if fetched:
                filename, content = fetched
                documents.append((filename, content))

        for related in ref.get("related_documents") or []:
            if not isinstance(related, dict):
                continue
            url = related.get("url") or ""
            if not url:
                continue
            fetched = self.download_document(url)
            if fetched:
                filename, content = fetched
                documents.append((filename, content))

        return documents or None

    def _documents_from_fixture(self, native_id: str):
        """The saved capture of the notice's documents."""
        path = self.fixture_path("documents.json")
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        docs = payload.get(native_id)
        if not docs:
            return None
        out = []
        for doc in docs:
            filename = doc.get("filename") or f"{native_id}.txt"
            content = doc.get("content") or ""
            out.append((filename, content.encode("utf-8")))
        return out or None

    def document_url(self, path: str) -> str:
        """Where a notice document is served from.

        The feed returns a site-root path such as "/bidding/IFB ....pdf"; the
        documents are served from the site root itself.
        """
        if not path:
            return self.DOCUMENT_BASE
        if path.startswith("http://") or path.startswith("https://"):
            return path
        # The published file names carry spaces, brackets and the occasional
        # '#'. Left raw, the '#' would cut the link short at the fragment and
        # the rest of the file name would never be sent to the server, so the
        # link would open the wrong thing — or nothing at all.
        return f"{self.DOCUMENT_BASE}{encode_path(path)}"

    def notice_url(self, path: str) -> str:
        """Where a reader should go to open this tender.

        NTDC publishes no page per notice. Its tenders page is a single-page
        application that opens each tender in a dialog, so there is no
        addressable URL for one tender — the tender is a file, and that file
        is what the notice link points at. Sending the reader to the tenders
        listing instead means they land on the NTDC home page with no sign of
        the tender they asked for, which is what the link used to do.

        Nine notices in the feed carry no file at all; for those the listing
        is the only place the notice can be seen, so it stays.
        """
        if not path:
            return self.LISTING_URL
        return self.document_url(path)
