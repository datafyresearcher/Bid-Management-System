"""Gold-set evaluation.

This module answers the question the design pack kept deferring: *how accurate
is the extraction, actually?*

It runs the real extraction and risk pipeline over a labelled set of tender
documents and reports per-field precision, recall and F1, plus a case-level
accuracy. The gold set lives in ``services/api/goldset/`` — one JSON manifest
plus the source documents. Every expected value there was read off the source
document by a human, not copied from the extractor's output.

The evaluation runs against a throwaway SQLite database so it never touches
operational data.
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    ExtractedRequirement,
    Opportunity,
    RiskFlag,
)

GOLDSET_DIR = Path(__file__).resolve().parents[2] / "goldset"
MANIFEST = GOLDSET_DIR / "cases.json"

# Numeric fields are compared with a small relative tolerance so that a
# rounding difference is not scored as a wrong answer.
AMOUNT_TOLERANCE = 0.001

SCALAR_FIELDS = [
    "submission_deadline",
    "bid_security_amount",
    "bid_security_form",
    "tender_fee",
    "pec_category_required",
    "prequal_required",
    "procurement_regime",
]
THRESHOLD_FIELDS = ["turnover", "similar_work_count"]


def load_cases(goldset_dir: Path = GOLDSET_DIR) -> list:
    manifest_path = Path(goldset_dir) / "cases.json"
    if not manifest_path.exists():
        return []
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return data.get("cases", [])


def _parse_expected_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    return None


def _compare_date(expected, actual):
    exp = _parse_expected_date(expected)
    if exp is None:
        return actual is None
    if actual is None:
        return False
    if hasattr(actual, "date"):
        actual = actual.date()
    return exp.date() == actual


def _compare_amount(expected, actual):
    if expected is None:
        return actual is None
    if actual is None:
        return False
    try:
        return abs(float(expected) - float(actual)) <= max(1.0, abs(float(expected)) * AMOUNT_TOLERANCE)
    except (TypeError, ValueError):
        return False


def _compare_text(expected, actual):
    if expected is None:
        return actual is None or actual == ""
    if actual is None:
        return False
    return str(expected).strip().lower() == str(actual).strip().lower()


def _compare_bool(expected, actual):
    if expected is None:
        return actual is None
    return bool(expected) == bool(actual)


COMPARATORS = {
    "submission_deadline": _compare_date,
    "bid_security_amount": _compare_amount,
    "tender_fee": _compare_amount,
    "bid_security_form": _compare_text,
    "pec_category_required": _compare_text,
    "prequal_required": _compare_bool,
    "procurement_regime": _compare_text,
}


def _opportunity_for_case(db, case):
    opp = Opportunity(
        dedup_key=f"goldset-{case['id']}",
        country="PK",
        area="Punjab",
        category_internal="Substations",
        tender_type="Works",
        buyer_name="Goldset",
        buyer_ref=case["id"],
        title=case.get("name", case["id"]),
        description="Gold-set evaluation case",
        state="NORMALIZED",
        source_refs=[],
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return opp


def evaluate_case(db, case, goldset_dir: Path = GOLDSET_DIR) -> dict:
    """Run the real pipeline over one labelled case and score it."""
    from app.services import documents, extractor, risk

    doc_path = Path(goldset_dir) / case["document"]
    content = doc_path.read_bytes()

    opp = _opportunity_for_case(db, case)
    documents.save_document(db, opp, doc_path.name, content)

    extractor_result = extractor.run(db, opp)
    risk_flags = risk.run(db, opp)

    db.refresh(opp)
    expected = case.get("expected", {})

    field_results = {}
    for field in SCALAR_FIELDS:
        comparator = COMPARATORS.get(field, _compare_text)
        exp = expected.get(field, None)
        actual = getattr(opp, field, None)
        field_results[field] = {
            "expected": exp,
            "actual": _serialise(actual),
            "match": comparator(exp, actual),
        }

    thresholds = expected.get("qualification_thresholds") or {}
    actual_thresholds = opp.qualification_thresholds or {}
    for field in THRESHOLD_FIELDS:
        exp = thresholds.get(field, None)
        actual = actual_thresholds.get(field, None)
        field_results[f"threshold.{field}"] = {
            "expected": exp,
            "actual": actual,
            "match": _compare_amount(exp, actual) if field == "turnover" else _compare_amount(exp, actual),
        }

    # Risk: recall over the labels a human assigned, plus a bound on the
    # total number of flags so a system cannot score well by flagging
    # everything.
    flag_titles = [f.title for f in db.execute(select(RiskFlag)).scalars().all() if f.opportunity_id == opp.id]
    missing_risk = []
    for wanted in case.get("risk_titles_containing", []):
        if not any(wanted.lower() in title.lower() for title in flag_titles):
            missing_risk.append(wanted)

    risk_min = case.get("risk_flags_min")
    risk_max = case.get("risk_flags_max")
    risk_ok = True
    if risk_min is not None and len(flag_titles) < risk_min:
        risk_ok = False
    if risk_max is not None and len(flag_titles) > risk_max:
        risk_ok = False

    expected_risk = case.get("risk_titles_containing", [])

    requirements = db.execute(
        select(ExtractedRequirement).where(ExtractedRequirement.opportunity_id == opp.id)
    ).scalars().all()
    min_requirements = case.get("min_requirements")
    requirements_ok = min_requirements is None or len(requirements) >= min_requirements

    all_fields_ok = all(r["match"] for r in field_results.values())
    passed = all_fields_ok and not missing_risk and risk_ok and requirements_ok

    return {
        "id": case["id"],
        "name": case.get("name", case["id"]),
        "source": case.get("source", ""),
        "passed": passed,
        "fields": field_results,
        "fields_matched": sum(1 for r in field_results.values() if r["match"]),
        "fields_total": len(field_results),
        "missing_risk_flags": missing_risk,
        "expected_risk_flags": expected_risk,
        "risk_flag_count": len(flag_titles),
        "risk_flag_titles": flag_titles,
        "requirements_found": len(requirements),
        "requirements_ok": requirements_ok,
        "extraction_grade": opp.extraction_grade,
        "confidence": opp.ai_confidence,
    }


def _serialise(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value


def _temp_session():
    """A throwaway database so evaluation never touches operational data."""
    handle, path = tempfile.mkstemp(suffix=".db", prefix="bms_goldset_")
    os.close(handle)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session, engine, path


def _aggregate(case_results: list) -> dict:
    fields = {}
    for result in case_results:
        for field, data in result["fields"].items():
            entry = fields.setdefault(field, {"tp": 0, "fp": 0, "fn": 0, "correct": 0, "total": 0})
            entry["total"] += 1
            expected_is_null = data["expected"] is None
            if data["match"]:
                entry["correct"] += 1
                if not expected_is_null:
                    entry["tp"] += 1
            else:
                if expected_is_null:
                    entry["fp"] += 1
                else:
                    entry["fn"] += 1

    summary = {}
    for field, entry in fields.items():
        tp, fp, fn = entry["tp"], entry["fp"], entry["fn"]
        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + fn) if (tp + fn) else None
        if precision is None or recall is None or (precision + recall) == 0:
            f1 = 0.0 if (tp + fp + fn) else None
        else:
            f1 = round(2 * precision * recall / (precision + recall), 4)
        summary[field] = {
            "tp": tp, "fp": fp, "fn": fn,
            "precision": round(precision, 4) if precision is not None else None,
            "recall": round(recall, 4) if recall is not None else None,
            "f1": f1,
            "accuracy": round(entry["correct"] / entry["total"], 4),
        }

    scored = [v["f1"] for v in summary.values() if v["f1"] is not None]
    risk_expected = sum(len(r.get("missing_risk_flags", [])) for r in case_results)
    risk_total = sum(len(r.get("expected_risk_flags", [])) for r in case_results)

    return {
        "fields": summary,
        "macro_f1": round(sum(scored) / len(scored), 4) if scored else None,
        "micro_accuracy": round(
            sum(v["correct"] for v in fields.values()) / sum(v["total"] for v in fields.values()), 4
        ) if fields else None,
        "case_accuracy": round(sum(1 for r in case_results if r["passed"]) / len(case_results), 4)
        if case_results else None,
        "risk_recall": round((risk_total - risk_expected) / risk_total, 4) if risk_total else None,
    }


def run_all(goldset_dir: Path = GOLDSET_DIR, cases=None) -> dict:
    """Evaluate every case and return the full report."""
    cases = cases or load_cases(goldset_dir)
    if not cases:
        return {"error": "no gold-set cases found", "cases": []}

    session, engine, path = _temp_session()
    results = []
    try:
        db = session()
        try:
            for case in cases:
                try:
                    results.append(evaluate_case(db, case, goldset_dir))
                except Exception as exc:
                    results.append(
                        {
                            "id": case.get("id", "?"),
                            "name": case.get("name", ""),
                            "passed": False,
                            "error": f"{type(exc).__name__}: {exc}",
                            "fields": {},
                            "fields_matched": 0,
                            "fields_total": 0,
                            "missing_risk_flags": [],
                            "risk_flag_count": 0,
                            "risk_flag_titles": [],
                            "requirements_found": 0,
                            "requirements_ok": False,
                        }
                    )
        finally:
            db.close()
    finally:
        engine.dispose()
        try:
            os.remove(path)
        except OSError:
            pass

    report = _aggregate(results)
    report["cases"] = results
    report["cases_total"] = len(results)
    report["cases_passed"] = sum(1 for r in results if r["passed"])
    return report


def format_report(report: dict) -> str:
    """Human-readable report, used by the CLI and the API."""
    if report.get("error"):
        return f"Evaluation error: {report['error']}"

    lines = []
    lines.append("GOLD-SET EVALUATION")
    lines.append("=" * 78)
    lines.append(
        f"Cases: {report.get('cases_passed', 0)}/{report.get('cases_total', 0)} passed"
        f"   Case accuracy: {_pct(report.get('case_accuracy'))}"
    )
    lines.append(
        f"Micro accuracy (all fields): {_pct(report.get('micro_accuracy'))}"
        f"   Macro F1: {_pct(report.get('macro_f1'))}"
        f"   Risk recall: {_pct(report.get('risk_recall'))}"
    )
    lines.append("")
    lines.append(f"{'FIELD':<28}{'PREC':>9}{'RECALL':>9}{'F1':>9}{'ACC':>9}   TP  FP  FN")
    lines.append("-" * 78)
    for field, data in sorted(report.get("fields", {}).items()):
        lines.append(
            f"{field:<28}{_pct(data['precision']):>9}{_pct(data['recall']):>9}"
            f"{_pct(data['f1']):>9}{_pct(data['accuracy']):>9}"
            f"   {data['tp']:>2}  {data['fp']:>2}  {data['fn']:>2}"
        )
    lines.append("")
    lines.append("PER-CASE")
    lines.append("-" * 78)
    for case in report.get("cases", []):
        mark = "PASS" if case["passed"] else "FAIL"
        lines.append(
            f"  [{mark}] {case['id']:<34} {case.get('fields_matched', 0)}/{case.get('fields_total', 0)} fields"
            f"  reqs={case.get('requirements_found', 0)}  risks={case.get('risk_flag_count', 0)}"
            f"  grade={case.get('extraction_grade', '-')}"
        )
        if case.get("error"):
            lines.append(f"         error: {case['error']}")
        for field, data in case.get("fields", {}).items():
            if not data["match"]:
                lines.append(
                    f"         MISS {field}: expected={data['expected']!r} actual={data['actual']!r}"
                )
        for missing in case.get("missing_risk_flags", []):
            lines.append(f"         MISS risk flag: {missing}")
    return "\n".join(lines)


def _pct(value):
    if value is None:
        return "   n/a"
    return f"{value * 100:6.1f}%"
