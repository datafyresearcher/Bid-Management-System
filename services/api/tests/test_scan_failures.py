"""A portal that could not be read has to be recorded as such.

The dashboard's whole promise is that it says what the feed is really doing. A
portal that this deployment cannot reach at all has to be marked as failed and
named in the banner, because telling the user that it has "not been read yet"
— and inviting them to press Scan — is a false promise: the host is not
answering from here, and another scan will not change that.
"""

import pytest


@pytest.fixture(autouse=True)
def clean_sources(db):
    """Each test starts from the same, known state of the source register."""
    from app.models import Source
    from app.services.utils import utcnow

    for source in db.query(Source).all():
        source.health = "ok"
        source.last_scan_at = utcnow()
        source.last_scan_stats = {"mode": "live", "notices": 10}
    db.commit()
    yield


def test_a_failed_read_is_recorded_as_a_failure(db):
    """The source is marked unhealthy and the reason is kept."""
    from app.models import Source
    from app.services import jobs

    source = db.query(Source).filter(Source.code == "ntdc").first()
    assert source is not None

    jobs.record_scan_failure(db, source, RuntimeError("could not read https://x/: timed out"))

    db.refresh(source)
    assert source.health == "error"
    assert source.last_scan_at is not None
    assert "could not read" in source.last_scan_stats["error"]


def test_the_startup_read_records_a_portal_it_could_not_reach(db, monkeypatch):
    """A portal that fails during the startup read is not left looking healthy."""
    from app import bootstrap
    from app.models import Source
    from app.services import jobs

    source = db.query(Source).filter(Source.code == "ppra_punjab").first()
    assert source is not None
    source.health = "ok"
    source.last_scan_at = None
    source.last_scan_stats = None
    db.commit()
    def explode(*args, **kwargs):
        raise RuntimeError(
            "could not read https://eproc.punjab.gov.pk/ActiveTenders.aspx: "
            "curl: (28) Connection timed out"
        )

    monkeypatch.setattr(jobs, "run_source", explode)

    bootstrap.read_within_budget(db, [source], budget=60)

    db.refresh(source)
    assert source.health == "error"
    assert source.last_scan_at is not None
    assert "Connection timed out" in source.last_scan_stats["error"]


def test_a_host_that_cannot_be_reached_is_told_apart_from_one_that_refused():
    """Pressing Scan again can help a refusal; it cannot help an unreachable host."""
    from app.connectors.http_client import is_connection_failure

    assert is_connection_failure("curl: (28) Connection timed out after 10002 milliseconds")
    assert is_connection_failure("could not connect to the host")
    assert is_connection_failure("No route to host")

    # A portal that answered and said no is a different matter.
    assert not is_connection_failure("HTTP 403 for https://ntdc.gov.pk/ntdc/api/tenders")


def test_the_dashboard_names_a_portal_that_cannot_be_reached(client, db, auth):
    """The banner's numbers come from the API, so the API has to name it."""
    from app.models import Source

    source = db.query(Source).filter(Source.code == "ppra_punjab").first()
    assert source is not None
    source.health = "error"
    source.last_scan_stats = {
        "error": "could not read https://eproc.punjab.gov.pk/ActiveTenders.aspx: "
                 "curl: (28) Connection timed out after 10002 milliseconds",
        "mode": "live",
    }
    db.commit()

    resp = client.get("/api/dashboard", headers=auth)
    assert resp.status_code == 200, resp.text
    feed = resp.json()["feed_status"]

    assert feed["portals_unreachable"] == 1
    assert "PPRA Punjab" in " ".join(feed["unreachable_names"])
    # A portal that could not be read is not also counted as merely unread.
    assert feed["portals_never_read"] == 0
    # And it is not counted as read either: the banner would otherwise say
    # "5 of 5 portals were read" and then say one could not be reached.
    assert feed["portals_read_live"] == feed["portals_total"] - 1


def test_a_portal_that_failed_for_another_reason_is_not_called_unreachable(client, db, auth):
    """A refusal is a failure, but it is not an unreachable host."""
    from app.models import Source

    source = db.query(Source).filter(Source.code == "ntdc").first()
    assert source is not None
    source.health = "error"
    source.last_scan_stats = {"error": "could not read https://ntdc.gov.pk/x: HTTP 403 for https://ntdc.gov.pk/x"}
    db.commit()

    resp = client.get("/api/dashboard", headers=auth)
    assert resp.status_code == 200, resp.text
    feed = resp.json()["feed_status"]

    assert feed["portals_failed"] >= 1
    assert feed["portals_unreachable"] == 0
