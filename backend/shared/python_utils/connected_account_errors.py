# backend/shared/python_utils/connected_account_errors.py
#
# Provider-neutral errors for connected-account execution.
# Provider adapters raise subclasses so the chat pipeline and the SDK route can
# tell "the user must reconnect" apart from "the provider is temporarily down"
# without importing every provider module.
#
# Spec: specifications/architecture/connected-accounts/specification.yml

from __future__ import annotations

# OAuth token-endpoint error codes that mean the stored grant is no longer usable.
RECONNECT_OAUTH_ERRORS = frozenset({"invalid_grant", "unauthorized_client", "invalid_client"})


class ConnectedAccountTokenExchangeError(RuntimeError):
    """Sanitized refresh-token exchange failure from any provider adapter.

    ``reconnect_required`` is True when the provider rejected the stored grant
    (revoked, expired, or issued to another client). Callers then ask the user to
    reconnect instead of retrying or asking for chat permission again.
    """

    def __init__(
        self,
        message: str,
        *,
        provider_id: str,
        status_code: int | None = None,
        provider_error: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider_id = provider_id
        self.status_code = status_code
        self.provider_error = provider_error

    @property
    def reconnect_required(self) -> bool:
        if self.provider_error and self.provider_error in RECONNECT_OAUTH_ERRORS:
            return True
        return self.status_code == 401


def connected_account_exchange_failure_payload(
    error: ConnectedAccountTokenExchangeError, *, app_id: str, skill_id: str,
) -> dict[str, object]:
    """Tool-result payload the assistant can explain without provider internals."""

    if error.reconnect_required:
        return {
            "status": "reconnect_required",
            "error": "connected_account_reconnect_required",
            "provider_id": error.provider_id,
            "reason": (
                "The connected account no longer accepts OpenMates' access. "
                "Ask the user to reconnect it in Settings > Apps."
            ),
            "app_id": app_id,
            "skill_id": skill_id,
        }
    return {
        "status": "provider_unavailable",
        "error": "provider_token_exchange_failed",
        "provider_id": error.provider_id,
        "reason": "The provider could not be reached to authorize this action. Try again later.",
        "app_id": app_id,
        "skill_id": skill_id,
    }
