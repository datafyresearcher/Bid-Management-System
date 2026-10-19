def test_leads_import_and_convert(client, auth):
    imported = client.post("/api/leads/import/annual-plan", headers=auth)
    assert imported.status_code == 200

    listing = client.get("/api/leads", headers=auth)
    assert listing.status_code == 200
    leads = listing.json()["items"]
    assert len(leads) >= 5

    tracking = next((l for l in leads if l["status"] == "Tracking"), None)
    assert tracking is not None, "Seeded annual-plan lead should be Tracking"

    converted = client.post(f"/api/leads/{tracking['id']}/convert", headers=auth)
    assert converted.status_code == 200
    payload = converted.json()
    assert payload["opportunity_id"]
    assert payload["state"] in {"SCORED", "GATE1", "AUTO_ARCHIVED", "SCREENED_OUT"}

    detail = client.get(f"/api/opportunities/{payload['opportunity_id']}", headers=auth)
    assert detail.status_code == 200
    assert detail.json()["lead_id"] == tracking["id"]


def test_manual_lead_create_and_status(client, auth):
    created = client.post(
        "/api/leads",
        json={
            "title": "Manual signal — 132kV grid station rehab (unit test)",
            "buyer": "Faisalabad Electric Supply Company (FESCO)",
            "category_internal": "Substations",
            "area": "Punjab",
            "estimated_value": 900000000,
            "confidence_tier": "Medium",
        },
        headers=auth,
    )
    assert created.status_code == 200
    lead_id = created.json()["id"]

    updated = client.post(f"/api/leads/{lead_id}/status", json={"status": "Tracking"}, headers=auth)
    assert updated.status_code == 200
    assert updated.json()["status"] == "Tracking"


def test_sources_and_manual_opportunity(client, auth):
    sources = client.get("/api/sources", headers=auth)
    assert sources.status_code == 200
    codes = {s["code"] for s in sources.json()}
    assert {"ppra_punjab", "epms_federal", "ntdc"}.issubset(codes)

    adapters = client.get("/api/sources/adapters", headers=auth)
    assert adapters.status_code == 200
    assert any(a["adapter"] == "fixture_json" for a in adapters.json())

    manual = client.post(
        "/api/opportunities/manual",
        json={
            "title": "Manual opportunity — 220kV bay extension (unit test)",
            "buyer_name": "NTDC",
            "category_internal": "Substations",
            "area": "Punjab",
            "estimated_value": 750000000,
            "submission_deadline": "2026-12-15",
        },
        headers=auth,
    )
    assert manual.status_code == 200
    opp_id = manual.json()["id"]

    scored = client.post(f"/api/opportunities/{opp_id}/score", headers=auth)
    assert scored.status_code == 200
    assert scored.json()["state"] in {"GATE1", "SCORED", "AUTO_ARCHIVED", "SCREENED_OUT"}
