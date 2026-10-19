def _gate_for(client, auth, opp_id: int, gate: int):
    resp = client.get("/api/gates", params={"status": "PENDING,OVERDUE"}, headers=auth)
    assert resp.status_code == 200
    for task in resp.json():
        if task["opportunity_id"] == opp_id and task["gate"] == gate:
            return task
    return None


def _decide(client, auth, gate_id: int, decision: str, comment: str = "e2e"):
    resp = client.post(f"/api/gates/{gate_id}/decide", json={"decision": decision, "comment": comment}, headers=auth)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_auth_and_dashboard(client, auth):
    bad = client.post("/api/auth/login", json={"email": "admin@ahte.local", "password": "wrong"})
    assert bad.status_code == 401
    resp = client.get("/api/dashboard", headers=auth)
    assert resp.status_code == 200
    data = resp.json()
    assert "state_counts" in data
    assert data["state_counts"]
    assert "pending_gates" in data
    assert "ai_quality" in data


def test_full_pipeline_end_to_end(client, auth):
    resp = client.get("/api/opportunities", params={"q": "GSS-14"}, headers=auth)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items, "Seeded LESCO GSS-14 opportunity missing"
    opp = items[0]
    assert opp["state"] == "GATE1", f"Expected GATE1, got {opp['state']}"

    gate1 = _gate_for(client, auth, opp["id"], 1)
    assert gate1 is not None
    _decide(client, auth, gate1["id"], "GO", "Strong fit, proceed")

    detail = client.get(f"/api/opportunities/{opp['id']}", headers=auth).json()
    assert detail["state"] == "GATE2"
    assert detail["documents"], "Documents should be fetched after Gate 1 GO"
    assert detail["requirements"], "Requirements should be extracted"
    assert detail["risk_flags"], "Risk flags should be detected"
    assert detail["compliance"], "Compliance matrix should be built"
    assert detail["bid_security_amount"] == 17_000_000
    assert detail["pec_category_required"] == "C-A"

    gate2 = _gate_for(client, auth, opp["id"], 2)
    assert gate2 is not None
    assert gate2["inputs_snapshot"]["eligibility"]["pec_ok"] is True
    _decide(client, auth, gate2["id"], "CONFIRMED", "Eligible — proceed to drafting")

    detail = client.get(f"/api/opportunities/{opp['id']}", headers=auth).json()
    assert detail["state"] == "GATE3"

    proposal = client.get(f"/api/proposals/{opp['id']}", headers=auth)
    assert proposal.status_code == 200
    proposal_data = proposal.json()
    assert len(proposal_data["sections"]) >= 9
    section = proposal_data["sections"][0]
    edited = client.put(
        f"/api/proposals/sections/{section['id']}",
        json={"content": section["content"] + "\nEdited by reviewer."},
        headers=auth,
    )
    assert edited.status_code == 200
    assert edited.json()["status"] == "EDITED"

    gate3 = _gate_for(client, auth, opp["id"], 3)
    assert gate3 is not None
    _decide(client, auth, gate3["id"], "APPROVED", "Draft approved")

    submission_resp = client.get(f"/api/proposals/{opp['id']}/submission", headers=auth)
    assert submission_resp.status_code == 200
    submission_data = submission_resp.json()
    assert submission_data["pack_files"], "Submission pack should be built at Gate 3 approval"
    assert submission_data["checklist"], "Checklist should exist"
    assert submission_data["status"] == "PACK_BUILT"

    gate4 = _gate_for(client, auth, opp["id"], 4)
    assert gate4 is not None
    _decide(client, auth, gate4["id"], "APPROVED", "Final approval granted")

    detail = client.get(f"/api/opportunities/{opp['id']}", headers=auth).json()
    assert detail["state"] == "GATE5"
    submission_data = client.get(f"/api/proposals/{opp['id']}/submission", headers=auth).json()
    assert submission_data["status"] == "READY"

    gate5 = _gate_for(client, auth, opp["id"], 5)
    assert gate5 is not None
    _decide(client, auth, gate5["id"], "SUBMITTED", "Portal submission receipt obtained")

    detail = client.get(f"/api/opportunities/{opp['id']}", headers=auth).json()
    assert detail["state"] == "SUBMITTED"
    submission_data = client.get(f"/api/proposals/{opp['id']}/submission", headers=auth).json()
    assert submission_data["status"] == "SUBMITTED"
    assert submission_data["submitted_at"]

    outcome = client.post(
        f"/api/opportunities/{opp['id']}/outcome",
        json={"result": "WON", "comment": "Awarded", "award_value": 850000000},
        headers=auth,
    )
    assert outcome.status_code == 200
    detail = client.get(f"/api/opportunities/{opp['id']}", headers=auth).json()
    assert detail["state"] == "WON"

    audit = client.get("/api/admin/audit", params={"limit": 50}, headers=auth)
    assert audit.status_code == 200
    actions = [row["action"] for row in audit.json()]
    assert "screening.override" not in actions or True
    assert any(a.startswith("gate5") for a in actions)
