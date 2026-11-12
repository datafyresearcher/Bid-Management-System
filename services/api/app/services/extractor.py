"""Extract structured requirements and key commercial fields from tender documents.

Two layers work together:

* a **deterministic layer** — patterns written against the formats Pakistani
  procurement notices actually use. It handles the fields that drive money and
  deadlines, where a miss is expensive;
* an **AI layer** — the LLM (or the deterministic engine) adds requirement
  recall on messy prose and tables, and its output is schema-validated before
  it is allowed into the database.

The result is graded so the bid room can show how far to trust the analysis.
"""

import re

from sqlalchemy import delete, select

from app import runtime
from app.llm import provider as llm
from app.llm import prompts, schemas
from app.models import Document, ExtractedRequirement
from app.services import audit
from app.services import bid_summary
from app.services import documents
from app.services.utils import normalize_key, parse_amount, parse_date, parse_money, snippet

# How much of a tender's text is read. A full bidding document runs to
# roughly a hundred thousand characters — the instructions, the bid data
# sheet, the conditions of contract and the forms — and the commercial terms
# a bid manager needs sit in the middle of it, so a cap that cuts the tail
# off loses the greater part of the document. The AI layer reads its own
# smaller slice below, so this does not change what is sent to the model.
TEXT_CAP = 200000
LLM_CAP = 40000

CATEGORY_HINTS = [
    ("qualification", ["pec", "licence", "license", "registration", "taxpayer", "blacklist", "turnover", "similar work", "experience", "iso"]),
    ("commercial", ["bid security", "earnest money", "performance security", "bank guarantee", "insurance", "price", "payment"]),
    ("form", ["form", "undertaking", "affidavit", "power of attorney", "declaration"]),
    ("deadline", ["deadline", "last date", "closing", "opening", "clarification", "query"]),
    ("technical", ["specification", "technical", "equipment", "personnel", "methodology", "schedule"]),
]

# Critical fields drive the commercial decision. Their presence drives the
# extraction grade shown to the reviewer.
CRITICAL_FIELDS = [
    "submission_deadline",
    "bid_security_amount",
    "pec_category_required",
    "qualification_thresholds",
]

SUBMISSION_DEADLINE_TRIGGERS = [
    r"last\s+date(?:\s+and\s+time)?(?:\s+for)?(?:\s+(?:of\s+)?(?:the\s+)?(?:submission|receipt|bids?|tender|proposals?))?",
    r"bid\s+submission\s+deadline",
    r"submission\s+deadline",
    r"closing\s+(?:date|of\s+bids?)",
    r"tender\s+closing\s+date",
    r"date\s+of\s+closing",
    r"date\s+of\s+receipt",
    r"due\s+date",
    r"receipt\s+of\s+bids?",
    r"submission\s+of\s+bids?",
]

OPENING_DATE_TRIGGERS = [
    r"date\s+of\s+opening",
    r"opening\s+date",
    r"bids?\s+(?:shall\s+be|will\s+be|are\s+to\s+be|shall\s+)?opened",
    r"opening\s+of\s+bids?",
    r"proposals?\s+(?:will\s+be|shall\s+be)?\s*opened",
]

BID_SECURITY_TRIGGERS = [
    r"bid\s+security",
    r"earnest\s+money",
    r"bid\s+bond",
]

# The bases a bid-security percentage can be taken of. A percentage on its
# own says nothing; "2% of the estimated cost" says what to multiply.
BOQ_BASE_PHRASES = (
    "estimated cost",
    "estimated value",
    "estimated boq",
    "estimated price",
    "estimated annual rent",
    "boq value",
    "bill of quantities",
    "contract price",
    "contract value",
    "bid price",
    "tender price",
    "price of the contract",
    "estimated amount",
    "total contract value",
)

# A base need not be one of the fixed phrases — buyers word it their own way
# ("2% of the estimated annual rent", "2% of price of procurement estimated
# by PEF"). What matters is that the percentage is of a *value*: the thing it
# is taken of has to be the contract's worth. A percentage of something that
# is not a value — "5% of the offer", which is the bidder's own price —
# says nothing about the contract's worth, so it is not taken.
BOQ_BASE_PATTERN = re.compile(
    r"\bof\s+(?:the\s+|an?\s+)?(?:\w+[\s-]+){0,4}?"
    r"(?:costs?|prices?|values?|amounts?|rents?|boqs?|bills?\s+of\s+quantit\w*|sums?)\b",
    re.I,
)

