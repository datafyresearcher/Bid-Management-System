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

from app.llm import provider as llm
from app.llm import prompts, schemas
from app.models import Document, ExtractedRequirement
from app.services import audit
from app.services.utils import normalize_key, parse_amount, parse_date, parse_money, snippet

TEXT_CAP = 80000
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
MONEY_TOKEN = re.compile(
    r"(?:(?<![A-Za-z])(?:rs\.?|pkr|usd)\b|us\$|\$)\s*\.?\s*"
    r"([\d][\d,\.]*\s*(?:million|billion|crore|lakh|thousand)?)",
    re.I,
)

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


def _closest_money(text, triggers, max_distance=200):
    """The money amount sitting closest to any trigger phrase.

    Proximity matters: a section heading like "BID SECURITY AND TENDER FEE"
    is a trigger match too, but the amount that belongs to it is far away.
    Picking the *nearest* amount to *any* trigger resolves that, and also
    handles a document that states the same field more than once.
    """
    best = None
    for trigger in triggers:
        for anchor in re.finditer(trigger, text, re.I):
            start = anchor.end()
            for match in MONEY_TOKEN.finditer(text, start, start + max_distance):
                distance = match.start() - start
                if best is None or distance < best[0]:
                    best = (distance, parse_amount(match.group(1)))
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
    amount = _closest_money(text, BID_SECURITY_TRIGGERS)
    if amount:
        detected["bid_security_amount"] = amount
    else:
        # Some notices quote bid security only as a percentage of the price.
        segment = _after(text, BID_SECURITY_TRIGGERS, window=120) or ""
        percent = re.search(r"(\d{1,2}(?:\.\d{1,2})?)\s*%", segment)
        if percent:
            detected["bid_security_percent"] = float(percent.group(1))
    for form_kw in SECURITY_FORM_KEYWORDS:
        if form_kw in text.lower():
            detected["bid_security_form"] = form_kw.title()
            break

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

    return detected


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


def run(db, opp) -> dict:
    text = collect_text(db, opp)
    requirements = []
    detected = {}

    # --- deterministic layer ---
    detected = _detect_fields(text)
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

    # --- AI layer: extra recall, schema-validated ---
    llm_requirements = 0
    provider = llm.get_provider()
    if provider.enabled and text:
        fenced = prompts.fence_untrusted(text[:LLM_CAP])
        result = provider.chat(
            prompts.EXTRACT_V1["system"],
            fenced + "\n\nExtract the requirements as JSON.",
            max_tokens=1500,
            task="extract",
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

    # How many requirements were genuinely extracted, before any system
    # fallback is added. This is what the grade should reflect.
    extracted = stored

    # Only fields that map to a real Opportunity column are written back.
    settable = {
        "submission_deadline",
        "opening_at",
        "bid_security_amount",
        "bid_security_form",
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

    if not text:
        if opp.documents_status in ("none", "uploaded"):
            opp.documents_status = "metadata_only"
        fallback = "No document text available — verify requirements manually from the notice."
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
