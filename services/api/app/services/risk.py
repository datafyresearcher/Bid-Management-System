import re

from sqlalchemy import delete

from app.llm import provider as llm
from app.llm import prompts
from app.models import RiskFlag
from app.services import audit
from app.services.utils import snippet

RULES = [
    {
        "keywords": ["uncapped", "without limitation", "unlimited liability", "no cap on"],
        "severity": "High",
        "category": "Liability",
        "title": "Uncapped / unlimited liability wording",
        "action": "Negotiate a liability cap or qualify at bid stage; escalate to management",
    },
    {
        "keywords": ["liquidated damages", "delay damages"],
        "severity": "Medium",
        "category": "Time & Cost",
        "title": "Delay damages provisions",
        "action": "Check per-day rate and cap against PEC/FIDIC norms",
    },
    {
        "keywords": ["no price adjustment", "without price adjustment", "firm price", "fixed price without"],
        "severity": "Medium",
        "category": "Time & Cost",
        "title": "No price adjustment clause",
        "action": "Consider escalation buffer in pricing or raise clarification",
    },
    {
        "keywords": ["termination for convenience"],
        "severity": "Medium",
        "category": "Commercial",
        "title": "Termination for convenience",
        "action": "Assess demobilisation cost exposure",
    },
    {
        "keywords": ["foreign arbitration", "arbitration in london", "arbitration in singapore", "icc arbitration"],
        "severity": "Medium",
        "category": "Dispute",
        "title": "Foreign arbitration seat",
        "action": "Budget legal costs; verify enforceability preferences",
    },
]

SPECIAL_RULES = [
    {
        "name": "advance_payment_without_guarantee",
        "trigger": "advance payment",
        "absence": "guarantee",
        "severity": "High",
        "category": "Payment",
        "title": "Advance payment without guarantee",
        "action": "Confirm repayment mechanism and security",
    },
    {
        "name": "epc_design_responsibility",
        "trigger_any": ["epc", "turnkey", "design-build", "design and build"],
        "severity": "High",
        "category": "Design",
        "title": "Contractor design responsibility (EPC/Turnkey context)",
        "action": "Verify design scope, geotechnical data and interface risks",
    },
    {
        "name": "foreign_jv_restriction",
        "trigger_all": ["joint venture", "foreign"],
        "severity": "Low",
        "category": "Eligibility",
        "title": "Foreign JV conditions mentioned",
        "action": "Check PEC JV requirements and partner arrangements",
    },
]

LLM_CAP = 40000


def run(db, opp) -> list:
    from app.services.extractor import collect_text

    text = collect_text(db, opp)
    flags = []
    lower = text.lower()

    for rule in RULES:
        hit = next((k for k in rule["keywords"] if k in lower), None)
        if hit:
            flags.append(
                {
                    "severity": rule["severity"],
                    "category": rule["category"],
                    "title": rule["title"],
                    "detail": snippet(text, hit) or f"Keyword detected: {hit}",
                    "anchor": "clause",
                    "suggested_action": rule["action"],
                }
            )

    for rule in SPECIAL_RULES:
        if "trigger_any" in rule:
            if any(k in lower for k in rule["trigger_any"]):
                ctx = next((k for k in rule["trigger_any"] if k in lower), "")
                flags.append(
                    {
                        "severity": rule["severity"],
                        "category": rule["category"],
                        "title": rule["title"],
                        "detail": snippet(text, ctx),
                        "anchor": "clause",
                        "suggested_action": rule["action"],
                    }
                )
        elif "trigger_all" in rule:
            if all(k in lower for k in rule["trigger_all"]):
                flags.append(
                    {
                        "severity": rule["severity"],
                        "category": rule["category"],
                        "title": rule["title"],
                        "detail": snippet(text, rule["trigger_all"][0]),
                        "anchor": "clause",
                        "suggested_action": rule["action"],
                    }
                )
        elif "trigger" in rule and rule["trigger"] in lower:
            window = snippet(text, rule["trigger"], radius=220).lower()
            if rule["absence"] not in window:
                flags.append(
                    {
                        "severity": rule["severity"],
                        "category": rule["category"],
                        "title": rule["title"],
                        "detail": snippet(text, rule["trigger"]),
                        "anchor": "clause",
                        "suggested_action": rule["action"],
                    }
                )

    provider = llm.get_provider()
    if provider.enabled and text:
        fenced = prompts.fence_untrusted(text[:LLM_CAP])
        result = provider.chat(
            prompts.RISK_V1["system"],
            fenced + "\n\nList contractor-side risk flags as JSON.",
            max_tokens=1200,
        )
        llm.record_metric(db, "risk", result, opportunity_id=opp.id)
        payload = llm.parse_json_block(result.text)
        if payload and isinstance(payload.get("flags"), list):
            existing_titles = {f["title"].lower()[:50] for f in flags}
            for item in payload["flags"][:15]:
                if isinstance(item, dict) and item.get("title") and item["title"].lower()[:50] not in existing_titles:
                    flags.append(
                        {
                            "severity": item.get("severity", "Medium"),
                            "category": item.get("category", "General"),
                            "title": str(item["title"])[:200],
                            "detail": str(item.get("detail", ""))[:600],
                            "anchor": item.get("anchor", "llm"),
                            "suggested_action": str(item.get("suggested_action", ""))[:300],
                        }
                    )

    db.execute(delete(RiskFlag).where(RiskFlag.opportunity_id == opp.id))
    for flag in flags:
        db.add(RiskFlag(opportunity_id=opp.id, **flag))
    db.commit()
    audit.record(db, "opportunity.risk_analyzed", opportunity_id=opp.id, detail={"flags": len(flags)})
    return flags
