"""The capture bridge: how a portal this deployment cannot reach still feeds the system.

eproc.punjab.gov.pk refuses connections from datacenter networks, so no scan
from any cloud region can read it. The bridge lets the bid desk's own machine
capture the listing in a real browser and hand the raw pages to
POST /api/sources/capture, where they run through the same parser,
normalizer and scorer a live scan would use.
"""

from app.config import settings

SECRET = "bridge-test-secret"

# One row of the portal's live WebForms grid, shaped exactly as the grid
# parser reads it: nine columns, a notice document for identity, and a close
# date still ahead so the tender is actionable. Built here rather than read
# from the golden capture so the test's data cannot collide with the seeded
# demo tenders the pipeline tests walk through.
GRID_ID = "ctl00_ContentPlaceHolderSRIS_rdgrdManageTender_ctl00"


def _grid_page(title: str, doc_stem: str) -> str:
    return f"""<html><body>
    <table id="{GRID_ID}">
      <tr>
        <th>Notice Kind</th><th>Procurement Title</th><th>Type</th>
        <th>Publish Date</th><th>Close Date</th><th>Department</th>
        <th>Status</th><th>Tender Notice</th><th>Bidding Document</th>
      </tr>
      <tr>
        <td>Tender Notice</td>
        <td>{title}</td>
        <td>Works</td>
        <td>01-Dec-2026</td>
        <td>15-Jan-2027</td>
        <td>Bridge Test Department</td>
        <td>Published</td>
        <td><a href="/Uploads/TenderNotice/{doc_stem}.pdf">Notice</a></td>
        <td></td>
      </tr>
    </table>
    </body></html>"""


def test_capture_without_a_configured_secret_reads_as_missing_route(client):
    resp = client.post(
        "/api/sources/capture",
        json={"code": "ppra_punjab", "pages": ["<html></html>"]},
        headers={"X-Capture-Secret": "anything"},
    )
    assert resp.status_code == 404


def test_capture_ingests_a_captured_listing(client, auth):
    settings.capture_secret = SECRET
    try:
        title = "Capture bridge 132kV grid station works package"
        resp = client.post(
            "/api/sources/capture",
            json={"code": "ppra_punjab", "pages": [_grid_page(title, "bridge-test-doc-001")]},
            headers={"X-Capture-Secret": SECRET},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["source"] == "ppra_punjab"
        assert body["notices"] == 1
        assert body["new"] == 1
        assert body["health"] == "ok"

        # The source reports itself healthy, with the capture as its latest
        # scan and the bridge named as the way it was read.
        sources = client.get("/api/sources", headers=auth).json()
        ppra = next(s for s in sources if s["code"] == "ppra_punjab")
        assert ppra["health"] == "ok"
        assert ppra["last_scan_stats"]["mode"] == "bridge"
        assert ppra["last_scan_stats"]["notices"] == 1

        # The captured tender reached the inbox with its close date intact.
        listed = client.get(
            "/api/opportunities", params={"q": "capture bridge 132kv"}, headers=auth
        ).json()
        assert listed["total"] == 1
        assert listed["items"][0]["submission_deadline"].startswith("2027-01-15")
    finally:
        settings.capture_secret = ""


def test_capture_twice_updates_in_place(client, auth):
    """Re-capturing the same notice updates its record, never duplicates it."""
    settings.capture_secret = SECRET
    try:
        page = _grid_page("Capture bridge repeatable works package", "bridge-test-doc-002")
        for expected_new in (1, 0):
            resp = client.post(
                "/api/sources/capture",
                json={"code": "ppra_punjab", "pages": [page]},
                headers={"X-Capture-Secret": SECRET},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["new"] == expected_new
    finally:
        settings.capture_secret = ""


def test_capture_refuses_an_unknown_source_code(client):
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
