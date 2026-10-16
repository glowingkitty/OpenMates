"""Engineering maintenance guards: no live accounts or services are touched."""

# contract-test-file: tooling
import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from backend.scripts import retire_mailosaur_accounts as retirement


def test_retirement_refuses_production_and_unrelated_recipients():
    retirement.require_development(
        {"SERVER_ENVIRONMENT": "development", "CMS_URL": "http://cms:8055"}
    )
    for values in (
        {"SERVER_ENVIRONMENT": "production", "CMS_URL": "http://cms:8055"},
        {"SERVER_ENVIRONMENT": "development", "CMS_URL": "https://api.openmates.org"},
        {
            "SERVER_ENVIRONMENT": "development",
            "CMS_URL": "http://cms:8055",
            "OPENMATES_CI_ISOLATED": "1",
        },
    ):
        with pytest.raises(RuntimeError):
            retirement.require_development(values)
    for email in (
        "person@example.com",
        "test@other.mailosaur.net",
        "test@ae20drx9.mailosaur.net.evil.test",
    ):
        with pytest.raises(ValueError):
            retirement.recipient_hash(email)
    assert retirement.recipient_hash(
        " Test@ae20drx9.mailosaur.net "
    ) == retirement.recipient_hash("test@ae20drx9.mailosaur.net")


def _fixture():
    digest = retirement.recipient_hash("test@ae20drx9.mailosaur.net")
    candidate = {
        "user": {"id": "fixture-user"},
        "recipient_hash": digest,
        "reminders": [{"id": "pending-reminder", "status": "pending"}],
        "workflows": [{"workflow_id": "active-workflow", "status": "active"}],
    }
    directus = Mock()

    async def read(collection, **_kwargs):
        if collection == "users":
            return [{"id": "fixture-user", "hashed_email": digest}]
        if collection == "reminders":
            return [
                {
                    "id": "pending-reminder",
                    "status": "cancelled"
                    if directus.update_item.await_count
                    else "pending",
                }
            ]
        if collection == "workflows":
            return [
                {
                    "id": "active-workflow",
                    "workflow_id": "active-workflow",
                    "status": "deleted"
                    if workflows.delete_workflow.call_count
                    else "active",
                    "enabled": not bool(workflows.delete_workflow.call_count),
                    "hashed_team_id": None,
                }
            ]
        return []

    directus.get_items = AsyncMock(side_effect=read)
    directus.create_item = AsyncMock(return_value=(True, {}))
    directus.update_user = AsyncMock(return_value=True)
    directus.revoke_user_api_keys = AsyncMock(return_value=True)
    directus.update_item = AsyncMock(return_value={"status": "cancelled"})
    cache = Mock(
        remove_reminder_from_cache=AsyncMock(return_value=True),
        delete_user_cache=AsyncMock(return_value=True),
    )
    workflows = Mock()
    return candidate, directus, cache, workflows


def test_mail_suppression_and_schedules_precede_normal_deletion():
    candidate, directus, cache, workflows = _fixture()

    def enqueue(*args):
        directus.create_item.assert_awaited_once()
        directus.update_user.assert_awaited_once_with(
            "fixture-user",
            {"email_notifications_enabled": False, "status": "suspended"},
        )
        directus.revoke_user_api_keys.assert_awaited_once_with("fixture-user")
        directus.update_item.assert_awaited_once_with(
            "reminders",
            "pending-reminder",
            {"status": "cancelled"},
            admin_required=True,
        )
        cache.remove_reminder_from_cache.assert_awaited_once_with("pending-reminder")
        workflows.delete_workflow.assert_called_once_with(
            "active-workflow", "fixture-user"
        )
        assert args[0] == "fixture-user"
        return "fixture-deletion-task"

    result = asyncio.run(
        retirement.retire_candidate(directus, cache, workflows, candidate, enqueue)
    )
    assert result["status"] == "queued"  # Queue acceptance is not deletion proof.
    assert result["reminders_cancelled"] == result["workflows_retired"] == 1
    assert "email" not in result


