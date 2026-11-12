"""The bid-submission checklist.

A tender asks for a specific set of documents, forms, schedules,
declarations and pieces of evidence, and the bid team has to produce every
one of them before the closing date. Reading a hundred-page bidding
document and listing the attachments by hand is where bids go wrong.

This module reads the bidding document and writes the list: what has to be
submitted, in what family, and where in the tender it is asked for. Each
item carries a reference — the clause number the tender prints, and the
page it is printed on — so the bid team can turn to the document and check
it rather than take the system's word for it.

The list is a starting point, not a verdict. The bid team marks each item
complete, pending, or not applicable, and the mark is theirs to change.
"""

import re

from app.services.documents import page_of_offset

# The three states a checklist item can be in.
STATUSES = ("pending", "complete", "not_applicable")

STATUS_LABELS = {
    "pending": "Pending",
    "complete": "Complete",
    "not_applicable": "Not applicable",
}

# The families of thing a tender asks for.
CATEGORIES = {
    "form": "Form",
    "declaration": "Declaration",
    "schedule": "Schedule",
    "certificate": "Certificate",
    "evidence": "Supporting evidence",
    "commercial": "Commercial",
    "portal": "Portal",
    "document": "Tender document",
}

# The things a bidding document asks for, and how each is recognised.
#
# Each pattern is a name to show the bid team and a way of finding it in
# the document. The patterns are written for the wording Pakistani bidding
# documents use, but they are deliberately loose: a tender that calls a
# form "Undertaking" rather than "Form of Undertaking" has to be caught
# too, and a false negative costs more than a false positive.
ITEM_PATTERNS = [
    # -- forms --
    ("Form — tenderer's information / Form A", "form", [r"\bform[\s\-–]?a\b", r"tenderer'?s\s+information\s+form"]),
    ("Form — Form B", "form", [r"\bform[\s\-–]?b\b"]),
    ("Form — Form C", "form", [r"\bform[\s\-–]?c\b"]),
    ("Form — Form D", "form", [r"\bform[\s\-–]?d\b"]),
    ("Form — Form E", "form", [r"\bform[\s\-–]?e\b"]),
    ("Form — Form F", "form", [r"\bform[\s\-–]?f\b"]),
    ("Form — Form G", "form", [r"\bform[\s\-–]?g\b"]),
    ("Form — Form H", "form", [r"\bform[\s\-–]?h\b"]),
    ("Form — Form of Tender", "form", [r"form\s+of\s+tender", r"tender\s+form"]),
    ("Form — schedule of deviations", "form", [r"schedule\s+of\s+deviations?", r"deviation\s+schedule"]),
    ("Form — power of attorney", "declaration", [r"power\s+of\s+attorney", r"authorised\s+signatory", r"authorization\s+letter"]),
    ("Form — undertaking / affidavit", "declaration", [r"undertaking", r"affidavit"]),
    ("Form — declaration of non-blacklisting", "declaration", [r"non[\s\-]?blacklist(?:ing)?\s+declaration", r"declaration\s+(?:of\s+)?non[\s\-]?blacklist", r"affidavit\s+of\s+non[\s\-]?blacklist"]),
    ("Form — declaration / certificate of correctness", "declaration", [r"declaration\s+of\s+(?:correctness|truth)", r"certificate\s+of\s+correctness"]),
    ("Form — joint venture / association agreement", "declaration", [r"joint\s+venture\s+agreement", r"association\s+agreement", r"memorandum\s+of\s+understanding", r"mou\b"]),
    # -- schedules --
    ("Schedule — priced bill of quantities (BOQ)", "schedule", [r"bill\s+of\s+quantit", r"\bboq\b", r"priced\s+(?:schedule|bill)", r"schedule\s+of\s+prices"]),
    ("Schedule — price schedule / unit rates", "schedule", [r"price\s+schedule", r"schedule\s+of\s+unit\s+rates", r"unit\s+rate\s+schedule"]),
    ("Schedule — technical / compliance schedule", "schedule", [r"compliance\s+schedule", r"technical\s+schedule", r"schedule\s+of\s+deviations"]),
    ("Schedule — evaluation criteria matrix", "schedule", [r"evaluation\s+criteria", r"criteria\s+for\s+(?:evaluation|award)"]),
    # -- certificates --
    ("Certificate — PEC licence", "certificate", [r"\bpec\b[^\n]{0,40}licen[cs]e", r"pakistan\s+engineering\s+council[^\n]{0,40}licen[cs]e"]),
    ("Certificate — NTN / sales tax registration", "certificate", [r"\bntn\b[^\n]{0,30}certificat", r"sales\s+tax\s+registration", r"active\s+taxpayers?\s+list"]),
    ("Certificate — incorporation / registration", "certificate", [r"certificate\s+of\s+incorporation", r"memorandum\s+of\s+association", r"company\s+registration\s+certificate"]),
    ("Certificate — CNIC", "certificate", [r"\bcnic\b", r"national\s+identity\s+card"]),
    ("Certificate — credit line / banking arrangement", "certificate", [r"credit\s+line", r"banking\s+arrangement", r"letter\s+of\s+credit"]),
    # -- supporting evidence --
    ("Evidence — similar work completion certificates", "evidence", [r"similar\s+work[^\n]{0,60}certificate", r"completion\s+certificate", r"certificate\s+of\s+completion"]),
    ("Evidence — audited financial statements", "evidence", [r"audited\s+(?:financial\s+statements|accounts)", r"auditor'?s\s+report", r"annual\s+report[^\n]{0,30}audited"]),
    ("Evidence — turnover proof / bank statement", "evidence", [r"turnover[^\n]{0,60}(?:certificate|statement|proof)", r"bank\s+statement"]),
    ("Evidence — list of key personnel with CVs", "evidence", [r"(?:resume|cv|curriculum\s+vitae)s?\s+of", r"key\s+personnel[^\n]{0,40}(?:list|schedule|cv)"]),
    ("Evidence — equipment / plant schedule", "evidence", [r"list\s+of\s+equipment", r"plant\s+and\s+equipment", r"schedule\s+of\s+equipment"]),
    # -- commercial --
    ("Commercial — bid security instrument", "commercial", [r"bid\s+security", r"earnest\s+money", r"bid\s+bond"]),
    ("Commercial — tender fee payment receipt / challan", "commercial", [r"tender\s+fee", r"cost\s+of\s+(?:the\s+)?bidding\s+document", r"document\s+fee", r"challan"]),
    ("Commercial — performance security", "commercial", [r"performance\s+security", r"performance\s+guarantee"]),
    # -- portal --
    ("Portal — supplier registration and DSC / e-token", "portal", [r"\bdsc\b", r"e[\s\-]?token", r"supplier\s+registration", r"digital\s+signature"]),
    ("Portal — electronic submission / uploaded envelope", "portal", [r"electronic\s+submission", r"e[\s\-]?submission", r"technical\s+envelope", r"financial\s+envelope", r"upload\s+on\s+the\s+portal"]),
]

