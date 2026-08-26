"""Service-boundary tests for the independent control-plane process.

The service must start without product configuration, require its dedicated
database URL for readiness, and expose no generated public API documentation.
These checks guard against accidental product-runtime coupling during buildout.
"""

# contract-test-file: infrastructure

from fastapi.testclient import TestClient

from backend.engineering_control_plane.config import Settings
from backend.engineering_control_plane.main import app


def test_settings_do_not_fall_back_to_product_database(monkeypatch) -> None:
    monkeypatch.delenv("ENGINEERING_CONTROL_PLANE_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://product-database")

    try:
        Settings.from_environment()
    except RuntimeError as exc:
        assert str(exc) == "ENGINEERING_CONTROL_PLANE_DATABASE_URL is required"
    else:
        raise AssertionError("product DATABASE_URL must not satisfy control-plane configuration")


def test_liveness_is_independent_and_readiness_fails_closed(monkeypatch) -> None:
    monkeypatch.delenv("ENGINEERING_CONTROL_PLANE_DATABASE_URL", raising=False)
    client = TestClient(app)

    assert client.get("/health/live").json() == {"status": "alive"}
    readiness = client.get("/health/ready")
    assert readiness.status_code == 503
    assert readiness.json() == {"detail": "control_plane_not_ready"}
    assert client.get("/openapi.json").status_code == 404
