import time

from sqlalchemy import select

from app.models import Source
from app.services import documents, extractor, normalizer, risk

DOCUMENT_TEXT = (
    "Instructions to Bidders.\n"
    "Bid security of PKR 5,000,000 shall be submitted as bank guarantee.\n"
    "Tender fee of PKR 25,000 is payable.\n"
    "The last date of submission is 25-Nov-2026 at 11:00 hours.\n"
    "Bidders shall hold PEC C-A licence for this work.\n"
    "The bidder must have average annual turnover of PKR 2,500,000,000.\n"
    "The bidder must have completed at least 3 similar nature works in the last ten years.\n"
    "An advance payment of 15 percent shall be released on commencement.\n"
    "The contractor's liability under this contract shall be without limitation.\n"
    "Liquidated damages for delay shall apply at 0.05 percent per day.\n"
    "All disputes shall be settled by ICC arbitration with seat in Singapore.\n"
)


def _fresh_opp(db, suffix):
    source = db.execute(select(Source).where(Source.code == "ppra_punjab")).scalars().first()
    notice = {
        "native_id": f"DOC-{suffix}",
        "title": f"132kV substation extension works {suffix}",
        "buyer_name": "DocTest Utility",
        "buyer_ref": f"DOCREF-{suffix}",
        "published_at": "2026-10-10",
        "submission_deadline": "2026-11-25",
    }
    return normalizer.normalize_notice(db, source, notice)


def test_document_pipeline_extracts_requirements_and_risks(db):
    suffix = str(time.time_ns())
    opp = _fresh_opp(db, suffix)
    documents.save_document(db, opp, "ITT_unit.txt", DOCUMENT_TEXT.encode("utf-8"))

    result = extractor.run(db, opp)
    assert result["requirements"] > 0
    assert opp.bid_security_amount == 5_000_000
    assert opp.pec_category_required == "C-A"
    assert opp.qualification_thresholds["turnover"] == 2_500_000_000
    assert opp.qualification_thresholds["similar_work_count"] == 3
    assert opp.submission_deadline is not None and opp.submission_deadline.day == 25

    flags = risk.run(db, opp)
    titles = [f["title"] for f in flags]
    assert any("Uncapped" in t for t in titles)
    assert any("Advance payment" in t for t in titles)
    assert any("Delay damages" in t or "arbitration" in t.lower() for t in titles)
