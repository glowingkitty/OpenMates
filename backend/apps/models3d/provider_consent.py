"""Versioned provider consent gate for Hi3D generation.

Hi3D currently licenses submitted inputs and outputs for model improvement, and
its public API docs do not provide verified per-task deletion. Product flows
must call this pure gate before sending any content to Hi3D.
"""

from __future__ import annotations


HI3D_CONSENT_VERSION = "2026-07-11"


class ProviderConsentRequired(PermissionError):
    """Raised when the current provider disclosure has not been accepted."""

    def __init__(self) -> None:
        super().__init__("Current Hi3D provider disclosure acceptance is required")
        self.provider_id = "hi3d"
        self.required_version = HI3D_CONSENT_VERSION


def require_current_hi3d_consent(
    *,
    accepted_version: str | None,
    current_version: str = HI3D_CONSENT_VERSION,
    withdrawn: bool = False,
) -> None:
    """Fail closed unless the current disclosure version is accepted."""
    if withdrawn or accepted_version != current_version:
        raise ProviderConsentRequired()
