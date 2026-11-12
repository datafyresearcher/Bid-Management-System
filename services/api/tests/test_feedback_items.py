"""Tests for the changes made in answer to the bidding team's feedback.

Each test names the piece of feedback it answers, so that a later change
that undoes one of them fails here rather than going unnoticed.
"""

from datetime import timedelta

from app.models import LibraryDocument, Opportunity
from app.services import bid_summary, checklist, extractor, shared_documents
from app.services.utils import utcnow


# ----------------------------------------------------------------------
# 2.2  The tender-source links
# ----------------------------------------------------------------------


def test_the_ntdc_document_link_is_the_real_file(client, auth):
    """A notice from NTDC points at a file that is really there."""
    from app.connectors.ntdc import NTDCConnector

    assert NTDCConnector.DOCUMENT_BASE == "https://ntdc.gov.pk"
    assert "/uploads/" not in NTDCConnector.DOCUMENT_BASE


def test_the_records_already_on_file_are_pointed_at_their_own_tender():
    """Tenders captured before the fix open their own document too.

    A record's notice link is rewritten in place from the document link
    already captured against it, so a tender on file opens its own file
    without waiting for the next scan.
    """
    from app.db import backfill_ntdc_notice_links
    from app.models import Opportunity

    db = _session()
    try:
        opp = Opportunity(
            title="An NTDC tender captured with the old listing link",
            buyer_name="NTDC",
            buyer_ref="NTDC-OLD-1",
            source_refs=[
                {
                    "source_code": "ntdc",
                    "native_id": "ntdc-4448",
                    "url": "https://ntdc.gov.pk/tendors",
                    "document_url": "https://ntdc.gov.pk/bidding/Notice #4 & Lot-2.pdf",
                }
            ],
        )
        db.add(opp)
        db.commit()
        opp_id = opp.id
    finally:
        db.close()

    changed = backfill_ntdc_notice_links()
    assert changed >= 1

    db = _session()
    try:
        stored = db.get(Opportunity, opp_id)
        ref = stored.source_refs[0]
        assert ref["url"] == "https://ntdc.gov.pk/bidding/Notice%20%234%20%26%20Lot-2.pdf"
        assert ref["url"] != "https://ntdc.gov.pk/tendors"
    finally:
        db.close()


def test_a_document_that_is_really_a_page_is_refused():
    """An HTML page is never filed as a tender document.

    NTDC answers every unknown path with its single-page application shell,
    so the broken document link used to answer 200 with a web page.
    """
    from app.connectors.base import BaseConnector

    html = b"<!DOCTYPE html><html><body><app-root></app-root></body></html>"
    assert not BaseConnector._is_document_body(html, "text/html; charset=utf-8")
    assert not BaseConnector._is_document_body(html, "application/octet-stream")
    assert not BaseConnector._is_document_body(b"", "application/pdf")
    assert BaseConnector._is_document_body(b"%PDF-1.7\n...", "application/pdf")
    assert BaseConnector._is_document_body(b"PK\x03\x04...", "application/zip")


# ----------------------------------------------------------------------
# 2.3 / 2.4  The bidding document, and what came with it
# ----------------------------------------------------------------------


def test_the_record_keeps_a_link_to_the_bidding_document(client, auth):
    """Even when nothing was downloaded, the record points at the file."""
    from app.serializers import document_link, related_documents

    opp_id = _make_opportunity(
        client,
        auth,
        title="Test tender with a document",
        source_refs=[
            {
                "source_code": "ntdc",
                "native_id": "ntdc-1",
                "url": "https://ntdc.gov.pk/tendors",
                "document_url": "https://ntdc.gov.pk/bidding/IFB_6a38d56507bf6.pdf",
                "related_documents": [
                    {
                        "title": "Amendment No. 02",
                        "url": "https://ntdc.gov.pk/bidding/Amendment_02.pdf",
                        "date": "2026-07-16",
                        "kind": "amendment",
                    }
                ],
            }
        ],
    )
    db, opp = _get(opp_id)
    assert document_link(opp) == "https://ntdc.gov.pk/bidding/IFB_6a38d56507bf6.pdf"
    related = related_documents(opp)
    assert len(related) == 1
    assert related[0]["kind"] == "amendment"
    db.close()

    detail = client.get(f"/api/opportunities/{opp_id}", headers=auth).json()
    assert detail["document_link"].endswith("IFB_6a38d56507bf6.pdf")
    assert detail["related_documents"][0]["title"] == "Amendment No. 02"


