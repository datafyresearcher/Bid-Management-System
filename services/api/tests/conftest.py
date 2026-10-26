import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="bms-test-"))

os.environ["BMS_DATABASE_URL"] = f"sqlite:///{(TMP / 'test.db').as_posix()}"
os.environ["BMS_STORAGE_DIR"] = str(TMP / "storage")
os.environ["BMS_FIXTURES"] = "true"
os.environ["BMS_SECRET_KEY"] = "test-secret"
os.environ["BMS_SCHEDULER_ENABLED"] = "false"
# The suite is hermetic and must not call a hosted model. The gold set
# measures extraction fidelity against known answers, and a free-tier router
# that answers with whatever model it happens to pick — sometimes nothing at
# all — would make those assertions meaningless and the suite slow. The
# configured provider is exercised against the deployment, not here.
os.environ["BMS_LLM_PROVIDER"] = "mock"

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def seeded():
    import seed

    seed.main()
    return True


@pytest.fixture(scope="session")
def client(seeded):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db(seeded):
    from app.db import SessionLocal

    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="session")
def admin_token(client):
    resp = client.post("/api/auth/login", json={"email": "admin@ahte.local", "password": "admin123"})
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


@pytest.fixture()
def auth(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}