# Other things a tender states a percentage of, which sit close enough to a
# bid security clause to be picked up by mistake. A percentage belonging to
# one of these is not the bid security's percentage.
OTHER_PERCENTAGE_SUBJECTS = (
    "liquidated damages",
    "liquidated damages",
    "retention money",
    "retention",
    "advance payment",
    "performance security",
    "performance guarantee",
    "price adjustment",
    "escalation",
    "defect liability",
    "profit",
    "markup",
    "withholding",
)

TENDER_FEE_TRIGGERS = [
    r"tender\s+document\s+fee",
    r"tender\s+fee",
    r"cost\s+of\s+(?:the\s+)?(?:bidding|tender)\s+documents?",
    r"document(?:s)?\s+fee",
    r"fee\s+for\s+(?:the\s+)?(?:bidding|tender)\s+documents?",
    r"non-?refundable\s+(?:tender\s+)?fee",
    r"cost\s+of\s+documents?",
]

TURNOVER_TRIGGERS = [
    r"average\s+annual\s+turnover",
    r"annual\s+turnover",
    r"turnover",
]

ESTIMATED_VALUE_TRIGGERS = [
    r"estimated\s+cost",
    r"estimated\s+value",
    r"estimated\s+amount",
    r"tender\s+value",
    r"cost\s+of\s+work",
]

# A money token: an amount that is explicitly currency-denominated. Percentages
# are deliberately excluded, so "bid security shall be 2% ... or Rs. 4,000,000"
# resolves to the rupee figure rather than to "2".
#
# A figure directly followed by a percent sign is excluded too. A tender's own
# table prints its column headings as "Estimated Cost in PKR 02% Bid Security
# in PKR 01", and those are a rate and a serial number rather than amounts.
#
# The scale a tender's tables put in brackets — "RS. 3.75 (M)" — is part of
# the amount and is read with it.
MONEY_TOKEN = re.compile(
    r"(?:(?<![A-Za-z])(?:rs\.?|pkr|usd)\b|us\$|\$)\s*\.?\s*"
    r"((?:\d[\d,\.]*\d|\d)(?!\d)"
    r"(?:\s*(?:million|billion|crore|lakh|lacs|thousand))?"
    r"(?:\s*\(\s*(?:million|mn|billion|bn|crore|lacs|lac|lakh|thousand|m|b|cr|l|k)\s*\))?)"
    r"(?!\s*%)",
    re.I,
)

# A bid security is a sum of money, and a sum in the low hundreds is not one.
# At that size the figure is a rate, a serial number or a stamp-paper value
# that happened to sit beside the words "bid security" — a flattened table
# heading is the usual culprit. Below the floor the figure is not read as the
# amount at all, so the record reports the amount as not found and asks for
# it to be checked, rather than dividing a stray digit into a confident
# number. A real bid security is never this small.
MIN_BID_SECURITY = 1_000

# A date candidate in any of the formats Pakistani notices use, including the
# ordinal and Urdu forms.
DATE_TOKEN = re.compile(
    r"\d{1,2}(?:st|nd|rd|th)?\s*[\-/.,]?\s*"
    r"(?:[A-Za-z]{3,9}\s*[\-/.,]?\s*)?\d{1,2}\s*[\-/.,]?\s*(?:[A-Za-z]{3,9}\s*)?\d{2,4}"
    r"|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}\s*,?\s*\d{2,4}"
    r"|\d{4}\s*[\-/]\s*\d{1,2}\s*[\-/]\s*\d{1,2}"
    r"|\d{1,2}\s*[؀-ۿ]{3,10}\s*,?\s*\d{2,4}"
)

WORK_NOUN = r"(?:works?|projects?|contracts?|studies|assignments|packages|consultanc\w*|schemes|facilities)"

