# contract-test-file: infrastructure
"""Local outcome checks for the isolated actual-PostgreSQL recovery race probe.

The transaction race itself runs only in the isolated API container via
scripts/storage_archive_integration.py.
"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import hashlib
import copy
import uuid

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "storage_archive_integration.py"
SPEC = spec_from_file_location("storage_archive_integration_pg_race", SCRIPT)
assert SPEC and SPEC.loader
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize("writer_status", [200, 404, 409])
def test_fenced_race_accepts_either_transaction_order_without_live_rows(writer_status):
    MODULE._assert_recovery_deletion_race(
        deletion_status=200, writer_status=writer_status,
        producer_rows=[{"state": "INVALIDATED"}] if writer_status == 200 else [],
        output_rows=[{"state": "DELETED", "deleted_at": "2026-10-04T00:00:00Z"}]
        if writer_status == 200 else [],
        preflight_rows=[],
    )


@pytest.mark.parametrize("mutated", [
    {"deletion_status": 409},
    {"writer_status": 500},
    {"producer_rows": [{"state": "PENDING"}]},
    {"output_rows": [{"state": "PREPARING", "deleted_at": None}]},
    {"output_rows": [{"state": "ACKNOWLEDGED", "deleted_at": None}]},
    {"preflight_rows": [{"state": "RUNNING"}]},
])
def test_fenced_race_rejects_failed_fence_or_resurrected_state(mutated):
    outcome = {
        "deletion_status": 200, "writer_status": 200,
        "producer_rows": [], "output_rows": [], "preflight_rows": [],
    }
    outcome.update(mutated)
    with pytest.raises(RuntimeError):
        MODULE._assert_recovery_deletion_race(**outcome)


@pytest.mark.parametrize("kind,once,again", [
    ("ordinary", {"claimed": True, "authorized": True},
     {"claimed": False, "authorized": False}),
    ("batch", {"claimed": True}, {"claimed": False}),
])
def test_concurrent_legacy_claim_permits_exactly_one_execution(kind, once, again):
    MODULE._assert_single_legacy_start(kind, [(200, once), (200, again)])
    MODULE._assert_single_legacy_start(kind, [(200, again), (200, once)])


@pytest.mark.parametrize("attempts", [
    [(200, {"claimed": True, "authorized": True}),
     (200, {"claimed": True, "authorized": True})],
    [(200, {"claimed": False, "authorized": False}),
     (200, {"claimed": False, "authorized": False})],
    [(200, {"claimed": True, "authorized": True}),
     (500, {"claimed": False, "authorized": False})],
])
def test_concurrent_legacy_claim_rejects_duplicate_start_or_failed_transaction(attempts):
    with pytest.raises(RuntimeError):
        MODULE._assert_single_legacy_start("ordinary", attempts)


def test_completed_claim_survives_deletion_as_permanent_replay_marker():
    MODULE._assert_completed_claim_survives_deletion(
        200, {"invalidated_legacy_batches": 0}, [{
            "state": "COMPLETED", "worker_completed": True,
            "persistence_observed": True, "invalidated_at": None,
        }],
    )


@pytest.mark.parametrize("deletion_status,deletion,claim_rows", [
    (409, {"invalidated_legacy_batches": 0}, [{"state": "COMPLETED",
      "worker_completed": True, "persistence_observed": True}]),
    (200, {"invalidated_legacy_batches": 1}, [{"state": "COMPLETED",
      "worker_completed": True, "persistence_observed": True}]),
    (200, {"invalidated_legacy_batches": 0}, []),
    (200, {"invalidated_legacy_batches": 0}, [{"state": "INVALIDATED",
      "worker_completed": True, "persistence_observed": True}]),
    (200, {"invalidated_legacy_batches": 0}, [{"state": "CLAIMED",
      "worker_completed": True, "persistence_observed": True}]),
    (200, {"invalidated_legacy_batches": 0}, [{"state": "COMPLETED",
      "worker_completed": False, "persistence_observed": True}]),
    (200, {"invalidated_legacy_batches": 0}, [{"state": "COMPLETED",
      "worker_completed": True, "persistence_observed": False}]),
    (200, {"invalidated_legacy_batches": 0}, [{"state": "COMPLETED",
      "worker_completed": True, "persistence_observed": True,
      "invalidated_at": "2026-10-04T00:00:00Z"}]),
])
def test_completed_claim_deletion_rejects_lost_or_mutated_marker(
    deletion_status, deletion, claim_rows,
):
    with pytest.raises(RuntimeError):
        MODULE._assert_completed_claim_survives_deletion(
            deletion_status, deletion, claim_rows)


@pytest.mark.asyncio
async def test_legacy_probe_refuses_to_downgrade_activated_protocol(monkeypatch):
    operations = []

    async def transaction(_directus, operation, _payload):
        operations.append(operation)
        return 200, {"protocol_epoch": 1, "sends_paused": False}

    monkeypatch.setattr(MODULE, "_recovery_sql", transaction)
    with pytest.raises(RuntimeError, match="epoch-zero"):
        await MODULE._probe_legacy_claim_sql_races(object(), 0)
    assert operations == ["get_cutover_state"]


def test_legacy_actor_payload_matches_disposable_account_shape():
    user_id = str(uuid.uuid4())
    payload = MODULE._legacy_claim_actor_payload(user_id)
    digest = hashlib.sha256(f"ci-legacy:{user_id}".encode()).hexdigest()
    assert payload["id"] == user_id
    assert payload["email"] == f"{digest}@example.com"
    assert payload["hashed_email"] == digest
    assert payload["status"] == "active"
    assert len(payload["password"]) >= 32
    assert user_id not in payload["email"]


@pytest.mark.asyncio
async def test_legacy_actor_create_reports_only_bounded_directus_schema_metadata():
    secret = "do-not-log-disposable-password-or-email"

    class Response:
        status_code = 400

        def json(self):
            return {"errors": [{"message": secret,
                     "extensions": {"code": "INVALID_PAYLOAD", "field": "email",
                                    "value": secret}}]}

    class Directus:
        base_url = "http://directus.invalid"

        async def ensure_auth_token(self, **_kwargs):
            return "disposable-admin-token"

        async def _make_api_request(self, method, url, *, headers, json):
            assert method == "POST" and url.endswith("/users")
            assert headers["Authorization"].startswith("Bearer ")
            assert json["email"].endswith("@example.com")
            assert json["password"]
            return Response()

    with pytest.raises(RuntimeError) as exc_info:
        await MODULE._legacy_claim_fixture_user(Directus(), str(uuid.uuid4()))
    assert "status=400 code=INVALID_PAYLOAD field=email" in str(exc_info.value)
    assert secret not in str(exc_info.value)
    assert "disposable-admin-token" not in str(exc_info.value)


def test_legacy_actor_create_diagnostics_ignore_unrecognized_values():
    class Response:
        status_code = 422

        def json(self):
            return {"errors": [{"extensions": {
                "code": "private-user-value", "field": "private-field-value"}}]}

    assert MODULE._user_create_failure_metadata(Response()) == (
        "status=422 code=unknown field=unknown")


def test_canonical_assistant_fixture_uses_real_database_identity():
    broker_id, chat_id = str(uuid.uuid4()), str(uuid.uuid4())
    row = MODULE._canonical_assistant_fixture(broker_id, chat_id, "owner-hash", 42)
    assert row["id"] == str(uuid.uuid5(uuid.NAMESPACE_DNS, broker_id))
    assert row["id"] != row["client_message_id"] == broker_id
    assert row["chat_id"] == chat_id
    assert row["role"] == "assistant"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,stage", [
    ("ordinary", "bind"), ("ordinary", "claim"), ("batch", "claim"),
])
async def test_canonical_guard_checks_distinct_client_id_before_start(
    monkeypatch, kind, stage,
):
    calls = []

    class Directus:
        async def create_item(self, collection, payload, **_kwargs):
            assert collection == "messages"
            assert payload["id"] != payload["client_message_id"]
            calls.append(("canonical", payload["client_message_id"]))
            return True, payload

        async def get_items(self, collection, **_kwargs):
            assert collection == "chat_recovery_legacy_batch_claims"
            return [{"id": "claim-row"}]

        async def delete_item(self, collection, _id, **_kwargs):
            calls.append(("delete", collection))
            return True

    async def transaction(_directus, operation, payload):
        calls.append(("operation", operation))
        if operation == "release_legacy_inference":
            return 200, {}
        if operation == "bind_ordinary_legacy_dispatch":
            if stage == "claim":
                return 200, {"enqueue_allowed": True}
            return 200, {"enqueue_allowed": False, "status": "CANONICAL_PRESENT"}
        if operation in {"claim_legacy_inference_start", "claim_legacy_batch"}:
            return 200, {"claimed": False, "status": "CANONICAL_PRESENT"}
        return 200, {}

    monkeypatch.setattr(MODULE, "_recovery_sql", transaction)
    await MODULE._probe_canonical_legacy_claim_guard(
        Directus(), kind=kind, stage=stage, user_id=str(uuid.uuid4()),
        chat_id=str(uuid.uuid4()), owner_hash="owner-hash", now=42,
    )
    canonical_at = next(i for i, call in enumerate(calls) if call[0] == "canonical")
    guard_operation = ("bind_ordinary_legacy_dispatch" if stage == "bind"
                       else "claim_legacy_inference_start" if kind == "ordinary"
                       else "claim_legacy_batch")
    assert ("operation", guard_operation) in calls[canonical_at + 1:]
    assert ("delete", "messages") in calls


@pytest.mark.asyncio
async def test_canonical_guard_rejects_lookup_by_database_id(monkeypatch):
    class Directus:
        async def create_item(self, _collection, payload, **_kwargs):
            return True, payload

        async def get_items(self, _collection, **_kwargs):
            return [{"id": "claim-row"}]

        async def delete_item(self, _collection, _id, **_kwargs):
            return True

    async def old_lookup(_directus, operation, _payload):
        if operation == "claim_legacy_batch":
            return 200, {"claimed": True, "status": "RUNNING"}
        return 200, {}

    monkeypatch.setattr(MODULE, "_recovery_sql", old_lookup)
    with pytest.raises(RuntimeError, match="did not fence legacy execution"):
        await MODULE._probe_canonical_legacy_claim_guard(
            Directus(), kind="batch", stage="claim", user_id=str(uuid.uuid4()),
            chat_id=str(uuid.uuid4()), owner_hash="owner-hash", now=42,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [None, "release", "ack", "worker"])
async def test_claim_lifecycle_requires_verified_output_and_worker_completion(
    monkeypatch, fault,
):
    task_identity = "a" * 64
    broker_id, chat_id = str(uuid.uuid4()), str(uuid.uuid4())
    owner_hash = "b" * 64
    events = []

    class Directus:
        def __init__(self):
            self.lifecycle = [{"task_identity": task_identity, "state": "RUNNING",
                               "expires_at": "2100-01-01T00:00:00Z",
                               "persistence_observed": False}]
            self.active = [task_identity]
            self.claim = {"state": "CLAIMED", "worker_completed": False,
                          "persistence_observed": False}
            self.message = None

        async def create_item(self, collection, payload, **_kwargs):
            assert collection == "messages"
            assert payload["id"] != payload["client_message_id"] == broker_id
            self.message = payload
            events.append("canonical")
            return True, payload

        async def get_items(self, collection, **_kwargs):
            if collection == "chat_recovery_protocol_state":
                return [{"legacy_task_lifecycle": copy.deepcopy(self.lifecycle),
                         "active_legacy_tasks": self.active.copy()}]
            if collection == "chat_recovery_legacy_batch_claims":
                return [self.claim.copy()]
            raise AssertionError(collection)

        async def delete_item(self, collection, item_id, **_kwargs):
            assert collection == "messages" and self.message["id"] == item_id
            self.message = None
            events.append("delete")
            return True

    directus = Directus()

    async def transaction(_directus, operation, payload):
        events.append(operation)
        if operation == "release_legacy_inference":
            return 200, ({"released": True} if fault == "release"
                         else {"held": True, "released": False})
        if operation == "cleanup_expired":
            if directus.lifecycle and directus.lifecycle[0]["expires_at"].startswith("20"):
                directus.lifecycle = []
            return 200, {}
        if operation == "acknowledge_legacy_persistence":
            assert directus.message is not None
            assert payload["task_identity"] == payload["assistant_message_id"] == broker_id
            assert payload["ciphertext_digest"] == hashlib.sha256(
                directus.message["encrypted_content"].encode()
            ).hexdigest()
            if fault == "ack":
                return 200, {"acknowledged": False}
            directus.lifecycle[0]["persistence_observed"] = True
            directus.claim["persistence_observed"] = True
            return 200, {"acknowledged": True, "output_receipt_verified": True,
                         "state": "RUNNING"}
        if operation == "mark_legacy_inference_completed":
            if fault == "worker":
                return 200, {"completed": False}
            assert directus.lifecycle[0]["persistence_observed"] is True
            directus.lifecycle[0]["state"] = "PERSISTED"
            directus.active = []
            directus.claim.update({"state": "COMPLETED", "worker_completed": True})
            return 200, {"completed": True, "state": "PERSISTED"}
        raise AssertionError(operation)

    async def patch(_directus, collection, item_id, payload):
        assert collection == "chat_recovery_protocol_state" and item_id == "chat-recovery"
        assert directus.claim == {"state": "COMPLETED", "worker_completed": True,
                                 "persistence_observed": True}
        events.append("expire_tombstone")
        directus.lifecycle = payload["legacy_task_lifecycle"]
        return {}

    monkeypatch.setattr(MODULE, "_recovery_sql", transaction)
    monkeypatch.setattr(MODULE, "_patch", patch)
    call = MODULE._complete_and_retire_legacy_claim(
        directus, task_identity=task_identity, broker_id=broker_id,
        chat_id=chat_id, owner_hash=owner_hash, now=1_700_000_000,
    )
    if fault:
        with pytest.raises(RuntimeError):
            await call
        assert "expire_tombstone" not in events
    else:
        await call
        assert events.index("canonical") < events.index("acknowledge_legacy_persistence")
        assert events.index("acknowledge_legacy_persistence") < events.index(
            "mark_legacy_inference_completed") < events.index("expire_tombstone")
        assert directus.lifecycle == [] and directus.active == []
    assert directus.message is None
