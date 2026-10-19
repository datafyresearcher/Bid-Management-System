"""Contract risk rules — the single definition of what counts as a risk flag.

Both the deterministic rule layer and the AI layer read this file, so the two
can never disagree about what a risk flag is. The deterministic layer matches
directly; the AI layer is asked to find the same risks in prose and in tables,
and anything it returns is merged with these.

Rule shape:

* ``all``    — every cue must be present (substring, case-insensitive)
* ``any``    — at least one cue must be present
* ``not_any``— none of these may be present (used to suppress a rule that a
  document explicitly negates, e.g. "no performance security is required")
"""

RULES = [
    {
        "id": "uncapped_liability",
        "any": [
            "uncapped",
            "without limitation",
            "unlimited liability",
            "shall be unlimited",
            "no cap on",
        ],
        "severity": "High",
        "category": "Liability",
        "title": "Uncapped / unlimited liability wording",
        "action": "Negotiate a liability cap or qualify at bid stage; escalate to management",
    },
    {
        "id": "delay_damages",
        "any": ["liquidated damages", "delay damages"],
        "severity": "Medium",
        "category": "Time & Cost",
        "title": "Delay damages provisions",
        "action": "Check the per-day rate and the cap against PEC/FIDIC norms",
    },
    {
        "id": "no_price_adjustment",
        "any": [
            "no price adjustment",
            "without price adjustment",
            "firm price",
            "firm and fixed",
            "fixed price without",
        ],
        "severity": "Medium",
        "category": "Time & Cost",
        "title": "No price adjustment clause",
        "action": "Consider an escalation buffer in pricing or raise a clarification",
    },
    {
        "id": "price_escalation_present",
        "all": ["price"],
        "any": ["escalation", "price revision", "escalation formula"],
        "severity": "Low",
        "category": "Time & Cost",
        "title": "Price adjustment mechanism present",
        "action": "Verify the index and the base date used for adjustment",
    },
    {
        "id": "termination_for_convenience",
        "all": ["for convenience"],
        "any": ["termination", "terminate", "right to terminate"],
        "severity": "Medium",
        "category": "Commercial",
        "title": "Termination for convenience",
        "action": "Assess demobilisation cost exposure",
    },
    {
        "id": "foreign_arbitration",
        "all": ["arbitration"],
        "any": [
            "singapore", "london", "dubai", "hong kong", "icc", "siac",
            "international chamber of commerce", "foreign",
        ],
        "severity": "Medium",
        "category": "Dispute",
        "title": "Foreign arbitration seat",
        "action": "Budget legal costs and verify enforceability preferences",
    },
    {
        "id": "dispute_resolution",
        "any": ["jurisdiction", "governing law", "courts of", "exclusive jurisdiction"],
        "severity": "Low",
        "category": "Dispute",
        "title": "Dispute resolution clause",
        "action": "Confirm the seat and governing law against company policy",
    },
    {
        "id": "advance_payment",
        "any": ["advance payment"],
        "severity": "High",
        "category": "Payment",
        "title": "Advance payment terms",
        "action": "Confirm the security, the recovery mechanism and the cash-flow impact",
    },
    {
        "id": "performance_security",
        "any": ["performance security", "performance guarantee"],
        "not_any": ["no performance security is required", "performance security is not required"],
        "severity": "Medium",
        "category": "Commercial",
        "title": "Performance security requirement",
        "action": "Arrange the instrument and confirm validity beyond the defects period",
    },
    {
        "id": "retention_money",
        "any": ["retention money", "retention", "withheld payment"],
        "severity": "Medium",
        "category": "Commercial",
        "title": "Retention / withheld payment",
        "action": "Model the cash-flow impact of the retention period",
    },
    {
        "id": "insurance",
        "any": ["insurance", "indemnif", "workmen's compensation"],
        "severity": "Medium",
        "category": "Liability",
        "title": "Insurance and indemnity obligations",
        "action": "Verify the required policies, limits and beneficiaries",
    },
    {
        "id": "tax",
        "any": ["withholding tax", "sales tax", "income tax", "taxes, duties", "customs duty"],
        "severity": "Low",
        "category": "Commercial",
        "title": "Tax and withholding obligations",
        "action": "Confirm who bears withholding tax and how it is evidenced",
    },
    {
        "id": "defects_liability",
        "any": ["defects liability", "defect liability", "warranty period", "guarantee period"],
        "severity": "Medium",
        "category": "Commercial",
        "title": "Defects liability / warranty period",
        "action": "Confirm the period and the cost of retaining site staff",
    },
    {
        "id": "force_majeure",
        "any": ["force majeure"],
        "severity": "Low",
        "category": "Time & Cost",
        "title": "Force majeure clause",
        "action": "Check notice periods and the relief granted",
    },
    {
        "id": "extension_of_time",
        "any": ["extension of time", "time extension", "prolongation"],
        "severity": "Low",
        "category": "Time & Cost",
        "title": "Extension of time entitlement",
        "action": "Confirm the notice period required to claim EOT",
    },
    {
        "id": "suspension",
        "any": ["suspend the works", "suspension of works", "may suspend"],
        "severity": "Low",
        "category": "Time & Cost",
        "title": "Suspension of works provision",
        "action": "Confirm whether prolongation costs are payable",
    },
    {
        "id": "local_content",
        "any": ["local employment", "local content", "foreign personnel", "foreign nationals", "local labour"],
        "severity": "Medium",
        "category": "Statutory",
        "title": "Local employment / content obligation",
        "action": "Quantify the local content commitment in the price",
    },
    {
        "id": "subcontracting",
        "any": ["subcontract"],
        "severity": "Low",
        "category": "Commercial",
        "title": "Subcontracting conditions",
        "action": "Confirm whether prior employer consent is required",
    },
    {
        "id": "confidentiality",
        "any": ["confidentiality", "confidential information"],
        "severity": "Low",
        "category": "Legal",
        "title": "Confidentiality obligations",
        "action": "Confirm the confidentiality period and permitted disclosures",
    },
    {
        "id": "epc_design",
        "any": ["epc", "turnkey", "design-build", "design and build", "on a turnkey basis"],
        "severity": "High",
        "category": "Design",
        "title": "Contractor design responsibility (EPC/Turnkey context)",
        "action": "Verify design scope, geotechnical data and interface risks",
    },
]


def _hit(rule: dict, lower: str) -> bool:
    all_cues = rule.get("all")
    if all_cues and not all(cue in lower for cue in all_cues):
        return False
    any_cues = rule.get("any")
    if any_cues and not any(cue in lower for cue in any_cues):
        return False
    not_cues = rule.get("not_any")
    if not_cues and any(cue in lower for cue in not_cues):
        return False
    return True


def _matched_cue(rule: dict, lower: str):
    """The cue that triggered the rule, for the snippet."""
    for cue in rule.get("any", []):
        if cue in lower:
            return cue
    for cue in rule.get("all", []):
        if cue in lower:
            return cue
    return ""


def match_rules(text: str) -> list:
    """Return the risk flags triggered by ``text``.

    Each flag carries the severity, category, title, action and the text
    excerpt around the trigger.
    """
    if not text:
        return []
    lower = text.lower()
    flags = []
    for rule in RULES:
        if not _hit(rule, lower):
            continue
        cue = _matched_cue(rule, lower)
        flags.append(
            {
                "rule_id": rule["id"],
                "severity": rule["severity"],
                "category": rule["category"],
                "title": rule["title"],
                "action": rule["action"],
                "cue": cue,
            }
        )
    return flags
