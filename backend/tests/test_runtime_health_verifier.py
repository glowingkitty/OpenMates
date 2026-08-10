"""Runtime health verifier contracts.

These tests define the no-spend, fail-closed server verification boundary used
after CLI-managed updates. The verifier is internal host tooling: it must select
self-host mode before billing secret access and finish within one global budget.
Spec: docs/specs/post-update-runtime-health-alerting/spec.yml.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.core.api.app.utils.server_mode import resolve_runtime_deployment_mode
from backend.scripts.runtime_health_verifier import (
    GLOBAL_DEADLINE_SECONDS,
    CheckDefinition,
    build_check_inventory,
    execute_checks,
)


@pytest.mark.parametrize(
    ("env", "status"),
    [
        ({}, "missing"),
        ({"OPENMATES_DEPLOYMENT_MODE": "cloud"}, "malformed"),
        ({"OPENMATES_DEPLOYMENT_MODE": "OFFICIAL_CLOUD"}, "malformed"),
        (
            {
                "OPENMATES_DEPLOYMENT_MODE": "official_cloud",
                "OPENMATES_CLOUD_OVERLAY_ENABLED": "false",
            },
            "conflicting",
        ),
    ],
)
def test_unknown_or_conflicting_mode_fails_closed(env: dict[str, str], status: str) -> None:
    result = resolve_runtime_deployment_mode(
        env=env,
        allowed_domain="example.org",
        hosting_domain="api.example.org",
        overlay_importable=True,
    )

    assert result.effective_mode == "self_host"
    assert result.status == status
    assert result.billing_enabled is False


def test_official_cloud_requires_all_local_witnesses() -> None:
    result = resolve_runtime_deployment_mode(
        env={
            "OPENMATES_DEPLOYMENT_MODE": "official_cloud",
            "OPENMATES_CLOUD_OVERLAY_ENABLED": "true",
            "OPENMATES_CLOUD_OVERLAY_PACKAGE": "OpenMatesCloud",
            "SERVER_ENVIRONMENT": "production",
        },
        allowed_domain="example.org",
        hosting_domain="api.example.org",
        overlay_importable=True,
    )

    assert result.effective_mode == "official_cloud"
    assert result.environment == "production"
    assert result.status == "valid"
    assert result.billing_enabled is True


def test_self_host_inventory_never_contains_billing_checks() -> None:
    mode = resolve_runtime_deployment_mode(
        env={"OPENMATES_DEPLOYMENT_MODE": "self_host"},
        allowed_domain=None,
        hosting_domain=None,
        overlay_importable=False,
    )

    ids = {check.id for check in build_check_inventory("core", mode)}

    assert "core.chat_plumbing" in ids
    assert not any(check_id.startswith("billing.") for check_id in ids)


def test_role_inventory_is_stable_and_bounded() -> None:
    mode = resolve_runtime_deployment_mode(
        env={"OPENMATES_DEPLOYMENT_MODE": "self_host"},
        allowed_domain=None,
        hosting_domain=None,
        overlay_importable=False,
    )

    expected = {
        "core": {"compose.required_services", "http.role_health", "core.database", "core.cache", "core.vault", "core.worker_queue", "core.scheduler_freshness", "core.chat_plumbing"},
        "upload": {"compose.required_services", "http.role_health", "core.vault", "upload.antivirus"},
        "preview": {"compose.required_services", "http.role_health", "preview.renderer"},
    }

    for role, required_ids in expected.items():
        checks = build_check_inventory(role, mode)
        assert required_ids <= {check.id for check in checks}
        assert all(0 < check.timeout_seconds <= GLOBAL_DEADLINE_SECONDS for check in checks)


@pytest.mark.asyncio
async def test_global_deadline_identifies_and_cancels_unfinished_checks() -> None:
    cleanup_ran = asyncio.Event()

    async def hangs() -> None:
        try:
            await asyncio.sleep(60)
        finally:
            cleanup_ran.set()

    results = await execute_checks(
        [CheckDefinition(id="core.chat_plumbing", timeout_seconds=60, runner=hangs)],
        global_deadline_seconds=0.01,
    )

    assert results[0].status == "failed"
    assert results[0].failure_class == "timeout"
    assert cleanup_ran.is_set()


def test_verifier_source_has_no_paid_provider_path() -> None:
    import backend.scripts.runtime_health_verifier as verifier

    forbidden = {
        "check_all_providers",
        "_get_provider_client",
        "ask_skill",
        "PaymentIntent.create",
        "Checkout.Session.create",
    }
    source = verifier.__loader__.get_source(verifier.__name__)  # type: ignore[union-attr]

    assert source is not None
    assert all(marker not in source for marker in forbidden)
