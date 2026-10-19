"""Tests for the proposal drafting path.

The drafting path is easy to break silently: if the grounding material stops
matching what the drafter sends, every call returns empty and the proposal
still "works" — it just contains nothing. These tests pin the contract.
"""

import time

from sqlalchemy import select

from app.models import Opportunity
from app.services import drafter
from app.llm import prompts


def _make_opp(db):
    suffix = str(time.time_ns())
    opp = Opportunity(
        dedup_key=f"draft-{suffix}",
        country="PK",
        area="Punjab",
        category_internal="Substations",
        tender_type="Works",
        buyer_name="Lesco",
        buyer_ref=f"DRAFT-{suffix}",
        title="132kV grid station construction and commissioning",
        description="Grid station and transmission line substation works",
        estimated_value=500_000_000,
        currency="PKR",
        state="DRAFTING",
        source_refs=[],
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return opp


def test_every_section_is_drafted(db):
    opp = _make_opp(db)
    result = drafter.generate(db, opp)
    assert result["sections"] == len(drafter.SECTION_SPECS)

    from app.models import Proposal, ProposalSection

    proposal = db.execute(
        select(Proposal).where(Proposal.opportunity_id == opp.id)
    ).scalars().first()
    assert proposal is not None
    sections = db.execute(
        select(ProposalSection).where(ProposalSection.proposal_id == proposal.id)
    ).scalars().all()
    assert len(sections) == len(drafter.SECTION_SPECS)
    for section in sections:
        assert section.content and section.content.strip(), f"{section.key} is empty"


def test_drafting_produces_non_empty_ai_output(db):
    """The AI layer must actually contribute, not silently return nothing."""
    from app.models import AIMetric

    opp = _make_opp(db)
    drafter.generate(db, opp)

    metrics = db.execute(
        select(AIMetric).where(AIMetric.task == "draft", AIMetric.opportunity_id == opp.id)
    ).scalars().all()
    assert metrics, "no draft metrics were recorded"
    assert all(m.output_valid for m in metrics), [m.error for m in metrics if not m.output_valid]


def test_gap_markers_survive_the_model(db):
    """A known evidence gap must not be erased by the rewriting step.

    The deterministic writer marks missing evidence with ``[[GAP: …]]``. That
    is a fact about the company, not a writing problem, so it is re-inserted
    if the model drops it.
    """
    opp = _make_opp(db)
    drafter.generate(db, opp)

    from app.models import ProposalSection

    sections = db.execute(select(ProposalSection)).scalars().all()
    for section in sections:
        if section.status == "GAPS":
            assert prompts.GAP_MARKER in section.content, f"{section.key} lost its gap marker"


def test_gap_marker_is_a_single_convention():
    """The drafter, the prompt and the status check must agree on the token."""
    assert prompts.GAP_MARKER == "[[GAP:"
    assert prompts.GAP_MARKER in prompts.DRAFT_V1["system"]
    assert drafter.GAP == prompts.GAP_MARKER
