import io
import re
from pathlib import Path

from sqlalchemy import delete, select

from app.config import storage_path
from app.models import Document, DocumentChunk
from app.services import audit

DOC_TYPE_KEYWORDS = [
    ("ITT", ["itt", "itb", "instruction", "tender document"]),
    ("GCC-PCC", ["gcc", "pcc", "conditions of contract", "general conditions"]),
    ("BOQ", ["boq", "bill of quantit", "price schedule", "priced"]),
    ("Specs", ["spec", "technical provision", "special provision"]),
    ("Forms", ["form", "appendices", "appendix"]),
    ("Drawings", ["drawing", "layout", "single line", "sld"]),
    # A buyer publishes changes to a tender against the tender itself. They
    # are not part of the bidding document, and a reader has to be able to
    # tell them apart at a glance — an amendment can move the deadline.
    ("Clarification", ["clarification", "clarifications", "pre-bid", "prebid", "q&a", "queries"]),
    ("Amendment", ["amendment", "addendum", "addenda"]),
    ("Corrigendum", ["corrigendum", "corrigenda", "revision", "revised"]),
]

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150

# Pages are separated by a form feed, so that a point taken from a document
# can be traced to the page it is printed on. A bid manager checking a
# clause needs to be able to turn to that page.
PAGE_BREAK = "\n\f\n"

# A record whose portal cannot be reached from here, and whose document is
# therefore being fetched by the bid desk's own machine.
AWAITING_BRIDGE = "awaiting_bridge"

# The placeholder written when no document could be fetched. It carries only
# what the listing already said, and is replaced by the real document when
# that arrives.
SUMMARY_FILENAME = "notice_summary.txt"


def page_count(text: str) -> int:
    """How many pages a document's text holds."""
    if not text:
        return 0
    return text.count("\f") + 1


def page_of_offset(text: str, offset: int) -> int:
    """The page an offset falls on, counted from one."""
    if not text or offset < 0:
        return 1
    return text.count("\f", 0, offset) + 1


def classify_doc(filename: str) -> str:
    f = filename.lower()
    for doc_type, keywords in DOC_TYPE_KEYWORDS:
        if any(k in f for k in keywords):
            return doc_type
    return "Other"