@pytest.mark.parametrize(
    "failure",
    [
        "identity",
        "suppression",
        "preferences",
        "api_keys",
        "reminder",
        "cache",
        "workflow",
    ],
)
def test_retirement_never_queues_deletion_after_an_unchecked_failure(failure):
    candidate, directus, cache, workflows = _fixture()
    if failure == "identity":
        directus.get_items.side_effect = [
            [{"id": "fixture-user", "hashed_email": "changed"}]
        ]
    elif failure == "suppression":
        directus.create_item.return_value = (False, None)
    elif failure == "preferences":
        directus.update_user.return_value = False
    elif failure == "api_keys":
        directus.revoke_user_api_keys.return_value = False
    elif failure == "reminder":
        directus.update_item.return_value = None
    elif failure == "cache":
        cache.remove_reminder_from_cache.return_value = False
    else:
        workflows.delete_workflow.side_effect = RuntimeError("fixture failure")
    enqueue = Mock()
    with pytest.raises(RuntimeError):
        asyncio.run(
            retirement.retire_candidate(directus, cache, workflows, candidate, enqueue)
        )
    enqueue.assert_not_called()


def test_team_ownership_blocks_retirement():
    digest = retirement.recipient_hash("test@ae20drx9.mailosaur.net")
    directus = Mock(
        get_items=AsyncMock(
            side_effect=[
                [{"id": "fixture-user", "hashed_email": digest}],
                [],
                [],
                [{"id": "owned-team", "hashed_team_id": "a" * 64}],
                [{"id": "active-team", "hashed_team_id": "a" * 64, "status": "active"}],
            ]
        )
    )
    candidates = asyncio.run(
        retirement.prepare_candidates(directus, {"test@ae20drx9.mailosaur.net"})
    )
    assert candidates[0]["blocked_reason"] == "team_ownership"


def test_new_team_ownership_after_discovery_blocks_before_any_mutation():
    candidate, directus, cache, workflows = _fixture()
    original = directus.get_items.side_effect

    async def acquired_owner(collection, **kwargs):
        return (
            [{"id": "new-owner"}]
            if collection == "team_memberships"
            else await original(collection, **kwargs)
        )

    directus.get_items.side_effect = acquired_owner
    enqueue = Mock()
    with pytest.raises(RuntimeError, match="Team ownership"):
        asyncio.run(
            retirement.retire_candidate(directus, cache, workflows, candidate, enqueue)
        )
    directus.create_item.assert_not_awaited()
    directus.update_user.assert_not_awaited()
    enqueue.assert_not_called()


def test_queued_retirement_rechecks_new_schedules_before_destructive_worker_phase():
    candidate, directus, cache, workflows = _fixture()
    with pytest.raises(RuntimeError, match="another active schedule"):
        asyncio.run(retirement.assert_retirement_ready(directus, "fixture-user"))
    directus.create_item.assert_not_awaited()
    directus.update_user.assert_not_awaited()


def test_confirmed_absent_hot_user_cache_does_not_block_retirement():
    candidate, directus, cache, workflows = _fixture()
    cache.delete_user_cache.return_value = False
    cache.USER_KEY_PREFIX = "user:"
    client = Mock(exists=AsyncMock(return_value=0))

    async def connection():
        return client

    cache.client = connection()
    result = asyncio.run(
        retirement.retire_candidate(
            directus, cache, workflows, candidate, Mock(return_value="task")
        )
    )
    assert result["status"] == "queued"
    client.exists.assert_awaited_once_with("user:fixture-user")


@pytest.mark.parametrize("still_present", [True, False])
def test_failed_or_present_cache_prevents_deletion(still_present):
    candidate, directus, cache, workflows = _fixture()
    cache.delete_user_cache.return_value = False
    cache.USER_KEY_PREFIX = "user:"
    client = Mock(exists=AsyncMock(return_value=1)) if still_present else None

    async def connection():
        return client

    cache.client = connection()
    enqueue = Mock()
    with pytest.raises(RuntimeError, match="cache absence"):
        asyncio.run(
            retirement.retire_candidate(directus, cache, workflows, candidate, enqueue)
        )
    enqueue.assert_not_called()


def test_private_receipt_cannot_follow_a_symlink(tmp_path):
    protected = tmp_path / "protected"
    protected.write_text("preserve")
    link = tmp_path / "receipt.json"
    link.symlink_to(protected)
    with pytest.raises(OSError):
        retirement.write_receipt(link, {"candidate_count": 1})
    assert protected.read_text() == "preserve"


