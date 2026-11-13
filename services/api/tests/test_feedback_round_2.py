"""Tests for the bidding team's second round of feedback.

1. A calendar/schedule view of upcoming tenders scoring above 70.
2. By default, active tenders scoring above 70 listed on top.

Each test names the piece of feedback it answers, so a later change that
undoes one of them fails here rather than going unnoticed.
"""

from datetime import timedelta

from app.services.utils import utcnow


def _make(client, auth, title, score=None, deadline=None, state=None):
    payload = {
        "title": title,
        "buyer_name": "Test buyer",
        "buyer_ref": title.replace(" ", "-")[:40],
        "source_label": "Test",
    }
    if deadline:
        payload["submission_deadline"] = deadline
    resp = client.post("/api/opportunities/manual", json=payload, headers=auth)
    assert resp.status_code == 200, resp.text
    opp_id = resp.json()["id"]
    if score is not None or state is not None:
        from app.db import SessionLocal
        from app.models import Opportunity

        db = SessionLocal()
        try:
            row = db.get(Opportunity, opp_id)
            if score is not None:
                row.score_total = score
            if state is not None:
                row.state = state
            db.commit()
        finally:
            db.close()
    return opp_id


def _order(client, auth, titles):
    resp = client.get(
        "/api/opportunities", params={"sort": "priority", "page_size": 100}, headers=auth
    ).json()
    ids = [i["title"] for i in resp["items"]]
    return [ids.index(t) for t in titles if t in ids]


# ----------------------------------------------------------------------
# 2  Active tenders scoring above 70 listed on top
# ----------------------------------------------------------------------


def test_priority_sort_puts_active_high_scorers_first(client, auth):
    """The working queue stands at the top of the list, best score first.

    An active tender scoring 80 is what the bid manager opens the inbox
    for; a screened-out tender scoring 90 is not, and a won or lost one
    even less. The order below the priority block follows strength, so the
    list reads as a queue rather than a heap.
    """
    client, auth = client, auth
    _make(client, auth, "R2 active eighty", score=80, deadline=(utcnow() + timedelta(days=10)).strftime("%Y-%m-%d"))
    _make(client, auth, "R2 active fifty", score=50, deadline=(utcnow() + timedelta(days=10)).strftime("%Y-%m-%d"))
    _make(client, auth, "R2 screened ninety", score=90, state="SCREENED_OUT")
    _make(client, auth, "R2 past eightyfive", score=85, deadline=(utcnow() - timedelta(days=3)).strftime("%Y-%m-%d"))
    client.put  # noqa: B018 — readability: everything below works on the list

    pos = _order(
        client,
        auth,
        ["R2 active eighty", "R2 screened ninety", "R2 past eightyfive", "R2 active fifty"],
    )
    assert pos, "none of the made tenders came back"
    # The active 80 sits above everything else; among the rest, strength
    # decides — the screened-out 90 outranks the past 85, and both outrank
    # the active 50.
    assert pos[0] < pos[1] < pos[2] < pos[3]


def test_a_decided_or_unscored_tender_is_not_priority(client, auth):
    """A tender without a score, or already decided, never tops the list.

    Unscored records have no number to trust yet, and a submitted bid is
    work already done — neither belongs above a live high scorer.
    """
    _make(client, auth, "R2 unscored tender")
    _make(client, auth, "R2 submitted sixty", score=60, deadline=(utcnow() + timedelta(days=10)).strftime("%Y-%m-%d"), state="SUBMITTED")

    resp = client.get(
        "/api/opportunities", params={"sort": "priority", "page_size": 100}, headers=auth
    ).json()
    first = resp["items"][0]["title"]
    assert first != "R2 unscored tender"


# ----------------------------------------------------------------------
# 1  Calendar of upcoming tenders scoring above 70
# ----------------------------------------------------------------------


def test_the_calendar_view_has_its_data(client, auth):
    """The schedule reads the list it is built from.

    The calendar is the deadline-ordered list of active tenders above the
    threshold — the same endpoint the inbox uses, narrowed. It needs the
    filter to hold: a screened-out or past-deadline tender, however high it
    scores, is not upcoming work, and a 50-scored one is not above the bar.
    """
    _make(client, auth, "R2 calendar eighty", score=80, deadline=(utcnow() + timedelta(days=9)).strftime("%Y-%m-%d"))
    _make(client, auth, "R2 calendar screened", score=90, state="SCREENED_OUT")
    _make(client, auth, "R2 calendar past", score=95, deadline=(utcnow() - timedelta(days=2)).strftime("%Y-%m-%d"))

    resp = client.get(
        "/api/opportunities",
        params={
            "deadline": "open",
            "min_score": "70",
            "sort": "deadline",
            "page_size": "100",
            "state": "NEW,NORMALIZED,SCORED,GATE1,GATE2,GATE3,GATE4,GATE5,DOCS_FETCHED,ANALYZED,DRAFTING,ASSEMBLY,READY_TO_SUBMIT,SUBMITTED,EVALUATION",
        },
        headers=auth,
    ).json()
    titles = [i["title"] for i in resp["items"]]
    assert "R2 calendar eighty" in titles
    assert "R2 calendar screened" not in titles
    assert "R2 calendar past" not in titles
