"""Disposable full-stack fixtures executed only inside the isolated CI API container.

The Playwright spec passes this file to ``python -c``; no source mount is needed.
Every ID and Vault key is generated for one case and removed in its finally block.
"""
# contract-test-file: infrastructure

import asyncio
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

assert os.environ.get("OPENMATES_CI_ISOLATED") == "1"


async def orphan_reminder(data):
    from backend.apps.reminder.tasks import _process_due_reminders_async
    from backend.core.api.app.tasks.base_task import BaseServiceTask
    from backend.core.api.app.tasks.celery_config import app
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.utils.encryption import EncryptionService

    reminder_id, owner_id = data["reminder_id"], data["owner_id"]
    cache = CacheService()
    encryption = EncryptionService(cache_service=cache)
    directus = DirectusService(cache_service=cache, encryption_service=encryption)
    key_id = None
    created = False
    try:
        owner_rows = await directus.get_items(
            "users", params={"filter[id][_eq]": owner_id, "fields": "id", "limit": 1},
            admin_required=True, no_cache=True, raise_on_error=True,
        )
        assert owner_rows == [], "Disposable owner UUID must not exist"
        key_id = await encryption.create_user_key()
        encrypted_owner, _ = await encryption.encrypt_with_user_key(owner_id, key_id)
        encrypted_prompt, _ = await encryption.encrypt_with_user_key("isolated orphan reminder", key_id)
        now = int(time.time())
        row = {
            "id": reminder_id, "hashed_user_id": hashlib.sha256(owner_id.encode()).hexdigest(),
            "encrypted_user_id": encrypted_owner, "encrypted_prompt": encrypted_prompt,
            "vault_key_id": key_id, "trigger_type": "specific", "trigger_at": now - 2,
            "target_type": "new_chat", "status": "pending", "response_type": "simple",
            "repeat_config": {"type": "daily", "interval": 1},
            "occurrence_count": 0, "created_at": now - 60, "timezone": "UTC",
        }
        assert await directus.reminder.create_reminder(row), "Failed to seed Directus reminder"
        created = True
        assert await cache.load_reminder_into_cache(row), "Failed to seed due cache"
        client = await cache.client
        assert await client.zscore("reminders:schedule", reminder_id) is not None
        assert await client.llen(f"reminder_pending_delivery:{owner_id}") == 0
        prior_chats = await directus.get_items(
            "chats", params={"filter[hashed_user_id][_eq]": row["hashed_user_id"], "fields": "id", "limit": 10},
            admin_required=True, no_cache=True, raise_on_error=True,
        )
        assert prior_chats == []

        # Use the real task services without initializing unrelated payment/S3 providers.
        # The reminder code calls initialize_services itself; core services are sufficient.
        class ReminderTask(BaseServiceTask):
            async def initialize_services(self):
                await self.initialize_core_services()

        for invocation in range(2):
            task = ReminderTask()
            # A standalone Celery Task must be bound before its request property
            # can read request_stack.top during core-service initialization.
            task.bind(app)
            task.push_request(id=f"ci-orphan-reminder-{reminder_id}-{invocation}")
            try:
                result = await _process_due_reminders_async(task)
            finally:
                task.pop_request()
            expected = {"success": True, "processed": 0, "errors": 0} if invocation == 0 else {"success": True, "processed": 0}
            assert result == expected, result
            durable = await directus.reminder.get_reminder(reminder_id)
            assert durable is not None
            assert durable["status"] == "cancelled", durable
            assert durable["occurrence_count"] == 0, durable
            assert await cache.get_reminder(reminder_id) is None
            assert await client.zscore("reminders:schedule", reminder_id) is None
            assert await client.llen(f"reminder_pending_delivery:{owner_id}") == 0
            chats = await directus.get_items(
                "chats", params={"filter[hashed_user_id][_eq]": row["hashed_user_id"], "fields": "id", "limit": 10},
                admin_required=True, no_cache=True, raise_on_error=True,
            )
            assert chats == [], chats
        return {"status": "cancelled", "occurrence_count": 0, "repeat_fired": False}
    finally:
        await cache.remove_reminder_from_cache(reminder_id)
        if created:
            await directus.delete_item("reminders", reminder_id, admin_required=True)
        if key_id:
            assert await encryption.delete_user_key(key_id), "Fixture Vault key cleanup failed"
        await directus.close()
        await cache.close()


