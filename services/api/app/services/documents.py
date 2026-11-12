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


def save_document(db, opp, filename: str, content: bytes) -> Document:
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
