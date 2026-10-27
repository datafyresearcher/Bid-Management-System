"""The capture bridge: how a portal this deployment cannot reach still feeds the system.

eproc.punjab.gov.pk refuses connections from datacenter networks, so no scan
from any cloud region can read it. The bridge lets the bid desk's own machine
capture the listing in a real browser and hand the raw pages to
POST /api/sources/capture, where they run through the same parser,
normalizer and scorer a live scan would use.
"""

from pathlib import Path

GOLDEN = Path(__file__).resolve().parent / "golden"
SECRET = "bridge-test-secret"


def test_capture_without_a_configured_secret_reads_as_missing_route(client):
    resp = client.post(
        "/api/sources/capture",
        json={"code": "ppra_punjab", "pages": ["<html></html>"]},
        headers={"X-Capture-Secret": "anything"},
    )
    assert resp.status_code == 404


def test_capture_ingests_a_captured_listing(client, auth):
    from app.config import settings

    settings.capture_secret = SECRET
    try:
        html = (GOLDEN / "ppra_punjab.html").read_text(encoding="utf-8")
        resp = client.post(
            "/api/sources/capture",
            json={"code": "ppra_punjab", "pages": [html]},
            headers={"X-Capture-Secret": SECRET},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["source"] == "ppra_punjab"
        assert body["notices"] > 0
        assert body["health"] == "ok"

        # The source now reports itself healthy, with the capture as its
        # latest scan and the bridge named as the way it was read.
        sources = client.get("/api/sources", headers=auth).json()
        ppra = next(s for s in sources if s["code"] == "ppra_punjab")
        assert ppra["health"] == "ok"
        assert ppra["last_scan_stats"]["mode"] == "bridge"
        assert ppra["last_scan_stats"]["notices"] == body["notices"]

        # The captured notices reached the tender inbox, traced to the
        # authority's own portal.
        listed = client.get(
            "/api/opportunities", params={"q": "PPRA"}, headers=auth
        ).json()
        assert listed["total"] > 0
    finally:
        settings.capture_secret = ""


def test_capture_refuses_an_unknown_source_code(client):
    from app.config import settings

    settings.capture_secret = SECRET
    try:
        resp = client.post(
            "/api/sources/capture",
            json={"code": "no_such_source", "pages": ["<html></html>"]},
            headers={"X-Capture-Secret": SECRET},
        )
        assert resp.status_code == 404
    finally:
        settings.capture_secret = ""


def test_capture_rejects_an_empty_capture(client):
    from app.config import settings

    settings.capture_secret = SECRET
    try:
        resp = client.post(
            "/api/sources/capture",
            json={"code": "ppra_punjab", "pages": ["  "]},
            headers={"X-Capture-Secret": SECRET},
        )
        assert resp.status_code == 400
    finally:
        settings.capture_secret = ""
