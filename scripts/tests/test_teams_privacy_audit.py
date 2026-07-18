"""Deterministic privacy audit for Teams V1 Directus schema.

Teams store encrypted user-visible metadata and hashed join identifiers. This
guard prevents accidental raw user/team/email fields from entering the backend
schema as the feature expands.
"""

from pathlib import Path

import yaml


SCHEMA_PATH = Path(__file__).resolve().parents[2] / "backend/core/directus/schemas/teams.yml"
SENSITIVE_CLEAR_FIELD_FRAGMENTS = ("email", "display_name", "name", "description", "billing_profile")
ALLOWED_CLEAR_FIELDS = {
    "encrypted_name",
    "encrypted_description",
    "encrypted_billing_profile",
    "encrypted_recipient_hint",
}


def _teams_schema() -> dict:
    return yaml.safe_load(SCHEMA_PATH.read_text())


def test_team_schema_uses_hashes_for_join_identifiers() -> None:
    schema = _teams_schema()

    assert "hashed_team_id" in schema["teams"]["fields"]
    assert "created_by_user_hash" in schema["teams"]["fields"]
    assert "hashed_team_id" in schema["team_memberships"]["fields"]
    assert "hashed_user_id" in schema["team_memberships"]["fields"]
    assert "hashed_team_id" in schema["team_key_wrappers"]["fields"]
    assert "hashed_user_id" in schema["team_key_wrappers"]["fields"]


def test_team_schema_keeps_user_visible_or_billing_metadata_encrypted() -> None:
    schema = _teams_schema()
    violations: list[str] = []

    for collection, config in schema.items():
        for field in config.get("fields", {}):
            if field in ALLOWED_CLEAR_FIELDS:
                continue
            if any(fragment in field for fragment in SENSITIVE_CLEAR_FIELD_FRAGMENTS) and not (
                field.startswith("encrypted_") or field.startswith("hashed_")
            ):
                violations.append(f"{collection}.{field}")

    assert violations == []


def test_team_schema_does_not_store_raw_member_or_invite_identity_fields() -> None:
    schema = _teams_schema()
    forbidden_fields = {
        "user_id",
        "member_user_id",
        "owner_user_id",
        "recipient_email",
        "recipient_user_id",
        "inviter_user_id",
    }
    violations = [f"{collection}.{field}" for collection, config in schema.items() for field in config.get("fields", {}) if field in forbidden_fields]

    assert violations == []
