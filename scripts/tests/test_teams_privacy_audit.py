"""Deterministic privacy audit for Teams V1 Directus schema.

Teams store encrypted user-visible metadata and hashed join identifiers. This
guard prevents accidental raw user/team/email fields from entering the backend
schema as the feature expands.
"""

from pathlib import Path

import yaml


SCHEMA_PATH = Path(__file__).resolve().parents[2] / "backend/core/directus/schemas/teams.yml"
SENSITIVE_CLEAR_FIELD_FRAGMENTS = ("email", "display_name", "name", "description", "billing_profile", "icon", "background_color")
ALLOWED_CLEAR_FIELDS = {
    "encrypted_name",
    "encrypted_description",
    "encrypted_billing_profile",
    "encrypted_profile_image_metadata",
    "encrypted_recipient_hint",
    "profile_image_s3_key",
    "profile_image_vault_key_id",
    "profile_image_aes_nonce",
    "profile_image_updated_at",
}


def _teams_schema() -> dict:
    return yaml.safe_load(SCHEMA_PATH.read_text())


# contract-test: supporting surface=rest_api assertions=teams.lifecycle.encrypted-profiled,teams.membership.role-gated
def test_team_schema_uses_hashes_for_join_identifiers() -> None:
    schema = _teams_schema()

    assert "hashed_team_id" in schema["teams"]["fields"]
    assert "created_by_user_hash" in schema["teams"]["fields"]
    assert "hashed_team_id" in schema["team_memberships"]["fields"]
    assert "hashed_user_id" in schema["team_memberships"]["fields"]
    assert "hashed_team_id" in schema["team_key_wrappers"]["fields"]
    assert "hashed_user_id" in schema["team_key_wrappers"]["fields"]


# contract-test: direct surface=rest_api assertions=teams.lifecycle.encrypted-profiled,teams.chat-billing.team-credit-boundary
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


# contract-test: direct surface=rest_api assertions=teams.lifecycle.encrypted-profiled,teams.profile-image.safe-parity
def test_team_schema_requires_encrypted_profile_image_metadata() -> None:
    schema = _teams_schema()
    team_fields = schema["teams"]["fields"]

    assert "encrypted_profile_image_metadata" in team_fields
    assert team_fields["encrypted_profile_image_metadata"]["type"] == "text"
    assert not team_fields["encrypted_profile_image_metadata"].get("nullable", False)
    assert "profile_image_s3_key" in team_fields
    assert "encrypted_profile_image_aes_key" in team_fields
    assert "profile_image_aes_nonce" in team_fields
    assert "profile_image_vault_key_id" in team_fields


# contract-test: direct surface=rest_api assertions=teams.lifecycle.encrypted-profiled,teams.profile-image.safe-parity
def test_team_schema_does_not_store_plain_generated_avatar_details() -> None:
    schema = _teams_schema()
    forbidden_fields = {
        "icon_name",
        "profile_icon_name",
        "profile_image_icon_name",
        "background_color",
        "profile_background_color",
        "profile_image_background_color",
    }
    violations = [field for field in schema["teams"].get("fields", {}) if field in forbidden_fields]

    assert violations == []


# contract-test: direct surface=rest_api assertions=teams.lifecycle.encrypted-profiled,teams.invites.fragment-key-web-flow,teams.membership.role-gated
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
