"""The bid summary: a tender read at a glance.

The bid room used to be shown one paragraph about a tender and had to find
whatever it needed inside it. This module writes the same material as
labelled sections — scope of work, experience, money, bid security,
deadline, key personnel, and the conditions that decide whether the job is
worth taking — so that a reader can go straight to the line they need.

The rules are the same as everywhere else in this codebase: the numbers
come from the deterministic layer, because a deadline or an amount that is
wrong is expensive, and the model is only allowed to add wording on top of
facts the deterministic layer has already established.
"""

import re

# The sections, in the order a bid manager reads them.
SECTIONS = [
    ("scope", "Scope of work"),
    ("experience", "Experience requirements"),
    ("financial", "Financial requirements"),
    ("bid_security", "Bid security"),
    ("deadline", "Submission deadline"),
    ("personnel", "Key personnel"),
    ("conditions", "Other important conditions"),
]

SECTION_LABELS = dict(SECTIONS)

# How each sentence is judged to belong to a section. The first section that
# matches a sentence wins, so the order here is the order of precedence.
SECTION_HINTS = {
    "bid_security": [
        "bid security", "earnest money", "bid bond", "bank guarantee",
    ],
    "deadline": [
        "last date", "submission deadline", "date of opening", "bid shall be opened",
        "bids will be opened", "closing date", "date of receipt", "clarification",
        "pre-bid meeting", "due date", "time of opening",
    ],
    "experience": [
        "similar work", "similar contract", "similar experience", "past experience",
        "years of experience", "previous contract", "comparable", "at least",
        "no. of contracts", "number of contracts", "track record",
    ],
    "financial": [
        "turnover", "net worth", "tender fee", "cost of documents",
        "price adjustment", "price shall be firm", "liquidated damages",
        "retention money", "advance payment", "insurance", "turnover",
    ],
    "personnel": [
        "personnel", "key staff", "site supervisor", "resident engineer",
        "project manager", "qualified engineer", "qualified staff", "staffing",
        "manpower", "team leader", "technical staff",
    ],
    "conditions": [
        "arbitration", "termination", "warranty", "defect liability",
        "completion period", "time for completion", "extension of time",
        "force majeure", "governing law", "dispute", "tax", "customs duty",
        "performance security", "performance guarantee",
    ],
    "scope": [
        "scope of work", "scope of supply", "the works", "the work consists",
        "the contractor shall", "the supplier shall", "shall supply",
        "shall construct", "shall erect", "commissioning", "the contractor is required",
    ],
}

# A sentence is only worth quoting when it says something about the tender.
# A heading on its own is not a requirement.
INTERESTING = re.compile(
    r"\b(shall|must|required|required to|is required|are required|mandatory|"
    r"not be|subject to|comply|complies|applicable|eligible|eligibility|"
    r"minimum|maximum|at least|not less than|within)\b",
    re.I,
)

# Where a section's points came from, so a reader can tell a tender's own
# words from the system's reading of them.
SOURCE_LABEL = {
    "clause": "Tender document",
    "field": "Tender record",
    "model": "System summary",
}

MAX_POINTS = 6
MAX_POINT_LENGTH = 260


def _sentences(text: str):
    """The sentences of a tender document, with their position.

    A sentence keeps its index so that a point can be traced back to where
    it was found, which is what makes a clause reference possible.
    """
    body = (text or "").replace("\r", "\n")
    parts = re.split(r"(?<=[.;])\s+|\n+", body)
    index = 0
    for part in parts:
        s = " ".join(part.split())
        if not s:
            continue
        yield index, s
        index += 1


def _clip(text: str, limit: int = MAX_POINT_LENGTH) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return (cut or text[:limit]) + "…"


def _section_for(sentence: str):
    """Which section a sentence belongs to, and whether it is worth quoting."""
    low = sentence.lower()
    for key, hints in SECTION_HINTS.items():
        if any(hint in low for hint in hints):
            return key
    return None


def _is_interesting(sentence: str) -> bool:
    if len(sentence) < 25:
        return False
    return bool(INTERESTING.search(sentence))


def _clause_anchor(sentence: str, index: int) -> str:
    """A reference to where in the document a point came from.

    A tender that prints its own clause numbers is best: the reader can
    open the document at the clause named. Otherwise the section of the
    document the sentence was found in is given, so the point is still
    traceable.
    """
    match = re.match(
        r"^\s*(?:clause|cl\.?|section|para(?:graph)?|art(?:icle)?)\s*"
        r"([0-9]+(?:\.[0-9]+)*)",
        sentence,
        re.I,
    )
    if match:
        return f"Clause {match.group(1)}"
    if re.match(r"^\s*\(\d+\)", sentence):
        return f"Clause {re.match(r'^\s*\((\d+)\)', sentence).group(1)}"
    return f"Section {index + 1}"


