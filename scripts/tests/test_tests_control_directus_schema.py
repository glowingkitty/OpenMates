#!/usr/bin/env python3
"""
Regression tests for Directus test-control-plane schemas.

These tests keep the durable test coordination collections aligned with the
script adapter contract without requiring a live Directus container.
"""

from __future__ import annotations

from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = PROJECT_ROOT / "backend" / "core" / "directus" / "schemas"


REQUIRED_SCHEMAS = {
    "test_catalog.yml": {"test_key", "suite", "test_name", "file_path", "verification_command", "metadata"},
    "test_runs.yml": {"run_key", "source", "external_run_id", "status", "requested_tests", "summary"},
    "test_results.yml": {"result_key", "run_key", "test_key", "status", "error_summary", "metadata"},
    "test_current_state.yml": {"test_key", "stable_status", "stable_result_key", "active_status", "active_run_key", "triage_group_id"},
    "test_claims.yml": {"claim_key", "group_id", "campaign_key", "debug_group_key", "status", "session_id", "worker_id", "expires_at_unix", "completed_commit"},
    "test_debug_campaigns.yml": {
        "campaign_key", "status", "session_id", "source_run_keys", "selected_test_keys",
        "selected_group_keys", "current_group_key", "completion_policy", "blocker",
        "created_at", "updated_at", "completed_at",
    },
    "test_debug_groups.yml": {
        "group_key", "campaign_key", "triage_group_id", "parent_group_key", "status",
        "member_test_keys", "observed_failure", "expected_behavior", "acceptance_criteria",
        "root_cause", "attempts", "red_evidence", "green_evidence", "blocker",
        "metadata", "verification_command", "selected_at_unix", "updated_at",
    },
}


def load_schema(name: str) -> dict:
    path = SCHEMA_DIR / name
    assert path.is_file(), f"missing Directus schema: {path}"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_test_control_plane_schemas_define_required_fields():
    for filename, required_fields in REQUIRED_SCHEMAS.items():
        data = load_schema(filename)
        collection_name = filename.removesuffix(".yml")
        collection = data[collection_name]
        fields = collection["fields"]
        assert required_fields <= set(fields), f"{filename} missing {required_fields - set(fields)}"


def test_test_control_plane_schemas_have_unique_upsert_keys():
    unique_fields = {
        "test_catalog.yml": "test_key",
        "test_runs.yml": "run_key",
        "test_results.yml": "result_key",
        "test_current_state.yml": "test_key",
        "test_claims.yml": "claim_key",
        "test_debug_campaigns.yml": "campaign_key",
        "test_debug_groups.yml": "group_key",
    }
    for filename, field_name in unique_fields.items():
        fields = load_schema(filename)[filename.removesuffix(".yml")]["fields"]
        field = fields[field_name]
        assert field.get("unique") is True or field.get("options", {}).get("unique") is True