@pytest.mark.parametrize("team_status,blocked", [("deleted", False), ("active", True)])
def test_legacy_owner_memberships_follow_current_team_tombstone(team_status, blocked):
    digest = retirement.recipient_hash("test@ae20drx9.mailosaur.net")
    team_hash = "a" * 64
    directus = Mock(
        get_items=AsyncMock(
            side_effect=[
                [{"id": "fixture-user", "hashed_email": digest}],
                [],
                [],
                [{"id": "legacy-owner", "hashed_team_id": team_hash}],
                [
                    {
                        "id": "team-row",
                        "hashed_team_id": team_hash,
                        "status": team_status,
                    }
                ],
            ]
        )
    )
    candidates = asyncio.run(
        retirement.prepare_candidates(directus, {"test@ae20drx9.mailosaur.net"})
    )
    assert bool(candidates[0]["blocked_reason"]) is blocked


def test_legacy_deleted_team_data_does_not_block_worker_recheck():
    team_hash = "a" * 64
    directus = Mock(
        get_items=AsyncMock(
            side_effect=[
                [],
                [],
                [{"id": "legacy-owner", "hashed_team_id": team_hash}],
                [{"id": "team-row", "hashed_team_id": team_hash, "status": "deleted"}],
            ]
        )
    )
    assert asyncio.run(retirement.owner_schedules(directus, "fixture-user")) == ([], [])


def test_missing_team_row_stays_protected_instead_of_being_treated_deleted():
    directus = Mock(get_items=AsyncMock(return_value=[]))
    with pytest.raises(RuntimeError, match="unavailable"):
        asyncio.run(
            retirement.has_non_deleted_team_ownership(
                directus, [{"hashed_team_id": "a" * 64}], []
            )
        )


def _legacy_workflow_row():
    owner_hash = "user_sha256:" + retirement.hashlib.sha256(b"fixture-user").hexdigest()
    return {
        "id": "workflow-primary-id",
        "workflow_id": "workflow-primary-id",
        "hashed_user_id": owner_hash,
        "hashed_team_id": None,
        "status": "active",
        "enabled": True,
        "version": 1,
        "record_json": {
            "id": "workflow-primary-id",
            "owner_hash": owner_hash,
            "status": "active",
            "enabled": True,
            "encrypted_graph_ref": "opaque-ref",
        },
    }


def test_legacy_json_missing_version_uses_checked_projection_without_mutating_source():
    row = _legacy_workflow_row()
    record = retirement.validated_workflow_record(
        row, "workflow-primary-id", "fixture-user"
    )
    assert record["version"] == 1
    assert "version" not in row["record_json"]
    assert record["encrypted_graph_ref"] == "opaque-ref"


@pytest.mark.parametrize(
    "defect",
    [
        "primary_id",
        "public_id",
        "record_id",
        "owner",
        "record_owner",
        "team",
        "record_team",
        "status",
        "enabled",
        "version",
        "record_version",
    ],
)
def test_legacy_normalization_rejects_unchecked_context_or_version(defect):
    row = _legacy_workflow_row()
    if defect == "primary_id":
        row["id"] = "other"
    elif defect == "public_id":
        row["workflow_id"] = "other"
    elif defect == "record_id":
        row["record_json"]["id"] = "other"
    elif defect == "owner":
        row["hashed_user_id"] = "other-owner"
    elif defect == "record_owner":
        row["record_json"]["owner_hash"] = "other-owner"
    elif defect == "team":
        row["hashed_team_id"] = "team-context"
    elif defect == "record_team":
        row["record_json"]["hashed_team_id"] = "team-context"
    elif defect == "status":
        row["record_json"]["status"] = "deleted"
    elif defect == "enabled":
        row["record_json"]["enabled"] = False
    elif defect == "version":
        row["version"] = None
    elif defect == "record_version":
        row["record_json"]["version"] = 2
    with pytest.raises(RuntimeError, match="workflow"):
        retirement.validated_workflow_record(row, "workflow-primary-id", "fixture-user")