SIMILAR_WORK_PATTERNS = [
    rf"(?:at\s+least|minimum(?:\s+of)?|not\s+less\s+than|no\.?\s*of\s*at\s+least)\s*"
    rf"(\d{{1,2}})\s*(?:no\.?s?\.?\s*of\s*)?[^.]{{0,30}}?{WORK_NOUN}",
    rf"(\d{{1,2}})\s*(?:no\.?s?\.?\s*of\s*)?similar\s+[^.]{{0,30}}?{WORK_NOUN}",
]

PEC_PATTERNS = [
    # An explicit category reference wins over a bare PEC mention, because
    # "PEC category C-A (No Limit)" should be read as C-A.
    r"(?:category|cat\.?)[^\n]{0,40}?\b(C-A|C-B|C-1|C-2|C-3|C-4)\b",
    r"\bPEC\b[^\n]{0,120}?\b(C-A|C-B|C-1|C-2|C-3|C-4|No\s*Limit)\b",
    r"pakistan\s+engineering\s+council[^\n]{0,60}?\bcategory\s+(C-A|C-B|C-1|C-2|C-3|C-4)\b",
]

SECURITY_FORM_KEYWORDS = [
    "bank guarantee", "pay order", "demand draft", "call deposit", "deposit at call",
    "letter of credit",
]


def _first_trigger(text, triggers):
    """Position of the earliest trigger match in the text."""
    best = None
    for trigger in triggers:
        match = re.search(trigger, text, re.I)
        if match and (best is None or match.start() < best.start()):
            best = match
    return best


def _after(text, triggers, window=120):
    """The text following the earliest trigger, bounded to ``window`` chars."""
    match = _first_trigger(text, triggers)
    if not match:
        return None
    return text[match.end() : match.end() + window]


def _closest_money(text, triggers, max_distance=200, minimum=0):
    """The money amount sitting closest to any trigger phrase.

    Proximity matters: a section heading like "BID SECURITY AND TENDER FEE"
    is a trigger match too, but the amount that belongs to it is far away.
    Picking the *nearest* amount to *any* trigger resolves that, and also
    handles a document that states the same field more than once.

    An amount below ``minimum`` is passed over rather than taken, and the
    search carries on: the nearest figure is sometimes a rate or a serial
    number that only looks like an amount, and the one that belongs to the
    field is further along.
    """
    best = None
    for trigger in triggers:
        for anchor in re.finditer(trigger, text, re.I):
            start = anchor.end()
            for match in MONEY_TOKEN.finditer(text, start, start + max_distance):
                amount = parse_amount(match.group(1))
                if amount is None or amount < minimum:
                    continue
                distance = match.start() - start
                if best is None or distance < best[0]:
                    best = (distance, amount)
                break
    return best[1] if best else None


def _closest_date(text, triggers, max_distance=200):
    """The parseable date sitting closest to any trigger phrase."""
    best = None
    for trigger in triggers:
        for anchor in re.finditer(trigger, text, re.I):
            start = anchor.end()
            for token in DATE_TOKEN.finditer(text, start, start + max_distance):
                parsed = parse_date(token.group(0))
                if parsed is None:
                    continue
                distance = token.start() - start
                if best is None or distance < best[0]:
                    best = (distance, parsed)
                break
    return best[1] if best else None


def _first_money_after(text, triggers, window=160):
    segment = _after(text, triggers, window)
    if not segment:
        return None
    match = MONEY_TOKEN.search(segment)
    if not match:
        return None
    return parse_amount(match.group(1))


def collect_text(db, opp) -> str:
    docs = db.execute(select(Document).where(Document.opportunity_id == opp.id)).scalars().all()
    return "\n\n".join(d.content_text or "" for d in docs if d.content_text)[:TEXT_CAP]


def _only_the_stand_in_is_on_file(db, opp) -> bool:
    """Whether the only document on file is the listing's stand-in.

    The stand-in is written from what the portal's listing already said. A
    real document beside it means there is something to read, and the reading
    is worth keeping even while the document of record is still on its way.
    """
    names = db.execute(
        select(Document.filename).where(Document.opportunity_id == opp.id)
    ).scalars().all()
    return all(name == documents.SUMMARY_FILENAME for name in names)


