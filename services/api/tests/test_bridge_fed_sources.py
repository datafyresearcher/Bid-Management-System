"""A portal the cloud cannot reach is fed by the bridge, and never read live.

PPRA Punjab and WAPDA refuse connections from datacenter networks as a class
— no scan from any cloud region can read them. The bid desk's own machine
captures their listings and hands the pages to POST /api/sources/capture.
Every cloud-side read path must therefore leave these sources alone: a live
attempt cannot succeed, and recording its failure would stamp a healthy,
bridge-fed source as error and hide the bridge's work.
"""

import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def bridge_sources(db):
    """Both bridge-fed portals start healthy, fed by a fresh bridge capture."""
    from app.models import Source
    from app.services.utils import utcnow

    for code in ("ppra_punjab", "wapda"):
        source = db.query(Source).filter(Source.code == code).first()
        assert source is not None, f"{code} missing from the registry"
        source.health = "ok"
        source.last_scan_at = utcnow()
        source.last_scan_stats = {"mode": "bridge", "notices": 10, "new": 0}
    db.commit()
    yield


@pytest.fixture()
def live_mode(monkeypatch):
    """The suite runs in demo mode; the bridge only matters when reading live."""
    monkeypatch.setattr(settings, "fixtures", False)


def test_run_scan_leaves_bridge_fed_portals_alone(db, live_mode, monkeypatch):
    """The scheduled scan neither reads them nor touches their recorded state."""
    from app.models import Source
    from app.services import jobs

    def fake_run_source(db, source, **kwargs):
        if source.code in ("ppra_punjab", "wapda"):
            raise AssertionError("a bridge-fed portal must never be read live")
        return {"notices": 0, "new": 0, "scored": 0}

    monkeypatch.setattr(jobs, "run_source", fake_run_source)

    stats = jobs.run_scan(db)

    assert stats["skipped"] >= 2
    for code in ("ppra_punjab", "wapda"):
        source = db.query(Source).filter(Source.code == code).first()
        db.refresh(source)
        assert source.health == "ok"
        assert source.last_scan_stats["mode"] == "bridge"


def test_in_demo_mode_the_fixtures_still_fill_the_database(db, monkeypatch):
    """The demo pipeline seeds from the saved captures, bridge or no bridge."""
    from app.services import jobs

    read = []
    monkeypatch.setattr(jobs, "run_source", lambda db, source, **kw: read.append(source.code) or {"notices": 0, "new": 0, "scored": 0})

    jobs.run_scan(db)

    assert "ppra_punjab" in read


def test_the_scan_button_refuses_a_bridge_fed_portal(client, db, auth):
    """Asking the cloud to scan one answers with why, and records no failure."""
    from app.models import Source

    source = db.query(Source).filter(Source.code == "ppra_punjab").first()
    resp = client.post(f"/api/sources/{source.id}/scan", headers=auth)

    assert resp.status_code == 409, resp.text
    assert "capture bridge" in resp.json()["detail"]

    db.refresh(source)
    assert source.health == "ok"
    assert source.last_scan_stats["mode"] == "bridge"


def test_the_startup_read_skips_bridge_fed_portals(db, live_mode, monkeypatch):
    """A cold start does not spend its budget on hosts that cannot answer."""
    from app import bootstrap
    from app.models import Source
    from app.services import jobs

    read = []

    def fake_run_source(db, source, **kwargs):
        read.append(source.code)
        return {"notices": 0, "new": 0, "scored": 0}

    monkeypatch.setattr(jobs, "run_source", fake_run_source)

    sources = db.query(Source).filter(Source.type == "portal").all()
    bootstrap.read_within_budget(db, sources, budget=60)

    assert "ppra_punjab" not in read
    assert "wapda" not in read
    assert read, "the cloud-readable portals were still read"
    for code in ("ppra_punjab", "wapda"):
        source = db.query(Source).filter(Source.code == code).first()
        db.refresh(source)
        assert source.health == "ok"
        assert source.last_scan_stats["mode"] == "bridge"


def test_the_dashboard_counts_what_the_bridge_feeds(client, db, auth):
    """Bridge-fed portals are neither 'read directly' nor failing."""
    from app.models import Source

    resp = client.get("/api/dashboard", headers=auth)
    assert resp.status_code == 200, resp.text
    feed = resp.json()["feed_status"]

    assert feed["portals_bridge"] == 2
    names = " ".join(feed["bridge_names"])
    assert "PPRA Punjab" in names
    assert "WAPDA" in names
    read_ids = feed["portals_read_live"] + feed["portals_bridge"] + feed["portals_failed"] + feed["portals_never_read"]
    assert read_ids <= feed["portals_total"]

    # The source register says how each portal is read, so the UI can offer
    # the bridge's name instead of a Scan button that could never succeed.
    sources = client.get("/api/sources", headers=auth).json()
    by_code = {s["code"]: s for s in sources}
    assert by_code["ppra_punjab"]["read_via"] == "bridge"
    assert by_code["wapda"]["read_via"] == "bridge"
    assert by_code["ntdc"]["read_via"] == "cloud"


def test_a_bridge_portal_that_has_gone_quiet_is_still_flagged(client, db, auth):
    """A stale error on a bridge-fed portal still reaches the banner."""
    from app.models import Source

    source = db.query(Source).filter(Source.code == "wapda").first()
    source.health = "error"
    source.last_scan_stats = {
        "error": "could not read https://wapda.gov.pk/wapda-tenders/: "
                 "curl: (35) Recv failure: Connection was reset",
        "mode": "live",
    }
    db.commit()

    resp = client.get("/api/dashboard", headers=auth)
    assert resp.status_code == 200, resp.text
    feed = resp.json()["feed_status"]

    assert feed["portals_bridge"] == 1
    assert feed["portals_failed"] >= 1
    assert "WAPDA" in " ".join(feed["failed_names"])
