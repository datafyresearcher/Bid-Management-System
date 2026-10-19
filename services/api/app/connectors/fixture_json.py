import json

from app.connectors.base import BaseConnector


class FixtureJsonConnector(BaseConnector):
    adapter = "fixture_json"
    label = "Fixture JSON portal (generic demo adapter)"

    def fetch_listing(self):
        if self.fixture_mode:
            path = self.fixture_path("listings.json")
            if not path.exists():
                return []
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.last_raw = json.dumps(payload)
            items = payload if isinstance(payload, list) else payload.get("notices", [])
            notices = []
            for index, item in enumerate(items):
                notices.append(
                    {
                        "native_id": item.get("native_id") or item.get("id") or f"{self.source.code}-{index + 1}",
                        "url": item.get("url", self.base_url),
                        "title": item.get("title", ""),
                        "buyer_name": item.get("buyer_name") or item.get("buyer", ""),
                        "buyer_ref": item.get("buyer_ref") or item.get("reference", ""),
                        "source_category": item.get("source_category") or item.get("category", ""),
                        "city": item.get("city", ""),
                        "area": item.get("area", self.source.area),
                        "estimated_value": item.get("estimated_value"),
                        "published_at": item.get("published_at"),
                        "submission_deadline": item.get("submission_deadline"),
                        "opening_at": item.get("opening_at"),
                        "description": item.get("description", ""),
                    }
                )
            return notices
        return []

    def fetch_documents(self, native_id):
        if not native_id or not self.fixture_mode:
            return None
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