def _classify_requirement(text: str) -> str:
    t = text.lower()
    for category, hints in CATEGORY_HINTS:
        if any(h in t for h in hints):
            return category
    return "compliance"


def _first_match(patterns, text, group=1):
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return match
    return None


def _flat(text: str) -> str:
    """The text with its line breaks flattened to single spaces.

    A tender's bidding document is mostly tables, and a table read as text
    puts every cell on its own line: "5% of" then "estimated" then "cost" are
    three lines, not one phrase. The phrase is there and the reader cannot see
    it. The windows a phrase is looked for in are flattened before the search,
    while the text the offsets are taken from is left alone, so a point can
    still be traced to the page it is printed on.
    """
    return re.sub(r"\s+", " ", text)


def _bid_security_percent(text: str):
    """The share of the estimated BOQ value that the bid security represents.

    A tender states it in the way the buyer likes: "bid security of 2% of
    the estimated cost", "2% of the contract price shall be furnished as
    bid security". The percentage is only usable when it is tied to a base
    value, so a bare "2%" is not enough — and if the document quotes more
    than one percentage against the same trigger, the figure is ambiguous
    and nothing is assumed.

    Returns ``(percent, ambiguous)``.
    """
    found = {}
    for trigger in BID_SECURITY_TRIGGERS:
        for anchor in re.finditer(trigger, text, re.I):
            # The percentage can sit either side of the trigger, so the
            # window is taken around it rather than after it.
            start = max(0, anchor.start() - 160)
            window = text[start : anchor.end() + 220]
            for match in re.finditer(r"(\d{1,2}(?:\.\d{1,2})?)\s*(?:%|percent(?![a-z]))", window, re.I):
                value = float(match.group(1))
                if not 0 < value <= 100:
                    continue
                # It has to belong to the bid security, not to something
                # else that happens to sit nearby — "liquidated damages at
                # 0.05% of the contract price" is a percentage too, and so is
                # "retain 5% of the contract value as retention money".
                near = _flat(window[max(0, match.start() - 70) : match.start()]).lower()
                tail = _flat(window[match.end() : match.end() + 100]).lower()
                if any(other in near or other in tail for other in OTHER_PERCENTAGE_SUBJECTS):
                    continue
                # The percentage has to be tied to a base value for it to
                # mean anything: "2% of the estimated cost".
                if not any(phrase in tail for phrase in BOQ_BASE_PHRASES) and not BOQ_BASE_PATTERN.search(tail):
                    continue
                found.setdefault(value, match.start())
    if not found:
        return None, False
    if len(found) > 1:
        # More than one percentage — the document is not saying clearly which
        # one the security is calculated on, so nothing is assumed.
        return None, True
    return next(iter(found)), False


