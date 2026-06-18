# backend/core/api/app/services/connected_accounts_service.py
#
# Connected account storage contracts for provider-backed user accounts.
# The persistent row is intentionally encrypted/hash-only so Directus admins and
# cold database dumps cannot identify provider accounts or read token material.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar


PLAINTEXT_CONNECTED_ACCOUNT_FIELDS: set[str] = {
    "provider",
    "provider_type",
    "provider_name",
    "provider_email",
    "email",
    "account_email",
    "account_label",
    "display_name",
    "oauth_scopes",
    "scopes",
    "refresh_token",
    "access_token",
    "provider_account_id",
}


@dataclass(frozen=True)
class ConnectedAccountRow:
    """Validated encrypted connected account row ready for persistence."""

    id: str
    hashed_user_id: str
    encrypted_provider_type: str
    provider_type_hash: str
    encrypted_account_label: str
    encrypted_refresh_token_bundle: str
    encrypted_capabilities: str
    encrypted_app_permissions: str
    provider_account_id_hash: str | None = None
    encrypted_provider_account_display: str | None = None
    encrypted_account_directory_hint: str | None = None
    server_access_enabled: bool = False
    encrypted_server_access_ref: str | None = None

    REQUIRED_ENCRYPTED_FIELDS: ClassVar[tuple[str, ...]] = (
        "encrypted_provider_type",
        "encrypted_account_label",
        "encrypted_refresh_token_bundle",
        "encrypted_capabilities",
        "encrypted_app_permissions",
    )
    REQUIRED_HASH_FIELDS: ClassVar[tuple[str, ...]] = (
        "id",
        "hashed_user_id",
        "provider_type_hash",
    )

    @classmethod
    def validate_for_storage(cls, payload: dict[str, Any]) -> "ConnectedAccountRow":
        """Fail closed when a connected account row contains plaintext identity."""

        plaintext_fields = sorted(
            key for key in payload if key in PLAINTEXT_CONNECTED_ACCOUNT_FIELDS
        )
        if plaintext_fields:
            raise ValueError(
                "connected account payload contains plaintext provider/account fields: "
                + ", ".join(plaintext_fields)
            )

        missing = [
            field
            for field in (*cls.REQUIRED_HASH_FIELDS, *cls.REQUIRED_ENCRYPTED_FIELDS)
            if not payload.get(field)
        ]
        if missing:
            raise ValueError(
                "connected account payload missing required encrypted/hash fields: "
                + ", ".join(missing)
            )

        server_access_enabled = bool(payload.get("server_access_enabled", False))
        if server_access_enabled and not payload.get("encrypted_server_access_ref"):
            raise ValueError(
                "server_access_enabled requires encrypted_server_access_ref"
            )

        return cls(
            id=str(payload["id"]),
            hashed_user_id=str(payload["hashed_user_id"]),
            encrypted_provider_type=str(payload["encrypted_provider_type"]),
            provider_type_hash=str(payload["provider_type_hash"]),
            encrypted_account_label=str(payload["encrypted_account_label"]),
            encrypted_refresh_token_bundle=str(
                payload["encrypted_refresh_token_bundle"]
            ),
            encrypted_capabilities=str(payload["encrypted_capabilities"]),
            encrypted_app_permissions=str(payload["encrypted_app_permissions"]),
            provider_account_id_hash=_optional_str(payload.get("provider_account_id_hash")),
            encrypted_provider_account_display=_optional_str(
                payload.get("encrypted_provider_account_display")
            ),
            encrypted_account_directory_hint=_optional_str(
                payload.get("encrypted_account_directory_hint")
            ),
            server_access_enabled=server_access_enabled,
            encrypted_server_access_ref=_optional_str(
                payload.get("encrypted_server_access_ref")
            ),
        )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