def test_the_same_clarification_is_not_offered_twice(client, auth):
    """A tender seen on two notices offers each clarification once."""
    from app.serializers import related_documents

    opp_id = _make_opportunity(
        client,
        auth,
        title="Test tender seen twice",
        source_refs=[
            {
                "source_code": "ntdc",
                "native_id": "ntdc-1",
                "document_url": "https://ntdc.gov.pk/bidding/a.pdf",
                "related_documents": [
                    {
                        "title": "Clarification 01",
                        "url": "https://ntdc.gov.pk/bidding/c1.pdf",
                        "kind": "clarification",
                    }
                ],
            },
            {
                "source_code": "epms_federal",
                "native_id": "epms-1",
                "document_url": "https://ntdc.gov.pk/bidding/a.pdf",
                "related_documents": [
                    {
                        "title": "Clarification 01",
                        "url": "https://ntdc.gov.pk/bidding/c1.pdf",
                        "kind": "clarification",
                    }
                ],
            },
        ],
    )
    db, opp = _get(opp_id)
    assert len(related_documents(opp)) == 1
    db.close()


# ----------------------------------------------------------------------
# 2.5  The sectioned summary
# ----------------------------------------------------------------------


def test_the_summary_is_written_as_sections(client, auth):
    """The tender is read at a glance, under headings."""
    opp_id = _make_opportunity(
        client,
        auth,
        title="Summary test tender",
        description="Construction of a 220kV grid station extension.",
    )
    db, opp = _get(opp_id)
    text = (
        "Scope of work: The Contractor shall construct the 220kV grid station extension "
        "including all civil works and commissioning. "
        "The bidder must have completed at least 3 similar works of comparable magnitude. "
        "The Contractor shall provide a Project Manager with 15 years experience and a "
        "Site Supervisor throughout the works. "
        "Liquidated damages at 0.05 percent of the contract price per day shall apply for delay. "
        "All disputes shall be settled by arbitration under ICC rules."
    )
    summary = bid_summary.build(None, opp, text, {})
    db.close()

    labels = [s["label"] for s in summary["sections"]]
    assert labels == [
        "Scope of work",
        "Experience requirements",
        "Financial requirements",
        "Bid security",
        "Submission deadline",
        "Key personnel",
        "Other important conditions",
    ]

    by_key = {s["key"]: s for s in summary["sections"]}
    assert by_key["scope"]["available"]
    assert by_key["experience"]["available"]
    assert by_key["personnel"]["available"]
    assert by_key["financial"]["available"]
    assert by_key["conditions"]["available"]
    # Every point says where it came from, so a reader can check it.
    for section in summary["sections"]:
        for point in section["points"]:
            assert point["text"]
            assert point["source"]
            assert point["anchor"]


def test_the_summary_reaches_the_tender_record(client, auth):
    """The sectioned summary is stored on the record and served with it."""
    opp_id = _make_opportunity(client, auth, title="Stored summary tender")
    db, opp = _get(opp_id)
    db.add(
        _document_for(
            db,
            opp,
            "ITT.txt",
            "Scope of work: The Contractor shall supply and install 220kV equipment. "
            "Bid security: Bid security of PKR 8,000,000 shall be furnished in the form of a "
            "bank guarantee. Last date for submission of bids: 10-Feb-2027 at 1100 hours.",
        )
    )
    db.commit()
    extractor.run(db, opp)
    db.refresh(opp)
    assert opp.bid_summary
    assert opp.bid_summary["sections"]
    db.close()

    detail = client.get(f"/api/opportunities/{opp_id}", headers=auth).json()
    assert detail["bid_summary"]["sections"]


# ----------------------------------------------------------------------
# 2.6  The implied BOQ value
# ----------------------------------------------------------------------


def test_the_boq_value_is_implied_from_the_bid_security():
    """Estimated value = bid security / bid security percentage."""
    detected = extractor._detect_fields(
        "Bid security: Bid security of PKR 8,000,000 shall be furnished, "
        "being 2% of the estimated cost of the works."
    )
    assert detected["bid_security_amount"] == 8_000_000
    assert detected["bid_security_percent"] == 2
    assert detected["estimated_boq_value"] == 400_000_000
    assert "Confirm" in detected["boq_estimate_note"]


