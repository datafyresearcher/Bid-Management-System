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


def test_batch_capture_matches_the_single_notice_path(db):
    """A whole listing captured at once is the same work, done once.

    The batch path exists so that a portal which published a hundred tenders
    between two scans does not cost a hundred round trips to the database. It
    has to reach the same place the one-at-a-time path does.
    """
    source = _source(db)
    suffix = str(time.time_ns())
    notices = [
        {
            "native_id": f"BATCH-{suffix}-1",
            "title": f"Supply of towers and hardware batch one {suffix}",
            "buyer_name": "NTDC Batch Test",
            "buyer_ref": f"BREF-1-{suffix}",
            "published_at": "2026-10-10",
            "submission_deadline": "2026-11-30",
        },
        {
            "native_id": f"BATCH-{suffix}-2",
            "title": f"Construction of 220kV grid station batch two {suffix}",
            "buyer_name": "NTDC Batch Test",
            "buyer_ref": f"BREF-2-{suffix}",
            "published_at": "2026-10-11",
            "submission_deadline": "2026-12-05",
        },
    ]

    normalizer.normalize_notices(db, source, notices)
    db.expire_all()

    rows = (
        db.execute(
            select(Opportunity).where(Opportunity.dedup_key.in_([
                normalizer.build_dedup_key(
                    "NTDC Batch Test", f"BREF-1-{suffix}", normalizer.parse_date("2026-10-10")
                ),
            ]))
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    first = rows[0]
    assert first.state == "NORMALIZED"
    assert first.source_id == source.id
    assert first.source_refs[0]["native_id"] == f"BATCH-{suffix}-1"
    assert first.source_refs[0]["mode"] in ("live", "saved-capture")

    # A second capture of the same listing must not create anything new.
    before = db.query(Opportunity).count()
    normalizer.normalize_notices(db, source, notices)
    assert db.query(Opportunity).count() == before


def test_batch_capture_keeps_the_lead_conversion(db):
    source = _source(db)
    suffix = str(time.time_ns())
    lead = Lead(
        source_code="L2",
        source_label="test",
        buyer="NTDC Batch Lead Test",
        title=f"220kV transmission line substation package batch {suffix}",
        category_internal="Transmission Lines",
        status="Tracking",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    notices = [{
        "native_id": f"BATCHLEAD-{suffix}",
        "title": f"Construction of 220kV transmission line package batch {suffix}",
        "buyer_name": "NTDC Batch Lead Test",
        "buyer_ref": f"BREF-LEAD-{suffix}",
        "published_at": "2026-10-12",
        "submission_deadline": "2026-12-01",
    }]
    normalizer.normalize_notices(db, source, notices)
    db.refresh(lead)
    assert lead.status == "Converted"
    assert lead.converted_opportunity_id is not None
