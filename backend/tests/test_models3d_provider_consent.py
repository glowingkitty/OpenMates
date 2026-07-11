# backend/tests/test_models3d_provider_consent.py
#
# Contracts for the versioned Hi3D provider disclosure gate.
# User content must not leave OpenMates until the current disclosure is accepted.
# Withdrawal and stale consent both fail closed without exposing user content.

from __future__ import annotations

import pytest

from backend.apps.models3d.provider_consent import (
    HI3D_CONSENT_VERSION,
    ProviderConsentRequired,
    require_current_hi3d_consent,
)


@pytest.mark.parametrize("accepted_version", [None, "2025-01-01"])
def test_missing_or_stale_hi3d_consent_fails_closed(accepted_version: str | None) -> None:
    with pytest.raises(ProviderConsentRequired) as excinfo:
        require_current_hi3d_consent(accepted_version=accepted_version)

    assert excinfo.value.required_version == HI3D_CONSENT_VERSION
    assert excinfo.value.provider_id == "hi3d"


def test_current_hi3d_consent_passes() -> None:
    require_current_hi3d_consent(accepted_version=HI3D_CONSENT_VERSION)


def test_withdrawn_hi3d_consent_fails_closed() -> None:
    with pytest.raises(ProviderConsentRequired):
        require_current_hi3d_consent(
            accepted_version=HI3D_CONSENT_VERSION,
            withdrawn=True,
        )
