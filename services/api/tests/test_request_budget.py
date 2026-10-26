"""Every part of a request draws from one budget.

The host stops a request after a fixed time. The work a request does —
reading a portal, capturing it, scoring it, asking the model to explain it
— happens in sequence, so if each of them had its own budget the request
could run for the sum of them. These tests pin that they do not.
"""

import time

from app import runtime


def test_nothing_is_timed_until_a_deadline_is_set():
    runtime.set_deadline(None)
    assert runtime.deadline() is None
    assert runtime.remaining() is None


def test_the_remaining_time_counts_down():
    runtime.set_deadline(time.monotonic() + 10)
    first = runtime.remaining()
    time.sleep(0.05)
    second = runtime.remaining()
    assert first is not None and second is not None
    assert first > second
    assert first <= 10


def test_a_past_deadline_leaves_nothing():
    runtime.set_deadline(time.monotonic() - 1)
    assert runtime.remaining() < 0


def test_the_start_up_cost_is_charged_once():
    runtime.set_startup_seconds(12.5)
    assert runtime.claim_startup_seconds() == 12.5
    # The instance is up now; the next request starts with a clean budget.
    assert runtime.claim_startup_seconds() == 0


def test_a_request_carries_a_deadline(client):
    """The work inside a request has to be able to see how much time is left."""
    from app.main import app

    @app.get("/_test/deadline")
    def _deadline():
        return {"remaining": runtime.remaining()}

    resp = client.get("/_test/deadline")
    assert resp.status_code == 200
    remaining = resp.json()["remaining"]
    assert remaining is not None
    assert 0 < remaining <= 60


def test_the_scoring_budget_follows_the_request(client, db):
    """A batch may not spend more than the request has left."""
    from app.config import settings
    from app.services import jobs

    runtime.set_deadline(time.monotonic() + 0.01)
    try:
        started = time.monotonic()
        jobs.score_new(db, [1, 2, 3], budget_seconds=30)
        elapsed = time.monotonic() - started
    finally:
        runtime.set_deadline(None)
    # The batch was told it had 30 seconds and the request had almost none.
    assert elapsed < 10
    assert settings.score_budget_seconds > 0


def test_a_scan_still_works_inside_a_request_deadline(db):
    """A scan must not break just because the request is being timed.

    The read takes the time the request has left, so the arithmetic around
    that has to hold when the connector has no deadline of its own.
    """
    from sqlalchemy import select

    from app.models import Source
    from app.services import jobs

    source = db.execute(select(Source).where(Source.code == "ntdc")).scalars().first()
    assert source is not None, "the seeded sources should include ntdc"

    runtime.set_deadline(time.monotonic() + 30)
    try:
        result = jobs.run_source(db, source)
    finally:
        runtime.set_deadline(None)

    assert "error" not in result
    assert result.get("notices", 0) >= 0
