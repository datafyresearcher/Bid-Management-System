"""Deterministic provider backend.

The default LLM provider (``BMS_LLM_PROVIDER=mock``) is not a stub that returns
an empty string. It is a *deterministic engine* that performs the same four
tasks the real LLM performs — narrative scoring, requirement extraction, risk
flagging and proposal drafting — using transparent, inspectable rules.

Why it exists:

* the system is fully demonstrable and testable with no API key and no network;
* it gives a reproducible baseline to diff a real LLM against, so you can prove
  the LLM is actually adding value rather than just adding words;
* the AI-quality dashboard has real numbers to show out of the box.

It is honest about what it is: every call it serves is recorded with
``provider='mock'`` and ``simulated=True``, so simulated output is never
confused with measured model behaviour.
"""

import json
import re
from datetime import datetime, timezone

# --- obligation detection -------------------------------------------------

OBLIGATION_CUES = [
    r"\bshall\b", r"\bmust\b", r"\brequired to\b", r"\bis required\b", r"\bmandatory\b",
    r"\bobligatory\b", r"\bneed to\b", r"\bis necessary\b", r"\bshould be\b",
    r"\bprovide\b", r"\bfurnish\b", r"\bsubmit\b", r"\battach\b", r"\baccompanied by\b",
    r"\bduly\b", r"\bin triplicate\b", r"\bon or before\b", r"\bprior to\b",
    r"\bnot later than\b", r"\bat least\b", r"\bminimum of\b", r"\bno\.?\s*of\b",
]

# Clause / form / annexure references used as requirement anchors.
REFERENCE_RE = re.compile(
    r"\b(?:clause|cl\.|article|para(?:graph)?|section|item|part)\s*[A-Z]?\.?\s*\d+(?:\.\d+)*"
    r"|\b(?:form|form\s*no\.?|annex(?:ure)?|appendix|schedule)\s*[A-Z]?-?\d+(?:\.\d+)*"
    r"|\bITB\s*\d+(?:\.\d+)*"
    r"|\bITP\s*\d+(?:\.\d+)*",
    re.I,
)

TABLE_SPLIT_RE = re.compile(r"\s{3,}|\t+|\s*\|\s*")

def _unwrap_fenced(text: str) -> str:
    """Return the payload inside an untrusted-document fence."""
    if not text:
        return ""
    match = re.search(
        r"<([A-Z_]+)_UNTRUSTED>(.*?)</\1_UNTRUSTED>", text, flags=re.S
    )
    if match:
        return match.group(2)
    return text


def _section(text: str, label: str) -> str:
    """Return the body of a labelled block, e.g. ``<GROUNDING MATERIAL>…``.

    The fences the callers use look like ``<LABEL>`` … ``</LABEL>``; this
    pulls the content back out so the simulator sees the same material a real
    model would.
    """
    if not text:
        return ""
    match = re.search(rf"<{re.escape(label)}>(.*?)</{re.escape(label)}>", text, flags=re.S)
    return match.group(1).strip() if match else ""


def _strip_instruction(text: str) -> str:
    """Remove the trailing instruction line the callers append to the prompt."""
    return re.sub(r"\n\n(Extract|List|Write)[^\n]*$", "", text).strip()


def _split_sentences(text: str):
    return [s.strip() for s in re.split(r"(?<=[.;:])\s+|\n+", text) if s.strip()]


def _classify(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ("pec", "licence", "license", "registration", "turnover",
                            "taxpayer", "blacklist", "similar work", "experience", "iso")):
        return "qualification"
    if any(k in t for k in ("bid security", "earnest money", "performance security",
                            "bank guarantee", "insurance", "price", "payment", "retention")):
        return "commercial"
    if any(k in t for k in ("form", "undertaking", "affidavit", "power of attorney", "declaration")):
        return "form"
    if any(k in t for k in ("deadline", "last date", "closing", "opening", "clarification", "query")):
        return "deadline"
    if any(k in t for k in ("specification", "technical", "equipment", "personnel",
                            "methodology", "schedule", "work plan")):
        return "technical"
    return "compliance"


def _anchor_for(text: str) -> str:
    match = REFERENCE_RE.search(text)
    if match:
        return match.group(0).strip()[:120]
    return ""


