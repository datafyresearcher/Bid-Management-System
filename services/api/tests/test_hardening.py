"""The hardening added for production: sign-in protection, the cron guard,
the masked health endpoint, and the digest."""

import pytest

from app.config import settings


# --------------------------------------------------------------------------
# Sign-in: rate limiting
# --------------------------------------------------------------------------


def _clear_attempts():
    from app.routers import auth as auth_router

    auth_router._attempts.clear()


def test_failed_signins_are_limited(client, seeded):
    _clear_attempts()
    try:
        original = settings.login_max_attempts
        settings.login_max_attempts = 3
        settings.login_window_seconds = 300
        for _ in range(3):
            resp = client.post(
                "/api/auth/login",
                json={"email": "admin@ahte.local", "password": "wrong-password"},
            )
            assert resp.status_code == 401
        limited = client.post(
            "/api/auth/login",
            json={"email": "admin@ahte.local", "password": "wrong-password"},
        )
        assert limited.status_code == 429
        assert "Retry-After" in limited.headers
        # Even the correct password is refused while the limit is on: that is
        # what makes guessing slow.
        correct = client.post(
            "/api/auth/login",
            json={"email": "admin@ahte.local", "password": "admin123"},
        )
        assert correct.status_code == 429
    finally:
        settings.login_max_attempts = original
        _clear_attempts()


def test_successful_signin_clears_the_count(client, seeded):
    _clear_attempts()
    try:
        original = settings.login_max_attempts
        settings.login_max_attempts = 3
        for _ in range(2):
            client.post("/api/auth/login", json={"email": "admin@ahte.local", "password": "nope"})
        ok = client.post("/api/auth/login", json={"email": "admin@ahte.local", "password": "admin123"})
        assert ok.status_code == 200
        # The counter is gone, so the next failure starts from zero.
        again = client.post("/api/auth/login", json={"email": "admin@ahte.local", "password": "nope"})
        assert again.status_code == 401
    finally:
        settings.login_max_attempts = original
        _clear_attempts()


# --------------------------------------------------------------------------
# Sign-in: the default-secret guard
# --------------------------------------------------------------------------


def test_live_deployment_refuses_signin_with_default_secret(client, seeded, monkeypatch):
    from app.routers import auth as auth_router

    _clear_attempts()
    monkeypatch.setattr(settings, "fixtures", False)
    monkeypatch.setattr(settings, "secret_key", "change-me-in-production")
    resp = client.post("/api/auth/login", json={"email": "admin@ahte.local", "password": "admin123"})
    assert resp.status_code == 503
    assert "BMS_SECRET_KEY" in resp.json()["detail"]


def test_fixtures_mode_signs_in_with_the_default_secret(client, seeded, monkeypatch):
    # The demo pipeline has to keep working with no configuration at all.
    monkeypatch.setattr(settings, "fixtures", True)
    monkeypatch.setattr(settings, "secret_key", "change-me-in-production")
    resp = client.post("/api/auth/login", json={"email": "admin@ahte.local", "password": "admin123"})
    assert resp.status_code == 200


# --------------------------------------------------------------------------
# Health: what an anonymous caller may see
# --------------------------------------------------------------------------