async def leaderboard_snapshot(data):
    from backend.scripts import aggregate_leaderboards as aggregate
    from backend.scripts.fetch_lmarena_rankings import parse_lmarena_markdown, validate_rankings
    from backend.core.api.app.tasks import leaderboard_tasks
    from backend.core.api.app.services.cache import CacheService

    registry = aggregate.load_provider_models()
    aliases = [config["external_ids"]["lmarena"] for config in registry.values()
               if isinstance(config.get("external_ids", {}).get("lmarena"), str)]
    assert aliases, "Provider registry has no LMArena aliases"
    # External feed fixture uses the current seven-column shape and multiple
    # model families/organizations; aliases come from the real provider registry.
    names = list(dict.fromkeys(aliases[:6] + [
        "gpt-ci-model", "gemini-ci-model", "claude-ci-model", "grok-ci-model",
    ]))
    while len(names) < 30:
        names.append(f"{['gpt', 'gemini', 'claude', 'grok'][len(names) % 4]}-ci-{len(names)}")
    names = names[:30]
    orgs = ["OpenAI", "Google", "Anthropic", "xAI"]
    header = "| Rank | Spread | Model | Score | Votes | Price | Context |\n| --- | --- | --- | --- | --- | --- | --- |"
    lines = [f"| {i + 1} | 1 | [{name}](https://arena.ai/model/{i}) {orgs[i % 4]} · Proprietary | {1500 - i * 8}±9Preliminary | {30000 - i * 100:,} | $1.00 | 128K |"
             for i, name in enumerate(names)]
    markdown = header + "\n" + "\n".join(lines)
    parsed = parse_lmarena_markdown(markdown, "text")
    validation = validate_rankings(parsed, "text", markdown)
    assert len(parsed) == 30 and validation["valid"], validation
    assert all(row["organization"] in orgs for row in parsed), parsed[:3]
    lmarena_data = {"source": "https://arena.ai/leaderboard/text/overall", "category": "text",
                    "rankings": parsed, "validation": validation}
    async def external_arena(*, category):
        assert category == "text"
        return lmarena_data
    async def external_router():
        return {"source": "isolated-external-fixture", "leaderboard": [],
                "validation": {"valid": True}}
    original_arena, original_router = aggregate.fetch_lmarena_data, aggregate.fetch_openrouter_data
    aggregate.fetch_lmarena_data, aggregate.fetch_openrouter_data = external_arena, external_router
    cache = CacheService()
    client = await cache.client
    key = leaderboard_tasks.LEADERBOARD_CACHE_KEY
    prior = await client.get(key)
    prior_ttl = await client.pttl(key)
    try:
        with tempfile.TemporaryDirectory(prefix="ci-leaderboard-") as folder:
            output_path = Path(folder) / "snapshot.yml"
            output = await aggregate.aggregate_leaderboards(
                category="text", output_path=output_path,
            )
            assert output["metadata"]["sources"]["lmarena"]["valid"] is True
            assert output["rankings"], "Real registry aliases must produce ranked models"
            assert any(row["model_id"] in registry for row in output["rankings"])
            assert await leaderboard_tasks._update_cache_async(output)
            assert await leaderboard_tasks.get_leaderboard_data() == output
            saved = output_path.read_bytes()
            cached = await client.get(key)

            async def broken_arena(*, category):
                return {"rankings": [], "validation": {"valid": False}}
            aggregate.fetch_lmarena_data = broken_arena
            try:
                await aggregate.aggregate_leaderboards(category="text", output_path=output_path)
            except ValueError as exc:
                assert "failed validation" in str(exc)
            else:
                raise AssertionError("Invalid external feed replaced the good snapshot")
            assert output_path.read_bytes() == saved
            assert await client.get(key) == cached
            assert await leaderboard_tasks.get_leaderboard_data() == output
            return {"parsed_rows": len(parsed), "ranked_models": len(output["rankings"]),
                    "source_valid": True, "invalid_feed_preserved_snapshot": True}
    finally:
        aggregate.fetch_lmarena_data, aggregate.fetch_openrouter_data = original_arena, original_router
        if prior is None:
            await client.delete(key)
        elif prior_ttl > 0:
            await client.set(key, prior, px=prior_ttl)
        else:
            await client.set(key, prior)
        await cache.close()


