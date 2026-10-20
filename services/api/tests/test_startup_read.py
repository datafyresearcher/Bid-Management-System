"""The first read of a freshly started deployment.

A serverless instance starts with nothing, and a dashboard that announces live
reading while showing no tenders is not much use. The startup read fills that
gap inside a budget that keeps it from holding up the first request.

These tests cover the budget itself. The read against the real portals is
exercised by running the API against the live sources, not by the test suite.
"""

from app.config import settings


class StubSource:
    code = "stub"
    name = "Stub source"
    area = ""
    type = "portal"
    url = "https://example.test/"
    listing_url = "https://example.test/"


def test_a_scan_can_be_given_a_tighter_budget():
    """A scan that has to fit a tight window asks for less."""
    from app.connectors.base import BaseConnector

    connector = BaseConnector(StubSource())
    assert connector.pages_allowed() == settings.live_max_pages

    connector.page_budget = 1
    assert connector.pages_allowed() == 1

    # A scan reads at least one page, however small its budget.
    connector.page_budget = 0
    assert connector.pages_allowed() == 1


def test_the_startup_budget_shortens_the_deadline():
    from app.connectors.base import BaseConnector

    connector = BaseConnector(StubSource())
    connector.scan_seconds = 6
    left, estimate = connector.scan_budget()
    assert left <= 6
    assert estimate > 0


def test_the_startup_read_does_not_read_the_portals_in_demo_mode(monkeypatch):
    """In demo mode the demo pipeline has already filled the database."""
    from app import bootstrap
    from app.services import jobs

    calls = []
    monkeypatch.setattr(jobs, "run_source", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(settings, "fixtures", True)

    bootstrap.populate_from_portals()

    assert calls == []


def test_the_startup_read_stops_when_the_budget_is_spent(monkeypatch):
    """The read is bounded, so a slow portal cannot hold the first request up."""
    from app import bootstrap
    from app.services import jobs

    calls = []
    monkeypatch.setattr(jobs, "run_source", lambda *args, **kwargs: calls.append(kwargs))

    class FakeSource:
        code = "fake"
        tier = "P1"

    bootstrap.read_within_budget(None, [FakeSource()], budget=60)

    assert calls, "the source should have been read"
    for kwargs in calls:
        assert kwargs["page_budget"] == 1
        assert kwargs["scan_seconds"] <= 6
        assert kwargs["connect_timeout"] <= 4


def test_the_startup_read_leaves_a_source_alone_when_the_budget_is_gone(monkeypatch):
    from app import bootstrap
    from app.services import jobs

    calls = []
    monkeypatch.setattr(jobs, "run_source", lambda *args, **kwargs: calls.append(kwargs))

    class FakeSource:
        code = "fake"
        tier = "P1"

    # A budget too small for even one read means no portal is touched.
    bootstrap.read_within_budget(None, [FakeSource()], budget=1)

    assert calls == []