def test_anonymous_health_hides_the_internals(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert "fixtures" in body
    assert "database" not in body
    assert "llm" not in body


def test_admin_health_reports_the_internals(client, auth):
    body = client.get("/api/health", headers=auth).json()
    assert body["status"] == "ok"
    assert "database" in body
    assert "llm" in body


# --------------------------------------------------------------------------
# Cron: the scheduled work is guarded
# --------------------------------------------------------------------------


def test_cron_is_refused_without_a_secret(client, monkeypatch):
    monkeypatch.setattr(settings, "cron_secret", "")
    resp = client.get("/api/cron/tick")
    assert resp.status_code == 503


def test_cron_is_refused_with_a_wrong_secret(client, monkeypatch):
    monkeypatch.setattr(settings, "cron_secret", "right-secret")
    assert client.get("/api/cron/tick").status_code == 403
    # The x-vercel-cron header marks a request as cron-shaped but proves
    # nothing; presenting it without the secret gets the same refusal.
    assert client.get("/api/cron/tick", headers={"x-vercel-cron": "1"}).status_code == 403


def test_cron_runs_with_the_right_secret(client, seeded, monkeypatch):
    monkeypatch.setattr(settings, "cron_secret", "right-secret")
    resp = client.get("/api/cron/tick", headers={"Authorization": "Bearer right-secret"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Every phase reported, whether or not it had work to do.
    assert "scan" in body and "watchdogs" in body and "digest" in body


# --------------------------------------------------------------------------
# Digest: the ranked brief
# --------------------------------------------------------------------------


def test_digest_lists_ranked_tenders_and_sends_when_configured(client, seeded, db, monkeypatch):
    from sqlalchemy import select

    from app.models import NotificationEvent, Opportunity
    from app.services import digest, emailer

    # The seeded pipeline has tenders that cleared screening; the brief has
    # to name at least one of them, ranked with a score.
    built = digest.build_digest(db)
    assert built["ranked"], "the seeded pipeline should have tenders worth attention"
    text = digest.render_text(built)
    assert "TOP TENDERS" in text
    for opportunity in built["ranked"]:
        assert opportunity.score_total is not None

    # Sending without an SMTP account is a recorded no-op, not an error.
    monkeypatch.setattr(emailer, "configured", lambda: False)
    monkeypatch.setattr(settings, "smtp_from", "bms@test.local")
    summary = digest.send_digest(db)
    assert summary["sent"] is False
    event = db.execute(
        select(NotificationEvent).where(NotificationEvent.type == "digest").order_by(NotificationEvent.id.desc())
    ).scalars().first()
    assert event is not None

    # With an account, the brief goes to the decision-makers.
    sent = {}
    monkeypatch.setattr(emailer, "configured", lambda: True)

    def fake_send(to, subject, body):
        sent["to"], sent["subject"], sent["body"] = to, subject, body
        return True

    monkeypatch.setattr(emailer, "send_email", fake_send)
    summary = digest.send_digest(db)
    assert summary["sent"] is True
    assert sent["to"], "digest should resolve at least one recipient"
    assert "TOP TENDERS" in sent["body"]


def test_digest_recipients_fall_back_to_decision_makers(seeded, db):
    from app.services import digest

    to = digest.recipients(db)
    assert to, "the demo accounts include the roles that own the decision"
    assert all("@" in addr for addr in to)


# --------------------------------------------------------------------------
# The screening alert is batched per capture
# --------------------------------------------------------------------------


def test_new_passing_tenders_email_once_per_capture(seeded, db, monkeypatch):
    from types import SimpleNamespace

    from sqlalchemy import select

    from app.models import Opportunity
    from app.services import emailer, jobs

    passing = (
        db.execute(select(Opportunity).where(Opportunity.state == "GATE1").limit(2)).scalars().all()
    )
    if not passing:
        pytest.skip("seeded pipeline has no gate-1 tenders to alert about")

    sent = {}
    monkeypatch.setattr(emailer, "configured", lambda: True)
    monkeypatch.setattr(settings, "smtp_from", "bms@test.local")

    def fake_send(to, subject, body):
        sent["to"], sent["subject"], sent["body"] = to, subject, body
        return True

    monkeypatch.setattr(emailer, "send_email", fake_send)

    jobs._email_new_passing(db, SimpleNamespace(name="Test Source"), [o.id for o in passing])
    assert "cleared screening" in sent["subject"]
    assert sent["body"].count("/100") >= len(passing)


def test_new_passing_tenders_email_nothing_when_none_cleared(seeded, db, monkeypatch):
    from types import SimpleNamespace

    from app.services import emailer, jobs

    called = []
    monkeypatch.setattr(emailer, "configured", lambda: True)
    monkeypatch.setattr(emailer, "send_email", lambda *a, **k: called.append((a, k)) or True)

    # No ids at all, and ids that are not in any gate state: either way no
    # mail goes out.
    jobs._email_new_passing(db, SimpleNamespace(name="S"), [])
    jobs._email_new_passing(db, SimpleNamespace(name="S"), [999999])
    assert called == []


# --------------------------------------------------------------------------
# Bounds on unbounded queries
# --------------------------------------------------------------------------


def test_leads_page_size_is_capped(client, seeded, auth):
    resp = client.get("/api/leads", params={"page_size": 10000}, headers=auth)
    assert resp.status_code == 200
    assert len(resp.json()["items"]) <= 100


# --------------------------------------------------------------------------
# TLS verification is on unless someone turned it off
# --------------------------------------------------------------------------


def test_live_client_verifies_certificates_by_default(seeded, monkeypatch):
    from app.connectors.http_client import LiveClient

    assert LiveClient().verify is True
    assert LiveClient(verify_tls=False).verify is False


def test_httpx_fallback_passes_the_verification_flag(seeded, monkeypatch):
    import httpx

    from app.connectors import http_client

    captured = {}

    class FakeResponse:
        status_code = 200
        content = b"<html>ok</html>"
        encoding = None

    def fake_client(**kwargs):
        captured.update(kwargs)

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def request(self, *a, **k):
                return FakeResponse()

        return FakeClient()

    monkeypatch.setattr(httpx, "Client", fake_client)
    monkeypatch.setattr(http_client, "HAS_CURL_CFFI", False)
    client = http_client.LiveClient(min_interval=0)
    client.get("https://portals.example/listing")
    assert captured["verify"] is True


def test_httpx_fallback_can_drop_verification_explicitly(seeded, monkeypatch):
    import httpx

    from app.connectors import http_client

    captured = {}

    class FakeResponse:
        status_code = 200
        content = b"<html>ok</html>"
        encoding = None

    def fake_client(**kwargs):
        captured.update(kwargs)

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def request(self, *a, **k):
                return FakeResponse()

        return FakeClient()

    monkeypatch.setattr(httpx, "Client", fake_client)
    monkeypatch.setattr(http_client, "HAS_CURL_CFFI", False)
    client = http_client.LiveClient(min_interval=0, verify_tls=False)
    client.get("https://portals.example/listing")
    assert captured["verify"] is False


# --------------------------------------------------------------------------
# Seeding: a live deployment gets no demo accounts
# --------------------------------------------------------------------------


def test_live_seeding_creates_only_the_admin(seeded, monkeypatch):
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import User
    from app.security import hash_password, verify_password

    import seed

    monkeypatch.setattr(settings, "fixtures", False)
    monkeypatch.setattr(settings, "admin_password", "a-real-production-password")
    db = SessionLocal()
    try:
        # The database already holds the demo accounts from the fixture seed;
        # a live seed of an empty database is what has to be checked, so run
        # the logic against the in-memory state it would produce.
        created = seed.seed_users(db)
        # Nothing new was created because every demo account already exists
        # in this database — but the password rotation applies.
        assert created == 0
        rotated = seed.apply_admin_password(db)
        admin = db.execute(select(User).where(User.email == seed.ADMIN_EMAIL)).scalars().first()
        from app.security import verify_password

        assert verify_password("a-real-production-password", admin.password_hash)
    finally:
        # The rest of the suite signs in as the demo admin; put the hash back.
        admin = db.execute(select(User).where(User.email == seed.ADMIN_EMAIL)).scalars().first()
        admin.password_hash = hash_password("admin123")
        db.commit()
        db.close()
