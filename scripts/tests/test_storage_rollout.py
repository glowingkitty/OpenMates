# contract-test-file: infrastructure
"""Reviewed rollout receipts gate both message and version archives."""

from copy import deepcopy
import base64
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from scripts.storage_rollout import (
    COLLECTIONS, PRUNE_CHECKS, READ_CHECKS, auto_advance, isolated_profile,
    operate, selector_digest, status, validate_receipt, validate_release_certificate,
    automatic_tick,
)


SOURCE = "a" * 40
REVIEW = f"reviewed:{SOURCE}:operator-approval-1"


def evidence(name: str) -> dict:
    result = {"passed": True, "source_commit": SOURCE, "evidence_id": f"reviewed-{name}-123"}
    if name == "p7_zero_provider_calls":
        result.update(real_provider_requests=0, provider_credentials="absent", provider_network="internal")
    if name == "p7_capacity_target":
        result.update(user_days=1000, simultaneous_executions=500, rounds=500000,
                      new_embeds=200000, file_versions=1000000)
    return result


def receipt(operation: str, *, profile: str = "real") -> dict:
    return {
        "schema": "agentic-storage-rollout-v1", "operation": operation,
        "source_commit": SOURCE, "profile": profile,
        "operator_review_receipt": REVIEW,
        "reader_receipt": f"reviewed:{SOURCE}:reader-compatibility-1",
        "validation_receipt": f"reviewed:{SOURCE}:capacity-validation-1",
        "checks": {name: evidence(name) for name in PRUNE_CHECKS},
        "pause_reason": "manual_pause",
    }


