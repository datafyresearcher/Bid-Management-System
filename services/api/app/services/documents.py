import io
import re
import time
from pathlib import Path

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import selectinload

from app.config import storage_path
from app.models import Document, DocumentChunk, Opportunity
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

# The largest file kept in the database as its own bytes. The disk copy
# beside it lives on whatever filesystem the instance runs on, and a
# serverless deployment sweeps that away between requests — so a document
# smaller than this is carried in the database as well, and keeps opening
# wherever the system runs. A file past the ceiling is not carried there; it
# keeps its disk copy and its read text.
MAX_INLINE_BYTES = 20_000_000

# A fetch for one tender — resolve the portal's page, download the files —
# can take the better part of half a minute when a portal is slow. A request
# with less left than this skips the fetch rather than run past its own
# deadline; the tender's documents are then fetched when its Stage 1 decision
# runs the full analysis.
STAGE1_FETCH_MIN_SECONDS = 15.0

# The analysis that follows a hand-over — reading the document out, extracting
# the requirements, building the checklist — takes real seconds, and the
# request that carried the file over has a hard limit. Below this much
# remaining, the analysis is deferred to the bridge's next call rather than
# let the whole hand-over be killed with the record half-done.
ANALYSIS_MIN_SECONDS = 25.0

# The document type given to the notice a buyer publishes to announce the
# tender, as opposed to the bidding document that carries the terms.
NOTICE_DOC_TYPE = "Tender notice"


def filename_from_url(url: str) -> str:
    """The file name a portal address ends with."""
    return (url or "").split("?")[0].rsplit("/", 1)[-1]


def safe_filename(filename: str) -> str:
    """The name a document is filed under."""
    return re.sub(r"[^A-Za-z0-9._\- ]", "_", filename)[:180]


# Reading the text out of a document is bounded. A tender book of hundreds
# of pages, or one whose structure pypdf picks through slowly, could hold
# the request that carries it past its whole life — the read stops at the
# budget or the page ceiling, and says where it stopped. The file itself is
# stored whole either way; the text is what the analysis works from.
TEXT_BUDGET_SECONDS = 15.0
MAX_PAGES_READ = 150


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
            pages = []
            deadline = time.monotonic() + TEXT_BUDGET_SECONDS
            for index, page in enumerate(reader.pages):
                if index >= MAX_PAGES_READ:
                    pages.append(f"[Document read stopped at page {index + 1} of {len(reader.pages)} — the ceiling of pages read. The file is on file whole.]")
                    break
                if index and time.monotonic() > deadline:
                    pages.append(f"[Document read stopped at page {index + 1} of {len(reader.pages)} — the time budget for reading ran out. The file is on file whole.]")
                    break
                pages.append(page.extract_text() or "")
            text = PAGE_BREAK.join(pages)
        elif name.endswith(".docx"):
            from docx import Document as DocxDocument

            doc = DocxDocument(io.BytesIO(content))
            text = PAGE_BREAK.join(p.text for p in doc.paragraphs)
        elif name.endswith((".html", ".htm")):
            from bs4 import BeautifulSoup

            text = BeautifulSoup(content.decode("utf-8", errors="ignore"), "html.parser").get_text(" ")
        else:
            text = content.decode("utf-8", errors="ignore")
    except Exception as exc:
        return f"[PARSE_ERROR] {exc}"
    # A reader can emit NUL bytes — pypdf picking through an Urdu scan does —
    # and the database refuses a text field that carries one. The bytes mean
    # nothing in either place; they are dropped.
    return text.replace("\x00", "")[:400_000]


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