async def legacy_workflow_readiness(data):
    from datetime import datetime, timedelta, timezone
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.services.workflow_models import (
        WorkflowLifecycle, WorkflowRunStatus, WorkflowValidationError,
    )
    from backend.core.api.app.services.workflow_runtime_service import WorkflowRuntimeService
    from backend.core.api.app.services.workflow_service import DirectusWorkflowRepository, WorkflowService
    from backend.core.api.app.tasks.workflow_tasks import run_scheduled_workflow_trigger_now

    owner_id = data["owner_id"]
    repository = DirectusWorkflowRepository()
    service = WorkflowService(repository=repository)
    directus = DirectusService()
    workflow = None
    try:
        owner_key = repository.get_user_vault_key_id(owner_id)
        assert owner_key, "Disposable owner requires a real Vault key"
        future = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        graph = {
            "version": 1, "trigger_node_id": "trigger",
            "nodes": [
                {"id": "trigger", "type": "schedule_trigger",
                 "config": {"schedule": {"type": "once", "at": future}}},
                {"id": "end", "type": "end", "config": {}},
            ],
            "edges": [{"from": "trigger", "to": "end"}],
        }
        workflow = service.create_workflow(
            owner_id, f"isolated legacy readiness {data['fixture_id']}", graph,
            enabled=False, lifecycle=WorkflowLifecycle.TEMPORARY,
            vault_key_id=owner_key,
        )
        head = repository._find_one(repository.WORKFLOWS, {"workflow_id": {"_eq": workflow.id}})
        trigger = repository._find_one(repository.TRIGGERS, {"workflow_id": {"_eq": workflow.id}})
        assert head and trigger, "Disabled workflow must persist a schedule trigger"
        assert head["hashed_user_id"] == trigger["hashed_user_id"]
        assert head["workflow_id"] == trigger["workflow_id"] == workflow.id
        assert trigger["owner_user_id"] == owner_id
        assert head["record_json"]["enabled"] is False and trigger["enabled"] is False
        assert trigger["encrypted_schedule_config_ref"], "Real schedule Vault blob missing"
        due = int(time.time()) - 2
        # Simulate only this fixture's pre-activation-guard durable state.
        legacy_head = {**head["record_json"], "enabled": True, "next_run_at": due}
        repository._patch_item(repository.WORKFLOWS, head["id"], {
            "enabled": True, "next_run_at": due, "record_json": legacy_head,
        })
        repository._patch_item(repository.TRIGGERS, trigger["id"], {
            "enabled": True, "next_run_at": due,
        })
        started = int(time.time())
        try:
            await run_scheduled_workflow_trigger_now(
                trigger["trigger_id"], runtime_service=WorkflowRuntimeService(directus),
                workflow_service=service,
            )
        except WorkflowValidationError as exc:
            assert str(exc) == "Workflow readiness requires a reachable qualifying effect"
        else:
            raise AssertionError("Legacy schedule without an effect was not rejected")
        runs = service.list_runs(workflow.id, owner_id, owner_key)
        assert len(runs) == 1, runs
        failed = service.get_run(workflow.id, runs[0].id, owner_id, owner_key)
        assert failed.status == WorkflowRunStatus.FAILED, failed
        assert failed.error_summary == "Workflow readiness requires a reachable qualifying effect"
        assert failed.started_at and started <= failed.finished_at <= int(time.time())
        assert failed.node_runs == [] and failed.output_summary == {}
        assert service.get_workflow(workflow.id, owner_id, owner_key).enabled is True
        assert repository._get_items(
            "workflow_delivery_history", {"workflow_id": {"_eq": workflow.id}}, fields="id",
        ) == []
        assert repository._get_items(
            "workflow_chat_deliveries", {"workflow_id": {"_eq": workflow.id}}, fields="id",
        ) == []
        return {"run_status": "failed", "error_summary": failed.error_summary,
                "node_runs": len(failed.node_runs), "finished_immediately": True}
    finally:
        if workflow is not None:
            # Atomic expiration removes only this temporary fixture's definition,
            # trigger, runs, versions, and encrypted Vault blob references.
            head = repository._find_one(repository.WORKFLOWS, {"workflow_id": {"_eq": workflow.id}})
            if head is not None:
                assert head["workflow_id"] == workflow.id
                cutoff = int(time.time())
                expired = {**head["record_json"], "auto_delete_at": cutoff - 1}
                repository._patch_item(repository.WORKFLOWS, head["id"], {
                    "auto_delete_at": cutoff - 1, "record_json": expired,
                })
                repository.expire_temporary_workflow(expired, cutoff)
        await directus.close()
        repository._client.close()


async def main():
    data = json.load(sys.stdin)
    if data.get("operation") == "orphan_reminder":
        result = await orphan_reminder(data)
    elif data.get("operation") == "leaderboard_snapshot":
        result = await leaderboard_snapshot(data)
    elif data.get("operation") == "legacy_workflow_readiness":
        result = await legacy_workflow_readiness(data)
    else:
        raise ValueError("Unknown isolated fixture operation")
    print(json.dumps(result, sort_keys=True))


asyncio.run(main())
