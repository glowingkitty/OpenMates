"""Disposable full-stack fixtures executed only inside the isolated CI API container.

The Playwright spec passes this file to ``python -c``; no source mount is needed.
Every ID and Vault key is generated for one case and removed in its finally block.
"""
# contract-test-file: infrastructure

import asyncio
import base64
import hashlib
import json
import os
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

assert os.environ.get("OPENMATES_CI_ISOLATED") == "1"


async def billing_snapshot(data):
    """Return aggregate billing state for one disposable signed replay identity."""
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.utils.encryption import EncryptionService

    assert os.environ.get("OPENMATES_STORAGE_CAPACITY_FIXTURES") == "true"
    assert os.environ.get("MOCK_EXTERNAL_APIS") == "true"
    email = data.get("account_email")
    assert isinstance(email, str) and email.startswith("ci-") and email.endswith("@example.com")
    cache = CacheService()
    encryption = EncryptionService(cache_service=cache)
    directus = DirectusService(cache_service=cache, encryption_service=encryption)
    try:
        email_hash = base64.b64encode(hashlib.sha256(email.strip().lower().encode()).digest()).decode()
        users = await directus.get_items(
            "users", params={"filter[hashed_email][_eq]": email_hash,
                             "fields": "id,email,hashed_email,vault_key_id,encrypted_credit_balance", "limit": 2},
            admin_required=True, no_cache=True, raise_on_error=True,
        )
        if (len(users) != 1 or users[0].get("hashed_email") != email_hash
                or users[0].get("email") != email_hash[:64] + "@example.com"):
            return {"status": "identity_unavailable"}
        user = users[0]
        user_id = user.get("id")
        try:
            if str(uuid.UUID(user_id, version=4)) != user_id:
                return {"status": "identity_unavailable"}
        except (TypeError, ValueError, AttributeError):
            return {"status": "identity_unavailable"}
        balance_text = await encryption.decrypt_with_user_key(
            user["encrypted_credit_balance"], user["vault_key_id"])
        balance = int(balance_text)
        owner_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()

        async def rows(collection, field, fields):
            found = await directus.get_items(
                collection, params={f"filter[{field}][_eq]": owner_hash,
                                    "fields": fields, "limit": 201},
                admin_required=True, no_cache=True, raise_on_error=True,
            )
            if len(found) > 200:
                raise ValueError("Billing snapshot exceeds the disposable account bound")
            return found

        reservations = await rows("billing_reservations", "subject_hash", "charge_id,quoted_credits,state,subject_kind,review_after_at")
        reservations = [row for row in reservations if row.get("subject_kind") == "personal"]
        settlements = await rows("billing_settlement_outbox", "hashed_user_id", "charge_id,state")
        charges = await rows("billing_charge_identities", "hashed_user_id", "charge_id")
        held = [row for row in reservations if row.get("state") == "reserved"]
        now = datetime.now(timezone.utc)
        def review_due(row):
            value = row.get("review_after_at")
            if not value:
                return False
            due_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return (due_at if due_at.tzinfo else due_at.replace(tzinfo=timezone.utc)) <= now

        overdue_held = [row for row in held if review_due(row)]
        held_ids = {row["charge_id"] for row in held}
        committed_ids = {row["charge_id"] for row in charges}
        pending_states = ("pending", "retry_scheduled", "manual_review")
        unmatched = [row for row in settlements if row.get("state") in pending_states
                     and row.get("charge_id") not in held_ids | committed_ids]
        return {
            "status": "ok",
            "balance_credits": balance,
            "active_held_count": len(held),
            "active_held_credits": sum(int(row["quoted_credits"]) for row in held),
            "overdue_held_count": len(overdue_held),
            "reservation_status": {state: sum(row.get("state") == state for row in reservations)
                                   for state in ("reserved", "settled", "released")},
            "unmatched_settlement_count": len(unmatched),
            "unmatched_settlement_status": {state: sum(row.get("state") == state for row in unmatched)
                                             for state in pending_states},
        }
    except Exception:
        # The diagnostic must never print an account selector, ciphertext, or a
        # Directus exception containing private request parameters.
        return {"status": "unavailable"}
    finally:
        await directus.close()
        await cache.close()


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


