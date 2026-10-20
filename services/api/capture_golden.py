"""Capture the live listing pages as golden fixtures for the parser tests.

Run from services/api:  python capture_golden.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.connectors.http_client import LiveClient  # noqa: E402

GOLDEN = Path(__file__).resolve().parent / "tests" / "golden"
GOLDEN.mkdir(parents=True, exist_ok=True)

client = LiveClient(timeout=60, min_interval=1.5, retries=2)

pages = {
    "epms_federal.html": "https://epms.ppra.gov.pk/public/tenders/active-tenders",
    "epads_federal.html": "https://epads.gov.pk/",
    "ppra_punjab.html": "https://eproc.punjab.gov.pk/ActiveTenders.aspx",
    "wapda.html": "https://wapda.gov.pk/wapda-tenders/",
}

for name, url in pages.items():
    html = client.get(url)
    (GOLDEN / name).write_text(html, encoding="utf-8")
    print(f"{name}: {len(html)} bytes")

raw = client.get("https://ntdc.gov.pk/ntdc/api/tenders")
try:
    payload = json.loads(raw)
except json.JSONDecodeError:
    payload = json.loads(raw[raw.find("[") : raw.rfind("]") + 1])
records = payload if isinstance(payload, list) else payload.get("data", [])
# Keep a spread of the feed — recent and old — so the look-back rule is
# exercised without carrying the whole history into the repository.
sample = records[:: max(1, len(records) // 250)][:250]
(GOLDEN / "ntdc.json").write_text(json.dumps(sample, indent=1), encoding="utf-8")
print(f"ntdc.json: {len(sample)} of {len(records)} records")
