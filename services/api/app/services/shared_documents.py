"""The shared documents every proposal carries.

The bid team writes the same evidence into every proposal it puts forward:
the PEC certificate, the procurement forms, the financial predictions, the
credit line certificate. Uploading each of them again for every tender is
wasteful and error-prone, and a proposal that carries a stale copy of the
licence is worse than one that carries none.

So those documents are held once, in the knowledge base, and each proposal
says which of them it carries. A shared document can be locked, so that it
is the master copy and can only be changed from the knowledge base and not
from inside a tender. And the proposal itself has a step where the bid team
ticks and unticks the shared documents, so a tender that does not need the
credit line certificate does not carry it.
"""

import re

from sqlalchemy import select

from app.config import storage_path
from app.models import LibraryDocument, Proposal

# The families of shared document a bid desk keeps.
CATEGORIES = [
    "PEC certificate",
    "Procurement forms",
    "Financial predictions",
    "Credit line certificate",
    "Company profile",
    "Bank guarantee template",
    "Standard tender template",
    "General",
]

MAX_UPLOAD = 30 * 1024 * 1024


def _safe_name(filename: str) -> str:
    return re.sub(r"[^A-Za-z0-9._\- ]", "_", filename or "document.bin")[:180]


def list_documents(db, shared_only: bool = False) -> list:
    """The knowledge-base documents, newest first."""
    query = select(LibraryDocument)
    if shared_only:
        query = query.where(LibraryDocument.shared == True)  # noqa: E712
    rows = db.execute(query.order_by(LibraryDocument.id.desc())).scalars().all()
    return [document(d) for d in rows]


def document(d) -> dict:
    """One knowledge-base document, as the bid team sees it."""
    return {
        "id": d.id,
        "title": d.title,
        "type": d.type,
        "category": d.category or "General",
        "tags": d.tags,
        "shared": bool(d.shared),
        "locked": bool(d.locked),
        "approved": bool(d.approved),
        "valid_until": d.valid_until or "",
        "has_file": bool(d.file_path),
        "file_path": d.file_path,
        "has_text": bool(d.content_text),
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


def save_file(db, doc: LibraryDocument, filename: str, content: bytes) -> LibraryDocument:
    """Store a document's file and read its text.

    The text is kept as well as the file, so that the drafting service can
    quote from the shared documents without opening the file each time.
    """
    from app.services.documents import extract_text

    folder = storage_path() / "knowledge-base"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{doc.id}_{_safe_name(filename)}"
    path.write_bytes(content)

    doc.file_path = str(path)
    doc.content_text = extract_text(filename, content)[:200_000]
    db.commit()
    db.refresh(doc)
    return doc


def selection_for(db, opp) -> list:
    """The shared documents, each marked as carried by this proposal or not.

    Until the bid team makes a choice, every approved shared document is
    carried: the point of the shared library is that the usual evidence is
    already on file and does not have to be uploaded again.
    """
    proposal = db.execute(
        select(Proposal).where(Proposal.opportunity_id == opp.id)
    ).scalars().first()
    chosen = None
    if proposal is not None and proposal.included_kb_docs is not None:
        chosen = {int(i) for i in proposal.included_kb_docs}

    rows = (
        db.execute(
            select(LibraryDocument)
            .where(LibraryDocument.shared == True)  # noqa: E712
            .order_by(LibraryDocument.id)
        )
        .scalars()
        .all()
    )
    out = []
    for d in rows:
        entry = document(d)
        if chosen is None:
            entry["included"] = bool(d.approved)
        else:
            entry["included"] = d.id in chosen
        out.append(entry)
    return out


def set_included(db, opp, doc_id: int, included: bool) -> list:
    """Tick or untick a shared document for one proposal.

    A locked document is the master copy and always travels with the
    proposal: it is edited and removed from the knowledge base, never from
    inside a tender, so that a proposal is never built on a document that
    somebody changed on the way past.
    """
    doc = db.get(LibraryDocument, doc_id)
    if not doc:
        raise LookupError("Shared document not found")
    if not doc.shared:
        raise ValueError("That document is not a shared document")
    if doc.locked and not included:
        raise ValueError(
            f"“{doc.title}” is locked — it is carried by every proposal and can only be changed "
            "from the knowledge base."
        )

    proposal = db.execute(
        select(Proposal).where(Proposal.opportunity_id == opp.id)
    ).scalars().first()
    if proposal is None:
        # The proposal is written at Stage 3. The choice is kept on the
        # opportunity until then, so that the bid team can make it while
        # they are preparing the bid.
        proposal = Proposal(opportunity_id=opp.id, status="DRAFT")
        db.add(proposal)
        db.flush()

    current = selection_for(db, opp)
    ids = {entry["id"] for entry in current if entry["included"]}
    if included:
        ids.add(doc_id)
    else:
        ids.discard(doc_id)
    proposal.included_kb_docs = sorted(ids)
    db.commit()
    return selection_for(db, opp)


def checklist_items(db, opp) -> list:
    """The shared documents, as items on the submission checklist.

    These are the documents the team has already said the proposal carries,
    so they are marked as covered rather than pending — but they are listed
    so that a reviewer can see the proposal was built on the master copies.
    """
    items = []
    for entry in selection_for(db, opp):
        if not entry["included"]:
            continue
        items.append(
            {
                "item": f"Shared document — {entry['title']}",
                "category": "shared",
                "category_label": "Shared document",
                "clause": "",
                "page": None,
                "mandatory": False,
                "status": "complete",
                "origin": "knowledge-base",
                "document_id": entry["id"],
            }
        )
    return items