def _detect_fields(text: str) -> dict:
    """Pull the critical commercial fields out of the document text."""
    detected = {}

    # --- submission deadline (kept separate from the opening date) ---
    parsed = _closest_date(text, SUBMISSION_DEADLINE_TRIGGERS)
    if parsed:
        detected["submission_deadline"] = parsed

    parsed = _closest_date(text, OPENING_DATE_TRIGGERS)
    if parsed:
        detected["opening_at"] = parsed

    # --- bid security ---
    amount = _closest_money(text, BID_SECURITY_TRIGGERS, minimum=MIN_BID_SECURITY)
    if amount:
        detected["bid_security_amount"] = amount
    # The percentage is read whether or not an amount was found: a tender
    # that states both is the normal case, and the implied BOQ value needs
    # the two together.
    percent, ambiguous = _bid_security_percent(text)
    if percent:
        detected["bid_security_percent"] = percent
    elif ambiguous:
        detected["bid_security_percent_ambiguous"] = True
    for form_kw in SECURITY_FORM_KEYWORDS:
        if form_kw in text.lower():
            detected["bid_security_form"] = form_kw.title()
            break

    # --- implied BOQ value ---
    # The estimated value of the work implied by the bid security:
    #     estimated BOQ value = bid-security amount / bid-security percentage
    # The percentage has to come from the tender document. Where it is not
    # stated, or is stated ambiguously, the estimate is not made and the
    # record says so instead.
    if amount and percent:
        detected["estimated_boq_value"] = round(amount / (percent / 100.0), 2)
        detected["boq_estimate_note"] = (
            f"Indicative only: implied from the bid security of {amount:,.0f} at {percent:g}% "
            "of the estimated value. Confirm against the tender document before pricing."
        )
    elif amount and ambiguous:
        detected["boq_estimate_note"] = (
            "The tender states more than one percentage against the bid security, so the "
            "estimated BOQ value has not been calculated. Verify the percentage from the tender document."
        )
    elif amount:
        detected["boq_estimate_note"] = (
            "The bid security amount was found, but the tender does not state the percentage it "
            "represents, so the estimated BOQ value has not been calculated. Verify it from the tender document."
        )
    elif percent:
        detected["boq_estimate_note"] = (
            f"The bid security is stated as {percent:g}% of the estimated value, but no bid security "
            "amount was found, so the estimated BOQ value has not been calculated."
        )

    # --- tender fee ---
    amount = _closest_money(text, TENDER_FEE_TRIGGERS)
    if amount:
        detected["tender_fee"] = amount

    # --- PEC category ---
    match = _first_match(PEC_PATTERNS, text)
    if match:
        detected["pec_category_required"] = re.sub(r"\s+", " ", match.group(1)).upper()

    # --- procurement regime ---
    if re.search(r"pre-?qualif", text, re.I):
        detected["prequal_required"] = True
    if re.search(r"two[- ](?:stage|envelope)", text, re.I):
        detected["procurement_regime"] = "two-stage-two-envelope"
    elif re.search(r"single[- ](?:stage|envelope)", text, re.I):
        detected["procurement_regime"] = "single-stage-one-envelope"

    # --- qualification thresholds ---
    thresholds = {}
    amount = _closest_money(text, TURNOVER_TRIGGERS)
    if amount:
        thresholds["turnover"] = amount
    match = _first_match(SIMILAR_WORK_PATTERNS, text)
    if match:
        try:
            thresholds["similar_work_count"] = int(match.group(1))
        except (TypeError, ValueError):
            pass
    if thresholds:
        detected["qualification_thresholds"] = thresholds

    # --- contract value stated in the document ---
    amount = _closest_money(text, ESTIMATED_VALUE_TRIGGERS)
    if amount:
        detected["document_estimated_value"] = amount

    # --- key personnel the tender asks for ---
    personnel = _key_personnel(text)
    if personnel:
        detected["personnel"] = personnel

    return detected


# The staff a tender names, and what it says about them. The bid team has to
# know who has to be named in the bid before they can staff it.
PERSONNEL_PATTERNS = [
    re.compile(
        r"[^.]{0,160}\b(?:project\s+manager|resident\s+engineer|site\s+(?:supervisor|manager|engineer)|"
        r"construction\s+manager|general\s+supervisor|key\s+staff|key\s+personnel|technical\s+staff|"
        r"team\s+leader|principal\s+engineer)\b[^.]{0,160}\.",
        re.I,
    ),
]


def _key_personnel(text: str) -> str:
    """The key personnel a tender asks for, as one readable line."""
    for pattern in PERSONNEL_PATTERNS:
        match = pattern.search(text or "")
        if not match:
            continue
        sentence = " ".join(match.group(0).split())
        if len(sentence) < 25:
            continue
        if sentence.endswith("."):
            sentence = sentence[:-1]
        return sentence[:300]
    return ""


def _grade(detected: dict, requirement_count: int, has_text: bool) -> tuple:
    """Grade the extraction so the reviewer knows how much to trust it.

    Returns ``(grade, confidence)``.
    """
    if not has_text:
        return "D", 0.1

    present = sum(1 for field in CRITICAL_FIELDS if detected.get(field))
    if present == len(CRITICAL_FIELDS):
        grade = "A"
    elif present >= 2:
        grade = "B"
    elif present == 1:
        grade = "C"
    else:
        grade = "D"

    field_score = present / len(CRITICAL_FIELDS)
    recall_score = min(1.0, requirement_count / 15)
    confidence = round(0.65 * field_score + 0.35 * recall_score, 3)
    return grade, confidence