def test_normal_workflow_delete_keeps_authoring_version_fence_for_legacy_json():
    from backend.core.api.app.services.workflow_service import WorkflowService

    repository = retirement.create_retirement_workflow_repository()
    try:
        repository._find_one = Mock(return_value=_legacy_workflow_row())
        service = WorkflowService(repository=repository)
        service.apply_authoring_batch = Mock(return_value=[])
        assert service.delete_workflow("workflow-primary-id", "fixture-user")
        assert service.apply_authoring_batch.call_args.args[1] == [
            {
                "type": "delete",
                "workflow_id": "workflow-primary-id",
                "expected_record_version": 1,
            }
        ]
        filters = repository._find_one.call_args.args[1]["_and"]
        assert filters[0] == {"id": {"_eq": "workflow-primary-id"}}
        assert filters[1]["hashed_team_id"] == {"_null": True}
        with pytest.raises(RuntimeError, match="Team workflows"):
            repository.get_workflow(
                "workflow-primary-id", "fixture-user", team_id="team"
            )
    finally:
        repository._client.close()


def test_schedule_retirement_uses_primary_id_even_when_legacy_public_field_missing():
    candidate, directus, cache, workflows = _fixture()
    original = directus.get_items.side_effect

    async def projection_without_public_id(collection, **kwargs):
        rows = await original(collection, **kwargs)
        if collection == "workflows":
            for row in rows:
                row.pop("workflow_id", None)
        return rows

    directus.get_items.side_effect = projection_without_public_id
    result = asyncio.run(
        retirement.retire_candidate(
            directus, cache, workflows, candidate, Mock(return_value="task")
        )
    )
    assert result["status"] == "queued"
    workflows.delete_workflow.assert_called_once_with("active-workflow", "fixture-user")


def _transaction_record():
    record = retirement.validated_workflow_record(
        _legacy_workflow_row(), "workflow-primary-id", "fixture-user"
    )
    record.update(
        updated_at=1,
        created_at=1,
        current_version_id="graph-version",
        encrypted_title_ref="vault://workflows/title",
        encrypted_title_checksum="sha256:" + "b" * 64,
        encrypted_graph_ref="vault://workflows/graph",
        encrypted_graph_checksum="sha256:" + "b" * 64,
        versions=[
            {
                "id": "graph-version",
                "version_number": 1,
                "encrypted_graph_ref": "vault://workflows/graph",
                "encrypted_graph_checksum": "sha256:" + "b" * 64,
                "created_at": 1,
            }
        ],
    )
    return record


def test_admin_deletion_keeps_opaque_legacy_graph_refs_without_hydration():
    record = _transaction_record()
    repository = retirement.create_retirement_workflow_repository()
    try:
        repository.get_workflow = Mock(return_value=record)
        repository.get_workflow_including_deleted = Mock(
            return_value={**record, "status": "deleted", "enabled": False, "version": 2}
        )
        captured = []

        def commit(method, path, *, payload):
            captured.append(payload)
            return {
                key: payload[key]
                for key in ("owner_hash", "operation_id", "request_hash", "outcomes")
            }

        repository.authoring_request = Mock(side_effect=commit)
        service = retirement.create_retirement_workflow_service(repository)
        service.apply_authoring_batch = Mock(
            side_effect=AssertionError("legacy graph hydration is forbidden")
        )
        service._detail_from_record = Mock(
            side_effect=AssertionError("legacy graph hydration is forbidden")
        )
        assert service.delete_workflow("workflow-primary-id", "fixture-user")
        payload = captured[0]
        assert payload["writes"][0]["expected_version"] == 1
        assert payload["writes"][0]["trigger"] is None
        assert (
            payload["writes"][0]["record"]["encrypted_graph_ref"]
            == record["encrypted_graph_ref"]
        )
        assert payload["writes"][0]["record"]["versions"] == record["versions"]
        assert payload["mutations"][0]["encrypted_before_ref"] is None
        assert payload["blobs"] == payload["obsolete_refs"] == []
        repository.authoring_request.assert_called_once_with(
            "POST", "/", payload=payload
        )
        service.apply_authoring_batch.assert_not_called()
        service._detail_from_record.assert_not_called()
    finally:
        repository._client.close()


