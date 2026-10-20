"""Reading the PPRA Punjab Active Procurement portal.

Two shapes have to be handled:

* The **live** listing is an ASP.NET WebForms grid. Moving between pages is a
  form post rather than a URL: the page returns a `__VIEWSTATE` and
  `__EVENTVALIDATION` token that the next post has to carry back, and the
  pager's postback target is read from the page rather than guessed.
* The **saved capture** used in demo mode is a plain HTML table with arbitrary
  column headings, so it is read by matching headings rather than positions.

The grid has nine columns: notice kind, procurement name, type, publish date,
close date, department, status, tender-notice document and bidding document.
Plain tender notices carry no detail page link — only corrigenda do — so a
notice is identified by its notice document, which every row has.

Only the public listing is read. Nothing here signs in, and the supplier
registration and captcha pages are left alone.
"""

import hashlib
import json
import re

from bs4 import BeautifulSoup

from app.connectors.base import BaseConnector
from app.services.utils import parse_amount, parse_date

GRID_ID = "ctl00_ContentPlaceHolderSRIS_rdgrdManageTender_ctl00"

# The grid's first column is a heading, not a notice.
HEADER_CELL = "Procurement Title"

# The detail page the grid links on a corrigendum row.
DETAIL_RE = re.compile(r"ActiveTendersDetail\.aspx\?id=(\d+)")

# A tender reference as Punjab notices write it, e.g. "IPL-10316". The word
# boundary matters: without it "Tender Notice" is read as "Tender No." and the
# reference comes out as "TICE".
REFERENCE_RE = re.compile(
    r"\b(?:Tender|IFB|NIT|Lot)\s*(?:No\.?|Number|#)\b\.?\s*[:#\-]?\s*([A-Z0-9][A-Z0-9/\(\)\.\-]{3,44})",
    re.I,
)

# Hidden form fields ASP.NET requires to be echoed back.
STATE_FIELDS = (
    "__VIEWSTATE",
    "__VIEWSTATEGENERATOR",
    "__EVENTVALIDATION",
    "__SCROLLPOSITIONX",
    "__SCROLLPOSITIONY",
    "__LASTFOCUS",
    "__EVENTTARGET",
    "__EVENTARGUMENT",
)

# The pager's postback targets, read off the page: the anchor text is the page
# number and the href carries the control that has to be posted back.
POSTBACK_RE = re.compile(r"__doPostBack\('([^']+)'")

HEADER_HINTS = {
    "title": ["tender description", "description of work", "tender title", "name of work", "title"],
    "ref": ["tender ref", "ref no", "reference", "tender no"],
    "buyer": ["department", "procuring", "organisation", "organization", "employer", "buyer", "office"],
    "city": ["city", "district"],
    "category": ["category", "pec code", "sector", "type of work"],
    "value": ["estimated cost", "estimated amount", "estimated value", "cost"],
    "published": ["publication", "published", "upload"],
    "deadline": ["last date of submission", "submission date", "closing", "last date"],
    "opening": ["opening date", "date of opening", "opening"],
}


def _match_column(header: str):
    h = (header or "").lower()
    for field, hints in HEADER_HINTS.items():
        if any(hint in h for hint in hints):
            return field
    return None


