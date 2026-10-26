"""Contract risk analysis.

The rule set lives in ``risk_rules`` so the deterministic layer and the AI
layer agree on what a risk flag is. The deterministic layer matches the
document directly; the AI layer is asked to find the same risks in prose and
in tables it may read differently, and its output is schema-validated before
being merged in.
"""

from sqlalchemy import delete

from app.llm import provider as llm
from app.llm import prompts, schemas
from app.models import RiskFlag
from app.services import audit
from app.services.risk_rules import match_rules
from app.services.utils import snippet

LLM_CAP = 40000


def run(db, opp) -> list:
    from app.services.extractor import collect_text

    text = collect_text(db, opp)
    flags = []

    # --- deterministic layer ---
    for rule in match_rules(text):
        flags.append(
            {
                "severity": rule["severity"],
                "category": rule["category"],
                "title": rule["title"],
                "detail": snippet(text, rule["cue"]) or f"Keyword detected: {rule['cue']}",
                "anchor": "clause",
                "suggested_action": rule["action"],
            }
        )

    # --- AI layer ---
    provider = llm.get_provider()
    if provider.enabled and text:
        fenced = prompts.fence_untrusted(text[:LLM_CAP])
        result = provider.chat(
            prompts.RISK_V1["system"],
            fenced + "\n\nList contractor-side risk flags as JSON.",
            max_tokens=1200,
            task="risk",
        )
        llm.record_metric(db, "risk", result, opportunity_id=opp.id)
        if result.valid and result.text.strip():
            payload = llm.parse_json_block(result.text, "flags")
            validation = schemas.validate_risk_flags(payload)
            if validation.valid:
                existing_titles = {f["title"].lower()[:50] for f in flags}
                for item in validation.payload["flags"][:15]:
                    key = item["title"].lower()[:50]
                    if key in existing_titles:
                        continue
                    existing_titles.add(key)
                    flags.append(
                        {
                            "severity": item["severity"],
                            "category": item["category"],
                            "title": item["title"],
                            "detail": item["detail"],
                            "anchor": item["anchor"],
                            "suggested_action": item["suggested_action"],
                        }
                    )
            else:
                audit.record(
                    db,
                    "ai.output_invalid",
                    opportunity_id=opp.id,
                    detail={"task": "risk", "errors": validation.error_text},
                )

    db.execute(delete(RiskFlag).where(RiskFlag.opportunity_id == opp.id))
    for flag in flags:
        db.add(RiskFlag(opportunity_id=opp.id, **flag))
    db.commit()
    audit.record(db, "opportunity.risk_analyzed", opportunity_id=opp.id, detail={"flags": len(flags)})
    return flags