def extract_text(filename: str, content: bytes) -> str:
    name = filename.lower()
    try:
        if name.endswith(".pdf"):
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(content))
            return PAGE_BREAK.join((page.extract_text() or "") for page in reader.pages)[:400_000]
        if name.endswith(".docx"):
            from docx import Document as DocxDocument

            doc = DocxDocument(io.BytesIO(content))
            return PAGE_BREAK.join(p.text for p in doc.paragraphs)[:400_000]
        if name.endswith((".html", ".htm")):
            from bs4 import BeautifulSoup

            return BeautifulSoup(content.decode("utf-8", errors="ignore"), "html.parser").get_text(" ")[:400_000]
        return content.decode("utf-8", errors="ignore")[:400_000]
    except Exception as exc:
        return f"[PARSE_ERROR] {exc}"


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        body = text[start:end].strip()
        if body:
            chunks.append(body)
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def save_document(db, opp, filename: str, content: bytes, source_url: str = "") -> Document:
    folder = storage_path() / "documents" / str(opp.id)
    folder.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._\- ]", "_", filename)[:180]
    path = folder / safe_name
    path.write_bytes(content)

    text = extract_text(filename, content)
    doc = Document(
        opportunity_id=opp.id,
        filename=safe_name,
        doc_type=classify_doc(filename),
        file_path=str(path),
        source_url=(source_url or "")[:600],
        size=len(content),
        pages=page_count(text),
        parsed=not text.startswith("[PARSE_ERROR]"),
        parse_status="" if not text.startswith("[PARSE_ERROR]") else text[:200],
        content_text=text,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
    for i, chunk in enumerate(chunk_text(text)):
        db.add(DocumentChunk(document_id=doc.id, opportunity_id=opp.id, chunk_index=i, text=chunk, anchor=f"{doc.doc_type} #{i+1}"))
    db.commit()

    if opp.documents_status in ("none", "metadata_only"):
        opp.documents_status = "uploaded"
        db.commit()
    audit.record(db, "document.saved", opportunity_id=opp.id, detail={"filename": safe_name, "type": doc.doc_type, "size": len(content)})
    return doc


def fetch_for_opportunity(db, opp) -> int:
    from app.connectors.registry import get_connector
    from app.models import Source

    fetched = 0
    refs = list(opp.source_refs or [])
    resolved_links = {}
    for ref in refs:
        source_id = ref.get("source_id")
        if not source_id:
            # A converted lead can carry a source reference with no source id.
            # db.get() with a None key is a warning today and is an error later.
            continue
        source = db.get(Source, source_id)
        if not source:
            continue
        connector = get_connector(source)
        if not connector:
            continue
        native_id = ref.get("native_id") or ""
        fetched_docs = connector.fetch_documents(native_id, ref=ref)
        # A portal may publish the document only behind a button on the
        # tender's page, in which case the file that was read from is kept on
        # the record — so the tender ends up with a direct link to the
        # document rather than only to the page it sits on.
        resolved = getattr(connector, "last_document_url", "") or ""
        if resolved:
            resolved_links[native_id] = resolved
        if fetched_docs is None:
            continue
        for filename, content in fetched_docs:
            if len(content) > 50 * 1024 * 1024:
                continue
            save_document(db, opp, filename, content)
            fetched += 1

    if resolved_links:
        _keep_resolved_links(opp, resolved_links)
    if fetched == 0 and opp.documents_status == "none":
        fallback = (
            f"Notice summary (no attachments retrieved).\n"
            f"Title: {opp.title}\nBuyer: {opp.buyer_name}\nReference: {opp.buyer_ref}\n"
            f"Description: {opp.description}\n"
        )
        save_document(db, opp, "notice_summary.txt", fallback.encode("utf-8"))
        fetched = 1

    # Whether the file itself was retrieved or not, the record has to say
    # where the bidding document lives. A tender whose document could not be
    # downloaded is still a tender the bid team has to open, so the link is
    # kept on the record and shown as a download link.
    if has_document_link(opp):
        opp.documents_status = "fetched" if fetched else "link_only"
    elif fetched:
        opp.documents_status = "fetched"
    db.commit()
    return fetched


def _keep_resolved_links(opp, resolved_links: dict) -> None:
    """Put the file links that were found onto the record's own references."""
    refs = []
    changed = False
    for ref in opp.source_refs or []:
        if not isinstance(ref, dict):
            refs.append(ref)
            continue
        resolved = resolved_links.get(ref.get("native_id") or "")
        if resolved and ref.get("document_url") != resolved:
            ref = dict(ref)
            ref["document_url"] = resolved
            ref["url"] = resolved
            changed = True
        refs.append(ref)
    if changed:
        opp.source_refs = refs


def has_document_link(opp) -> bool:
    """Whether the record points at a bidding document on the portal.

    The link is the fallback when the file cannot be downloaded, so it is
    kept whatever happens to the download.
    """
    for ref in opp.source_refs or []:
        if not isinstance(ref, dict):
            continue
        if ref.get("document_url"):
            return True
        for related in ref.get("related_documents") or []:
            if isinstance(related, dict) and related.get("url"):
                return True
    return False


def related_documents(opp) -> list:
    """Every related document the buyer published against this tender.

    Deduplicated across the notices the record was captured from, because a
    tender can be seen on more than one of them and a reader must not be
    offered the same clarification twice.
    """
    seen = set()
    out = []
    for ref in opp.source_refs or []:
        if not isinstance(ref, dict):
            continue
        for related in ref.get("related_documents") or []:
            if not isinstance(related, dict):
                continue
            url = related.get("url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            out.append(
                {
                    "title": related.get("title") or "Related document",
                    "url": url,
                    "date": related.get("date") or "",
                    "kind": related.get("kind") or "related",
                }
            )
    return out


def document_link(opp) -> str:
    """The direct link to the bidding document on the authority's site."""
    for ref in opp.source_refs or []:
        if not isinstance(ref, dict):
            continue
        url = ref.get("document_url") or ""
        if url:
            return url
    return ""


def pending_document_urls(opp) -> list[dict]:
    """The documents this tender still needs, and where each one is.

    A portal publishes more than one file against a tender — the bidding
    document, the tender notice, and any correction published against it —
    and the record carries the address of each. What is still missing is
    decided by what is already on file: a document is matched on the address
    it was fetched from, and on its name for the files that were fetched
    before the address was kept. So the same document is not asked for twice,
    even when what was filed is its text rather than the file itself.
    """
    on_file = {doc.filename for doc in (opp.documents or []) if doc.filename}
    fetched_from = {
        (doc.source_url or "").strip()
        for doc in (opp.documents or [])
        if (doc.source_url or "").strip()
    }
    wanted: list[dict] = []
    seen: set[str] = set()
    for ref in opp.source_refs or []:
        if not isinstance(ref, dict):
            continue
        candidates: list[dict] = []
        primary = ref.get("document_url") or ""
        if primary:
            candidates.append(
                {"url": primary, "kind": "bidding document", "title": "Bidding document"}
            )
        for entry in ref.get("related_documents") or []:
            if isinstance(entry, dict) and entry.get("url"):
                candidates.append(
                    {
                        "url": entry["url"],
                        "kind": entry.get("kind") or "related",
                        "title": entry.get("title") or "Related document",
                    }
                )
        for candidate in candidates:
            url = candidate["url"]
            if url in seen:
                continue
            seen.add(url)
            if url in fetched_from:
                continue
            name = url.split("?")[0].rsplit("/", 1)[-1]
            if name and name in on_file:
                continue
            wanted.append({**candidate, "filename": name})
    return wanted


def drop_placeholder_summary(db, opp) -> bool:
    """Remove the notice summary once the real document has arrived.

    The summary is a stand-in, written from what the listing already said.
    Left in place it would be read alongside the real document and dilute
    what the analysis is drawn from.

    The summary's own chunks go with it. They point at the summary, and the
    database the system runs on refuses a row that is deleted while another
    still points at it — so a summary deleted without its chunks would fail
    on the deployment and pass on a developer's machine, where the same
    rule is not enforced by default.
    """
    removed = False
    for doc in list(opp.documents or []):
        if doc.filename != SUMMARY_FILENAME:
            continue
        db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
        db.delete(doc)
        removed = True
    if removed:
        db.commit()
        # The tender's documents are read again on the next access, rather
        # than refreshed in place: the summary that was just deleted is still
        # in the loaded collection, and refreshing would go looking for it.
        db.expire(opp, ["documents"])
    return removed


def settle(db, opp) -> bool:
    """Finish a tender whose document has arrived.

    A hand-over can be cut off half way through — the request runs out of
    time after the file has been stored but before the tender is analysed
    again. The record is then waiting for a document it already has, and
    nothing would fetch it again, so it would wait for ever.

    So a record with a document on file and no analysis of it is finished
    here: the stand-in is dropped, the record is marked as carrying its
    documents, and the tender is analysed again from the documents
    themselves.

    Returns whether the record was settled.
    """
    from app.services import workflow

    if opp.documents_status != AWAITING_BRIDGE:
        return False
    if not has_document_link(opp):
        # Nothing was ever published against this tender to fetch.
        return False
    if not any(doc.filename != SUMMARY_FILENAME for doc in (opp.documents or [])):
        # Only the stand-in is on file: the document has not arrived.
        return False

    drop_placeholder_summary(db, opp)
    opp.documents_status = "uploaded"
    db.commit()
    workflow.reanalyze(db, opp)
    return True


def mark_awaiting_bridge(db, opp) -> int:
    """Mark a tender whose document has to come from the bid desk's machine.

    The portal refuses connections from here, so the document is fetched
    where the portal answers. The stand-in written from the listing is kept
    for now — it is what there is to read until the real document arrives —
    and the record is marked so the desk's machine knows to go and fetch it.
    """
    saved = 0
    if not any(doc.filename == SUMMARY_FILENAME for doc in (opp.documents or [])):
        fallback = (
            "Notice summary (the bidding document is being fetched from the bid desk).\n"
            f"Title: {opp.title}\nBuyer: {opp.buyer_name}\nReference: {opp.buyer_ref}\n"
            f"Description: {opp.description}\n"
        )
        save_document(db, opp, SUMMARY_FILENAME, fallback.encode("utf-8"))
        saved = 1
    opp.documents_status = AWAITING_BRIDGE
    db.commit()
    return saved


def search_chunks(db, opportunity_id: int, query: str, limit: int = 5):
    terms = [t for t in re.findall(r"[a-z0-9]{3,}", query.lower())]
    chunks = db.execute(select(DocumentChunk).where(DocumentChunk.opportunity_id == opportunity_id)).scalars().all()
    scored = []
    for chunk in chunks:
        text_l = chunk.text.lower()
        score = sum(text_l.count(term) for term in terms)
        if score:
            scored.append((score, chunk))
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:limit]]