class PPRAPunjabConnector(BaseConnector):
    adapter = "ppra_punjab"
    label = "PPRA Punjab e-Procurement portal"

    def fetch_listing(self):
        if self.fixture_mode:
            return self._from_fixture()
        return self._from_live()

    # -- saved capture --------------------------------------------------

    def _from_fixture(self):
        path = self.fixture_path("listings.html")
        if not path.exists():
            return []
        html = path.read_text(encoding="utf-8")
        self.last_raw = html
        return self.parse_listing(html)

    def parse_listing(self, html: str):
        """Read a capture whose columns are matched by heading."""
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if not table:
            return []
        rows = table.find_all("tr")
        columns = {}
        notices = []
        for row in rows:
            cells = row.find_all(["th", "td"])
            if not cells:
                continue
            texts = [c.get_text(" ", strip=True) for c in cells]
            if not columns:
                mapped = [_match_column(t) for t in texts]
                if sum(1 for m in mapped if m) >= 3:
                    columns = {i: field for i, field in enumerate(mapped) if field}
                    continue
            if not columns:
                continue
            data = {}
            for i, field in columns.items():
                if i < len(texts):
                    data[field] = texts[i]
            title = data.get("title", "").strip()
            if not title or _match_column(title):
                continue
            ref = data.get("ref", "").strip()
            notices.append(
                {
                    "native_id": ref or f"row-{len(notices) + 1}",
                    "url": f"{self.base_url}#{ref}" if self.base_url else "",
                    "title": title,
                    "buyer_name": data.get("buyer", ""),
                    "buyer_ref": ref,
                    "source_category": data.get("category", ""),
                    "city": data.get("city", ""),
                    "area": self.source.area or "Punjab",
                    "estimated_value": parse_amount(data.get("value")),
                    "published_at": parse_date(data.get("published")),
                    "submission_deadline": parse_date(data.get("deadline")),
                    "opening_at": parse_date(data.get("opening")),
                    "description": "",
                }
            )
        return notices

    # -- live ----------------------------------------------------------

    def _from_live(self):
        from app.config import settings

        client = self.client()
        html = client.get(self.base_url)
        self.note_request()
        self.last_raw = html
        notices = self.parse_grid(html)
        seen = {n["native_id"] for n in notices}

        # Walk the remaining pages. Each page is a postback that carries the
        # state tokens from the previous response, and the target of the
        # postback is the pager's own control id.
        state = self._state(html)
        targets = self._pager_targets(html)
        page = 2
        while page <= settings.live_max_pages:
            left, estimate = self.scan_budget()
            if left < estimate:
                # Not enough time left for another page. Stop with what has
                # been read rather than be cut off part way through.
                break
            target = targets.get(page)
            if not target:
                break
            payload = dict(state)
            payload["__EVENTTARGET"] = target
            payload["__EVENTARGUMENT"] = ""
            try:
                html = client.post(self.base_url, payload)
            except Exception:
                break
            self.note_request()
            self.last_raw = html
            page_notices = self.parse_grid(html)
            fresh = [n for n in page_notices if n["native_id"] not in seen]
            if not fresh:
                # The pager did not move on. Stop rather than repeat a page.
                break
            seen.update(n["native_id"] for n in fresh)
            notices.extend(fresh)
            state = self._state(html)
            targets = self._pager_targets(html)
            page += 1

        return self._resolve_corrigenda(client, self._merge_corrigenda(notices))

    def _merge_corrigenda(self, notices: list) -> list:
        """Pair a corrigendum with the notice it corrects, where it is clear.

        The portal lists a corrigendum as a notice of its own, so the same
        tender can appear twice — once as the original notice and once as the
        correction. A corrigendum and its original carry the same procurement
        name and the same department, so a pair that is the only one of its
        kind can be tied together here. Where more than one notice shares
        those two details the pairing is left alone: which notice is the
        original is then not knowable from the listing, and guessing would
        merge two different tenders.
        """
        groups: dict = {}
        for notice in notices:
            key = (notice["title"].strip().upper(), notice["buyer_name"].strip().upper())
            groups.setdefault(key, []).append(notice)

        for group in groups.values():
            if len(group) != 2:
                continue
            corrigenda = [n for n in group if n.get("notice_status") == "Corrigendum"]
            originals = [n for n in group if n.get("notice_status") != "Corrigendum"]
            if len(corrigenda) != 1 or len(originals) != 1:
                continue
            corrigendum, original = corrigenda[0], originals[0]
            corrigendum["native_id"] = original["native_id"]
            corrigendum["buyer_ref"] = original["buyer_ref"]
            # The tender was first published with the original notice.
            if original.get("published_at"):
                corrigendum["published_at"] = original["published_at"]
            corrigendum["_paired"] = True
        return notices

    def _resolve_corrigenda(self, client, notices: list) -> list:
        """Tie a corrigendum to the tender it corrects through its detail page.

        The corrigendum's detail page names the notice document of the tender
        being corrected, which is the one identifier both rows share. Reading
        it settles the pairing for the cases the listing cannot: a correction
        whose original sits outside the pages being read.
        """
        from app.config import settings

        budget = settings.live_max_details
        for notice in notices:
            if not notice.get("detail_url") or notice.get("_paired") or budget <= 0:
                continue
            left, estimate = self.scan_budget()
            if left < estimate:
                # The detail pages are the slow ones. Stop while there is
                # still time for the scan to finish and be recorded.
                break
            budget -= 1
            try:
                html = client.get(notice["detail_url"])
            except Exception:
                continue
            self.note_request()
            fields = self._detail_fields(html)
            parent_stem = self._document_stem(fields.get("Tender Notice", {}).get("links", []))
            if not parent_stem:
                continue
            notice["native_id"] = f"ppra-{parent_stem}"
            notice["buyer_ref"] = f"PPRA/{parent_stem}"
            # The tender was first published on the original notice's date.
            parent_published = parse_date(fields.get("Publish Date", {}).get("text", ""))
            if parent_published:
                notice["published_at"] = parent_published
            parent_name = fields.get("Procurement Name", {}).get("text", "")
            if parent_name:
                notice["parent_title"] = parent_name
        return notices

    @staticmethod
    def _detail_fields(html: str) -> dict:
        """The label/value rows of a notice's detail page."""
        soup = BeautifulSoup(html, "html.parser")
        fields = {}
        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if len(cells) != 2:
                    continue
                label = cells[0].get_text(" ", strip=True).rstrip(":").strip()
                if not label or label in fields:
                    continue
                fields[label] = {
                    "text": cells[1].get_text(" ", strip=True),
                    "links": [a["href"] for a in cells[1].find_all("a", href=True) if a["href"]],
                }
        return fields

    @staticmethod
    def _document_stem(links: list) -> str:
        """The file name of a notice document, without its folder or extension."""
        for link in links:
            if not link:
                continue
            name = link.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            if name:
                return name
        return ""

    def _state(self, html: str) -> dict:
        """The hidden fields the next postback has to echo back."""
        soup = BeautifulSoup(html, "html.parser")
        state = {}
        for name in STATE_FIELDS:
            node = soup.find("input", attrs={"name": name})
            if node is not None:
                state[name] = node.get("value") or ""
        state.setdefault("__EVENTTARGET", "")
        state.setdefault("__EVENTARGUMENT", "")
        state.setdefault("__SCROLLPOSITIONX", "0")
        state.setdefault("__SCROLLPOSITIONY", "0")
        return state

    def _pager_targets(self, html: str) -> dict:
        """The postback target for each page number the pager offers."""
        soup = BeautifulSoup(html, "html.parser")
        targets = {}
        for anchor in soup.find_all("a", href=True):
            label = anchor.get_text(strip=True)
            if not label.isdigit():
                continue
            match = POSTBACK_RE.search(anchor["href"])
            if match:
                targets[int(label)] = match.group(1)
        return targets

    def parse_grid(self, html: str):
        """Read the live WebForms grid."""
        soup = BeautifulSoup(html, "html.parser")
        grid = soup.find("table", id=GRID_ID)
        if grid is None:
            return []

        notices = []
        for row in grid.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) != 9:
                continue

            notice_kind = cells[0].get_text(" ", strip=True)
            if not notice_kind or notice_kind == HEADER_CELL:
                continue

            title = self._row_title(cells[1])
            if not title:
                continue

            procurement_type = cells[2].get_text(" ", strip=True)
            department = cells[5].get_text(" ", strip=True)
            status = cells[6].get_text(" ", strip=True)
            notice_pdf = self._cell_link(cells[7])
            bidding_pdf = self._cell_link(cells[8])

            # Only corrigenda carry a detail page; a plain tender notice has
            # none, and is identified by its notice document instead.
            tender_id = ""
            detail_url = ""
            for anchor in cells[1].find_all("a", href=True):
                match = DETAIL_RE.search(anchor["href"])
                if match:
                    tender_id = match.group(1)
                    detail_url = self.abs_url(anchor["href"])
                    break

            identity = self._identity(notice_pdf, title, tender_id)
            reference = ""
            ref_match = REFERENCE_RE.search(title)
            if ref_match:
                reference = ref_match.group(1).strip(" .:-")

            description = f"{notice_kind}. Type: {procurement_type}." if procurement_type else notice_kind
            if status and status != notice_kind:
                description = f"{description} Status: {status}."

            notices.append(
                {
                    "native_id": f"ppra-{identity}",
                    # The notice document is the authority's own publication of
                    # this tender, and it is what the portal links a reader to.
                    "url": self.abs_url(notice_pdf) or detail_url or self.base_url,
                    "title": title,
                    "buyer_name": department,
                    # The identity of the tender is the document the authority
                    # published it under. A reference printed in the title is
                    # kept separately, because it is the number a bidder quotes.
                    "buyer_ref": f"PPRA/{identity}",
                    "portal_reference": reference,
                    "source_category": procurement_type or notice_kind,
                    "city": "",
                    "area": self.source.area or "Punjab",
                    "estimated_value": None,
                    "published_at": parse_date(cells[3].get_text(" ", strip=True)),
                    "submission_deadline": parse_date(cells[4].get_text(" ", strip=True)),
                    "opening_at": None,
                    "description": description,
                    "tender_type": self._tender_type(procurement_type),
                    "notice_status": "Corrigendum" if notice_kind == "Corrigendum" else "Published",
                    "document_url": self.abs_url(notice_pdf),
                    "bidding_document_url": self.abs_url(bidding_pdf),
                    "detail_url": detail_url,
                }
            )
        return notices

    @staticmethod
    def _row_title(cell) -> str:
        """The procurement name, without the grid's 'View Tender Detail' link."""
        text = cell.get_text(" ", strip=True)
        text = re.sub(r"\(?\s*View\s+Tender\s+Detail\s*\)?", " ", text, flags=re.I)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _cell_link(cell) -> str:
        for anchor in cell.find_all("a", href=True):
            if anchor["href"]:
                return anchor["href"]
        return ""

    @staticmethod
    def _identity(notice_pdf: str, title: str, tender_id: str) -> str:
        """A stable id for one notice.

        The notice document's file name is unique per publication and does not
        move, so it is the best identifier the listing offers.
        """
        if notice_pdf:
            return notice_pdf.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if tender_id:
            return tender_id
        return hashlib.sha1(title.encode("utf-8", errors="ignore")).hexdigest()[:16]

    @staticmethod
    def _tender_type(procurement_type: str) -> str:
        """Map the portal's own type onto the internal vocabulary."""
        value = (procurement_type or "").strip().lower()
        if value == "work":
            return "Works"
        if value in ("goods", "services"):
            return value.title()
        return ""

    def fetch_detail(self, native_id):
        """Read one notice's detail page, which carries the tender number."""
        if self.fixture_mode or not native_id:
            return None
        url = f"{self.base_url.rsplit('/', 1)[0]}/ActiveTendersDetail.aspx?id={native_id.split('-')[-1]}"
        try:
            html = self.client().get(url)
        except Exception:
            return None
        return {"url": url, "html": html}

    def fetch_documents(self, native_id, ref=None):
        """The notice document, either from the saved capture or the portal."""
        if not native_id:
            return None

        if not self.fixture_mode:
            document_url = (ref or {}).get("document_url") or ""
            if not document_url:
                return None
            content = self._download(document_url)
            if not content:
                return None
            filename = document_url.rsplit("/", 1)[-1] or f"{native_id}.pdf"
            return [(filename, content)]

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
        return [(d.get("filename", "document.txt"), str(d.get("content", "")).encode("utf-8")) for d in docs]

    def _download(self, url: str) -> bytes:
        """Fetch a document from the portal."""
        try:
            from curl_cffi import requests as curl_requests

            response = curl_requests.request(
                "GET",
                url,
                impersonate="chrome124",
                timeout=60,
                allow_redirects=True,
            )
        except Exception:
            return b""
        if response.status_code >= 400:
            return b""
        return response.content
