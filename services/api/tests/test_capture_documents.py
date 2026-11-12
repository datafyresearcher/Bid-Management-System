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


def test_a_document_that_arrived_is_analysed_even_if_the_hand_over_was_cut_short(client, db, auth, live_mode):
    """A record waiting for a document it already has is finished, not left.

    A hand-over that is cut off half way through leaves the file on the
    record and the analysis undone. Nothing would fetch that document again,
    so the record would wait for ever.
    """
    from app.models import Document, DocumentChunk, Opportunity
    from app.services import documents as documents_service
    from app.services import workflow

    opp_id = _capture_one(client, auth, "Bridge document half carried tender", "notice-h1", "bidding-h1")
    opp = db.get(Opportunity, opp_id)
    workflow.run_analysis(db, opp)
    db.refresh(opp)

    # The document arrived, and the request died before it was analysed.
    documents_service.save_document(
        db,
        opp,
        "bidding-h1.txt",
        BIDDING_TEXT.encode("utf-8"),
        source_url="https://eproc.punjab.gov.pk/BiddingDocuments/bidding-h1.pdf",
    )
    db.refresh(opp)
    assert opp.documents_status == "awaiting_bridge"

    pending = client.get(
        "/api/sources/documents-pending", headers={"X-Capture-Secret": SECRET}
    ).json()
    # The tender notice is still wanted, but the tender itself has been
    # analysed from the document that arrived.
    db.expire_all()
    opp = db.get(Opportunity, opp_id)
    assert opp.documents_status != "awaiting_bridge"
    assert opp.estimated_boq_value == 2_000_000
    # The stand-in is gone, and its chunks went with it.
    assert [d.filename for d in opp.documents] == ["bidding-h1.txt"]
    assert db.query(DocumentChunk).filter(DocumentChunk.opportunity_id == opp_id).count() > 0
    assert db.query(Document).filter(Document.opportunity_id == opp_id).count() == 1
    assert [p for p in pending if p["opportunity_id"] == opp_id]


def test_the_stand_in_goes_with_its_chunks(client, db, auth, live_mode):
    """The chunks of a deleted document go with it.

    The database the system runs on refuses a row that is deleted while
    another still points at it, so a stand-in deleted without its chunks
    would fail on the deployment and pass on a developer's machine.
    """
    from app.models import DocumentChunk, Opportunity
    from app.services import documents as documents_service
    from app.services import workflow

    opp_id = _capture_one(client, auth, "Bridge document chunks tender", "notice-c1", "bidding-c1")
    opp = db.get(Opportunity, opp_id)
    workflow.run_analysis(db, opp)
    db.refresh(opp)

    summary = [d for d in opp.documents if d.filename == documents_service.SUMMARY_FILENAME]
    assert summary, [d.filename for d in opp.documents]
    assert db.query(DocumentChunk).filter(DocumentChunk.document_id == summary[0].id).count() > 0

    assert documents_service.drop_placeholder_summary(db, opp) is True
    assert (
        db.query(DocumentChunk).filter(DocumentChunk.document_id == summary[0].id).count() == 0
    )


def test_a_tender_whose_analysis_failed_is_not_locked(client, db, auth, live_mode, monkeypatch):
    """A failed analysis must not leave the tender behind a closed gate.

    The gate is closed and the analysis is run. If the analysis does not
    finish, the tender would sit at Stage 1 with nothing to show it and no
    way to move — so the gate is opened again.
    """
    from app.models import GateTask, Opportunity
    from app.services import workflow

    opp_id = _capture_one(client, auth, "Bridge document failing analysis", "notice-f1", "bidding-f1")
    opp = db.get(Opportunity, opp_id)
    gate = (
        db.query(GateTask)
        .filter(GateTask.opportunity_id == opp_id, GateTask.gate == 1)
        .first()
    )
    assert gate is not None

    def _fail(db, opp):
        raise RuntimeError("the knowledge base could not be read")

    monkeypatch.setattr(workflow, "run_analysis", _fail)
    resp = client.post(
        f"/api/gates/{gate.id}/decide",
        json={"decision": "GO", "comment": "proceed"},
        headers=auth,
    )
    assert resp.status_code == 400, resp.text
    assert "reopened" in resp.json()["detail"]

    db.expire_all()
    assert db.get(GateTask, gate.id).status == "PENDING"


def test_a_tender_whose_analysis_was_interrupted_carries_on(client, db, auth, live_mode):
    """Re-analysing a tender whose analysis was interrupted finishes it.

    A tender approved at Stage 1 has its analysis run and its gate closed.
    If the analysis does not finish, the tender is left at Stage 1 with no
    second gate to move to. Re-analysing it completes what was left undone.
    """
    from app.models import GateTask, Opportunity
    from app.services import documents as documents_service
    from app.services import workflow

    opp_id = _capture_one(client, auth, "Bridge document interrupted tender", "notice-i1", "bidding-i1")
    opp = db.get(Opportunity, opp_id)
    workflow.run_analysis(db, opp)
    db.refresh(opp)

    # The document arrived, and the request died before the analysis was
    # finished: the gate is closed and there is no second gate.
    documents_service.save_document(
        db,
        opp,
        "bidding-i1.txt",
        BIDDING_TEXT.encode("utf-8"),
        source_url="https://eproc.punjab.gov.pk/BiddingDocuments/bidding-i1.pdf",
    )
    documents_service.drop_placeholder_summary(db, opp)
    opp.state = "DOCS_FETCHED"
    db.commit()
    first = (
        db.query(GateTask)
        .filter(GateTask.opportunity_id == opp_id, GateTask.gate == 1)
        .first()
    )
    first.status = "APPROVED"
    db.commit()
    assert (
        db.query(GateTask).filter(GateTask.opportunity_id == opp_id, GateTask.gate == 2).count() == 0
    )

    workflow.reanalyze(db, opp)
    db.expire_all()
    opp = db.get(Opportunity, opp_id)
    assert opp.state == "GATE2"
    assert opp.estimated_boq_value == 2_000_000
    second = (
        db.query(GateTask)
        .filter(GateTask.opportunity_id == opp_id, GateTask.gate == 2)
        .first()
    )
    assert second is not None, "the tender must not be stranded at Stage 1"
