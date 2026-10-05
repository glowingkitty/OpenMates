# contract-test-file: infrastructure
"""The archive DB/S3 probe cannot run outside its disposable profile."""

import pytest
import asyncio
import sys
from types import ModuleType

from scripts.storage_archive_integration import require_isolated_storage, _load_archive_services


def test_archive_probe_requires_exact_isolated_storage_profile(monkeypatch) -> None:
    for key, value in {
        "OPENMATES_CI_ISOLATED": "1",
        "OPENMATES_STORAGE_CAPACITY_FIXTURES": "true",
        "CHAT_MESSAGE_ARCHIVE_READS_ENABLED": "1",
        "S3_ENDPOINT_URL": "http://storage.ci.test:9000",
        "SERVER_ENVIRONMENT": "development",
        "INTERNAL_API_SHARED_TOKEN": "disposable-token",
    }.items():
        monkeypatch.setenv(key, value)
    require_isolated_storage()
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://storage.example.com")
    with pytest.raises(RuntimeError, match="exact isolated"):
        require_isolated_storage()
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://storage.ci.test:9000")
    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="refuses production"):
        require_isolated_storage()


def test_archive_probe_initializes_only_directus_and_s3_without_celery(monkeypatch) -> None:
    events = []

    class SecretsManager:
        async def initialize(self):
            events.append("secrets_initialized")

        async def aclose(self):
            events.append("secrets_closed")

    class DirectusService:
        async def close(self):
            events.append("directus_closed")

    class S3UploadService:
        def __init__(self, *, secrets_manager, directus_service):
            assert isinstance(secrets_manager, SecretsManager)
            assert isinstance(directus_service, DirectusService)

        async def initialize(self, *, configure_buckets):
            assert configure_buckets is False
            events.append("s3_initialized")

    for path, name, value in (
        ("backend.core.api.app.utils.secrets_manager", "SecretsManager", SecretsManager),
        ("backend.core.api.app.services.directus", "DirectusService", DirectusService),
        ("backend.core.api.app.services.s3.service", "S3UploadService", S3UploadService),
    ):
        module = ModuleType(path)
        setattr(module, name, value)
        monkeypatch.setitem(sys.modules, path, module)

    secrets, directus, s3 = asyncio.run(_load_archive_services())
    assert isinstance(secrets, SecretsManager)
    assert isinstance(directus, DirectusService)
    assert isinstance(s3, S3UploadService)
    assert events == ["secrets_initialized", "s3_initialized"]


@pytest.mark.parametrize("fails", [False, True])
def test_team_portability_selector_runs_only_its_probe_and_closes_resources(monkeypatch, fails) -> None:
    from scripts import storage_archive_integration as integration
    events = []
    monkeypatch.setenv("BUILD_COMMIT_SHA", "a" * 40)

    class Directus:
        async def close(self):
            events.append("directus_closed")

    class Secrets:
        async def aclose(self):
            events.append("secrets_closed")

    directus, secrets, s3 = Directus(), Secrets(), object()

    async def load():
        return secrets, directus, s3

    async def team_probe(actual_directus, actual_s3, now):
        assert actual_directus is directus and actual_s3 is s3 and isinstance(now, int)
        events.append("team_probe")
        if fails:
            raise RuntimeError("synthetic probe failure")
        return {"passed": True, "team_portability_cleanup_verified": True}

    monkeypatch.setattr(integration, "require_isolated_storage", lambda: events.append("profile_guard"))
    monkeypatch.setattr(integration, "_load_archive_services", load)
    monkeypatch.setattr(integration, "_probe_team_portability", team_probe)
    if fails:
        with pytest.raises(RuntimeError, match="synthetic probe failure"):
            asyncio.run(integration.probe_team_portability())
    else:
        result = asyncio.run(integration.probe_team_portability())
        assert result == {"passed": True, "team_portability_cleanup_verified": True, "source_commit": "a" * 40}
    assert events == ["profile_guard", "team_probe", "directus_closed", "secrets_closed"]


@pytest.mark.parametrize("failure_at,error_class", [
    ("service_initialization", "AttributeError"),
    ("export", "RuntimeError"),
    ("fixture_cleanup", "ExceptionGroup"),
    ("directus_close", "ConnectionError"),
    ("secrets_close", "OtherError"),
])
def test_team_failure_receipt_preserves_stage_without_private_exception_data(monkeypatch, failure_at, error_class):
    import json
    from builtins import ExceptionGroup
    from scripts import storage_archive_integration as integration

    private = "private-token-ciphertext-object-key"
    events = []

    class PrivateNamedException(Exception):
        pass

    class Directus:
        async def close(self):
            events.append("directus_closed")
            if failure_at == "directus_close":
                raise ConnectionError(private)

    class Secrets:
        async def aclose(self):
            events.append("secrets_closed")
            if failure_at == "secrets_close":
                raise PrivateNamedException(private)

    async def load():
        if failure_at == "service_initialization":
            raise AttributeError(private)
        return Secrets(), Directus(), object()

    async def team_probe(*args):
        integration._TEAM_PORTABILITY_STAGE.set(failure_at)
        if failure_at == "export":
            raise RuntimeError(private)
        if failure_at == "fixture_cleanup":
            raise ExceptionGroup(private, [RuntimeError(private), ValueError(private)])
        return {"passed": True}

    monkeypatch.setenv("BUILD_COMMIT_SHA", "a" * 40)
    monkeypatch.setattr(integration, "require_isolated_storage", lambda: None)
    monkeypatch.setattr(integration, "_load_archive_services", load)
    monkeypatch.setattr(integration, "_probe_team_portability", team_probe)
    receipt = asyncio.run(integration._team_portability_cli_result())
    assert receipt == {"passed": False, "stage": failure_at, "reason": "probe_exception", "error_class": error_class}
    assert private not in json.dumps(receipt)
    assert "PrivateNamedException" not in json.dumps(receipt)
    assert events == ([] if failure_at == "service_initialization" else ["directus_closed", "secrets_closed"])


@pytest.mark.parametrize("fail", [False, True])
def test_official_billing_probe_restores_isolated_deployment_and_billing_configuration(monkeypatch, fail):
    import os
    from scripts.storage_archive_integration import _official_billing_hold
    monkeypatch.setenv("OPENMATES_DEPLOYMENT_MODE", "self_host")
    monkeypatch.setenv("STORAGE_LOGICAL_S3_BILLING_ENABLED", "1")
    try:
        with _official_billing_hold():
            assert os.environ["OPENMATES_DEPLOYMENT_MODE"] == "official_cloud"
            assert "STORAGE_LOGICAL_S3_BILLING_ENABLED" not in os.environ
            if fail:
                raise RuntimeError("synthetic fixture failure")
    except RuntimeError:
        assert fail
    assert os.environ["OPENMATES_DEPLOYMENT_MODE"] == "self_host"
    assert os.environ["STORAGE_LOGICAL_S3_BILLING_ENABLED"] == "1"
