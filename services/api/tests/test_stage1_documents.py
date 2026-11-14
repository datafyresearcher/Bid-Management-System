"""The notice and the bidding document are in hand while Stage 1 is decided.

Stage 1 is the Go/No-Go review, and the decision is taken on the documents:
the notice says what the buyer is buying, the bidding document says on what
terms. So both are fetched when the review opens and stored in the system —
not only after the decision — each kept with the portal address it was
fetched from, so what the record holds can be verified against what the
authority still publishes. A stored document can be opened from the record,
wherever the system runs.
"""

import pytest


PDF_BYTES = b"%PDF-1.4 fake bidding document for the test"
NOTICE_BYTES = b"%PDF-1.4 fake tender notice for the test"


class FakeConnector:
    """A connector that answers from in-memory files instead of a portal."""

    def __init__(self, docs=None, notice=None):
        self.docs = docs or []
        self.notice = notice
        self.notice_requests = []

    def fetch_documents(self, native_id, ref=None):
        return self.docs or None

    def download_document(self, url, filename=""):
        self.notice_requests.append(url)
        if self.notice is None:
            return None
        name = filename or url.split("?")[0].rsplit("/", 1)[-1] or "notice.pdf"
        return name, self.notice


@pytest.fixture()
def fake_connector(monkeypatch):
    """The registry hands back the fake, and the fake is reachable from tests."""
    holder = {}

    def get_connector(source):
        return holder.get("connector")

    from app.connectors import registry

    monkeypatch.setattr(registry, "get_connector", get_connector)
    holder["connector"] = FakeConnector()
    return holder


@pytest.fixture()
def live_mode(monkeypatch):
    """The suite runs in demo mode; the bridge only matters when reading live."""
    from app.config import settings

    monkeypatch.setattr(settings, "fixtures", False)


@pytest.fixture()
def epms_source(db):
    from app.models import Source

    source = db.query(Source).filter(Source.code == "epms_federal").first()
    assert source is not None, "the seeded sources should include epms_federal"
    return source


