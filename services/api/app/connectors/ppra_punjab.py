from app.connectors.base import BaseConnector
from app.services.utils import parse_amount, parse_date

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

    def _fetch_html(self) -> str:
        if self.fixture_mode:
            path = self.fixture_path("listings.html")
            if not path.exists():
                return ""
            return path.read_text(encoding="utf-8")
        raise RuntimeError("Live PPRA Punjab scanning requires portal session configuration — run with BMS_FIXTURES=true for demo")

    def parse_listing(self, html: str):
        from bs4 import BeautifulSoup

        self.last_raw = html
        soup = BeautifulSoup(html, "html.parser")
        notices = []
        table = soup.find("table")
        if not table:
            return notices
        rows = table.find_all("tr")
        columns = {}
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
            notice = {
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
            notices.append(notice)
        return notices

    def fetch_listing(self):
        return self.parse_listing(self._fetch_html())

    def fetch_documents(self, native_id):
        if not native_id:
            return None
        path = self.fixture_path("documents.json")
        if not path.exists():
            return None
        import json

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        docs = payload.get(native_id)
        if not docs:
            return None
        return [(d.get("filename", "document.txt"), str(d.get("content", "")).encode("utf-8")) for d in docs]