def _row_is_requirement(cells) -> bool:
    joined = " ".join(cells).lower()
    if len(cells) < 2:
        return False
    if any(cue.strip(" .,:;") in joined for cue in ("shall", "must", "required", "mandatory",
                                                    "obligatory", "provide", "submit", "furnish")):
        return True
    # A two-column table where the second cell states a requirement.
    return len(cells) == 2 and len(cells[1]) > 25 and any(
        cue in cells[1].lower() for cue in ("shall", "must", "required", "provide", "submit", "applicable")
    )


def _table_requirements(text: str):
    """Recover requirements from pipe/column-aligned tables in BOQ-style documents."""
    found = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or len(stripped) < 20:
            continue
        if "|" in stripped:
            cells = [c.strip() for c in stripped.strip("|").split("|")]
        elif re.search(r"\S {3,}\S", stripped):
            cells = [c.strip() for c in TABLE_SPLIT_RE.split(stripped) if c.strip()]
        else:
            continue
        if len(cells) < 2 or len(cells) > 8:
            continue
        if not _row_is_requirement(cells):
            continue
        # Skip header rows.
        if all(len(c) < 30 for c in cells) and not any(
            cue in " ".join(cells).lower() for cue in ("shall", "must", "required")
        ):
            continue
        body = " | ".join(c for c in cells if c)
        if len(body) < 25:
            continue
        found.append(body[:300])
    return found


def _sentence_requirements(text: str):
    found = []
    seen = set()
    for sentence in _split_sentences(text):
        if not (25 < len(sentence) < 400):
            continue
        lowered = sentence.lower()
        if not any(re.search(cue, lowered) for cue in OBLIGATION_CUES):
            continue
        if re.search(r"^[\s\-–—•*]*\d+[.)]\s*$", sentence):
            continue
        key = re.sub(r"[^a-z0-9]+", " ", lowered).strip()[:60]
        if key in seen:
            continue
        seen.add(key)
        found.append(sentence[:300])
    return found


def _simulate_extract(user: str) -> str:
    document = _strip_instruction(_unwrap_fenced(user))
    requirements = []
    seen = set()

    def add(text, category=None, anchor=""):
        key = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()[:80]
        if not key or key in seen:
            return
        seen.add(key)
        requirements.append(
            {
                "category": category or _classify(text),
                "text": text,
                "anchor": anchor or _anchor_for(text),
                "mandatory": True,
            }
        )

    for row in _table_requirements(document):
        add(row)
    for sentence in _sentence_requirements(document):
        add(sentence)

    return json.dumps({"requirements": requirements[:40]})


def _simulate_risk(user: str) -> str:
    from app.services.risk_rules import match_rules
    from app.services.utils import snippet

    document = _strip_instruction(_unwrap_fenced(user))
    flags = []
    for rule in match_rules(document):
        flags.append(
            {
                "severity": rule["severity"],
                "category": rule["category"],
                "title": rule["title"],
                "detail": (snippet(document, rule["cue"], radius=200) or "")[:600],
                "anchor": "clause",
                "suggested_action": rule["action"],
            }
        )
    return json.dumps({"flags": flags[:15]})


def _simulate_score(user: str) -> str:
    def grab(pattern, default=""):
        match = re.search(pattern, user)
        return match.group(1).strip() if match else default

    title = grab(r"Tender:\s*([^\n]+)")
    buyer = grab(r"Buyer:\s*([^\n]+)")
    category = grab(r"Category:\s*([^\n]+)")
    value = grab(r"Value:\s*([^\n]+)")
    total_text = grab(r"Total:\s*([\d.]+)", "0")
    sub_raw = grab(r"Subscores:\s*(\{.*\})", "{}")
    warnings = grab(r"Warnings:\s*([^\n]*)")

    try:
        subscores = json.loads(sub_raw)
    except Exception:
        try:
            import ast

            subscores = ast.literal_eval(sub_raw)
        except Exception:
            subscores = {}
    total = float(total_text or 0)

    def part(key):
        entry = subscores.get(key) or {}
        try:
            return float(entry.get("score", 0)), float(entry.get("max", 1))
        except (TypeError, ValueError):
            return 0.0, 1.0

    scope, scope_max = part("scope")
    buyer_score, buyer_max = part("buyer")
    margin, margin_max = part("margin")
    strategy, strategy_max = part("strategy")
    geography, geography_max = part("geography")
    value_score, value_max = part("value")

    strength = "strong" if total >= 70 else "moderate" if total >= 55 else "thin"
    lines = [
        f"{title or 'This tender'} from {buyer or 'the buyer'} scores {total:.0f}/100, "
        f"indicating a {strength} strategic fit for the {category or 'current'} scope.",
        f"Scope alignment is the strongest signal ({scope:.0f}/{scope_max:.0f}), reflecting "
        f"directly comparable delivery experience rather than a generic qualification claim.",
        f"Buyer familiarity contributes {buyer_score:.0f}/{buyer_max:.0f} and margin headroom "
        f"{margin:.0f}/{margin_max:.0f}; the estimated value of {value or 'not stated'} "
        f"scores {value_score:.0f}/{value_max:.0f} against company turnover.",
        f"Strategic fit contributes {strategy:.0f}/{strategy_max:.0f} and geographic coverage "
        f"{geography:.0f}/{geography_max:.0f}, so delivery capacity is the constraint to confirm.",
    ]
    if warnings and warnings not in ("[]", ""):
        lines.append(f"Caveat to clear before committing: {warnings}.")
    else:
        lines.append("No qualification warnings were raised; confirm the referenced certificates are current.")
    return " ".join(lines)


