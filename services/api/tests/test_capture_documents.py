"""The documents the cloud cannot fetch, carried by the bid desk's machine.

One portal refuses connections from datacenter networks, so the documents it
publishes can only be fetched from a machine the portal answers. The bid
manager approves a tender in the cloud, the record is marked as waiting for
its document, and the machine on the bid desk fetches it and hands it over.
"""

import pytest

from app.config import settings

SECRET = "bridge-document-secret"

GRID_ID = "ctl00_ContentPlaceHolderSRIS_rdgrdManageTender_ctl00"


@pytest.fixture()
def live_mode(monkeypatch):
    """The suite runs in demo mode; the bridge only matters when reading live.

    In demo mode the documents are the saved fixtures on this machine's own
    disk, so they are read directly and the bridge has nothing to do.
    """
    monkeypatch.setattr(settings, "fixtures", False)
    monkeypatch.setattr(settings, "capture_secret", SECRET)


def _grid_page(title: str, notice_stem: str, bidding_stem: str) -> str:
    """One row of the portal's live WebForms grid, with both document columns."""
    return f"""<html><body>
    <table id="{GRID_ID}">
      <tr>
        <th>Procurement Title</th><th>Procurement Name</th><th>Type</th>
        <th>Publish Date</th><th>Close Date</th><th>Department</th>
        <th>Status</th><th>Tender Notice</th><th>Bidding Document</th>
      </tr>
      <tr>
        <td>Tender Notice</td>
        <td>{title}</td>
        <td>Works</td>
        <td>01-Dec-2026</td>
        <td>15-Jan-2027</td>
        <td>Bridge Document Department</td>
        <td>Published</td>
        <td><a href="/Uploads/TenderNotice/{notice_stem}.pdf">Notice</a></td>
        <td><a href="/BiddingDocuments/{bidding_stem}.pdf">Bidding Document</a></td>
      </tr>
    </table>
    </body></html>"""


BIDDING_TEXT = (
    "Bid Security PKR 40,000 shall be furnished. Bid Security 2% (Rs) of the "
    "estimated cost of the works shall apply. Last date for submission of bids: "
    "15-Jan-2027."
)


def _capture_one(client, auth, title, notice_stem, bidding_stem) -> int:
    """Capture one tender through the bridge and return its opportunity id."""
    resp = client.post(
        "/api/sources/capture",
        json={"code": "ppra_punjab", "pages": [_grid_page(title, notice_stem, bidding_stem)]},
        headers={"X-Capture-Secret": SECRET},
    )
    assert resp.status_code == 200, resp.text
    listed = client.get("/api/opportunities", params={"q": title}, headers=auth).json()
    return listed["items"][0]["id"]