def save_document(db, opp, filename: str, content: bytes, source_url: str = "", doc_type: str = "") -> Document:
    folder = storage_path() / "documents" / str(opp.id)
    folder.mkdir(parents=True, exist_ok=True)
    safe_name = safe_filename(filename)
    path = folder / safe_name
    path.write_bytes(content)

    text = extract_text(filename, content)
    doc = Document(
        opportunity_id=opp.id,
        filename=safe_name,
        doc_type=doc_type or classify_doc(filename),
        file_path=str(path),
        source_url=(source_url or "")[:600],
        size=len(content),
        pages=page_count(text),
        parsed=not text.startswith("[PARSE_ERROR]"),
        parse_status="" if not text.startswith("[PARSE_ERROR]") else text[:200],
        content_text=text,
        # The file itself, up to the ceiling — see MAX_INLINE_BYTES. This is
        # what lets the bid team open the document from the record wherever
        # the system runs, not only on the instance that downloaded it.
        data=content if len(content) <= MAX_INLINE_BYTES else None,
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


def _already_on_file(db, opp) -> tuple[set, set]:
    """What a tender already carries: its file names, and the addresses files
    were fetched from. A document is matched on the address first — the name
    is the fallback for files fetched before addresses were kept.

    Read from the database rather than the record's loaded collection: the
    session does not expire on commit, so a collection loaded before this
    request saved documents would not show them.
    """
    rows = db.execute(select(Document).where(Document.opportunity_id == opp.id)).scalars().all()
    names = {doc.filename for doc in rows if doc.filename}
    urls = {(doc.source_url or "").strip() for doc in rows if (doc.source_url or "").strip()}
    return names, urls


def _ref_addresses(ref: dict) -> dict:
    """The portal address each file a notice publishes is fetched from.

    A file is filed under the name its address ends with, so the address can
    be kept on the stored document — the record then carries, next to every
    file, the link to open it on the portal and confirm the two are the same.
    """
    addresses: dict[str, str] = {}
    for key in ("document_url", "url", "notice_url", "bidding_document_url"):
        url = (ref.get(key) or "").strip()
        if url:
            addresses.setdefault(filename_from_url(url), url)
    for entry in ref.get("related_documents") or []:
        if isinstance(entry, dict):
            url = (entry.get("url") or "").strip()
            if url:
                addresses.setdefault(filename_from_url(url), url)
    return addresses


def fetch_for_opportunity(db, opp) -> int:
    """Fetch the tender's documents and file them.

    Every notice the record was captured from publishes a bidding document
    and usually the tender notice as a file of its own, plus any correction
    published against it. Each is downloaded, stored whole, and kept with the
    address it came from, so what is on file can always be checked against
    what the portal still publishes. A file already on the record is not
    fetched a second time — matched on the address it was fetched from, then
    on its name — so a fetch that runs twice, once when the tender reaches
    Stage 1 and again when it is approved, files nothing twice.
    """
    from app.connectors.registry import get_connector
    from app.models import Source

    fetched = 0
    on_file_names, on_file_urls = _already_on_file(db, opp)
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
        addresses = _ref_addresses(ref)
        fetched_docs = connector.fetch_documents(native_id, ref=ref)
        # A portal may publish the document only behind a button on the
        # tender's page, in which case the file that was read from is kept on
        # the record — so the tender ends up with a direct link to the
        # document rather than only to the page it sits on.
        resolved = getattr(connector, "last_document_url", "") or ""
        if resolved:
            resolved_links[native_id] = resolved
        for filename, content in fetched_docs or []:
            if len(content) > 50 * 1024 * 1024:
                continue
            if safe_filename(filename) in on_file_names:
                continue
            doc = save_document(
                db, opp, filename, content, source_url=addresses.get(filename_from_url(filename), "")
            )
            on_file_names.add(doc.filename)
            if doc.source_url:
                on_file_urls.add(doc.source_url)
            fetched += 1

        # The tender notice itself. The bidding document is what the analysis
        # reads, but the notice is what the buyer published to announce the
        # tender, and the bid team verifies the one against the other — so it
        # is fetched and filed with the rest. A notice that is a web page
        # rather than a file (WAPDA's notice is the post itself) is refused
        # by the downloader, and honestly left as a link.
        notice_url = (ref.get("notice_url") or "").strip()
        if notice_url and notice_url not in on_file_urls:
            if safe_filename(filename_from_url(notice_url)) not in on_file_names:
                downloaded = connector.download_document(notice_url)
                if downloaded:
                    filename, content = downloaded
                    doc = save_document(
                        db, opp, filename, content, source_url=notice_url, doc_type=NOTICE_DOC_TYPE
                    )
                    on_file_names.add(doc.filename)
                    on_file_urls.add(doc.source_url or notice_url)
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
    # kept on the record and shown as a download link. A pass that found
    # files reports them; a pass that found nothing new never demotes a
    # record that already carries documents — uploaded by hand, or fetched by
    # an earlier pass — to link-only.
    if fetched:
        opp.documents_status = "fetched"
    elif opp.documents_status not in ("uploaded", "parsed", "fetched"):
        if has_document_link(opp):
            opp.documents_status = "link_only"
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
        # The tender notice the buyer published to announce the tender. Where
        # the notice is a file of its own the desk's machine fetches it with
        # the rest; where the notice is only a web page the downloader
        # refuses it and the link stays as the way to read it.
        notice = (ref.get("notice_url") or "").strip()
        if notice:
            candidates.append({"url": notice, "kind": "notice", "title": "Tender notice"})
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
            name = filename_from_url(url)
            if name and name in on_file:
                continue
            wanted.append({**candidate, "filename": name})
    return wanted


def find_by_source_url(opp, url: str):
    """The document on file that was fetched from this address, if any."""
    wanted = (url or "").strip()
    if not wanted:
        return None
    for doc in opp.documents or []:
        if (doc.source_url or "").strip() == wanted:
            return doc
    return None


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

    A tender whose document has already arrived is not waiting for one, so it
    is left as it is.
    """
    if any(doc.filename != SUMMARY_FILENAME for doc in (opp.documents or [])):
        # The document has arrived; there is nothing to wait for.
        return 0

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


def ensure_stage1_documents(db, opp) -> None:
    """Put the tender's documents in hand while Stage 1 is being decided.

    Stage 1 is the Go/No-Go review, and the decision is taken on the
    documents: the notice says what the buyer is buying, the bidding document
    says on what terms. So both are fetched when the review opens, not only
    once it is approved — the reviewer opens the bid room and finds them on
    file, each with the link to the portal address it came from.

    A tender whose portal answers this deployment has its files fetched here,
    bounded by what the request can still afford; a tender whose portal
    refuses datacenter connections is marked for the bid desk's capture
    bridge, which fetches them on its next run. Either way the fetch is
    idempotent — a tender whose documents are already on file gets nothing
    downloaded twice — and anything that could not be got in time is fetched
    again by the analysis that runs on the Stage 1 decision.
    """
    from app import runtime
    from app.services import workflow

    if workflow._needs_the_bridge(db, opp):
        mark_awaiting_bridge(db, opp)
        return
    left = runtime.remaining()
    if left is not None and left < STAGE1_FETCH_MIN_SECONDS:
        return
    try:
        fetch_for_opportunity(db, opp)
    except Exception as exc:
        # The gate has opened either way. Whatever went wrong is recorded and
        # the fetch is retried on the Stage 1 decision, which runs the same
        # fetch before the analysis.
        audit.record(
            db,
            "documents.stage1_fetch_failed",
            opportunity_id=opp.id,
            detail={"error": str(exc)[:200]},
        )


def sweep_due_analyses(db) -> int:
    """Finish the analyses a hand-over had to defer.

    A document carried over in a request that was running out of time is on
    file but unread — no requirements, no figures — and nothing in the
    ordinary flow would pick it up: the record is no longer waiting for a
    document, and the analysis runs on its own only when the Stage 1 decision
    is taken. The bridge's call sweeps those records here, as many as the
    request can still afford, before asking for more documents.
    """
    from app import runtime
    from app.services import workflow

    from app.serializers import FINAL_STATES

    handled: set[int] = set()
    done = 0
    while True:
        left = runtime.remaining()
        if left is not None and left < ANALYSIS_MIN_SECONDS:
            break
        conditions = [
            Opportunity.documents_status == "uploaded",
            or_(Opportunity.extraction_grade == "", Opportunity.extraction_grade.is_(None)),
            Opportunity.state.not_in(tuple(FINAL_STATES)),
        ]
        if handled:
            conditions.append(Opportunity.id.not_in(sorted(handled)))
        opp = (
            db.execute(
                select(Opportunity)
                .options(selectinload(Opportunity.documents))
                .where(*conditions)
                .order_by(Opportunity.id)
                .limit(1)
            )
            .scalars()
            .first()
        )
        if opp is None:
            break
        handled.add(opp.id)
        try:
            workflow.reanalyze(db, opp)
            done += 1
        except Exception:
            # One record that will not analyse must not eat the sweep; it is
            # left for the Stage 1 decision, which runs the analysis again.
            db.rollback()
    return done


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
