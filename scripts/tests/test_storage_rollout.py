# contract-test-file: infrastructure
"""Reviewed rollout receipts gate both message and version archives."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from scripts.storage_rollout import (
    COLLECTIONS, PRUNE_CHECKS, isolated_profile,
    operate, selector_digest, status, validate_receipt,
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