def test_the_document_door_is_closed_without_the_secret(client):
    """An unconfigured or wrong secret reads as a missing route."""
    resp = client.get("/api/sources/documents-pending")
    assert resp.status_code == 404, resp.text

    resp = client.post(
        "/api/sources/capture/document",
        data={"opportunity_id": "1", "filename": "x.txt"},
        files={"file": ("x.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 404, resp.text


def test_a_tender_whose_portal_is_out_of_reach_waits_for_its_document(client, db, auth, live_mode):
    """The cloud does not pretend it has the document: it says it is waiting."""
    from app.models import Opportunity
    from app.services import workflow

    opp_id = _capture_one(client, auth, "Bridge document waiting tender", "notice-w1", "bidding-w1")

    opp = db.get(Opportunity, opp_id)
    workflow.run_analysis(db, opp)
    db.refresh(opp)

    assert opp.documents_status == "awaiting_bridge"
    # The stand-in written from the listing is there to read until the
    # real document arrives, and it is clearly the stand-in.
    assert [d.filename for d in opp.documents] == ["notice_summary.txt"]
    # Nothing may be worked out from the listing's summary, so no bid
    # security and no implied value are claimed.
    assert opp.bid_security_amount is None
    assert opp.estimated_boq_value is None


def test_the_bridge_is_told_which_document_to_fetch(client, db, auth, live_mode):
    """The machine that can reach the portal is told the address of the file."""
    from app.models import Opportunity
    from app.services import workflow

    opp_id = _capture_one(client, auth, "Bridge document pending tender", "notice-p1", "bidding-p1")
    opp = db.get(Opportunity, opp_id)
    workflow.run_analysis(db, opp)
    db.refresh(opp)

    pending = client.get(
        "/api/sources/documents-pending", headers={"X-Capture-Secret": SECRET}
    ).json()
    mine = [p for p in pending if p["opportunity_id"] == opp_id]
    assert mine, pending

    urls = [d["url"] for d in mine[0]["documents"]]
    assert any(u.endswith("bidding-p1.pdf") for u in urls), urls
    assert any(u.endswith("notice-p1.pdf") for u in urls), urls


def test_a_document_brought_over_is_read_and_the_implied_value_worked_out(client, db, auth, live_mode):
    """The file the bridge brings over is the one the analysis is drawn from.

    The bid security and the percentage it represents are stated only in the
    bidding document, so the implied value appears when the document arrives.
    """
    from app.models import Opportunity
    from app.services import workflow

    opp_id = _capture_one(client, auth, "Bridge document delivered tender", "notice-d1", "bidding-d1")
    opp = db.get(Opportunity, opp_id)
    workflow.run_analysis(db, opp)
    db.refresh(opp)

    resp = client.post(
        "/api/sources/capture/document",
        data={
            "opportunity_id": str(opp_id),
            "filename": "bidding-d1.txt",
            "kind": "bidding document",
        },
        files={"file": ("bidding-d1.txt", BIDDING_TEXT.encode("utf-8"), "text/plain")},
        headers={"X-Capture-Secret": SECRET},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["bid_security_amount"] == 40_000
    assert body["bid_security_percent"] == 2
    assert body["estimated_boq_value"] == 2_000_000

    db.expire_all()
    opp = db.get(Opportunity, opp_id)
    assert opp.estimated_boq_value == 2_000_000
    assert opp.documents_status != "awaiting_bridge"
    # The stand-in is dropped, so the analysis is drawn from the document
    # and not from the listing's summary of it.
    assert [d.filename for d in opp.documents] == ["bidding-d1.txt"]


def test_the_document_door_refuses_an_unknown_tender(client, live_mode):
    resp = client.post(
        "/api/sources/capture/document",
        data={"opportunity_id": "99999999", "filename": "x.txt"},
        files={"file": ("x.txt", b"hello", "text/plain")},
        headers={"X-Capture-Secret": SECRET},
    )
    assert resp.status_code == 404, resp.text


def test_a_document_carried_over_is_not_asked_for_again(client, db, auth, live_mode):
    """A file handed over is settled, whether it arrived whole or as its text.

    The address it was fetched from is kept with it, so a document that
    arrived as its text is not fetched and filed again on every run.
    """
    from app.models import Opportunity
    from app.services import documents as documents_service
    from app.services import workflow

    opp_id = _capture_one(client, auth, "Bridge document settled tender", "notice-s1", "bidding-s1")
    opp = db.get(Opportunity, opp_id)
    workflow.run_analysis(db, opp)
    db.refresh(opp)

    resp = client.post(
        "/api/sources/capture/document",
        data={
            "opportunity_id": str(opp_id),
            "filename": "bidding-s1.txt",
            "kind": "bidding document",
            "source_url": "https://eproc.punjab.gov.pk/BiddingDocuments/bidding-s1.pdf",
        },
        files={"file": ("bidding-s1.txt", BIDDING_TEXT.encode("utf-8"), "text/plain")},
        headers={"X-Capture-Secret": SECRET},
    )
    assert resp.status_code == 200, resp.text

    db.expire_all()
    opp = db.get(Opportunity, opp_id)
    wanted = documents_service.pending_document_urls(opp)
    urls = [w["url"] for w in wanted]
    assert not any(u.endswith("bidding-s1.pdf") for u in urls), urls
