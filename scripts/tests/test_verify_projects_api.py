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
