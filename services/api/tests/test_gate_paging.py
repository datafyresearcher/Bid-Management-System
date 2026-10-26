"""The gate queue has to be able to say how big it is.

A queue of several hundred gates is not something anybody reads off one
screen, so the page that lists them has to say how many are behind it, and
every page of the list has to be reachable.
"""

from app.models import GateTask, Opportunity


def _opp(db, suffix):
    opp = Opportunity(
        dedup_key=f"count-{suffix}",
        country="PK",
        area="Punjab",
        title=f"Test tender {suffix}",
        buyer_name="Test Buyer",
        source_id=1,
        state="GATE1",
    )
    db.add(opp)
    db.commit()
    db.refresh(opp)
    return opp


def test_the_count_endpoint_reports_the_size_of_the_queue(client, auth, db):
    resp = client.get("/api/gates/count", params={"status": "PENDING,OVERDUE"}, headers=auth)
    assert resp.status_code == 200, resp.text
    total = resp.json()["total"]
    assert isinstance(total, int)
    assert total >= 0

    listed = client.get("/api/gates", params={"status": "PENDING,OVERDUE", "limit": 300}, headers=auth)
    assert listed.status_code == 200
    assert len(listed.json()) <= total


def test_the_count_follows_the_filters(client, auth, db):
    """The count is of the view being asked for, not of the whole queue."""
    for status in ("PENDING,OVERDUE", "APPROVED", "OVERDUE"):
        counted = client.get("/api/gates/count", params={"status": status}, headers=auth).json()["total"]
        listed = client.get("/api/gates", params={"status": status, "limit": 300}, headers=auth).json()
        assert len(listed) <= counted, f"{status}: {len(listed)} listed but {counted} counted"
        if counted <= 300:
            assert len(listed) == counted, f"{status}: the count and the list disagree"


def test_every_gate_can_be_reached_by_paging(client, auth, db):
    """The list is paged, so the pages have to add up to the whole queue."""
    total = client.get("/api/gates/count", params={"status": "PENDING,OVERDUE"}, headers=auth).json()["total"]
    if total == 0:
        return
    seen = set()
    offset = 0
    while offset < total:
        resp = client.get(
            "/api/gates",
            params={"status": "PENDING,OVERDUE", "limit": 25, "offset": offset},
            headers=auth,
        )
        assert resp.status_code == 200
        rows = resp.json()
        if not rows:
            break
        seen.update(row["id"] for row in rows)
        offset += 25
    assert len(seen) == total, f"paged through {len(seen)} of {total} gates"


def test_the_opportunity_list_pages_too(client, auth):
    """The tender inbox lists every captured tender, not the first page of them."""
    first = client.get("/api/opportunities", params={"page": 1, "page_size": 25}, headers=auth)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["total"] >= len(body["items"])
    assert body["page"] == 1
    assert body["page_size"] == 25

    if body["total"] > 25:
        second = client.get("/api/opportunities", params={"page": 2, "page_size": 25}, headers=auth).json()
        first_ids = {o["id"] for o in body["items"]}
        second_ids = {o["id"] for o in second["items"]}
        assert second["items"], "the second page was empty"
        assert not (first_ids & second_ids), "the pages overlap"
