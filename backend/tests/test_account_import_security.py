# backend/tests/test_account_import_security.py
#
# Focused security contracts for account-import route shells.
# Account imports may transiently scan plaintext client-provided exports, so the
# route layer must keep tight auth, rate-limit, and payload-size boundaries.

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.core.api.app.routes import account_imports
from backend.core.api.app.routes.auth_routes.auth_dependencies import _enforce_api_key_route_policy


ACCOUNT_IMPORTS_PATH = Path(__file__).resolve().parents[2] / "backend/core/api/app/routes/account_imports.py"


def _request(method: str, path: str) -> SimpleNamespace:
    return SimpleNamespace(method=method, url=SimpleNamespace(path=path))


def test_account_import_routes_have_explicit_slowapi_limits() -> None:
    lines = ACCOUNT_IMPORTS_PATH.read_text(encoding="utf-8").splitlines()
    missing_limits: list[str] = []

    for index, line in enumerate(lines):
        if not line.startswith("@router."):
            continue
        next_non_empty = next((candidate.strip() for candidate in lines[index + 1:] if candidate.strip()), "")
        if not next_non_empty.startswith("@limiter.limit("):
            missing_limits.append(f"line {index + 1}: {line.strip()}")

    assert missing_limits == []


def test_account_import_api_key_access_requires_import_scope() -> None:
    missing_scope_key = {
        "api_key_metadata": {
            "full_access": False,
            "scopes": {"account": []},
        }
    }
    scoped_key = {
        "api_key_metadata": {
            "full_access": False,
            "scopes": {"account": ["account:import"]},
        }
    }

    with pytest.raises(HTTPException) as exc:
        _enforce_api_key_route_policy(_request("POST", "/v1/account-imports/import-1/scan"), missing_scope_key)

    assert exc.value.status_code == 403
    assert exc.value.detail == {"error": "missing_scope", "missing_scope": "account:import"}

    _enforce_api_key_route_policy(_request("POST", "/v1/account-imports/import-1/scan"), scoped_key)


def test_account_import_plaintext_and_completion_payloads_are_size_limited() -> None:
    with pytest.raises(ValidationError):
        account_imports.ScanImportRequest(
            chats=[{} for _ in range(account_imports.MAX_IMPORT_SCAN_CHATS + 1)]
        )

    with pytest.raises(ValidationError):
        account_imports.PersistEncryptedImportRequest(
            chats=[{} for _ in range(account_imports.MAX_IMPORT_PERSIST_CHATS + 1)]
        )

    with pytest.raises(ValidationError):
        account_imports.CompleteImportRequest(
            imported_chat_ids=[f"chat-{index}" for index in range(account_imports.MAX_IMPORT_PERSIST_CHATS + 1)]
        )


def test_plaintext_scan_route_does_not_write_client_chats_to_request_state() -> None:
    source = ACCOUNT_IMPORTS_PATH.read_text(encoding="utf-8")

    assert "request.app.state.account_import_jobs[" not in source
    assert "payload.chats" in source
    assert "scan_selected_chats" in source
