#!/usr/bin/env python3
"""Unit tests for the direct REST Projects verifier.

These tests cover payload context, stable parsing, and safety classification.
They import the verifier without invoking login, subprocesses, or network calls.
Run: python3 -m pytest scripts/tests/test_verify_projects_api.py.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "verify_projects_api.py"


def load_verifier():
    spec = importlib.util.spec_from_file_location("verify_projects_api", MODULE_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["verify_projects_api"] = module
    spec.loader.exec_module(module)
    return module


def test_project_payload_uses_exact_personal_or_team_key_context() -> None:
    verifier = load_verifier()

    personal = verifier.project_payload("personal-project", timestamp=10)
    team = verifier.project_payload("team-project", team_id="team-1", timestamp=10)

    assert personal["encrypted_project_key"]
    assert personal["key_wrappers"] == []
    assert team["encrypted_project_key"] is None
    assert team["key_wrappers"] == [
        {
            "key_type": "team",
            "hashed_team_id": verifier.hashlib.sha256(b"team-1").hexdigest(),
            "team_key_epoch": 1,
            "encrypted_project_key": team["key_wrappers"][0]["encrypted_project_key"],
            "wrapper_version": 1,
            "created_at": 10,
        }
    ]


def test_fixture_payloads_use_unix_seconds_consistently(monkeypatch: pytest.MonkeyPatch) -> None:
    verifier = load_verifier()
    monkeypatch.setattr(verifier.time, "time", lambda: 1_700_000_000.987)

    project = verifier.project_payload("project-1", team_id="team-1")
    source = verifier.source_payload("source-1")
    team = verifier.team_payload("team-1")

    assert project["created_at"] == 1_700_000_000
    assert project["updated_at"] == 1_700_000_000
    assert project["last_opened_at"] == 1_700_000_000
    assert project["key_wrappers"][0]["created_at"] == 1_700_000_000
    assert source["created_at"] == 1_700_000_000
    assert source["updated_at"] == 1_700_000_000
    assert team["created_at"] == 1_700_000_000
    assert "time() * 1000" not in MODULE_PATH.read_text(encoding="utf-8")


def test_failed_team_creation_does_not_attempt_team_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    verifier = load_verifier()
    requests: list[tuple[str, str]] = []

    class FakeRestClient:
        def __init__(self, api_url: str, headers: dict[str, str] | None = None) -> None:
            self.authenticated = headers is not None

        def request(self, method: str, path: str, **kwargs) -> object:
            requests.append((method, path))
            if not self.authenticated:
                return verifier.ApiResponse(401, {})
            if method == "GET" and path == "/v1/projects":
                return verifier.ApiResponse(403, {"detail": "TEAM_PERMISSION_DENIED"})
            if method == "POST" and path == "/v1/teams":
                return verifier.ApiResponse(500, {})
            raise AssertionError(f"unexpected request: {method} {path}")

    monkeypatch.setattr(verifier, "RestClient", FakeRestClient)

    report, exit_code = verifier.run_verification("https://api.dev.openmates.org", {"Cookie": "test"})

    assert exit_code == 1
    assert report["scenarios"]["team_fixture_create"]["code"] == "expected_http_200_got_500"
    assert report["cleanup"] == {"status": "passed", "failed_resources": []}
    assert not any(method == "DELETE" and path.startswith("/v1/teams/") for method, path in requests)


def test_project_and_source_response_helpers_fail_with_stable_codes() -> None:
    verifier = load_verifier()

    assert verifier.project_ids({"projects": [{"project_id": "one"}, {"id": "internal"}]}) == {"one"}
    assert verifier.source_records({"sources": [{"source_id": "source"}, "ignored"]}) == [{"source_id": "source"}]
    with pytest.raises(verifier.VerificationFailure, match="projects_list_missing"):
        verifier.project_ids({"projects": "private-invalid-value"})
    with pytest.raises(verifier.VerificationFailure, match="sources_list_missing"):
        verifier.source_records({})


def test_api_url_validation_refuses_credentials_and_production() -> None:
    verifier = load_verifier()

    assert verifier.validate_api_url("https://api.dev.openmates.org/") == "https://api.dev.openmates.org"
    with pytest.raises(verifier.VerificationFailure, match="invalid_api_url"):
        verifier.validate_api_url("https://user:secret@example.test")
    with pytest.raises(verifier.VerificationFailure, match="production_target_refused"):
        verifier.validate_api_url("https://api.openmates.org")


def test_report_classification_declares_encryption_and_access_boundaries() -> None:
    verifier = load_verifier()

    result = verifier.classification()

    assert result["access_model"] == "first_party_client_only"
    assert result["data_boundary"] == "opaque_client_side_encrypted_metadata_only"
    assert result["decrypted_plaintext"] == "none"
    assert result["credit_budget"] == "none"


def test_live_verifier_uses_exact_delete_identifiers_without_boolean_compatibility() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")

    assert '"confirmation_project_id": project_id' in source
    assert '"confirmation_source_id": source_id' in source
    assert '"confirmed": "true"' not in source
    assert "SOURCE_REMOVAL_CONFIRMATION_REQUIRED" in source
    assert "SOURCE_REMOVAL_CONFIRMATION_MISMATCH" in source
