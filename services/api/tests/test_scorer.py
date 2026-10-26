import time

from sqlalchemy import select

from app.models import GateTask, Opportunity
from app.services import scorer


def _make_opp(db, **overrides):
    suffix = str(time.time_ns())
    data = dict(
        dedup_key=f"unit-{suffix}",
        country="PK",
        area="Punjab",
        category_internal="Substations",
        tender_type="Works",
        buyer_name="Lesco",
        buyer_ref=f"UNIT-{suffix}",
        title="Construction of 132kV grid station including transformer installation",
        description="Grid station and transmission line substation works",
        estimated_value=500_000_000,
        currency="PKR",
        state="NORMALIZED",
        source_refs=[],
    )
    data.update(overrides)
    opp = Opportunity(**data)
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return opp


def test_good_opportunity_scores_and_opens_gate(db):
    opp = _make_opp(db)
    score = scorer.run(db, opp)
    assert score.total >= 55
    assert score.hard_gates["passed"] is True
    assert opp.state == "GATE1"
    task = db.execute(select(GateTask).where(GateTask.opportunity_id == opp.id)).scalars().first()
    assert task is not None
    assert task.gate == 1
    assert task.status == "PENDING"


def test_auction_is_screened_out(db):
    opp = _make_opp(db, tender_type="Auction-Disposal", title="Auction of scrap transformers")
    scorer.run(db, opp)
    assert opp.state == "SCREENED_OUT"
    failures = opp.hard_gate_result["failures"]
    assert any(f["gate"] == "strategy" for f in failures)


def test_weak_opportunity_auto_archives(db):
    opp = _make_opp(
        db,
        category_internal="General",
        tender_type="Services",
        title="Hiring of event management services for annual dinner",
        description="Catering and event services",
        estimated_value=None,
        buyer_name="Unknown Buyer",
        area="Islamabad",
    )
    score = scorer.run(db, opp)
    assert score.total < 40
    assert opp.state == "AUTO_ARCHIVED"


def test_a_tender_can_be_scored_without_the_model(db):
    """The score must not wait on a model that is slow or absent.

    A tender is scored, it opens its gate, and the deterministic explanation
    stands in for the written one. The score itself is the same either way.
    """
    opp = _make_opp(db)
    score = scorer.run(db, opp, narrate=False)
    assert score.total >= 55
    assert opp.state == "GATE1"
    assert opp.ai_rationale
    task = db.execute(select(GateTask).where(GateTask.opportunity_id == opp.id)).scalars().first()
    assert task is not None
    assert task.status == "PENDING"


def test_the_gate_snapshot_follows_a_re_score(db):
    """The reviewer reads the snapshot, so it has to describe the current score."""
    opp = _make_opp(db)
    scorer.run(db, opp)
    task = db.execute(select(GateTask).where(GateTask.opportunity_id == opp.id)).scalars().first()
    first = dict(task.inputs_snapshot)

    scorer.run(db, opp)
    db.refresh(task)
    assert task.inputs_snapshot["score"] == opp.score_total
    assert task.inputs_snapshot["rationale"] == opp.ai_rationale
    assert task.inputs_snapshot["score"] == first["score"]
