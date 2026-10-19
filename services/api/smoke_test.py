"""Live end-to-end smoke test against a running API.

Exercises the full operational path over HTTP:
login -> dashboard -> analyse a tender -> approve every gate -> record a
win -> read the AI-quality and gold-set endpoints.

Run with the API on http://localhost:8000.
"""

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("BMS_BASE_URL", "http://localhost:8000")
TOKEN = None
FAILURES = []


def call(path, method="GET", body=None, expect=200):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw and raw[0] in "[{" else raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, raw


def check(label, condition, detail=""):
    mark = "PASS" if condition else "FAIL"
    if not condition:
        FAILURES.append(f"{label}: {detail}")
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail and not condition else ""))


def main():
    global TOKEN
    print("LIVE END-TO-END SMOKE TEST")
    print("=" * 70)

    status, health = call("/api/health")
    check("health endpoint", status == 200, str(health))
    print(f"       provider: {health.get('llm', {}).get('provider')} / {health.get('llm', {}).get('model')}")
    print(f"       simulated: {health.get('llm', {}).get('simulated')}")

    status, out = call("/api/auth/login", "POST", {"email": "bm@ahte.local", "password": "bid123"})
    check("login as bid manager", status == 200, str(out)[:200])
    TOKEN = out.get("token") if isinstance(out, dict) else None
    if not TOKEN:
        print("cannot continue without a token")
        return 1

    status, dash = call("/api/dashboard")
    check("dashboard loads", status == 200, str(dash)[:200])
    print(f"       active={dash.get('active_count')} screened_out={dash.get('screened_out_count')} "
          f"submitted={dash.get('submitted_count')} pending_gates={dash.get('pending_gates_total')}")

    active = dash.get("active_count", 0)
    screened = dash.get("screened_out_count", 0)
    submitted = dash.get("submitted_count", 0)
    state_counts = dash.get("state_counts", {})

    ACTIVE_STATES = {
        "NORMALIZED", "SCORED", "GATE1", "DOCS_FETCHED", "ANALYZED", "GATE2",
        "DRAFTING", "GATE3", "ASSEMBLY", "GATE4", "READY_TO_SUBMIT", "GATE5", "SUBMITTED", "EVALUATION",
    }
    CLOSED_STATES = {"SCREENED_OUT", "AUTO_ARCHIVED"}
    expected_active = sum(n for s, n in state_counts.items() if s in ACTIVE_STATES)
    expected_screened = sum(n for s, n in state_counts.items() if s in CLOSED_STATES)
    check("active count matches the server's own definition",
          active == expected_active, f"tile={active} expected={expected_active}")
    check("screened-out bids are not counted as active",
          expected_screened == 0 or active == expected_active,
          f"active={active} screened={screened}")
    check("screened-out count is separate", screened == expected_screened,
          f"tile={screened} expected={expected_screened}")
    print(f"       state counts: {state_counts}")

    gates = dash.get("pending_gates", [])
    with_deadline = [g for g in gates if g.get("opportunity", {}).get("submission_deadline")]
    check("published tenders in the gate queue carry their tender deadline",
          bool(with_deadline) and len(with_deadline) == len([g for g in gates if g.get("opportunity")]),
          f"{len(with_deadline)}/{len(gates)} gate rows have a submission_deadline")

    # Pick the first opportunity and drive it through every gate.
    status, inbox = call("/api/opportunities?limit=50")
    items = inbox if isinstance(inbox, list) else inbox.get("items", [])
    target = None
    # Prefer a published tender: a converted lead has no submission deadline
    # and no source documents, so it cannot exercise the document pipeline.
    for item in items:
        if item.get("state") == "GATE1" and item.get("submission_deadline"):
            target = item
            break
    if not target:
        for item in items:
            if item.get("state") == "GATE1":
                target = item
                break
    if not target:
        check("found a GATE1 opportunity to process", False, "none available")
        return 1
    opp_id = target["id"]
    print(f"       driving opportunity #{opp_id}: {target['title'][:60]}")

    status, detail = call(f"/api/opportunities/{opp_id}")
    check("opportunity detail loads", status == 200)
    print(f"       score={detail.get('score_total')} confidence={detail.get('ai_confidence')} "
          f"grade={detail.get('extraction_grade')}")
    check("score has a confidence value", detail.get("ai_confidence") is not None)

    # Approve gates 1..5 as the right role for each.
    roles = {1: "bid_manager", 2: "proposal_engineer", 3: "proposal_engineer", 4: "management", 5: "bid_manager"}
    accounts = {
        "bid_manager": ("bm@ahte.local", "bid123"),
        "proposal_engineer": ("engineer@ahte.local", "prop123"),
        "management": ("mgmt@ahte.local", "mgmt123"),
        "admin": ("admin@ahte.local", "admin123"),
    }
    decisions = {1: "GO", 2: "CONFIRMED", 3: "APPROVED", 4: "APPROVED", 5: "SUBMITTED"}

    for gate in range(1, 6):
        role = roles[gate]
        email, password = accounts[role]
        status, out = call("/api/auth/login", "POST", {"email": email, "password": password})
        if status != 200:
            check(f"login as {role}", False, str(out)[:150])
            continue
        role_token = out.get("token")
        saved, TOKEN = TOKEN, role_token

        status, gate_list = call(f"/api/gates?status=PENDING,OVERDUE&role={role}")
        pending = [g for g in gate_list if g["opportunity_id"] == opp_id] if isinstance(gate_list, list) else []
        if not pending:
            check(f"gate {gate} present for {role}", False, "no pending gate for this opportunity")
            TOKEN = saved
            continue
        gate_id = pending[0]["id"]
        status, out = call(f"/api/gates/{gate_id}/decide", "POST",
                           {"decision": decisions[gate], "comment": f"smoke test gate {gate}"})
        check(f"gate {gate} approved by {role}", status == 200, str(out)[:200])
        TOKEN = saved

    status, detail = call(f"/api/opportunities/{opp_id}")
    print(f"       state after gates: {detail.get('state')}")
    check("extraction grade is set after analysis", bool(detail.get("extraction_grade")),
          f"grade={detail.get('extraction_grade')}")
    check("documents were fetched and analysed", len(detail.get("requirements") or []) > 0,
          f"requirements={len(detail.get('requirements') or [])}")
    check("risk flags were produced", len(detail.get("risk_flags") or []) > 0,
          f"risk_flags={len(detail.get('risk_flags') or [])}")
    check("compliance matrix was built", len(detail.get("compliance") or []) > 0,
          f"compliance={len(detail.get('compliance') or [])}")

    status, out = call(f"/api/opportunities/{opp_id}/outcome", "POST",
                       {"result": "WON", "comment": "smoke test win", "reason_code": "price"})
    check("outcome recorded", status == 200, str(out)[:200])

    # The admin-only views.
    admin_token = TOKEN
    status, out = call("/api/auth/login", "POST", {"email": "admin@ahte.local", "password": "admin123"})
    if status == 200:
        TOKEN = out.get("token")
    else:
        check("login as admin", False, str(out)[:150])

    status, proposals = call(f"/api/proposals/{opp_id}")
    if status == 200:
        sections = proposals.get("sections") or []
        check("proposal sections were drafted", len(sections) > 0, f"sections={len(sections)}")
        check("no drafted section is empty",
              all((s.get("content") or "").strip() for s in sections),
              "a section came back empty")
        drafted = sum(1 for s in sections if s.get("status") == "DRAFTED")
        print(f"       proposal sections: {len(sections)} ({drafted} drafted, "
              f"{len(sections) - drafted} with gaps)")

    status, quality = call("/api/admin/ai-quality")
    check("ai-quality endpoint", status == 200, str(quality)[:200])
    if status == 200:
        print(f"       llm tasks: {list((quality.get('llm_by_task') or {}).keys())}")
        print(f"       outcomes={quality.get('outcomes_total')} win_rate={quality.get('win_rate')}")
        print(f"       bands={quality.get('score_band_performance')}")
        print(f"       calibration={quality.get('calibration')}")
        check("LLM calls are now recorded", bool(quality.get("llm_by_task")),
              "no llm_by_task buckets — the AI layer is not running")
        check("outcome feedback is wired", quality.get("outcomes_total", 0) > 0,
              "outcomes_total is zero — the feedback loop is not reading the outcomes table")

    status, ev = call("/api/admin/evaluation")
    check("gold-set evaluation endpoint", status == 200, str(ev)[:200])
    if status == 200:
        print(f"       cases {ev.get('cases_passed')}/{ev.get('cases_total')} "
              f"micro={ev.get('micro_accuracy')} macro_f1={ev.get('macro_f1')} risk_recall={ev.get('risk_recall')}")

    TOKEN = admin_token
    status, gaps = call("/api/kb/gaps")
    check("kb gap report", status == 200, str(gaps)[:200])
    if status == 200:
        print(f"       kb gaps: {gaps.get('gaps')}")

    print("=" * 70)
    if FAILURES:
        print(f"FAILURES ({len(FAILURES)}):")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