@pytest.mark.parametrize("defect", ["owner", "version", "team", "claimed_trigger"])
def test_admin_transaction_uses_real_cms_commit_guards_and_output_fences(defect):
    import json
    from pathlib import Path
    import subprocess

    root = Path(__file__).resolve().parents[2]
    operations = (
        root
        / "backend/core/directus/extensions/workflow-authoring-transaction/src/operations.js"
    )
    existing_test = (
        root
        / "backend/core/directus/extensions/workflow-authoring-transaction/test/operations.test.js"
    )
    # Reuse the extension's existing transaction fixture, and execute its actual
    # owner/version/reference/trigger/output guard code without a real database.
    fixture_source = (
        existing_test.read_text()
        .split("class Query {", 1)[1]
        .split("\nfunction createBody(", 1)[0]
    )
    fixture_source = "class Query {" + fixture_source
    record = _transaction_record()
    payload = retirement.workflow_retirement_transaction(
        record, operation_id="retirement-probe", now=2
    )
    source = 'import assert from "node:assert/strict";\n'
    source += f"import {{ executeAuthoring, AuthoringError }} from {json.dumps(operations.as_uri())};\n"
    source += fixture_source
    source += (
        "\nconst record = "
        + json.dumps(record)
        + ";\nconst payload = "
        + json.dumps(payload)
        + ";\n"
    )
    source += r"""
const db = new FakeDatabase();
const graphCiphertext = 'vault:v1:legacy-Ask-AI-tools-and-conversation';
db.tables.workflows.push({id:record.id,workflow_id:record.id,hashed_user_id:record.owner_hash,
  hashed_team_id:null,version:1,status:'active',enabled:true,updated_at:1,
  record_json:JSON.stringify(record)});
db.tables.workflow_encrypted_blobs.push(...['title','graph'].map(kind=>({
  id:kind,ref:record[`encrypted_${kind}_ref`],hashed_user_id:record.owner_hash,
  checksum:record[`encrypted_${kind}_checksum`],ciphertext:graphCiphertext})));
db.tables.workflow_triggers.push({id:'trigger',workflow_id:record.id,hashed_user_id:record.owner_hash,
  enabled:true,claim_status:null});
db.tables.workflow_chat_deliveries.push({id:'delivery',workflow_id:record.id,
  hashed_user_id:record.owner_hash.replace(/^user_sha256:/,''),status:'queued',client_persisted_at:null,
  encrypted_payload:'opaque-output',claim_generation:2,claim_token_hash:'claim',revision:1});
const original = structuredClone(db.tables);
const bad = structuredClone(original);
"""
    if defect == "owner":
        source += 'bad.workflows[0].hashed_user_id="user_sha256:"+"c".repeat(64);\n'
    elif defect == "version":
        source += "bad.workflows[0].version=2;\n"
    elif defect == "team":
        source += 'bad.workflows[0].hashed_team_id="d".repeat(64);\n'
    else:
        source += 'bad.workflow_triggers[0].claim_status="claimed";\n'
    expected_code = "trigger_claim_conflict" if defect == "claimed_trigger" else "head_conflict"
    source += "const expectedCode=" + json.dumps(expected_code) + ";\n"
    source += r"""
db.tables=bad;
await assert.rejects(executeAuthoring(db,'/',payload),error=>error instanceof AuthoringError&&error.code===expectedCode);
assert.deepEqual(db.tables,bad);
db.tables=structuredClone(original);
const receipt=await executeAuthoring(db,'/',payload);
assert.equal(receipt.outcomes[0].version,2);
assert.equal(db.tables.workflows[0].status,'deleted');
assert.equal(db.tables.workflows[0].enabled,false);
assert.equal(db.tables.workflow_triggers.length,0);
assert.equal(db.tables.workflow_chat_deliveries[0].status,'cancelled');
assert.equal(db.tables.workflow_chat_deliveries[0].encrypted_payload,'');
assert.equal(db.tables.workflow_chat_deliveries[0].claim_generation,3);
assert.ok(db.tables.workflow_encrypted_blobs.every(blob=>blob.ciphertext===graphCiphertext));
assert.deepEqual(await executeAuthoring(db,'/',payload),receipt);
assert.equal(db.tables.workflow_authoring_operations.length,1);
console.log('normal atomic retirement guards passed');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-"],
        input=source,
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "normal atomic retirement guards passed"
