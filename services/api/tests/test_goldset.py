"""Gold-set regression test.

This runs the real extraction and risk pipeline over the labelled documents in
``services/api/goldset/`` and fails the build if accuracy regresses.

Note on what this number means: the gold set is small and was written by the
same team that wrote the extractor, so it is a *regression baseline* — it
protects against silent breakage. It is not a production accuracy claim. A
real accuracy claim needs a gold set built from AHTE's own historical tender
packages (assumption A-01 in the design pack).
"""

import pytest

from app.services import evaluation


@pytest.fixture(scope="module")
def report():
    return evaluation.run_all()


def test_goldset_is_not_empty(report):
    assert not report.get("error"), report.get("error")
    assert report["cases_total"] >= 7


def test_every_case_passes(report):
    failures = [
        (case["id"], case.get("fields_matched"), case.get("fields_total"))
        for case in report["cases"]
        if not case["passed"]
    ]
    assert not failures, f"gold-set cases regressed: {failures}"


def test_field_accuracy_meets_threshold(report):
    assert report["micro_accuracy"] >= 0.95, report["micro_accuracy"]
    assert report["macro_f1"] >= 0.95, report["macro_f1"]
    assert report["case_accuracy"] >= 0.95, report["case_accuracy"]


def test_no_hallucinated_fields(report):
    """A field that should be absent must not be extracted.

    This is the negative case that keeps the extractor honest: a system that
    invents a bid security for a tender that never mentions one is worse than
    one that misses it.
    """
    for field, data in report["fields"].items():
        assert data["fp"] == 0, f"{field} produced {data['fp']} false positives"


def test_risk_recall_is_complete(report):
    assert report["risk_recall"] == 1.0, report["risk_recall"]