def test_the_boq_value_is_not_guessed_without_a_percentage():
    """No percentage, no estimate — and the record says so."""
    detected = extractor._detect_fields(
        "Bid security: Bid security of PKR 8,000,000 shall be furnished in the form of a bank guarantee."
    )
    assert detected["bid_security_amount"] == 8_000_000
    assert "bid_security_percent" not in detected
    assert "estimated_boq_value" not in detected
    assert "does not state the percentage" in detected["boq_estimate_note"]


def test_an_ambiguous_percentage_is_not_assumed():
    """Two percentages against the same trigger mean nothing is assumed."""
    detected = extractor._detect_fields(
        "Bid security: Bid security of PKR 8,000,000 shall be furnished, being 2% of the estimated "
        "cost, or 3% of the contract price where the contract price is used."
    )
    assert "bid_security_percent" not in detected
    assert "estimated_boq_value" not in detected
    assert "more than one percentage" in detected["boq_estimate_note"]


def test_another_percentage_is_not_mistaken_for_the_bid_securitys():
    """A percentage about something else nearby is not the security's."""
    detected = extractor._detect_fields(
        "Bid security of PKR 8,000,000 shall be furnished as a bank guarantee. "
        "Liquidated damages at 0.05 percent of the contract price per day shall apply for delay."
    )
    assert "bid_security_percent" not in detected
    assert "estimated_boq_value" not in detected


def test_a_bare_percentage_is_not_a_percentage():
    """A percentage has to be tied to a base value to mean anything."""
    detected = extractor._detect_fields(
        "Bid security of PKR 8,000,000 shall be furnished. The contractor shall retain 5% of the "
        "contract value as retention money."
    )
    assert "bid_security_percent" not in detected


def test_the_boq_estimate_reaches_the_record(client, auth):
    opp_id = _make_opportunity(client, auth, title="BOQ estimate tender")
    db, opp = _get(opp_id)
    db.add(
        _document_for(
            db,
            opp,
            "ITT.txt",
            "Bid security: Bid security of PKR 8,000,000 shall be furnished, being 2% of the "
            "estimated cost of the works. Last date for submission of bids: 10-Feb-2027.",
        )
    )
    db.commit()
    extractor.run(db, opp)
    db.refresh(opp)
    assert opp.bid_security_percent == 2
    assert opp.estimated_boq_value == 400_000_000
    db.close()

    detail = client.get(f"/api/opportunities/{opp_id}", headers=auth).json()
    assert detail["estimated_boq_value"] == 400_000_000
    assert detail["bid_security_percent"] == 2
    assert detail["boq_estimate_note"]


# ----------------------------------------------------------------------
# 2.9  The submission checklist
# ----------------------------------------------------------------------


def test_the_checklist_is_read_out_of_the_bidding_document():
    """The document's own requirements become the list to submit."""
    text = (
        "Clause 4.1: The bidder shall submit Form A — Tenderer's Information. "
        "Clause 4.2: Form B shall be completed in full. "
        "Clause 5.1: An affidavit of non-blacklisting shall be attached. "
        "Clause 6.1: The priced Bill of Quantities shall be submitted. "
        "Clause 7.1: A valid PEC licence certificate shall be provided. "
        "Clause 8.1: Audited financial statements for the last three years shall be submitted."
    )
    items = checklist.build(None, _stub_opportunity(), text)
    labels = [i["item"] for i in items]
    assert any("Form A" in label for label in labels)
    assert any("Form B" in label for label in labels)
    assert any("non-blacklisting" in label for label in labels)
    assert any("bill of quantities" in label.lower() for label in labels)
    assert any("PEC licence" in label for label in labels)
    assert any("audited financial statements" in label for label in labels)


def test_a_checklist_item_carries_its_clause():
    """A reader can turn to the clause the item came from."""
    text = (
        "Clause 4.1: The bidder shall submit Form A — Tenderer's Information. "
        "Clause 4.2: Form B shall be completed in full."
    )
    items = checklist.build(None, _stub_opportunity(), text)
    form_a = next(i for i in items if "Form A" in i["item"])
    assert form_a["clause"] == "Clause 4.1"
    assert form_a["page"]