def _apply_fields(opp, detected: dict) -> None:
    """Put the fields that were detected on the record.

    Only fields that map to a real Opportunity column are written back.
    """
    settable = {
        "submission_deadline",
        "opening_at",
        "bid_security_amount",
        "bid_security_form",
        "bid_security_percent",
        "estimated_boq_value",
        "boq_estimate_note",
        "tender_fee",
        "pec_category_required",
        "prequal_required",
        "procurement_regime",
    }
    for field, value in detected.items():
        if field == "qualification_thresholds":
            merged = dict(opp.qualification_thresholds or {})
            merged.update(value or {})
            opp.qualification_thresholds = merged
        elif field in settable:
            setattr(opp, field, value)

    # A percentage that was found on a previous read but is no longer stated
    # must not stay behind as a stale number, or the implied BOQ value would
    # keep pointing at a figure the document no longer supports.
    if "bid_security_percent" not in detected:
        opp.bid_security_percent = None
        opp.estimated_boq_value = None
    if "boq_estimate_note" not in detected:
        opp.boq_estimate_note = ""


def _replace_requirements(db, opp, requirements) -> int:
    """Write the requirements found, replacing any that were there before."""
    seen = set()
    db.execute(delete(ExtractedRequirement).where(ExtractedRequirement.opportunity_id == opp.id))
    stored = 0
    for category, req_text, anchor, mandatory in requirements:
        key = normalize_key(req_text)[:80]
        if not key or key in seen:
            continue
        seen.add(key)
        db.add(
            ExtractedRequirement(
                opportunity_id=opp.id,
                category=category,
                text=req_text,
                anchor=anchor,
                mandatory=mandatory,
            )
        )
        stored += 1
    return stored


