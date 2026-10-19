import re

from sqlalchemy import delete, select

from app.llm import provider as llm
from app.llm import prompts
from app.models import Document, ExtractedRequirement
from app.services import audit
from app.services.utils import normalize_key, parse_amount, parse_date

TEXT_CAP = 80000
LLM_CAP = 40000

CATEGORY_HINTS = [
    ("qualification", ["pec", "licence", "license", "registration", "taxpayer", "blacklist", "turnover", "similar work", "experience", "iso"]),
    ("commercial", ["bid security", "earnest money", "performance security", "bank guarantee", "insurance", "price", "payment"]),
    ("form", ["form", "undertaking", "affidavit", "power of attorney", "declaration"]),
    ("deadline", ["deadline", "last date", "closing", "opening", "clarification", "query"]),
    ("technical", ["specification", "technical", "equipment", "personnel", "methodology", "schedule"]),
]


def collect_text(db, opp) -> str:
    docs = db.execute(select(Document).where(Document.opportunity_id == opp.id)).scalars().all()
    return "\n\n".join(d.content_text or "" for d in docs if d.content_text)[:TEXT_CAP]


def _classify_requirement(text: str) -> str:
    t = text.lower()
    for category, hints in CATEGORY_HINTS:
        if any(h in t for h in hints):
            return category
    return "compliance"


def run(db, opp) -> dict:
    text = collect_text(db, opp)
    requirements = []
    detected = {}

    sec = re.search(
        r"(?:bid security|earnest money)[^.\n]{0,120}?(?:rs\.?|pkr|usd)\s*([\d][\d,\.]*)",
        text,
        re.I,
    )
    if sec:
        detected["bid_security_amount"] = parse_amount(sec.group(1))
        requirements.append(("commercial", f"Bid security {sec.group(1)} as specified — arrange instrument (BG/deposit).", "bid-security", True))
    for form_kw in ["bank guarantee", "pay order", "demand draft", "call deposit", "deposit at call"]:
        if form_kw in text.lower():
            detected["bid_security_form"] = form_kw.title()
            break

    fee = re.search(
        r"(?:tender fee|cost of (?:tender )?documents?|document(?:s)? fee)[^.\n]{0,80}?(?:rs\.?|pkr)\s*([\d][\d,\.]*)",
        text,
        re.I,
    )
    if fee:
        detected["tender_fee"] = parse_amount(fee.group(1))

    deadline_m = re.search(
        r"(?:last date|closing date|deadline for submission|submission deadline|due date|bids? (?:must|shall) be (?:submitted|received)[^.\n]{0,40})[^.\n]{0,60}?(\d{1,2}[\s\-/](?:[A-Za-z]{3,9}|\d{1,2})[\s\-/,]*\d{4})",
        text,
        re.I,
    )
    if deadline_m:
        parsed = parse_date(deadline_m.group(1))
        if parsed:
            detected["submission_deadline"] = parsed
            requirements.append(("deadline", f"Submission deadline: {parsed.date().isoformat()} — confirm portal closing time.", "deadline", True))

    pec_m = re.search(r"\bPEC\b[^\n]{0,100}?\b(C-A|C-B|C-1|C-2|C-3|C-4|No Limit)\b", text, re.I)
    if pec_m:
        detected["pec_category_required"] = pec_m.group(1).upper()
        requirements.append(("qualification", f"PEC licence category {pec_m.group(1).upper()} required.", "pec", True))

    if re.search(r"pre-?qualif", text, re.I):
        detected["prequal_required"] = True
        requirements.append(("qualification", "Pre-qualification applies — PQ status/forms required.", "pq", True))

    if re.search(r"two[- ](?:stage|envelope)", text, re.I):
        detected["procurement_regime"] = "two-stage-two-envelope"

    thresholds = dict(opp.qualification_thresholds or {})
    turnover_m = re.search(
        r"average (?:annual )?turnover[^.\n]{0,80}?(?:rs\.?|pkr)\s*([\d][\d,\.]*)",
        text,
        re.I,
    )
    if turnover_m:
        thresholds["turnover"] = parse_amount(turnover_m.group(1))
        requirements.append(("qualification", f"Minimum average turnover: PKR {turnover_m.group(1)}.", "turnover", True))
    similar_m = re.search(
        r"(?:at least|minimum(?: of)?)?\s*(\d{1,2})\s*(?:no\.?s?\.? of\s*)?similar (?:nature\s*)?(?:works?|projects?|contracts?)",
        text,
        re.I,
    )
    if similar_m:
        thresholds["similar_work_count"] = int(similar_m.group(1))
        requirements.append(("qualification", f"Similar work requirement: {similar_m.group(1)} comparable contracts.", "similar-work", True))
    if thresholds:
        detected["qualification_thresholds"] = thresholds

    sentence_hits = 0
    for sentence in re.split(r"(?<=[.;])\s+|\n+", text):
        s = sentence.strip()
        if 40 < len(s) < 320 and re.search(r"\b(shall|must|required to|mandatory)\b", s, re.I):
            requirements.append((_classify_requirement(s), s[:300], "clause", True))
            sentence_hits += 1
            if sentence_hits >= 25:
                break

    provider = llm.get_provider()
    if provider.enabled and text:
        fenced = prompts.fence_untrusted(text[:LLM_CAP])
        result = provider.chat(
            prompts.EXTRACT_V1["system"],
            fenced + "\n\nExtract the requirements as JSON.",
            max_tokens=1500,
        )
        llm.record_metric(db, "extract", result, opportunity_id=opp.id)
        payload = llm.parse_json_block(result.text)
        if payload and isinstance(payload.get("requirements"), list):
            for item in payload["requirements"][:40]:
                if isinstance(item, dict) and item.get("text"):
                    requirements.append(
                        (
                            item.get("category", "compliance"),
                            str(item["text"])[:300],
                            item.get("anchor", "llm"),
                            bool(item.get("mandatory", True)),
                        )
                    )

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

    for field, value in detected.items():
        setattr(opp, field, value)
    if text:
        opp.documents_status = "parsed"
    elif opp.documents_status == "none":
        opp.documents_status = "metadata_only"
        db.add(
            ExtractedRequirement(
                opportunity_id=opp.id,
                category="compliance",
                text="No document text available — verify requirements manually from the notice.",
                anchor="system",
                mandatory=True,
            )
        )
        stored += 1

    db.commit()
    audit.record(
        db,
        "opportunity.extracted",
        opportunity_id=opp.id,
        detail={"requirements": stored, "detected": {k: str(v) for k, v in detected.items()}},
    )
    return {"requirements": stored, "detected": {k: str(v) for k, v in detected.items()}}
