"""PPRA Punjab: the record must point at the bidding document, not the notice.

The portal publishes two files against every tender: the tender notice, which
is the authority's advertisement of the tender and is very often a scanned
advertisement with no readable text, and the bidding document, which carries
the instructions, the bid data sheet and the commercial terms — the bid
security among them.

The record was pointing at the notice. That put a scanned advertisement in
front of the bid manager instead of the document they have to work from, and
it meant the implied BOQ value could never be calculated, because the
percentage of the estimated cost is stated in the bidding document and
nowhere else.
"""

from app.config import settings

SECRET = "bridge-bidding-doc-secret"

GRID_ID = "ctl00_ContentPlaceHolderSRIS_rdgrdManageTender_ctl00"


def _grid_page(title: str, notice_stem: str, bidding_stem: str, kind: str = "Tender Notice") -> str:
    """One row of the portal's live WebForms grid, with both document columns."""
    return f"""<html><body>
    <table id="{GRID_ID}">
      <tr>
        <th>Procurement Title</th><th>Procurement Name</th><th>Type</th>
        <th>Publish Date</th><th>Close Date</th><th>Department</th>
        <th>Status</th><th>Tender Notice</th><th>Bidding Document</th>
      </tr>
      <tr>
        <td>{kind}</td>
        <td>{title}</td>
        <td>Works</td>
        <td>01-Dec-2026</td>
        <td>15-Jan-2027</td>
        <td>Bidding Document Test Department</td>
        <td>Published</td>
        <td><a href="/Uploads/TenderNotice/{notice_stem}.pdf">Notice</a></td>
        <td><a href="/BiddingDocuments/{bidding_stem}.pdf">Bidding Document</a></td>
      </tr>
    </table>
    </body></html>"""


def _connector():
    from app.connectors.ppra_punjab import PPRAPunjabConnector

    class StubSource:
        code = "ppra_punjab"
        name = "PPRA Punjab e-Procurement"
        area = "Punjab"
        adapter = "ppra_punjab"
        url = "https://eproc.punjab.gov.pk/"
        listing_url = "https://eproc.punjab.gov.pk/ActiveTenders.aspx"

    return PPRAPunjabConnector(StubSource())


# -- the listing parse ----------------------------------------------------


def test_the_record_points_at_the_bidding_document():
    """The document the bid team works from is the bidding document."""
    notices = _connector().parse_grid(
        _grid_page("Bidding document tender", "notice-001", "bidding-001")
    )
    assert len(notices) == 1
    notice = notices[0]
    assert notice["document_url"] == "https://eproc.punjab.gov.pk/BiddingDocuments/bidding-001.pdf"
    assert notice["bidding_document_url"] == notice["document_url"]
    assert notice["notice_url"] == "https://eproc.punjab.gov.pk/Uploads/TenderNotice/notice-001.pdf"


def test_the_tender_notice_is_kept_beside_the_bidding_document():
    """The notice is the authority's own publication of the tender, so it stays
    reachable — it is simply no longer what the record points at."""
    notices = _connector().parse_grid(
        _grid_page("Bidding document tender", "notice-002", "bidding-002")
    )
    related = notices[0]["related_documents"]
    assert len(related) == 1
    assert related[0]["url"] == "https://eproc.punjab.gov.pk/Uploads/TenderNotice/notice-002.pdf"
    assert related[0]["kind"] == "notice"


def test_a_corrigendum_is_kept_beside_the_bidding_document():
    """A correction is published as a notice, and a reader has to see it."""
    notices = _connector().parse_grid(
        _grid_page("Corrected tender", "correction-001", "bidding-003", kind="Corrigendum")
    )
    related = notices[0]["related_documents"]
    assert [r["kind"] for r in related] == ["corrigendum"]
    assert related[0]["url"].endswith("correction-001.pdf")


def test_a_tender_with_no_bidding_document_still_points_at_its_notice():
    """Not every row publishes a bidding document. The notice is then the
    document, and the record must not end up with nothing."""
    page = _grid_page("Notice only tender", "notice-003", "bidding-004")
    page = page.replace(
        '<td><a href="/BiddingDocuments/bidding-004.pdf">Bidding Document</a></td>', "<td></td>"
    )
    notices = _connector().parse_grid(page)
    assert notices[0]["document_url"] == "https://eproc.punjab.gov.pk/Uploads/TenderNotice/notice-003.pdf"
    assert notices[0]["related_documents"] == []