def run(db, opp) -> dict:
    text = collect_text(db, opp)
    requirements = []
    detected = {}

    # --- deterministic layer ---
    detected = _detect_fields(text)

    # A tender whose document of record has not arrived yet has nothing to
    # read the bid security from. What is on file is the listing's stand-in,
    # which carries only what the portal already said, so nothing may be
    # concluded from it — in particular no implied BOQ value, which would be
    # a number with nothing behind it.
    awaiting = opp.documents_status == documents.AWAITING_BRIDGE
    if awaiting and _only_the_stand_in_is_on_file(db, opp):
        for field in ("bid_security_amount", "bid_security_percent", "estimated_boq_value"):
            detected.pop(field, None)
        detected["boq_estimate_note"] = (
            "The bidding document has not been retrieved yet, so the bid security and the "
            "estimated BOQ value it implies have not been read. They are worked out once "
            "the document arrives."
        )

    if "submission_deadline" in detected:
        requirements.append(
            (
                "deadline",
                f"Submission deadline: {detected['submission_deadline'].date().isoformat()} — confirm portal closing time.",
                "deadline",
                True,
            )
        )
    if detected.get("bid_security_amount"):
        requirements.append(
            (
                "commercial",
                f"Bid security {detected['bid_security_amount']:,.0f} as specified — arrange instrument "
                f"({detected.get('bid_security_form') or 'form to confirm'}).",
                "bid-security",
                True,
            )
        )
    if detected.get("tender_fee"):
        requirements.append(
            ("commercial", f"Tender fee: {detected['tender_fee']:,.0f} — pay before downloading documents.", "tender-fee", True)
        )
    if detected.get("pec_category_required"):
        requirements.append(
            ("qualification", f"PEC licence category {detected['pec_category_required']} required.", "pec", True)
        )
    if detected.get("prequal_required"):
        requirements.append(
            ("qualification", "Pre-qualification applies — PQ status/forms required.", "pq", True)
        )
    thresholds = detected.get("qualification_thresholds") or {}
    if thresholds.get("turnover"):
        requirements.append(
            ("qualification", f"Minimum average turnover: PKR {thresholds['turnover']:,.0f}.", "turnover", True)
        )
    if thresholds.get("similar_work_count"):
        requirements.append(
            (
                "qualification",
                f"Similar work requirement: {thresholds['similar_work_count']} comparable contracts.",
                "similar-work",
                True,
            )
        )

    sentence_hits = 0
    for sentence in re.split(r"(?<=[.;])\s+|\n+", text):
        s = sentence.strip()
        if 40 < len(s) < 320 and re.search(r"\b(shall|must|required to|mandatory)\b", s, re.I):
            requirements.append((_classify_requirement(s), s[:300], "clause", True))
            sentence_hits += 1
            if sentence_hits >= 25:
                break

    # --- the facts go on the record before the model is asked ---
    #
    # The bid security, the percentage it represents and the value that
    # implies are read out of the document itself, and they are the numbers
    # the bid room acts on. A model call that runs past the end of the
    # request must not take them with it, so they are written down and
    # committed first. The model only adds recall on top of them.
    _apply_fields(opp, detected)
    _replace_requirements(db, opp, requirements)
    db.commit()

    # --- AI layer: extra recall, schema-validated ---
    llm_requirements = 0
    provider = llm.get_provider()
    ask, model_deadline = runtime.model_budget()
    if provider.enabled and text and ask:
        fenced = prompts.fence_untrusted(text[:LLM_CAP])
        result = provider.chat(
            prompts.EXTRACT_V1["system"],
            fenced + "\n\nExtract the requirements as JSON.",
            max_tokens=1500,
            task="extract",
            deadline=model_deadline,
        )
        llm.record_metric(db, "extract", result, opportunity_id=opp.id)
        if result.valid and result.text.strip():
            payload = llm.parse_json_block(result.text, "requirements")
            validation = schemas.validate_requirements(payload)
            if validation.valid:
                for item in validation.payload["requirements"][:40]:
                    requirements.append(
                        (item["category"], item["text"], item["anchor"] or "llm", item["mandatory"])
                    )
                llm_requirements = len(validation.payload["requirements"])
            else:
                audit.record(
                    db,
                    "ai.output_invalid",
                    opportunity_id=opp.id,
                    detail={"task": "extract", "errors": validation.error_text},
                )

    # --- persist ---
    stored = _replace_requirements(db, opp, requirements)

    # How many requirements were genuinely extracted, before any system
    # fallback is added. This is what the grade should reflect.
    extracted = stored

    _apply_fields(opp, detected)

    if not text:
        if opp.documents_status in ("none", "uploaded"):
            opp.documents_status = "metadata_only"
        fallback = "No document text available — verify requirements manually from the notice."
    elif awaiting:
        # The document is on its way from the bid desk. The record says so
        # rather than claiming the analysis was drawn from a document that
        # is not here.
        fallback = (
            "The bidding document has not been retrieved yet — what is on file is the portal "
            "listing's summary of it. Read the requirements and the bid security from the "
            "document itself."
        )
    elif stored == 0:
        opp.documents_status = "parsed"
        fallback = (
            "Document text was retrieved but no mandatory requirement could be identified "
            "automatically — read the notice and record the requirements manually."
        )
    else:
        opp.documents_status = "parsed"
        fallback = None

    if fallback:
        db.add(
            ExtractedRequirement(
                opportunity_id=opp.id,
                category="compliance",
                text=fallback,
                anchor="system",
                mandatory=True,
            )
        )
        stored += 1

    grade, confidence = _grade(detected, extracted, bool(text))
    opp.extraction_grade = grade
    opp.ai_confidence = confidence

    # The sectioned summary, written from the same text and the same fields
    # so that it can never disagree with the numbers above.
    try:
        opp.bid_summary = bid_summary.build(db, opp, text, detected)
    except Exception as exc:
        # A summary that cannot be written must not stop the extraction.
        audit.record(
            db,
            "ai.summary_failed",
            opportunity_id=opp.id,
            detail={"error": str(exc)[:200]},
        )

    db.commit()
    audit.record(
        db,
        "opportunity.extracted",
        opportunity_id=opp.id,
        detail={
            "requirements": stored,
            "llm_requirements": llm_requirements,
            "grade": grade,
            "confidence": confidence,
            "detected": {k: str(v) for k, v in detected.items()},
        },
    )
    return {
        "requirements": stored,
        "llm_requirements": llm_requirements,
        "grade": grade,
        "confidence": confidence,
        "detected": {k: str(v) for k, v in detected.items()},
    }