# The items every tender needs, whether or not the document names them. A
# bid that misses the bid security or the priced bill of quantities does not
# open, whatever the document says.
ALWAYS_ITEMS = [
    ("Commercial — bid security instrument", "commercial", True),
    ("Schedule — priced bill of quantities (BOQ)", "schedule", True),
    ("Form — signed and sealed technical and financial bids", "form", True),
]

MAX_ITEMS = 40


def _find_all(text: str, patterns):
    """The first place each pattern matches, with what it matched."""
    hits = []
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            hits.append((match.start(), match.group(0)))
    return hits


def _clause_before(text: str, offset: int) -> str:
    """The clause number printed nearest before this point in the document."""
    window = text[max(0, offset - 700) : offset]
    matches = list(re.finditer(r"(?:clause|cl\.?|section|para(?:graph)?|art(?:icle)?)\s*([0-9]+(?:\.[0-9]+)*)", window, re.I))
    if matches:
        return f"Clause {matches[-1].group(1)}"
    return ""


def build(db, opp, text: str) -> list:
    """The list of things this tender asks the bidder to submit.

    Each entry says what the item is, which family it belongs to, where in
    the tender it is asked for, and whether it is mandatory.
    """
    text = text or ""
    items = []
    seen = set()

    def add(label, category, clause, page, mandatory, origin):
        key = label.lower()
        if key in seen:
            return
        seen.add(key)
        items.append(
            {
                "item": label,
                "category": category,
                "category_label": CATEGORIES.get(category, category),
                "clause": clause,
                "page": page,
                "mandatory": mandatory,
                "status": "pending",
                "origin": origin,
            }
        )

    # --- what the document itself asks for ---
    for label, category, patterns in ITEM_PATTERNS:
        hits = _find_all(text, patterns)
        if not hits:
            continue
        offset = min(h[0] for h in hits)
        clause = _clause_before(text, offset)
        page = page_of_offset(text, offset)
        add(label, category, clause, page, True, "document")

    # --- what every bid needs ---
    for label, category, mandatory in ALWAYS_ITEMS:
        add(label, category, "", None, mandatory, "standard")

    # --- the commercial fields the record already holds ---
    if opp.tender_fee:
        add(
            f"Commercial — tender fee of PKR {opp.tender_fee:,.0f} paid and receipted",
            "commercial",
            "",
            None,
            True,
            "record",
        )
    if opp.bid_security_amount:
        currency = getattr(opp, "bid_security_currency", "") or "PKR"
        add(
            f"Commercial — bid security of {currency} {opp.bid_security_amount:,.0f} arranged",
            "commercial",
            "",
            None,
            True,
            "record",
        )
    if opp.submission_deadline:
        add(
            "Document — submission receipt / acknowledgement saved as proof",
            "document",
            "",
            None,
            True,
            "standard",
        )

    return items[:MAX_ITEMS]


def with_statuses(existing, generated) -> list:
    """Merge a freshly generated list with the marks the bid team has made.

    The list is regenerated whenever the analysis is re-run, so the marks
    the team has already made are carried over. A mark is only kept while
    the item it was made on is still on the list.
    """
    marks = {}
    for item in existing or []:
        if not isinstance(item, dict):
            continue
        key = (item.get("item") or "").strip().lower()
        status = item.get("status") or ""
        if key and status in STATUSES:
            marks[key] = status

    out = []
    for item in generated:
        key = (item.get("item") or "").strip().lower()
        if key in marks:
            item = {**item, "status": marks[key]}
        out.append(item)
    return out


def regenerate(db, opp) -> list:
    """Rebuild the checklist for a tender and store it on the record.

    The marks the bid team has already made are carried across, so that
    re-running the analysis does not throw away their work.
    """
    from app.services.extractor import collect_text

    text = collect_text(db, opp)
    generated = build(db, opp, text)
    merged = with_statuses(opp.checklist, generated)
    opp.checklist = merged
    db.commit()
    return merged


def set_status(db, opp, index: int, status: str) -> list:
    """Mark one item of the checklist.

    Returns the updated list. The index is the item's place on the list the
    bid team is looking at, so it is the one the marks are kept against.
    """
    if status not in STATUSES:
        raise ValueError(f"Unknown checklist status: {status}")
    items = [dict(item) for item in (opp.checklist or [])]
    if index < 0 or index >= len(items):
        raise IndexError("Invalid checklist index")
    items[index]["status"] = status
    opp.checklist = items
    db.commit()
    return items