async def recent_task_activity(data):
    """Exercise fractional recent-Task discovery against integer Directus Activity."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from backend.apps.ai.processing.related_work import fetch_related_task_candidates
    from backend.core.api.app.services.directus import DirectusService
    from backend.shared.python_utils.recent_work_summary_cache import RECENT_WORK_WINDOW_SECONDS
    from types import SimpleNamespace

    owner_id = data["owner_id"]
    fixture_id = data["fixture_id"]
    assert str(uuid.UUID(owner_id, version=4)) == owner_id
    assert str(uuid.UUID(fixture_id, version=4)) == fixture_id
    owner_hash = hashlib.sha256(owner_id.encode()).hexdigest()
    team_id = str(uuid.uuid4())
    team_hash = hashlib.sha256(team_id.encode()).hexdigest()
    now_whole = int(time.time())
    now = now_whole + 0.75
    cutoff = now_whole - RECENT_WORK_WINDOW_SECONDS
    directus = DirectusService()
    created = []

    def encrypted(value):
        key = AESGCM.generate_key(bit_length=256)
        nonce = os.urandom(12)
        return base64.b64encode(nonce + AESGCM(key).encrypt(nonce, value.encode(), None)).decode()

    async def create(collection, record):
        success, row = await directus.create_item(collection, record, admin_required=True)
        assert success and isinstance(row, dict) and row.get("id"), f"Could not create isolated {collection}"
        created.append((collection, row["id"]))
        return row

    try:
        owner = await directus.get_items("users", params={
            "filter[id][_eq]": owner_id, "fields": "id,vault_key_id", "limit": 1,
        }, admin_required=True, no_cache=True, raise_on_error=True)
        assert len(owner) == 1 and owner[0]["id"] == owner_id and owner[0].get("vault_key_id")
        await create("teams", {
            "team_id": team_id, "hashed_team_id": team_hash, "slug": f"ci-{fixture_id[:12]}",
            "encrypted_name": encrypted("isolated related work team"),
            "encrypted_profile_image_metadata": encrypted("{}"), "security_policy": {},
            "created_by_user_hash": owner_hash, "status": "active",
            "created_at": now_whole, "updated_at": now_whole,
        })
        await create("team_memberships", {
            "hashed_team_id": team_hash, "hashed_user_id": owner_hash, "user_id": owner_id,
            "role": "owner", "status": "active", "joined_at": now_whole,
            "created_at": now_whole, "updated_at": now_whole,
        })
        await directus.team.require_team_role(team_id, owner_id, {"owner"})

        task_ids = {}
        summaries = []
        for scope in ("personal", "team"):
            for recency, created_at in (("before", cutoff), ("inside", cutoff + 1)):
                task_id = str(uuid.uuid4())
                task_ids[(scope, recency)] = task_id
                task_scope = {"hashed_user_id": owner_hash,
                              "hashed_team_id": team_hash if scope == "team" else None}
                await create("user_tasks", {
                    "task_id": task_id, **task_scope, "status": "done", "assignee_type": "user",
                    "assignee_hash": owner_hash, "version": 1,
                    "encrypted_title": encrypted("isolated related work task"),
                    "created_at": now_whole, "updated_at": now_whole,
                })
                await create("user_task_activity", {
                    "task_id": task_id, "hashed_task_id": hashlib.sha256(task_id.encode()).hexdigest(),
                    "entry_id": str(uuid.uuid4()), **task_scope, "kind": "comment",
                    "actor_type": "user", "actor_hash": owner_hash,
                    "event_type": "comment_added", "source_surface": "cli",
                    "created_at": created_at, "encrypted_message": encrypted("isolated comment"),
                })
                summaries.append({"id": task_id, "summary": "disposable authorized task", "version": 1})

        observed = {}
        for scope in ("personal", "team"):
            request = SimpleNamespace(user_id=owner_id, team_id=team_id if scope == "team" else None)
            candidates = await fetch_related_task_candidates(
                request, directus, client_summaries=summaries, now=now,
            )
            observed[scope] = {candidate.id: candidate.meaningful_changed_at for candidate in candidates}
            assert set(observed[scope]) == {task_ids[(scope, "before")], task_ids[(scope, "inside")]}
            assert observed[scope][task_ids[(scope, "before")]] is None
            assert observed[scope][task_ids[(scope, "inside")]] == cutoff + 1
        return {"personal_scope": True, "team_scope": True,
                "fractional_query_succeeded": True, "exact_boundary_preserved": True}
    finally:
        cleanup_failures = []
        for collection, row_id in reversed(created):
            try:
                if not await directus.delete_item(collection, row_id, admin_required=True):
                    cleanup_failures.append(collection)
            except Exception:
                cleanup_failures.append(collection)
        await directus.close()
        assert not cleanup_failures, f"Isolated cleanup failed for {cleanup_failures}"


async def openrouter_health_probe(data):
    """Prove health status through the real probe, wrapper, HTTP client, and Redis."""
    import httpx
    from backend.apps.ai.llm_providers import openai_openrouter, openrouter_client
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.tasks import health_check_tasks as health

    fixture_id = data["fixture_id"]
    assert str(uuid.UUID(fixture_id, version=4)) == fixture_id
    cache_key_prefix = f"ci:openrouter:health:{fixture_id}:"
    cache_key = f"{cache_key_prefix}openrouter"
    cache = CacheService()
    client = await cache.client
    assert client is not None and await client.get(cache_key) is None
    assert health._get_cheapest_model_for_server("openrouter") == "mistral/mistral-small-latest"

    class PlaceholderSecrets:
        async def initialize(self):
            return True

        async def aclose(self):
            pass

    async def placeholder_key(_secrets_manager):
        return "ci-openrouter-placeholder"

    async def discard_event(**_kwargs):
        # Health transition history is outside this isolated routing proof.
        pass

    statuses = [429, 429, 429, 200, 401]
    captured = []

    def handler(request):
        assert str(request.url) == openrouter_client.OPENROUTER_API_URL
        assert request.headers["Authorization"] == "Bearer ci-openrouter-placeholder"
        payload = json.loads(request.content)
        captured.append(payload)
        assert payload["models"] == [
            "mistralai/mistral-small-2603", "deepseek/deepseek-v4-flash",
        ]
        assert "model" not in payload
        assert payload["messages"] == [
            {"role": "system", "content": "Answer short"},
            {"role": "user", "content": "1+2?"},
        ]
        status = statuses.pop(0)
        if status == 200:
            return httpx.Response(200, json={
                "model": "deepseek/deepseek-v4-flash",
                "choices": [{"message": {"content": "3"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
            })
        return httpx.Response(status, json={"error": {"message": "isolated probe failure"}})

    original_client = openrouter_client.httpx.AsyncClient
    original_secrets = health.SecretsManager
    original_prefix = health.HEALTH_CHECK_CACHE_KEY_PREFIX
    original_event = health._record_health_event_if_changed
    original_key = openai_openrouter._get_openrouter_api_key
    try:
        openrouter_client.httpx.AsyncClient = lambda **kwargs: original_client(
            transport=httpx.MockTransport(handler), **kwargs,
        )
        health.SecretsManager = PlaceholderSecrets
        health.HEALTH_CHECK_CACHE_KEY_PREFIX = cache_key_prefix
        health._record_health_event_if_changed = discard_event
        openai_openrouter._get_openrouter_api_key = placeholder_key

        observed = []
        observed_counts = []
        for expected_status, expected_count in [
            ("healthy", 1), ("healthy", 2), ("unhealthy", 3),
            ("healthy", 0), ("unhealthy", 1),
        ]:
            result = await health._check_provider_health("openrouter")
            assert len(captured) == len(observed) + 1, "Each probe must send one completion POST"
            cached = json.loads(await client.get(cache_key))
            assert result["status"] == cached["status"] == expected_status
            assert result["consecutive_failures"] == cached["consecutive_failures"] == expected_count
            observed.append(expected_status)
            observed_counts.append(result["consecutive_failures"])
        assert result["last_error"] == "credential_error"
        assert statuses == [] and len(captured) == 5
        return {"statuses": observed, "failure_counts": observed_counts,
                "request_count": len(captured), "auth_error": result["last_error"]}
    finally:
        openrouter_client.httpx.AsyncClient = original_client
        health.SecretsManager = original_secrets
        health.HEALTH_CHECK_CACHE_KEY_PREFIX = original_prefix
        health._record_health_event_if_changed = original_event
        openai_openrouter._get_openrouter_api_key = original_key
        await client.delete(cache_key)
        await cache.close()


async def main():
    data = json.load(sys.stdin)
    if data.get("operation") == "orphan_reminder":
        result = await orphan_reminder(data)
    elif data.get("operation") == "leaderboard_snapshot":
        result = await leaderboard_snapshot(data)
    elif data.get("operation") == "legacy_workflow_readiness":
        result = await legacy_workflow_readiness(data)
    elif data.get("operation") == "billing_snapshot":
        result = await billing_snapshot(data)
    elif data.get("operation") == "recent_task_activity":
        result = await recent_task_activity(data)
    elif data.get("operation") == "openrouter_health_probe":
        result = await openrouter_health_probe(data)
    else:
        raise ValueError("Unknown isolated fixture operation")
    print(json.dumps(result, sort_keys=True))


asyncio.run(main())