def _simulate_draft(user: str) -> str:
    """Restructure grounded material into flowing proposal prose.

    The simulator is only allowed to reorganise and rephrase the grounding
    material it is given. It never introduces a fact that is not present in the
    input, which is the same constraint the real prompt imposes.
    """
    grounding = _section(user, "GROUNDING MATERIAL") or _section(user, "GROUNDING")
    if not grounding:
        match = re.search(r"Grounding material:\n(.*?)(?:\n\nRequirements context:|\Z)", user, flags=re.S)
        grounding = match.group(1).strip() if match else ""

    title = ""
    m = re.search(r"Section:\s*([^\n]+)", user)
    if m:
        title = m.group(1).strip()

    if not grounding:
        return ""

    requirements = []
    req_block = _section(user, "REQUIREMENTS_UNTRUSTED") or _section(user, "REQUIREMENTS")
    if req_block:
        requirements = [line.strip("- ").strip() for line in req_block.splitlines() if line.strip()]
    else:
        req_match = re.search(r"Requirements context:\n(.*)", user, flags=re.S)
        if req_match:
            requirements = [line.strip("- ").strip() for line in req_match.group(1).splitlines() if line.strip()]

    requirements = []
    req_match = re.search(r"Requirements context:\n(.*)", user, flags=re.S)
    if req_match:
        requirements = [line.strip("- ").strip() for line in req_match.group(1).splitlines() if line.strip()]

    paragraphs = []
    bullets = []
    for block in re.split(r"\n\s*\n", grounding):
        block = block.strip()
        if not block:
            continue
        lines = block.splitlines()
        head = lines[0].strip()
        body = lines[1:]
        if body and all(l.strip().startswith(("-", "*", "•")) for l in body if l.strip()):
            bullets.extend(l.strip().lstrip("-*• ").strip() for l in body if l.strip())
            paragraphs.append(head)
        else:
            paragraphs.append(block.replace("\n", " "))

    out = []
    if title:
        out.append(f"{title}.")
    out.extend(paragraphs)
    if requirements:
        out.append("The following tender requirements are addressed under this section:")
        out.extend(f"- {r[:220]}" for r in requirements[:6])
    if bullets:
        out.append("Supporting evidence from the company knowledge base:")
        out.extend(f"- {b[:220]}" for b in bullets[:8])
    return "\n\n".join(p for p in out if p).strip()


_SIMULATORS = {
    "score": _simulate_score,
    "extract": _simulate_extract,
    "risk": _simulate_risk,
    "draft": _simulate_draft,
}


def simulate(task: str, system: str, user: str) -> str:
    """Run the deterministic engine for a task and return the raw model output."""
    handler = _SIMULATORS.get(task)
    if not handler:
        return ""
    try:
        return handler(user or "")
    except Exception:
        return ""


def simulated_latency_ms(user: str) -> int:
    """Deterministic synthetic latency, so dashboards show a stable figure.

    This is explicitly *not* a measurement of anything real; every metric row
    produced by the simulator is flagged ``simulated=True``.
    """
    size = len(user or "")
    return int(min(1800, 140 + size // 30))


def simulated_tokens(text: str) -> int:
    return max(1, len(text or "") // 4)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).isoformat()
