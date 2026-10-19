import time

from sqlalchemy import select

from app.models import Lead, Opportunity, Source
from app.services import normalizer


def _source(db, code="ntdc"):
    return db.execute(select(Source).where(Source.code == code)).scalars().first()


def test_dedup_same_notice_creates_one_opportunity(db):
    source = _source(db)
    suffix = str(time.time_ns())
    notice = {
        "native_id": f"DEDUP-{suffix}",
        "title": f"Supply of towers and hardware unit test {suffix}",
        "buyer_name": "NTDC Unit Test",
        "buyer_ref": f"REF-{suffix}",
        "published_at": "2026-10-10",
        "submission_deadline": "2026-11-30",
    }
    first = normalizer.normalize_notice(db, source, notice)
    second = normalizer.normalize_notice(db, source, notice)
    assert first.id == second.id
    refs = [r for r in second.source_refs if r.get("native_id") == f"DEDUP-{suffix}"]
    assert len(refs) == 1


def test_tracking_lead_converts_on_published_notice(db):
    source = _source(db)
    suffix = str(time.time_ns())
    lead = Lead(
        source_code="L2",
        source_label="test",
        buyer="NTDC Lead Test",
        title=f"220kV transmission line substation package signal {suffix}",
        category_internal="Transmission Lines",
        status="Tracking",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    notice = {
        "native_id": f"LEAD-{suffix}",
        "title": f"Construction of 220kV transmission line package {suffix}",
        "buyer_name": "NTDC Lead Test",
        "buyer_ref": f"REF-LEAD-{suffix}",
        "published_at": "2026-10-12",
        "submission_deadline": "2026-12-01",
    }
    opp = normalizer.normalize_notice(db, source, notice)
    db.refresh(lead)
    assert lead.status == "Converted"
    assert lead.converted_opportunity_id == opp.id
    assert opp.lead_id == lead.id