def test_a_corrigendum_keeps_the_original_tenders_bidding_document():
    """A corrigendum and its original are one tender, so the record ends up with
    the original's bidding document and the correction beside it."""
    connector = _connector()
    original = connector.parse_grid(
        _grid_page("Corrected tender", "notice-original", "bidding-original")
    )[0]
    corrigendum = connector.parse_grid(
        _grid_page("Corrected tender", "notice-corrigendum", "bidding-original", kind="Corrigendum")
    )[0]
    merged = connector._merge_corrigenda([corrigendum, original])

    for notice in merged:
        assert notice["document_url"].endswith("bidding-original.pdf"), notice
        kinds = sorted(r["kind"] for r in notice["related_documents"])
        assert kinds == ["corrigendum", "notice"], notice


# -- what the bidding document says ---------------------------------------


def test_the_percentage_as_the_portal_states_it_is_read():
    """The wording the portal actually uses."""
    from app.services import extractor

    detected = extractor._detect_fields(
        "Bid Security 2% (Rs) of the estimated cost. Tender Process 1. "
        "Each bidder shall submit Bid Security @ 2% of the item-wise/Lot/composite "
        "estimated amount through the Punjab e-Procurement System."
    )
    assert detected["bid_security_percent"] == 2


def test_the_implied_boq_value_is_worked_out_from_the_bidding_document():
    """The whole point of reading the bidding document: the percentage of the
    estimated cost is stated there, so the estimated value can be implied."""
    from app.services import extractor

    detected = extractor._detect_fields(
        "Bid Security PKR 40,000 shall be furnished. Bid Security 2% (Rs) of the "
        "estimated cost of the works shall apply."
    )
    assert detected["bid_security_amount"] == 40_000
    assert detected["bid_security_percent"] == 2
    assert detected["estimated_boq_value"] == 2_000_000


# -- the capture bridge ----------------------------------------------------


def test_the_capture_leaves_the_record_on_its_bidding_document(client, db, auth):
    """The bridge feeds this portal, so the capture is what puts the bidding
    document on the record."""
    settings.capture_secret = SECRET
    try:
        resp = client.post(
            "/api/sources/capture",
            json={
                "code": "ppra_punjab",
                "pages": [_grid_page("Bidding document bridge tender", "notice-b1", "bidding-b1")],
            },
            headers={"X-Capture-Secret": SECRET},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["notices"] == 1

        listed = client.get("/api/opportunities", params={"q": "bidding document bridge"}, headers=auth).json()
        items = listed.get("items", listed if isinstance(listed, list) else [])
        assert items, "the captured tender did not reach the inbox"
        opp = items[0]

        detail = client.get(f"/api/opportunities/{opp['id']}", headers=auth).json()
        assert detail["document_link"] == "https://eproc.punjab.gov.pk/BiddingDocuments/bidding-b1.pdf"
        assert any(
            r["url"].endswith("notice-b1.pdf") for r in (detail.get("related_documents") or [])
        ), detail.get("related_documents")
    finally:
        settings.capture_secret = ""


def test_a_capture_repoints_a_tender_that_was_captured_with_its_notice(client, db, auth):
    """A tender captured before the fix points at its notice. The next capture
    moves it onto the bidding document, and the notice is kept beside it."""
    settings.capture_secret = SECRET
    try:
        page = _grid_page("Repointed bridge tender", "notice-r1", "bidding-r1")
        for expected_new in (1, 0):
            resp = client.post(
                "/api/sources/capture",
                json={"code": "ppra_punjab", "pages": [page]},
                headers={"X-Capture-Secret": SECRET},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["new"] == expected_new

        listed = client.get("/api/opportunities", params={"q": "repointed bridge"}, headers=auth).json()
        items = listed.get("items", listed if isinstance(listed, list) else [])
        assert len(items) == 1, items
        detail = client.get(f"/api/opportunities/{items[0]['id']}", headers=auth).json()
        assert detail["document_link"] == "https://eproc.punjab.gov.pk/BiddingDocuments/bidding-r1.pdf"
    finally:
        settings.capture_secret = ""


# -- fetching --------------------------------------------------------------


def test_the_bidding_document_and_the_notice_are_both_fetched(monkeypatch):
    """Both files are retrieved: the bidding document to work from, and the
    notice so the reader can see what the authority published."""
    connector = _connector()
    monkeypatch.setattr(connector, "fixture_mode", False)
    monkeypatch.setattr(
        connector,
        "_download",
        lambda url: b"%PDF-1.4 fake " + url.encode("utf-8"),
    )

    fetched = connector.fetch_documents(
        "ppra-notice-1",
        ref={
            "document_url": "https://eproc.punjab.gov.pk/BiddingDocuments/b1.pdf",
            "related_documents": [
                {"url": "https://eproc.punjab.gov.pk/Uploads/TenderNotice/n1.pdf", "kind": "notice"}
            ],
        },
    )
    names = sorted(name for name, _ in fetched)
    assert names == ["b1.pdf", "n1.pdf"]