def make_opportunity(db, source, **ref_extra):
    from app.models import Opportunity

    ref = {
        "source_id": source.id,
        "source_code": source.code,
        "native_id": "epms-1001",
        "url": "https://epms.ppra.gov.pk/tender-details/TS-1001",
        "document_url": "https://epms.ppra.gov.pk/files/TS-1001-bidding-document.pdf",
    }
    ref.update(ref_extra)
    opp = Opportunity(
        title="Supply of laboratory equipment",
        buyer_name="A federal buyer",
        buyer_ref="TS-1001",
        source_refs=[ref],
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return opp


def documents_of(db, opp):
    """The record's documents, read back from the database rather than the
    (cache-friendly) relationship."""
    from app.models import Document

    return db.query(Document).filter(Document.opportunity_id == opp.id).all()


# -- storage --------------------------------------------------------------


def test_a_stored_document_keeps_its_bytes(db, epms_source):
    from app.services import documents

    opp = make_opportunity(db, epms_source)
    doc = documents.save_document(
        db, opp, "bidding.pdf", PDF_BYTES, source_url="https://epms.ppra.gov.pk/files/TS-1001-bidding-document.pdf"
    )

    assert doc.data == PDF_BYTES
    assert doc.source_url == "https://epms.ppra.gov.pk/files/TS-1001-bidding-document.pdf"


def test_a_file_past_the_ceiling_is_not_carried_in_the_database(db, epms_source, monkeypatch):
    from app.services import documents

    monkeypatch.setattr(documents, "MAX_INLINE_BYTES", 8)
    opp = make_opportunity(db, epms_source)
    doc = documents.save_document(db, opp, "huge.pdf", b"x" * 64)

    assert doc.data is None
    assert doc.size == 64


def test_a_document_can_be_filed_under_a_stated_type(db, epms_source):
    from app.services import documents

    opp = make_opportunity(db, epms_source)
    doc = documents.save_document(db, opp, "0009_2026-27.pdf", PDF_BYTES, doc_type=documents.NOTICE_DOC_TYPE)

    assert doc.doc_type == "Tender notice"


# -- fetching: bidding document, notice, provenance, dedup ----------------


def test_the_fetch_stores_the_bidding_document_and_the_notice(db, epms_source, fake_connector):
    from app.services import documents

    fake_connector["connector"] = FakeConnector(
        docs=[("TS-1001-bidding-document.pdf", PDF_BYTES)],
        notice=NOTICE_BYTES,
    )
    opp = make_opportunity(
        db,
        epms_source,
        notice_url="https://epms.ppra.gov.pk/files/TS-1001-notice.pdf",
    )

    fetched = documents.fetch_for_opportunity(db, opp)

    assert fetched == 2
    docs = {d.filename: d for d in documents_of(db, opp)}
    assert docs["TS-1001-bidding-document.pdf"].doc_type != "Tender notice"
    assert docs["TS-1001-bidding-document.pdf"].source_url == (
        "https://epms.ppra.gov.pk/files/TS-1001-bidding-document.pdf"
    )
    assert docs["TS-1001-notice.pdf"].doc_type == "Tender notice"
    assert docs["TS-1001-notice.pdf"].source_url == "https://epms.ppra.gov.pk/files/TS-1001-notice.pdf"
    assert opp.documents_status == "fetched"


def test_a_fetch_that_runs_twice_files_nothing_twice(db, epms_source, fake_connector):
    from app.services import documents

    fake_connector["connector"] = FakeConnector(
        docs=[("TS-1001-bidding-document.pdf", PDF_BYTES)],
        notice=NOTICE_BYTES,
    )
    opp = make_opportunity(
        db,
        epms_source,
        notice_url="https://epms.ppra.gov.pk/files/TS-1001-notice.pdf",
    )

    documents.fetch_for_opportunity(db, opp)
    documents.fetch_for_opportunity(db, opp)

    docs = documents_of(db, opp)
    assert len(docs) == 2
    assert {d.filename for d in docs} == {"TS-1001-bidding-document.pdf", "TS-1001-notice.pdf"}


def test_a_notice_that_is_the_same_file_as_the_bidding_document_is_not_fetched_twice(
    db, epms_source, fake_connector
):
    """NTDC publishes the notice and the bidding document as one file."""
    from app.services import documents

    fake_connector["connector"] = FakeConnector(docs=[("IFB-77.pdf", PDF_BYTES)])
    opp = make_opportunity(
        db,
        epms_source,
        url="https://ntdc.gov.pk/bidding/IFB-77.pdf",
        document_url="https://ntdc.gov.pk/bidding/IFB-77.pdf",
        notice_url="https://ntdc.gov.pk/bidding/IFB-77.pdf",
    )

    documents.fetch_for_opportunity(db, opp)

    docs = documents_of(db, opp)
    assert len(docs) == 1
    assert docs[0].filename == "IFB-77.pdf"


def test_a_notice_that_is_a_web_page_is_left_as_a_link(db, epms_source, fake_connector):
    """The downloader refuses a page; the record keeps the portal link instead."""
    from app.services import documents

    fake_connector["connector"] = FakeConnector(
        docs=[("TS-1001-bidding-document.pdf", PDF_BYTES)],
        # download_document returns None for a page, as the real one does.
        notice=None,
    )
    opp = make_opportunity(
        db,
        epms_source,
        notice_url="https://epms.ppra.gov.pk/tender-details/TS-1001",
    )

    documents.fetch_for_opportunity(db, opp)

    docs = documents_of(db, opp)
    assert len(docs) == 1
    assert docs[0].filename == "TS-1001-bidding-document.pdf"


# -- the bridge's fetch list ----------------------------------------------


def test_the_desk_is_asked_for_the_notice_as_well(db, epms_source):
    from app.services import documents

    opp = make_opportunity(
        db,
        epms_source,
        notice_url="https://epms.ppra.gov.pk/files/TS-1001-notice.pdf",
        related_documents=[],
    )

    wanted = documents.pending_document_urls(opp)

    kinds = {w["kind"]: w["url"] for w in wanted}
    assert kinds["bidding document"] == "https://epms.ppra.gov.pk/files/TS-1001-bidding-document.pdf"
    assert kinds["notice"] == "https://epms.ppra.gov.pk/files/TS-1001-notice.pdf"


def test_the_desk_is_not_asked_for_a_notice_it_already_has(db, epms_source):
    from app.services import documents

    opp = make_opportunity(
        db,
        epms_source,
        notice_url="https://epms.ppra.gov.pk/files/TS-1001-notice.pdf",
        related_documents=[],
    )
    documents.save_document(
        db, opp, "TS-1001-notice.pdf", NOTICE_BYTES,
        source_url="https://epms.ppra.gov.pk/files/TS-1001-notice.pdf",
        doc_type=documents.NOTICE_DOC_TYPE,
    )

    wanted = documents.pending_document_urls(opp)

    assert [w["kind"] for w in wanted] == ["bidding document"]


# -- Stage 1 opens the gate and the documents arrive ----------------------


def test_opening_stage_1_fetches_the_documents(db, epms_source, fake_connector):
    from app.services import workflow

    fake_connector["connector"] = FakeConnector(
        docs=[("TS-1001-bidding-document.pdf", PDF_BYTES)],
        notice=NOTICE_BYTES,
    )
    opp = make_opportunity(
        db,
        epms_source,
        notice_url="https://epms.ppra.gov.pk/files/TS-1001-notice.pdf",
    )

    task = workflow.open_gate(db, opp, gate=1, title="Go/No-Go — supply of laboratory equipment")

    assert task.gate == 1
    docs = documents_of(db, opp)
    assert {d.filename for d in docs} == {"TS-1001-bidding-document.pdf", "TS-1001-notice.pdf"}
    db.refresh(opp)
    assert opp.documents_status == "fetched"


def test_opening_stage_1_hands_a_bridge_tender_to_the_desk(db, live_mode):
    """A tender whose portal refuses the cloud is marked for the bridge."""
    from app.config import settings
    from app.models import Source
    from app.services import documents, workflow

    assert settings.fixtures is False
    source = db.query(Source).filter(Source.code == "ppra_punjab").first()
    opp = make_opportunity(db, source)

    workflow.open_gate(db, opp, gate=1, title="Go/No-Go — a Punjab tender")

    db.refresh(opp)
    assert opp.documents_status == documents.AWAITING_BRIDGE


# -- opening a stored document --------------------------------------------


def test_a_stored_document_can_be_downloaded_again(client, db, auth, epms_source):
    from app.services import documents

    opp = make_opportunity(db, epms_source)
    doc = documents.save_document(db, opp, "bidding.pdf", PDF_BYTES)

    resp = client.get(f"/api/opportunities/{opp.id}/documents/{doc.id}/download", headers=auth)

    assert resp.status_code == 200, resp.text
    assert resp.content == PDF_BYTES
    assert "bidding.pdf" in resp.headers.get("content-disposition", "")


def test_a_document_whose_disk_copy_is_gone_still_opens(client, db, auth, epms_source, monkeypatch):
    """The copy in the database answers when the disk does not."""
    from pathlib import Path

    from app.services import documents

    opp = make_opportunity(db, epms_source)
    doc = documents.save_document(db, opp, "notice.pdf", NOTICE_BYTES, doc_type=documents.NOTICE_DOC_TYPE)
    assert Path(doc.file_path).exists()
    Path(doc.file_path).unlink()

    resp = client.get(f"/api/opportunities/{opp.id}/documents/{doc.id}/download", headers=auth)

    assert resp.status_code == 200, resp.text
    assert resp.content == NOTICE_BYTES


def test_a_document_cannot_be_opened_through_another_tender(client, db, auth, epms_source):
    from app.services import documents

    opp = make_opportunity(db, epms_source)
    doc = documents.save_document(db, opp, "bidding.pdf", PDF_BYTES)

    resp = client.get(f"/api/opportunities/{opp.id + 1}/documents/{doc.id}/download", headers=auth)

    assert resp.status_code == 404


def test_a_document_with_no_file_anywhere_says_so(client, db, auth, epms_source, monkeypatch):
    from pathlib import Path

    from app.services import documents

    monkeypatch.setattr(documents, "MAX_INLINE_BYTES", 8)
    opp = make_opportunity(db, epms_source)
    doc = documents.save_document(db, opp, "huge.pdf", b"x" * 64)
    Path(doc.file_path).unlink()

    resp = client.get(f"/api/opportunities/{opp.id}/documents/{doc.id}/download", headers=auth)

    assert resp.status_code == 404
    assert "read text" in resp.json()["detail"]


# -- what the record page and the review card are told --------------------


def test_the_record_page_is_told_what_can_be_opened_and_verified(client, db, auth, epms_source):
    from app.services import documents

    opp = make_opportunity(db, epms_source)
    documents.save_document(
        db, opp, "bidding.pdf", PDF_BYTES, source_url="https://epms.ppra.gov.pk/files/TS-1001-bidding-document.pdf"
    )

    resp = client.get(f"/api/opportunities/{opp.id}", headers=auth)

    assert resp.status_code == 200, resp.text
    docs = resp.json()["documents"]
    assert docs[0]["has_file"] is True
    assert docs[0]["source_url"] == "https://epms.ppra.gov.pk/files/TS-1001-bidding-document.pdf"


def test_the_review_card_is_told_what_has_arrived(db, epms_source):
    from app.serializers import gate_task
    from app.services import documents, workflow

    opp = make_opportunity(db, epms_source)
    documents.save_document(db, opp, "bidding.pdf", PDF_BYTES)
    task = workflow.open_gate(db, opp, gate=1, title="Go/No-Go — serializer check")

    data = gate_task(task, include_opportunity=True)

    assert data["opportunity"]["documents_status"] == "uploaded"
    assert data["opportunity"]["documents_count"] == 1


def test_a_long_document_is_read_only_to_its_ceiling(db, epms_source, monkeypatch):
    """Reading a huge tender book stops at the ceiling instead of the request.

    The file is stored whole either way; the text says where the read
    stopped, so nobody mistakes a partial read for the whole document.
    """
    import io

    from pypdf import PdfWriter

    from app.services import documents

    monkeypatch.setattr(documents, "MAX_PAGES_READ", 3)
    writer = PdfWriter()
    for _ in range(5):
        writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    content = buffer.getvalue()

    opp = make_opportunity(db, epms_source)
    doc = documents.save_document(db, opp, "tender-book.pdf", content)

    assert doc.size == len(content)
    assert "stopped at page 4 of 5" in doc.content_text
    assert "on file whole" in doc.content_text
