"""Account Export API security and retention contract tests.

Purpose: keep the `/v1/account-exports` route approved-device and scoped.
Architecture: docs/specs/account-export-v1/spec.yml and regional cold storage.
Security: limited API-key callers need an approved device and explicit account scope.
Privacy: export routes expose encrypted user data and must be rate limited.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.core.api.app.routes.auth_routes.auth_dependencies import _enforce_api_key_route_policy


ACCOUNT_EXPORTS_PATH = Path(__file__).resolve().parents[2] / "backend/core/api/app/routes/account_exports.py"
PERSISTENCE_TASKS_PATH = Path(__file__).resolve().parents[2] / "backend/core/api/app/tasks/persistence_tasks.py"
CELERY_CONFIG_PATH = Path(__file__).resolve().parents[2] / "backend/core/api/app/tasks/celery_config.py"


def _request(method: str, path: str, headers: dict[str, str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(method=method, url=SimpleNamespace(path=path), headers=headers or {})


# contract-test: direct surface=rest_api assertions=sdk.auth.approved-api-key-device,storage.privacy.ciphertext-boundary
def test_account_export_api_key_access_requires_approved_device_and_export_scope() -> None:
    scoped_key = {
        "device_hash": "approved-sdk-device",
        "api_key_metadata": {
            "full_access": False,
            "scopes": {"account": ["account:export"]},
        }
    }
    missing_scope_key = {
        "device_hash": "approved-sdk-device",
        "api_key_metadata": {
            "full_access": False,
            "scopes": {"account": []},
        }
    }
    full_access_without_export_scope = {
        "device_hash": "approved-sdk-device",
        "api_key_metadata": {"full_access": True, "scopes": {}},
    }

    with pytest.raises(HTTPException) as generic_exc:
        _enforce_api_key_route_policy(
            _request("GET", "/v1/account-exports/export-1", {}),
            {**scoped_key, "device_hash": None},
        )

    assert generic_exc.value.status_code == 403
    assert generic_exc.value.detail == {"error": "developer_api_access_not_classified"}

    with pytest.raises(HTTPException) as scope_exc:
        _enforce_api_key_route_policy(
            _request("POST", "/v1/account-exports"),
            missing_scope_key,
        )

    assert scope_exc.value.status_code == 403
    assert scope_exc.value.detail == {"error": "missing_scope", "missing_scope": "account:export"}

    _enforce_api_key_route_policy(_request("POST", "/v1/account-exports"), full_access_without_export_scope)
    _enforce_api_key_route_policy(_request("GET", "/v1/account-exports/export-1"), scoped_key)
    _enforce_api_key_route_policy(_request("GET", "/v1/account-exports/export-1", {"x-openmates-sdk": "cli"}), scoped_key)


# contract-test: supporting surface=rest_api assertions=storage.export.persisted-bounded-complete,storage.privacy.ciphertext-boundary
def test_account_export_routes_have_explicit_slowapi_limits() -> None:
    lines = ACCOUNT_EXPORTS_PATH.read_text(encoding="utf-8").splitlines()
    missing_limits: list[str] = []

    for index, line in enumerate(lines):
        if not line.startswith("@router."):
            continue
        next_non_empty = next((candidate.strip() for candidate in lines[index + 1 :] if candidate.strip()), "")
        if not next_non_empty.startswith("@limiter.limit("):
            missing_limits.append(f"line {index + 1}: {line.strip()}")

    assert missing_limits == []
    start_route_index = next(index for index, line in enumerate(lines) if line.startswith('@router.post(""'))
    assert lines[start_route_index + 1] == '@limiter.limit("5/hour")'


# contract-test: supporting surface=rest_api assertions=storage.export.persisted-bounded-complete,storage.privacy.ciphertext-boundary
def test_expired_account_export_cleanup_is_scheduled_on_persistence_queue() -> None:
    persistence_source = PERSISTENCE_TASKS_PATH.read_text(encoding="utf-8")
    celery_source = CELERY_CONFIG_PATH.read_text(encoding="utf-8")

    assert "def cleanup_expired_account_exports" in persistence_source
    assert "app.tasks.persistence_tasks.cleanup_expired_account_exports" in celery_source
    assert "'cleanup-expired-account-exports'" in celery_source