def build(db, opp, text: str, detected: dict) -> dict:
    """Write the sectioned summary for one tender.

    The result is a list of sections, each with a label and the points
    under it. A section the tender says nothing about is returned empty
    rather than left out, so the reader can see that it was looked for.
    """
    points = {key: [] for key, _ in SECTIONS}
    seen = {key: set() for key, _ in SECTIONS}

    def add(key, value, source="clause", anchor=""):
        value = _clip(value)
        if not value:
            return
        marker = value.lower()[:70]
        if marker in seen[key]:
            return
        seen[key].add(marker)
        points[key].append({"text": value, "source": source, "anchor": anchor})

    # The commercial fields come first, because they are the facts a bid
    # manager is actually looking for and the ones that must not be
    # paraphrased. The tender's own words fill in the rest of each section.
    _add_fields(points, add, opp, detected)

    # --- the tender's own words ---
    for index, sentence in _sentences(text):
        if not _is_interesting(sentence):
            continue
        key = _section_for(sentence)
        if not key:
            continue
        add(key, sentence, "clause", _clause_anchor(sentence, index))

    sections = []
    for key, label in SECTIONS:
        items = points[key][:MAX_POINTS]
        sections.append(
            {
                "key": key,
                "label": label,
                "available": bool(items),
                "points": items,
            }
        )
    return {"sections": sections}


def _add_fields(points, add, opp, detected: dict):
    """Add the fields that are known to the rupee and the minute.

    These come first in their section because they are the facts a bid
    manager is actually looking for, and they are the ones that must not be
    paraphrased.
    """
    # --- scope ---
    if opp.description:
        add("scope", opp.description, "field", "Tender notice")
    if opp.category_internal and opp.category_internal != "General":
        add("scope", f"Internal category: {opp.category_internal}", "field", "Tender record")
    if opp.contract_family:
        add("scope", f"Contract family: {opp.contract_family}", "field", "Tender record")
    if opp.procurement_regime:
        add("scope", f"Procurement regime: {opp.procurement_regime}", "field", "Tender record")

    # --- experience ---
    thresholds = detected.get("qualification_thresholds") or opp.qualification_thresholds or {}
    if thresholds.get("similar_work_count"):
        add(
            "experience",
            f"At least {thresholds['similar_work_count']} similar contract(s) of comparable value are required.",
            "field",
            "Qualification criteria",
        )
    if opp.pec_category_required:
        add(
            "experience",
            f"PEC licence category {opp.pec_category_required} is required.",
            "field",
            "Qualification criteria",
        )
    if opp.prequal_required:
        add("experience", "Pre-qualification applies — PQ status and forms are required.", "field", "Qualification criteria")

    # --- money ---
    if thresholds.get("turnover"):
        add(
            "financial",
            f"Minimum average annual turnover: PKR {thresholds['turnover']:,.0f}.",
            "field",
            "Qualification criteria",
        )
    if opp.estimated_value:
        add(
            "financial",
            f"Estimated value: {opp.currency} {opp.estimated_value:,.0f}.",
            "field",
            "Tender record",
        )
    if opp.tender_fee:
        add("financial", f"Tender fee: PKR {opp.tender_fee:,.0f}.", "field", "Tender document")
    boq_value = detected.get("estimated_boq_value")
    if boq_value:
        add(
            "financial",
            f"Indicative estimated BOQ value: PKR {boq_value:,.0f}, implied from the bid security.",
            "field",
            "Derived — verify",
        )
    if opp.value_band:
        add("financial", f"Value band: {opp.value_band}.", "field", "Tender record")

    # --- bid security ---
    if opp.bid_security_amount:
        currency = getattr(opp, "bid_security_currency", "") or "PKR"
        add(
            "bid_security",
            f"Bid security: {currency} {opp.bid_security_amount:,.0f}"
            + (f", in the form of a {opp.bid_security_form.lower()}." if opp.bid_security_form else "."),
            "field",
            "Tender document",
        )
    if opp.bid_security_percent:
        add(
            "bid_security",
            f"The bid security is stated as {opp.bid_security_percent:g}% of the estimated value.",
            "field",
            "Tender document",
        )
    if opp.boq_estimate_note:
        add("bid_security", opp.boq_estimate_note, "field", "Needs checking")

    # --- deadline ---
    if opp.submission_deadline:
        add(
            "deadline",
            f"Last date for submission of bids: {opp.submission_deadline.date().isoformat()}.",
            "field",
            "Tender document",
        )
    if opp.clarification_deadline:
        add(
            "deadline",
            f"Deadline for clarifications and queries: {opp.clarification_deadline.date().isoformat()}.",
            "field",
            "Tender document",
        )
    if opp.opening_at:
        add(
            "deadline",
            f"Bids are opened on {opp.opening_at.date().isoformat()}.",
            "field",
            "Tender document",
        )
    if not opp.submission_deadline:
        add(
            "deadline",
            "The tender does not publish a closing date — take it from the bidding document.",
            "field",
            "Needs checking",
        )

    # --- key personnel ---
    personnel = detected.get("personnel")
    if personnel:
        add("personnel", personnel, "field", "Tender document")