def test_the_marks_the_team_made_survive_a_rebuild():
    """Re-running the analysis does not throw away the team's work."""
    generated = [
        {"item": "Form A", "status": "pending"},
        {"item": "Form B", "status": "pending"},
    ]
    existing = [
        {"item": "Form A", "status": "complete"},
        {"item": "Form B", "status": "not_applicable"},
    ]
    merged = checklist.with_statuses(existing, generated)
    assert merged[0]["status"] == "complete"
    assert merged[1]["status"] == "not_applicable"


def test_the_checklist_is_marked_through_the_api(client, auth):
    opp_id = _make_opportunity(client, auth, title="Checklist tender")
    db, opp = _get(opp_id)
    db.add(_document_for(db, opp, "ITT.txt", "Clause 4.1: The bidder shall submit Form A."))
    db.commit()
    from app.services import workflow

    workflow.reanalyze(db, opp)
    db.refresh(opp)
    assert opp.checklist
    db.close()

    resp = client.put(
        f"/api/opportunities/{opp_id}/checklist",
        json={"index": 0, "status": "complete"},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["checklist"][0]["status"] == "complete"

    bad = client.put(
        f"/api/opportunities/{opp_id}/checklist",
        json={"index": 0, "status": "whenever"},
        headers=auth,
    )
    assert bad.status_code == 400


# ----------------------------------------------------------------------
# 2.7  The shared knowledge-base documents
# ----------------------------------------------------------------------


def test_a_shared_document_is_carried_by_every_proposal(client, auth):
    """The usual evidence does not have to be uploaded for every tender."""
    db = _session()
    doc = LibraryDocument(
        title="PEC certificate",
        type="certificate",
        category="PEC certificate",
        shared=True,
        locked=False,
        approved=True,
    )
    db.add(doc)
    db.commit()

    opp_id = _make_opportunity(client, auth, title="Shared document tender")
    _, opp = _get(opp_id)
    selection = shared_documents.selection_for(db, opp)
    mine = [entry for entry in selection if entry["id"] == doc.id]
    assert len(mine) == 1
    assert mine[0]["included"] is True

    items = shared_documents.checklist_items(db, opp)
    assert any("PEC certificate" in item["item"] for item in items)
    db.close()


def test_a_shared_document_can_be_left_out_of_a_proposal(client, auth):
    """The bid team unticks what this tender does not need."""
    db = _session()
    doc = LibraryDocument(
        title="Credit line certificate",
        category="Credit line certificate",
        shared=True,
        approved=True,
    )
    db.add(doc)
    db.commit()

    opp_id = _make_opportunity(client, auth, title="Unticking tender")
    _, opp = _get(opp_id)
    shared_documents.set_included(db, opp, doc.id, False)
    selection = shared_documents.selection_for(db, opp)
    mine = [entry for entry in selection if entry["id"] == doc.id]
    assert mine[0]["included"] is False
    assert not any("Credit line certificate" in item["item"] for item in shared_documents.checklist_items(db, opp))
    db.close()


def test_a_locked_document_cannot_be_left_out(client, auth):
    """A locked document is the master copy and always travels."""
    db = _session()
    doc = LibraryDocument(
        title="Procurement forms",
        category="Procurement forms",
        shared=True,
        locked=True,
        approved=True,
    )
    db.add(doc)
    db.commit()

    opp_id = _make_opportunity(client, auth, title="Locked document tender")
    _, opp = _get(opp_id)
    try:
        shared_documents.set_included(db, opp, doc.id, False)
    except ValueError as exc:
        assert "locked" in str(exc)
    else:
        raise AssertionError("a locked document must not be unticked")
    db.close()


def test_the_shared_documents_are_served(client, auth):
    resp = client.get("/api/kb/shared", headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    assert "documents" in body
    assert "categories" in body
    # The seeded shared evidence is the evidence the feedback names.
    titles = [d["title"] for d in body["documents"]]
    assert any("PEC Certificate" in title for title in titles)
    assert any("Procurement Forms" in title for title in titles)


# ----------------------------------------------------------------------
# 2.8  Tenders whose deadline has passed
# ----------------------------------------------------------------------


def test_a_tender_whose_deadline_has_passed_is_marked_expired(client, auth):
    """A tender that can no longer be bid is not left looking live."""
    opp_id = _make_opportunity(
        client,
        auth,
        title="Long past deadline tender",
        submission_deadline=(utcnow() - timedelta(days=3)).strftime("%Y-%m-%d"),
    )
    detail = client.get(f"/api/opportunities/{opp_id}", headers=auth).json()
    assert detail["deadline_status"] == "expired"


def test_a_tender_still_open_is_not_marked_expired(client, auth):
    opp_id = _make_opportunity(
        client,
        auth,
        title="Still open tender",
        submission_deadline=(utcnow() + timedelta(days=10)).strftime("%Y-%m-%d"),
    )
    detail = client.get(f"/api/opportunities/{opp_id}", headers=auth).json()
    assert detail["deadline_status"] == "open"


def test_the_list_can_be_split_into_open_and_expired(client, auth):
    """The working list holds the tenders that can still be bid."""
    _make_opportunity(
        client,
        auth,
        title="Expired for the list test",
        submission_deadline=(utcnow() - timedelta(days=5)).strftime("%Y-%m-%d"),
    )
    _make_opportunity(
        client,
        auth,
        title="Open for the list test",
        submission_deadline=(utcnow() + timedelta(days=5)).strftime("%Y-%m-%d"),
    )

    expired = client.get("/api/opportunities", params={"deadline": "expired", "page_size": 100}, headers=auth).json()
    open_ = client.get("/api/opportunities", params={"deadline": "open", "page_size": 100}, headers=auth).json()

    expired_titles = [i["title"] for i in expired["items"]]
    open_titles = [i["title"] for i in open_["items"]]
    assert "Expired for the list test" in expired_titles
    assert "Expired for the list test" not in open_titles
    assert "Open for the list test" in open_titles
    assert "Open for the list test" not in expired_titles


def test_an_expired_tender_is_still_reachable(client, auth):
    """Moving a tender out of the working list must not lose it."""
    opp_id = _make_opportunity(
        client,
        auth,
        title="Expired but on file",
        submission_deadline=(utcnow() - timedelta(days=5)).strftime("%Y-%m-%d"),
    )
    detail = client.get(f"/api/opportunities/{opp_id}", headers=auth)
    assert detail.status_code == 200
    assert detail.json()["title"] == "Expired but on file"


def test_a_screened_out_tender_with_a_passed_date_is_expired(client, auth):
    """A tender whose window has shut is out of date whatever became of it.

    A tender that was screened out on merit is not out of date while its
    date is still ahead of us, but once the date has passed it can no
    longer be bid, and it belongs in the past-deadline section rather than
    sitting in the working list looking live.
    """
    opp_id = _make_opportunity(
        client,
        auth,
        title="Screened out, date already passed",
        submission_deadline=(utcnow() - timedelta(days=5)).strftime("%Y-%m-%d"),
    )
    db, opp = _get(opp_id)
    opp.state = "SCREENED_OUT"
    db.commit()
    db.close()

    detail = client.get(f"/api/opportunities/{opp_id}", headers=auth).json()
    assert detail["deadline_status"] == "expired"

    expired = client.get("/api/opportunities", params={"deadline": "expired", "page_size": 100}, headers=auth).json()
    titles = [i["title"] for i in expired["items"]]
    assert "Screened out, date already passed" in titles


def test_a_screened_out_tender_with_a_future_date_is_not_expired(client, auth):
    """It is judged on its date, not on being screened out."""
    opp_id = _make_opportunity(
        client,
        auth,
        title="Screened out, date still ahead",
        submission_deadline=(utcnow() + timedelta(days=20)).strftime("%Y-%m-%d"),
    )
    db, opp = _get(opp_id)
    opp.state = "SCREENED_OUT"
    db.commit()
    db.close()

    detail = client.get(f"/api/opportunities/{opp_id}", headers=auth).json()
    assert detail["deadline_status"] == "open"


def test_a_decided_bid_is_closed_rather_than_expired(client, auth):
    """A bid that was won or lost is closed, not merely out of date."""
    opp_id = _make_opportunity(
        client,
        auth,
        title="Decided bid with a passed date",
        submission_deadline=(utcnow() - timedelta(days=5)).strftime("%Y-%m-%d"),
    )
    db, opp = _get(opp_id)
    opp.state = "WON"
    db.commit()
    db.close()

    detail = client.get(f"/api/opportunities/{opp_id}", headers=auth).json()
    assert detail["deadline_status"] == "closed"

    expired = client.get("/api/opportunities", params={"deadline": "expired", "page_size": 100}, headers=auth).json()
    titles = [i["title"] for i in expired["items"]]
    assert "Decided bid with a passed date" not in titles


# ----------------------------------------------------------------------
# 2.1  The words on the screen
# ----------------------------------------------------------------------


def test_no_screen_prints_the_internal_workflow_state():
    """The internal state name never reaches the reader.

    The states are the system's own vocabulary: GATE1, SCREENED_OUT,
    NORMALIZED. A screen that prints one of them shows the reader the
    machinery instead of the bid. Every place that shows a state has to
    put it through stateLabel() first.
    """
    import re
    from pathlib import Path

    web = Path(__file__).resolve().parents[3] / "apps" / "web"
    assert web.is_dir(), f"the web app is not where this test expects it: {web}"
    # A state printed on its own: {o.state}, {opp.state}, {res.state}.
    raw = re.compile(r"\{[A-Za-z_$][\w$]*(?:\.[\w$]+)*\.state\}")

    offenders = []
    scanned = 0
    for path in web.rglob("*.js"):
        if "node_modules" in path.parts or ".next" in path.parts:
            continue
        scanned += 1
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if raw.search(line):
                offenders.append(f"{path.relative_to(web)}:{number}")

    assert scanned > 0, "no web sources were scanned, so the check proved nothing"
    assert not offenders, "raw workflow state printed on screen: " + ", ".join(offenders)


def test_every_workflow_state_has_a_readable_name():
    """Every state the system can be in has a word for the reader."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[3] / "apps" / "web" / "lib" / "api.js"
    ).read_text(encoding="utf-8")

    for state in (
        "NEW", "NORMALIZED", "SCORED", "SCREENED_OUT", "AUTO_ARCHIVED",
        "GATE1", "GATE2", "GATE3", "GATE4", "GATE5", "DOCS_FETCHED",
        "ANALYZED", "DRAFTING", "ASSEMBLY", "READY_TO_SUBMIT", "SUBMITTED",
        "EVALUATION", "WON", "LOST", "REJECTED", "ABANDONED",
    ):
        assert f"{state}:" in source, f"{state} has no readable name"


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _session():
    from app.db import SessionLocal

    return SessionLocal()


def _get(opp_id: int):
    """A tender record, read afresh so it can be changed and saved."""
    db = _session()
    return db, db.get(Opportunity, opp_id)


def _stub_opportunity():
    """A stand-in for the tender record, for the pure functions."""

    class _Opp:
        id = 1
        title = "Stub tender"
        description = ""
        category_internal = "General"
        contract_family = ""
        procurement_regime = ""
        pec_category_required = ""
        prequal_required = False
        qualification_thresholds = {}
        estimated_value = None
        value_band = ""
        currency = "PKR"
        tender_fee = None
        bid_security_amount = None
        bid_security_form = ""
        bid_security_percent = None
        estimated_boq_value = None
        boq_estimate_note = ""
        submission_deadline = None
        clarification_deadline = None
        opening_at = None

    return _Opp()


def _make_opportunity(client, auth, title, source_refs=None, submission_deadline="", description=""):
    """Create a tender through the API and return its id."""
    payload = {
        "title": title,
        "buyer_name": "Test buyer",
        "buyer_ref": "TEST-1",
        "description": description,
        "submission_deadline": submission_deadline,
        "source_label": "Test",
    }
    resp = client.post("/api/opportunities/manual", json=payload, headers=auth)
    assert resp.status_code == 200, resp.text
    opp_id = resp.json()["id"]

    if source_refs:
        db = _session()
        opp = db.get(Opportunity, opp_id)
        opp.source_refs = source_refs
        db.commit()
        db.close()

    return opp_id


def _document_for(db, opp, filename, content):
    from app.models import Document

    return Document(
        opportunity_id=opp.id,
        filename=filename,
        doc_type="ITT",
        file_path="",
        size=len(content),
        pages=1,
        parsed=True,
        content_text=content,
    )