def signed_certificate(*, prune_ready: bool = False) -> tuple[dict, dict]:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    now = datetime.now(timezone.utc)
    payload = {
        "source_commit": SOURCE, "profile": "real",
        "issued_at": (now - timedelta(minutes=1)).isoformat(),
        "expires_at": (now + timedelta(days=7)).isoformat(),
        "client_compatibility_verified": True,
        "reader_ready": True, "prune_ready": prune_ready,
        "checks": {name: evidence(name) for name in (PRUNE_CHECKS if prune_ready else READ_CHECKS)},
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    certificate = {
        "schema": "agentic-storage-release-eligibility-v1", "payload": payload,
        "signature": base64.b64encode(private.sign(raw)).decode(),
    }
    env = {"BUILD_COMMIT_SHA": SOURCE, "SERVER_ENVIRONMENT": "production",
           "STORAGE_ROLLOUT_RELEASE_PUBLIC_KEY": base64.b64encode(public).decode()}
    return certificate, env


class FakeDirectus:
    base_url = "http://directus.test"

    def __init__(self):
        self.rows = {name: {} for name in COLLECTIONS}
        self.writes = []

    async def get_items(self, collection, params, **kwargs):
        assert kwargs.get("admin_required") is True
        if "aggregate[count]" in params:
            assert "fields" not in params
            return [{"count": "2"}]
        assert params["filter[id][_eq]"] == "agentic-storage-v2"
        row = self.rows[collection]
        return [deepcopy(row)] if row else []

    async def create_item(self, collection, payload, **kwargs):
        assert kwargs["admin_required"] is True
        self.rows[collection] = deepcopy(payload)
        self.writes.append((collection, deepcopy(payload)))
        return True, deepcopy(payload)

    async def ensure_auth_token(self, **kwargs):
        assert kwargs["admin_required"] is True
        return "test-token"

    async def _make_api_request(self, method, url, headers, json):
        assert method == "PATCH" and headers["Authorization"] == "Bearer test-token"
        collection = url.split("/items/")[1].split("/")[0]
        self.rows[collection].update(json)
        self.writes.append((collection, deepcopy(json)))
        return SimpleNamespace(status_code=200, json=lambda: {"data": self.rows[collection]})


def test_real_receipt_rejects_wrong_source_synthetic_and_incomplete_p7() -> None:
    env = {"BUILD_COMMIT_SHA": SOURCE, "SERVER_ENVIRONMENT": "production"}
    value = receipt("configure-prune")
    assert validate_receipt(value, operation="configure-prune", environ=env) is value
    wrong = deepcopy(value)
    wrong["checks"]["apple_reader"]["source_commit"] = "b" * 40
    with pytest.raises(ValueError, match="apple_reader"):
        validate_receipt(wrong, operation="configure-prune", environ=env)
    wrong = deepcopy(value)
    wrong["checks"]["p7_zero_provider_calls"]["real_provider_requests"] = 1
    with pytest.raises(ValueError, match="zero-provider"):
        validate_receipt(wrong, operation="configure-prune", environ=env)
    wrong = deepcopy(value)
    wrong["checks"]["p7_capacity_target"]["simultaneous_executions"] = 499
    with pytest.raises(ValueError, match="target capacity"):
        validate_receipt(wrong, operation="configure-prune", environ=env)
    wrong = deepcopy(value)
    wrong["reader_receipt"] = "ci-storage-capacity:fixture"
    with pytest.raises(ValueError, match="reader receipt"):
        validate_receipt(wrong, operation="configure-prune", environ=env)
    wrong = receipt("configure-prune", profile="isolated-ci")
    with pytest.raises(ValueError, match="Synthetic CI receipt"):
        validate_receipt(wrong, operation="configure-prune", environ=env)


def test_isolated_profile_requires_all_exact_boundaries() -> None:
    env = {"OPENMATES_CI_ISOLATED": "1", "OPENMATES_STORAGE_CAPACITY_FIXTURES": "true",
           "S3_ENDPOINT_URL": "http://storage.ci.test:9000", "SERVER_ENVIRONMENT": "development",
           "BUILD_COMMIT_SHA": SOURCE}
    assert isolated_profile(env)
    assert validate_receipt(receipt("prepare-read", profile="isolated-ci"),
                            operation="prepare-read", environ=env)
    env["SERVER_ENVIRONMENT"] = "production"
    assert not isolated_profile(env)
    with pytest.raises(ValueError, match="exact isolated"):
        validate_receipt(receipt("prepare-read", profile="isolated-ci"),
                         operation="prepare-read", environ=env)


@pytest.mark.asyncio
async def test_operator_prepares_both_then_prunes_only_after_matching_receipts_and_pause_keeps_reads() -> None:
    directus = FakeDirectus()
    read = receipt("prepare-read")
    await operate(directus, operation="prepare-read", receipt=read)
    assert all(directus.rows[name]["read_enabled"] and directus.rows[name]["initial_cohort"]
               and not directus.rows[name]["pruning_enabled"] for name in COLLECTIONS)
    prune = receipt("configure-prune")
    prune["reader_receipt"] = f"reviewed:{SOURCE}:wrong-reader-receipt"
    with pytest.raises(RuntimeError, match="Both verified readers"):
        await operate(directus, operation="configure-prune", receipt=prune)
    assert all(not directus.rows[name]["pruning_enabled"] for name in COLLECTIONS)
    prune["reader_receipt"] = read["reader_receipt"]
    await operate(directus, operation="configure-prune", receipt=prune)
    assert all(directus.rows[name]["pruning_enabled"] for name in COLLECTIONS)
    await operate(directus, operation="pause", receipt=receipt("pause"))
    assert all(directus.rows[name]["read_enabled"] and not directus.rows[name]["pruning_enabled"]
               and directus.rows[name]["failure_code"] == "manual_pause" for name in COLLECTIONS)


@pytest.mark.asyncio
async def test_partial_prune_gate_update_compensates_to_disabled() -> None:
    class FailingVersionDirectus(FakeDirectus):
        async def _make_api_request(self, method, url, headers, json):
            if "embed_version_archive_rollout" in url and json.get("pruning_enabled") is True:
                return SimpleNamespace(status_code=503, json=lambda: {"error": "unavailable"})
            return await super()._make_api_request(method, url, headers, json)

    directus = FailingVersionDirectus()
    await operate(directus, operation="prepare-read", receipt=receipt("prepare-read"))
    with pytest.raises(RuntimeError, match="Prune setup failed"):
        await operate(directus, operation="configure-prune", receipt=receipt("configure-prune"))
    assert all(not directus.rows[name]["pruning_enabled"] for name in COLLECTIONS)


@pytest.mark.asyncio
async def test_status_only_returns_boolean_gates_and_aggregate_counts() -> None:
    directus = FakeDirectus()
    await operate(directus, operation="prepare-read", receipt=receipt("prepare-read"))
    output = await status(directus)
    assert output["version_rows"] == {"copied": 2, "reader_active": 2, "pruned": 2, "stale": 2}
    assert output["message_segments"] == {"copying": 2, "verified": 2, "reader_active": 2}
    assert output["message_pages"] == {"read_enabled": 2, "pruned": 2}
    assert "reader_receipt" not in str(output)
    assert "operator-approval" not in str(output)


def test_rollback_receipt_is_bound_to_one_private_selector() -> None:
    selector = {"user_id": "owner", "chat_id": "chat", "client_message_id": "message"}
    value = receipt("restore-page")
    value["selector_sha256"] = selector_digest(selector)
    env = {"BUILD_COMMIT_SHA": SOURCE, "SERVER_ENVIRONMENT": "production"}
    validate_receipt(value, operation="restore-page", environ=env, selector=selector)
    with pytest.raises(ValueError, match="selected page"):
        validate_receipt(value, operation="restore-page", environ=env,
                         selector={**selector, "client_message_id": "different"})


def test_signed_release_certificate_binds_source_evidence_and_validity() -> None:
    certificate, env = signed_certificate(prune_ready=True)
    assert validate_release_certificate(certificate, environ=env, trusted_public_key=env["STORAGE_ROLLOUT_RELEASE_PUBLIC_KEY"])["payload"]["prune_ready"] is True
    altered = deepcopy(certificate)
    altered["payload"]["source_commit"] = "b" * 40
    with pytest.raises(ValueError, match="installed source"):
        validate_release_certificate(altered, environ=env, trusted_public_key=env["STORAGE_ROLLOUT_RELEASE_PUBLIC_KEY"])
    altered = deepcopy(certificate)
    altered["payload"]["checks"]["apple_reader"]["passed"] = False
    with pytest.raises(ValueError, match="signature"):
        validate_release_certificate(altered, environ=env, trusted_public_key=env["STORAGE_ROLLOUT_RELEASE_PUBLIC_KEY"])
    with pytest.raises(ValueError, match="validity window"):
        validate_release_certificate(certificate, environ=env,
                                     trusted_public_key=env["STORAGE_ROLLOUT_RELEASE_PUBLIC_KEY"], now=datetime.now(timezone.utc) + timedelta(days=8))


@pytest.mark.asyncio
async def test_auto_rollout_is_resumable_and_requires_runtime_client_enforcement() -> None:
    directus = FakeDirectus()
    assert await auto_advance(directus, certificate=None, environ={}) == {
        "status": "pending", "reason": "release_certificate_unavailable", "retry_seconds": 60,
    }
    certificate, env = signed_certificate(prune_ready=True)
    first = await auto_advance(directus, certificate=certificate, environ=env,
                               trusted_public_key=env["STORAGE_ROLLOUT_RELEASE_PUBLIC_KEY"])
    assert first["status"] == "pending"
    assert first["reason"] == "client_compatibility_enforcement_pending"
    assert all(not directus.rows[name] for name in COLLECTIONS)
    compatible = {"enforced": True, "minimum_capability": "agentic-storage-v2",
                  "incompatible_sessions": 0, "source_commit": SOURCE}
    second = await auto_advance(directus, certificate=certificate, environ=env,
                                compatibility_status=compatible,
                                trusted_public_key=env["STORAGE_ROLLOUT_RELEASE_PUBLIC_KEY"])
    assert second["status"] == "prune_enabled"
    assert all(directus.rows[name]["pruning_enabled"] for name in COLLECTIONS)
    writes = len(directus.writes)
    assert (await auto_advance(directus, certificate=certificate, environ=env,
                               compatibility_status=compatible,
                                trusted_public_key=env["STORAGE_ROLLOUT_RELEASE_PUBLIC_KEY"]))["status"] == "prune_enabled"
    assert len(directus.writes) == writes


@pytest.mark.asyncio
async def test_automatic_rollout_suspends_active_pruning_on_lost_evidence_or_compatibility():
    certificate, env = signed_certificate(prune_ready=True)
    public = env["STORAGE_ROLLOUT_RELEASE_PUBLIC_KEY"]
    compatible = {"enforced": True, "minimum_capability": "agentic-storage-v2",
                  "incompatible_sessions": 0, "source_commit": SOURCE}
    for bad_certificate, bad_compatibility in (
        (None, compatible),
        ({**certificate, "signature": "invalid"}, compatible),
        (certificate, {**compatible, "incompatible_sessions": 1}),
        (certificate, {**compatible, "incompatible_sessions": False}),
    ):
        directus = FakeDirectus()
        await auto_advance(directus, certificate=certificate, environ=env,
                           compatibility_status=compatible, trusted_public_key=public)
        result = await auto_advance(directus, certificate=bad_certificate, environ=env,
                                   compatibility_status=bad_compatibility, trusted_public_key=public)
        assert result["status"] in {"paused", "pending"}
        assert all(row["read_enabled"] and not row["pruning_enabled"] for row in directus.rows.values())
        assert (await auto_advance(directus, certificate=certificate, environ=env,
                                  compatibility_status=compatible, trusted_public_key=public))["status"] == "prune_enabled"


def test_installation_env_cannot_replace_release_trust_key():
    certificate, env = signed_certificate(prune_ready=True)
    with pytest.raises(ValueError, match="trust key|signature"):
        validate_release_certificate(certificate, environ=env)


def test_certificate_renewal_preserves_reader_and_validation_identity():
    certificate, env = signed_certificate(prune_ready=True)
    public = env["STORAGE_ROLLOUT_RELEASE_PUBLIC_KEY"]
    original = validate_release_certificate(certificate, environ=env, trusted_public_key=public)
    # Receipt identities depend only on source-bound evidence, independently
    # of certificate renewal and the addition of pruning checks.
    from scripts.storage_rollout import _canonical_json
    private = Ed25519PrivateKey.generate()
    renewed = deepcopy(certificate)
    renewed["payload"]["issued_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    renewed["signature"] = base64.b64encode(private.sign(_canonical_json(renewed["payload"]))).decode()
    renewed_public = base64.b64encode(private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    current = validate_release_certificate(renewed, environ=env, trusted_public_key=renewed_public)
    assert original["receipt"] == current["receipt"]
    renewed["payload"]["prune_ready"] = False
    renewed["payload"]["checks"] = {name: evidence(name) for name in READ_CHECKS}
    renewed["signature"] = base64.b64encode(private.sign(_canonical_json(renewed["payload"]))).decode()
    reader = validate_release_certificate(renewed, environ=env, trusted_public_key=renewed_public)
    assert reader["receipt"]["reader_receipt"] == current["receipt"]["reader_receipt"]


@pytest.mark.asyncio
async def test_periodic_tick_malformed_release_preserves_reads_and_suspends_pruning(monkeypatch):
    import scripts.storage_rollout as rollout
    directus = FakeDirectus()
    await operate(directus, operation="prepare-read", receipt=receipt("prepare-read"))
    await operate(directus, operation="configure-prune", receipt=receipt("configure-prune"))
    def fail(_env):
        raise ValueError("Malformed certificate")
    monkeypatch.setattr(rollout, "fetch_release_certificate", fail)
    assert (await automatic_tick(directus, environ={"BUILD_COMMIT_SHA": SOURCE}))["status"] == "pending"
    assert all(row["read_enabled"] and not row["pruning_enabled"] for row in directus.rows.values())


@pytest.mark.asyncio
async def test_auto_reader_certificate_promotes_to_prune_without_operator_receipts():
    from scripts.storage_rollout import _canonical_json
    private = Ed25519PrivateKey.generate()
    public = base64.b64encode(private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    certificate, env = signed_certificate(prune_ready=False)
    certificate["signature"] = base64.b64encode(private.sign(_canonical_json(certificate["payload"]))).decode()
    directus = FakeDirectus()
    compatible = {"enforced": True, "minimum_capability": "agentic-storage-v2",
                  "incompatible_sessions": 0, "source_commit": SOURCE}
    result = await auto_advance(directus, certificate=certificate, environ=env,
                               compatibility_status=compatible, trusted_public_key=public)
    assert result["status"] == "reader_enabled" and result["reason"] == "prune_evidence_pending"
    reader = directus.rows[COLLECTIONS[0]]["reader_receipt"]
    certificate["payload"]["prune_ready"] = True
    certificate["payload"]["checks"] = {name: evidence(name) for name in PRUNE_CHECKS}
    certificate["signature"] = base64.b64encode(private.sign(_canonical_json(certificate["payload"]))).decode()
    assert (await auto_advance(directus, certificate=certificate, environ=env,
                              compatibility_status=compatible, trusted_public_key=public))["status"] == "prune_enabled"
    assert all(row["reader_receipt"] == reader for row in directus.rows.values())


@pytest.mark.asyncio
async def test_automatic_status_does_not_trust_stale_cached_prune_success():
    class Cache:
        async def get(self, _key):
            return {"status": "prune_enabled", "reader_receipt": "private", "user_id": "private"}
    directus = FakeDirectus()
    await operate(directus, operation="prepare-read", receipt=receipt("prepare-read"))
    result = await status(directus, cache_service=Cache())
    assert result["automatic"]["status"] == "reader_enabled"
    await operate(directus, operation="pause", receipt=receipt("pause"))
    result = await status(directus, cache_service=Cache())
    assert result["automatic"]["status"] == "paused"
    assert "private" not in str(result)


def test_archive_workers_default_to_unattended_mode_with_emergency_opt_out():
    from backend.shared.python_utils.storage_archive_rollout_config import archive_feature_enabled
    assert archive_feature_enabled("CHAT_MESSAGE_ARCHIVE_COPY_ENABLED", {})
    assert archive_feature_enabled("EMBED_VERSION_ARCHIVE_PRUNE_ENABLED", {})
    assert not archive_feature_enabled("EMBED_VERSION_ARCHIVE_PRUNE_ENABLED", {"EMBED_VERSION_ARCHIVE_PRUNE_ENABLED": "0"})
    assert not archive_feature_enabled("EMBED_VERSION_ARCHIVE_PRUNE_ENABLED", {"EMBED_VERSION_ARCHIVE_PRUNE_ENABLED": "unexpected"})


@pytest.mark.asyncio
async def test_destructive_entrypoint_revalidates_current_signed_release_and_actual_runtime(monkeypatch, tmp_path):
    import sys
    import scripts.storage_rollout as rollout
    from backend.shared.python_utils import storage_archive_rollout_config as config
    certificate, env = signed_certificate(prune_ready=True)
    trust = tmp_path / "trust.json"
    trust.write_text(json.dumps({"schema": "agentic-storage-release-trust-v1", "algorithm": "Ed25519",
                                "public_key": env["STORAGE_ROLLOUT_RELEASE_PUBLIC_KEY"]}))
    monkeypatch.setattr(rollout, "RELEASE_TRUST_PATH", trust)
    async def cached(_env):
        return certificate
    monkeypatch.setattr(config, "cached_release_certificate", cached)
    runtime = {"enforced": True, "minimum_capability": "agentic-storage-v2",
               "incompatible_sessions": 0, "source_commit": SOURCE}
    async def compatible(_directus, *, source_commit):
        return runtime
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.storage_archive_client_compatibility",
                        SimpleNamespace(runtime_compatibility_status=compatible))
    directus = FakeDirectus()
    await auto_advance(directus, certificate=certificate, environ=env, compatibility_status=runtime)
    assert await config.archive_advancement_allowed(directus, phase="prune", environ=env)
    runtime["incompatible_sessions"] = 1
    assert not await config.archive_advancement_allowed(directus, phase="prune", environ=env)
    assert all(row["read_enabled"] and not row["pruning_enabled"] for row in directus.rows.values())
    runtime["incompatible_sessions"] = 0
    await auto_advance(directus, certificate=certificate, environ=env, compatibility_status=runtime)
    assert not await config.archive_advancement_allowed(directus, phase="prune", environ={**env, "BUILD_COMMIT_SHA": "b" * 40})
    assert all(not row["pruning_enabled"] for row in directus.rows.values())
    with pytest.raises(ValueError, match="phase"):
        await config.archive_advancement_allowed(directus, phase="invented", environ=env)


@pytest.mark.asyncio
async def test_periodic_migration_task_retries_through_existing_services_and_always_cleans_up(monkeypatch):
    import importlib.util
    import sys
    from pathlib import Path
    from unittest.mock import AsyncMock
    monkeypatch.setitem(sys.modules, "backend.core.api.app.tasks.base_task", SimpleNamespace(BaseServiceTask=object))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.tasks.celery_config",
                        SimpleNamespace(app=SimpleNamespace(task=lambda **kwargs: lambda function: function)))
    spec = importlib.util.spec_from_file_location("migration_task_fixture", Path(__file__).resolve().parents[2] / "backend/core/api/app/tasks/storage_rollout_tasks.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    task = SimpleNamespace(initialize_services=AsyncMock(), cleanup_services=AsyncMock(),
                           directus_service=object(), cache_service=object())
    result = {"status": "pending", "reason": "release_certificate_unavailable", "retry_seconds": 60}
    monkeypatch.setattr(module, "automatic_tick", AsyncMock(return_value=result))
    assert await module.run_automatic_migration(task) == result
    module.automatic_tick.assert_awaited_once_with(task.directus_service, cache_service=task.cache_service)
    task.cleanup_services.assert_awaited_once()
    task.initialize_services.side_effect = RuntimeError("service unavailable")
    with pytest.raises(RuntimeError, match="service unavailable"):
        await module.run_automatic_migration(task)
    assert task.cleanup_services.await_count == 2


@pytest.mark.asyncio
async def test_signed_release_cannot_override_operator_emergency_opt_out():
    certificate, env = signed_certificate(prune_ready=True)
    public = env["STORAGE_ROLLOUT_RELEASE_PUBLIC_KEY"]
    compatible = {"enforced": True, "minimum_capability": "agentic-storage-v2",
                  "incompatible_sessions": 0, "source_commit": SOURCE}
    directus = FakeDirectus()
    result = await auto_advance(directus, certificate=certificate, environ={**env, "CHAT_MESSAGE_ARCHIVE_PRUNE_ENABLED": "0"},
                               compatibility_status=compatible, trusted_public_key=public)
    assert result["status"] == "reader_enabled" and result["reason"] == "pruning_emergency_opt_out"
    assert all(row["read_enabled"] and not row["pruning_enabled"] for row in directus.rows.values())
    result = await auto_advance(directus, certificate=certificate, environ={**env, "EMBED_VERSION_ARCHIVE_READ_ENABLED": "0"},
                               compatibility_status=compatible, trusted_public_key=public)
    assert result["status"] == "paused" and result["reason"] == "migration_emergency_opt_out"


def test_immutable_source_release_attestation_has_no_calendar_expiry_but_still_binds_source():
    from scripts.storage_rollout import _canonical_json
    certificate, env = signed_certificate(prune_ready=True)
    private = Ed25519PrivateKey.generate()
    public = base64.b64encode(private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    certificate["payload"].update(validity="exact-source", expires_at=None)
    certificate["signature"] = base64.b64encode(private.sign(_canonical_json(certificate["payload"]))).decode()
    assert validate_release_certificate(certificate, environ=env, trusted_public_key=public,
                                        now=datetime.now(timezone.utc) + timedelta(days=365))["payload"]["prune_ready"]
    with pytest.raises(ValueError, match="installed source"):
        validate_release_certificate(certificate, environ={**env, "BUILD_COMMIT_SHA": "b" * 40}, trusted_public_key=public)


def test_isolated_eligibility_requires_host_verified_readonly_source_bound_network_and_secret_proof(monkeypatch, tmp_path):
    import time
    from backend.shared.python_utils import storage_archive_rollout_config as config
    env = {"BUILD_COMMIT_SHA": SOURCE, "OPENMATES_CI_ISOLATED": "1", "OPENMATES_STORAGE_CAPACITY_FIXTURES": "true",
           "S3_ENDPOINT_URL": "http://storage.ci.test:9000", "SERVER_ENVIRONMENT": "development"}
    proof_path = tmp_path / "proof.json"
    mountinfo = tmp_path / "mountinfo"
    monkeypatch.setattr(config, "CI_ISOLATION_PROOF", proof_path)
    monkeypatch.setattr(config, "CI_MOUNTINFO", mountinfo)
    assert not config.trusted_isolated_storage_profile(env)
    proof = {"schema": "agentic-storage-ci-isolation-v1", "source_commit": SOURCE, "harness_commit": "b" * 40,
             "run_id": "123", "environment": "github-isolated", "observed_at": int(time.time()) - 1,
             "expires_at": int(time.time()) + 1000, "provider_network": "internal", "provider_credentials": "absent",
             "vault_provider_keys": ["core_server", "hetzner"], "source_mount": "read_only_exact_candidate",
             "shared_dev_dns": "rejected", "shared_dev_https": "rejected", "object_storage": "authenticated_disposable_roundtrip"}
    proof_path.write_text(json.dumps(proof))
    proof_path.chmod(0o444)
    mountinfo.write_text(f"1 0 0:1 / {tmp_path} rw - tmpfs tmpfs rw\n")
    assert not config.trusted_isolated_storage_profile(env)
    mountinfo.write_text(f"1 0 0:1 / {tmp_path} ro - tmpfs tmpfs ro\n")
    assert config.trusted_isolated_storage_profile(env)
    assert not config.trusted_isolated_storage_profile({**env, "BUILD_COMMIT_SHA": "c" * 40})
    assert not config.trusted_isolated_storage_profile({**env, "SERVER_ENVIRONMENT": "production"})
    for name, value in (("provider_credentials", "present"), ("provider_network", "external"), ("vault_provider_keys", ["openai"]), ("source_mount", "writable")):
        proof_path.chmod(0o644)
        proof_path.write_text(json.dumps({**proof, name: value}))
        proof_path.chmod(0o444)
        assert not config.trusted_isolated_storage_profile(env)


@pytest.mark.asyncio
async def test_trusted_isolated_path_preserves_actual_client_and_source_receipt_fences(monkeypatch):
    import sys
    from backend.shared.python_utils import storage_archive_rollout_config as config
    env = {"BUILD_COMMIT_SHA": SOURCE, "OPENMATES_CI_ISOLATED": "1", "OPENMATES_STORAGE_CAPACITY_FIXTURES": "true",
           "S3_ENDPOINT_URL": "http://storage.ci.test:9000", "SERVER_ENVIRONMENT": "development"}
    monkeypatch.setattr(config, "trusted_isolated_storage_profile", lambda _env: True)
    directus = FakeDirectus()
    await operate(directus, operation="prepare-read", receipt=receipt("prepare-read", profile="isolated-ci"))
    await operate(directus, operation="configure-prune", receipt=receipt("configure-prune", profile="isolated-ci"))
    runtime = {"enforced": True, "minimum_capability": "agentic-storage-v2", "incompatible_sessions": 0, "source_commit": SOURCE}
    async def compatible(_directus, *, source_commit):
        return runtime
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.storage_archive_client_compatibility", SimpleNamespace(runtime_compatibility_status=compatible))
    assert await config.archive_advancement_allowed(directus, phase="prune", environ=env)
    directus.rows[COLLECTIONS[0]]["reader_receipt"] = "ci-storage-capacity:" + "b" * 40
    assert not await config.archive_advancement_allowed(directus, phase="prune", environ=env)
    assert all(not row["pruning_enabled"] for row in directus.rows.values())
    runtime["incompatible_sessions"] = 1
    assert not await config.archive_advancement_allowed(directus, phase="read", environ=env)


@pytest.mark.asyncio
async def test_isolated_automatic_tick_pauses_and_resumes_with_live_runtime_without_release_fetch(monkeypatch):
    import sys
    from unittest.mock import AsyncMock
    from backend.shared.python_utils import storage_archive_rollout_config as config
    env = {"BUILD_COMMIT_SHA": SOURCE, "OPENMATES_CI_ISOLATED": "1", "OPENMATES_STORAGE_CAPACITY_FIXTURES": "true",
           "S3_ENDPOINT_URL": "http://storage.ci.test:9000", "SERVER_ENVIRONMENT": "development"}
    monkeypatch.setattr(config, "trusted_isolated_storage_profile", lambda _env: True)
    fetch = AsyncMock(side_effect=AssertionError("isolated proof must not fetch a public release"))
    monkeypatch.setattr(config, "cached_release_certificate", fetch)
    directus = FakeDirectus()
    for collection in COLLECTIONS:
        directus.rows[collection] = {"id": "agentic-storage-v2", "read_enabled": True, "pruning_enabled": True,
            "compatibility_verified": True, "reader_receipt": "ci-storage-capacity:" + SOURCE,
            "validation_receipt": "ci-storage-capacity:" + SOURCE, "initial_cohort": False}
    runtime = {"enforced": True, "minimum_capability": "agentic-storage-v2", "incompatible_sessions": 1, "source_commit": SOURCE}
    async def compatible(_directus, *, source_commit):
        return runtime
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.storage_archive_client_compatibility",
                        SimpleNamespace(runtime_compatibility_status=compatible))
    assert (await automatic_tick(directus, environ=env))["status"] == "pending"
    assert all(not row["pruning_enabled"] and row["read_enabled"] for row in directus.rows.values())
    runtime["incompatible_sessions"] = 0
    assert (await automatic_tick(directus, environ=env))["status"] == "prune_enabled"
    assert all(row["pruning_enabled"] for row in directus.rows.values())
    directus.rows[COLLECTIONS[0]]["validation_receipt"] = "ci-storage-capacity:" + "b" * 40
    assert (await automatic_tick(directus, environ=env))["status"] == "pending"
    assert all(not row["pruning_enabled"] for row in directus.rows.values())
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_installed_guard_stages_reader_admission_before_retiring_legacy_sessions():
    certificate, env = signed_certificate(prune_ready=True)
    public = env["STORAGE_ROLLOUT_RELEASE_PUBLIC_KEY"]
    runtime = {"enforced": True, "minimum_capability": "agentic-storage-v2",
               "incompatible_sessions": 1, "source_commit": SOURCE}
    directus = FakeDirectus()
    result = await auto_advance(directus, certificate=certificate, environ=env,
                               compatibility_status=runtime, trusted_public_key=public)
    assert result["status"] == "pending" and result["reason"] == "client_compatibility_enforcement_pending"
    expected = validate_release_certificate(certificate, environ=env, trusted_public_key=public)["receipt"]
    assert all(row["read_enabled"] and row["reader_receipt"] == expected["reader_receipt"]
               and row["initial_cohort"] and not row["pruning_enabled"]
               and not row.get("validation_receipt") for row in directus.rows.values())
    # FakeDirectus exposes only gate writes: this tick activates no archive unit.
    assert all(collection in COLLECTIONS for collection, _ in directus.writes)
    runtime["incompatible_sessions"] = 0
    assert (await auto_advance(directus, certificate=certificate, environ=env,
                              compatibility_status=runtime, trusted_public_key=public))["status"] == "prune_enabled"
    for unverified in ({**runtime, "enforced": False}, {**runtime, "source_commit": "b" * 40},
                       {**runtime, "incompatible_sessions": -1}):
        untouched = FakeDirectus()
        assert (await auto_advance(untouched, certificate=certificate, environ=env,
                                  compatibility_status=unverified, trusted_public_key=public))["status"] == "pending"
        assert untouched.writes == []
