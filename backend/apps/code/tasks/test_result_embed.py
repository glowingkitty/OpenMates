# backend/apps/code/tasks/test_result_embed.py
# contract-test-file: infrastructure
#
# Test result embed (code/test_result). Turns a finished TestRunResult (contract:
# docs/plans/agentic-tests-and-git-sync/contracts/test-run.md) into the
# encrypted embed content that clients decode: summary, ordered steps and
# evidence references. Evidence bytes never enter the embed; evidence entries
# carry the encrypted artifact `asset_id`. The embed links the code/application
# embeds (or Project files) it tested and the revisions it ran against, and is
# re-flagged stale when those revisions change (result_is_current()).
# Assertion: code-run.tests.recorded-evidence.

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime
from typing import Any

from toon_format import decode, encode

from backend.shared.python_schemas.code_test_run import (
    ProjectFileRevision,
    TestRunResult,
    result_is_current,
)

logger = logging.getLogger(__name__)

TEST_RESULT_EMBED_TYPE = "test_result"
TEST_RESULT_FRONTEND_TYPE = "code-test-result"
TEST_RESULT_APP_ID = "code"
TEST_RESULT_SKILL_ID = "test_result"
STALE_REASON_REVISIONS_CHANGED = "revisions_changed"
# Fixed namespace: one execution always maps to the same test result embed id.
_TEST_RESULT_EMBED_NAMESPACE = uuid.UUID("5b0c3e8e-2f4a-4d55-9a57-6f1d8c0e7a21")


def run_result_embed_id(execution_id: str) -> str:
    """Id of the test result embed of one Code Run execution.

    Known before the run ends, so a chat-bound run without a target embed stores
    its evidence under this id; the owner-checked generated-assets download-url
    route then finds the embed that references the evidence.
    """
    return str(uuid.uuid5(_TEST_RESULT_EMBED_NAMESPACE, f"test_result:{execution_id}"))


def build_test_result_content(
    result: dict[str, Any],
    *,
    embed_ref: str,
    execution_id: str | None = None,
    project_id: str | None = None,
    tested_embed_ids: list[str] | None = None,
    current_revisions: list[ProjectFileRevision] | None = None,
) -> dict[str, Any]:
    """Validate a result dict and build the embed content mapping.

    Only flat scalars and arrays of flat objects are used so the TOON text stays
    tabular and every client decodes it without nested-key conventions.
    `current_revisions` (when known) decides the initial `is_current` flag.
    """
    parsed = TestRunResult.model_validate(result)
    content: dict[str, Any] = {
        "type": TEST_RESULT_EMBED_TYPE,
        "app_id": TEST_RESULT_APP_ID,
        "skill_id": TEST_RESULT_SKILL_ID,
        "embed_ref": embed_ref,
        "status": "finished",
        "title": _title(parsed),
        "kind": parsed.kind,
        "target": parsed.target,
        "run_status": parsed.status,
        "exit_code": parsed.exit_code,
        "duration_ms": parsed.duration_ms,
        "passed": parsed.passed,
        "failed": parsed.failed,
        "skipped": parsed.skipped,
        "error": parsed.error,
        "preview_step_index": parsed.preview_step_index,
        "execution_id": execution_id,
        "project_id": project_id,
        "tested_embed_ids": list(dict.fromkeys(tested_embed_ids or [])),
        "revisions": [item.model_dump() for item in parsed.revisions],
        "tests": [item.model_dump() for item in parsed.tests],
        "steps": [item.model_dump() for item in parsed.steps],
        "evidence": [item.model_dump() for item in parsed.evidence],
        "is_current": True,
        "stale_reason": None,
    }
    if current_revisions is not None:
        content = apply_currency(content, current_revisions)
    return content


FAILURE_LOG_FIELD_CHARS = 160


def failure_log_summary(content: dict[str, Any]) -> str:
    """Bounded operator summary of a non-passing run for the worker log.

    Holds only the exit code, counts, the first failing step name and the run's
    own error line, each cut to FAILURE_LOG_FIELD_CHARS; command output and test
    file contents are never logged.
    """
    if content.get("run_status") == "passed":
        return ""
    failing = next((step for step in content.get("steps") or [] if step.get("status") != "passed"), None)

    def cut(value: object) -> str:
        return str(value or "").splitlines()[0][:FAILURE_LOG_FIELD_CHARS] if value else ""

    return (
        f"exit={content.get('exit_code')} passed={content.get('passed')} failed={content.get('failed')} "
        f"steps={len(content.get('steps') or [])} failing_step={cut(failing and failing.get('name'))!r} "
        f"step_error={cut(failing and failing.get('error'))!r} error={cut(content.get('error'))!r}"
    )


def _title(result: TestRunResult) -> str:
    label = {"unit": "Unit tests", "browser": "Browser test", "cli": "CLI test"}[result.kind]
    return f"{label}: {result.status}"


def apply_currency(
    content: dict[str, Any],
    current_revisions: list[ProjectFileRevision],
) -> dict[str, Any]:
    """Return content with `is_current` / `stale_reason` set from the current revisions."""
    ran = [ProjectFileRevision.model_validate(item) for item in content.get("revisions") or []]
    probe = TestRunResult(kind=content["kind"], target=content["target"], status=content["run_status"], revisions=ran)
    current = result_is_current(probe, current_revisions)
    return {
        **content,
        "is_current": current,
        "stale_reason": None if current else STALE_REASON_REVISIONS_CHANGED,
    }


async def create_test_result_embed(
    embed_service: Any,
    *,
    result: dict[str, Any],
    chat_id: str,
    message_id: str,
    user_id: str,
    user_id_hash: str,
    user_vault_key_id: str,
    execution_id: str | None = None,
    project_id: str | None = None,
    tested_embed_ids: list[str] | None = None,
    task_id: str | None = None,
    log_prefix: str = "",
    embed_id: str | None = None,
) -> dict[str, Any]:
    """Create the finished test result embed and deliver it to the client.

    Raises RuntimeError when the embed could not be cached and delivered; the
    caller reports that instead of silently dropping the result.
    """
    embed_id = embed_id or str(uuid.uuid4())
    embed_ref = embed_service._generate_direct_embed_ref(
        TEST_RESULT_EMBED_TYPE, embed_id, {"title": "test-result"}
    )
    content = build_test_result_content(
        result,
        embed_ref=embed_ref,
        execution_id=execution_id,
        project_id=project_id,
        tested_embed_ids=tested_embed_ids,
        current_revisions=None,
    )
    content_toon = encode(content)
    encrypted_content, _ = await embed_service.encryption_service.encrypt_with_user_key(
        content_toon, user_vault_key_id
    )
    created_at = int(datetime.now().timestamp())
    linked = content["tested_embed_ids"]
    embed_data = {
        "embed_id": embed_id,
        "type": TEST_RESULT_EMBED_TYPE,
        "chat_id": chat_id,
        "message_id": message_id,
        "hashed_chat_id": hashlib.sha256(chat_id.encode()).hexdigest(),
        "hashed_message_id": hashlib.sha256(message_id.encode()).hexdigest(),
        "hashed_task_id": hashlib.sha256(task_id.encode()).hexdigest() if task_id else None,
        "status": "finished",
        "hashed_user_id": user_id_hash,
        "is_private": False,
        "is_shared": False,
        "encryption_mode": "client",
        "embed_ids": linked,
        "encrypted_content": encrypted_content,
        "text_length_chars": len(content_toon),
        "created_at": created_at,
        "updated_at": created_at,
    }
    delivered = await embed_service.send_embed_data_to_client(
        embed_id=embed_id,
        embed_type=TEST_RESULT_EMBED_TYPE,
        content_toon=content_toon,
        chat_id=chat_id,
        message_id=message_id,
        user_id=user_id,
        user_id_hash=user_id_hash,
        status="finished",
        task_id=task_id,
        embed_ids=linked,
        text_length_chars=len(content_toon),
        created_at=created_at,
        updated_at=created_at,
        log_prefix=log_prefix,
        check_cache_status=False,
        app_id=TEST_RESULT_APP_ID,
        skill_id=TEST_RESULT_SKILL_ID,
        finished_cache_data=embed_data,
        finished_cache_vault_key_id=user_vault_key_id,
    )
    if not delivered:
        raise RuntimeError("Test result embed was not cached and delivered")
    embed_service._schedule_embed_persistence_fallback(embed_id)
    logger.info("%s Created test result embed %s (%s) %s", log_prefix, embed_id, content["run_status"],
                failure_log_summary(content))
    return {"embed_id": embed_id, "embed_ref": embed_ref, "linked_embed_ids": linked}


async def refresh_test_result_currency(
    embed_service: Any,
    *,
    embed_id: str,
    chat_id: str,
    user_id: str,
    user_id_hash: str,
    user_vault_key_id: str,
    current_revisions: list[ProjectFileRevision],
    log_prefix: str = "",
) -> bool:
    """Re-evaluate a stored test result against the current file revisions.

    Publishes a new embed version only when `is_current` changes. Returns True
    when a new version was published. Callers run this for the test result
    embeds of a Project (or tested embed) after its file revisions change.
    """
    toon = await embed_service._get_cached_embed_toon(embed_id, user_vault_key_id, log_prefix)
    content = decode(toon) if toon else None
    if not isinstance(content, dict) or content.get("type") != TEST_RESULT_EMBED_TYPE:
        raise ValueError(f"Embed {embed_id} is not a cached test result")
    updated = apply_currency(content, current_revisions)
    if updated["is_current"] == bool(content.get("is_current", True)):
        return False
    record = await embed_service._get_embed_record(embed_id, log_prefix) or {}
    version_number = int(record.get("version_number") or 1) + 1
    updated_at = int(datetime.now().timestamp())
    updated["version_number"] = version_number
    updated_toon = encode(updated)
    encrypted_content, _ = await embed_service.encryption_service.encrypt_with_user_key(
        updated_toon, user_vault_key_id
    )
    # Run status is a server-owned field of a Project test-result link (contract P11).
    from backend.core.api.app.services.project_embed_server_fields import grant_server_owned_refresh
    await grant_server_owned_refresh(
        embed_service.cache_service, embed_id=embed_id, kind="test_result",
        version_number=version_number, before=content, after=updated,
    )
    published = await embed_service.send_embed_data_to_client(
        embed_id=embed_id,
        embed_type=TEST_RESULT_EMBED_TYPE,
        content_toon=updated_toon,
        chat_id=chat_id,
        message_id=str(record.get("message_id") or ""),
        user_id=user_id,
        user_id_hash=user_id_hash,
        status="finished",
        embed_ids=updated.get("tested_embed_ids"),
        version_number=version_number,
        created_at=record.get("created_at"),
        updated_at=updated_at,
        log_prefix=log_prefix,
        check_cache_status=False,
        app_id=TEST_RESULT_APP_ID,
        skill_id=TEST_RESULT_SKILL_ID,
        finished_cache_data={
            **record,
            "encrypted_content": encrypted_content,
            "status": "finished",
            "version_number": version_number,
            "updated_at": updated_at,
        },
        finished_cache_vault_key_id=user_vault_key_id,
    )
    embed_service._schedule_embed_persistence_fallback(embed_id)
    return bool(published)


async def persist_test_result_embed(
    payload: dict[str, Any],
    test_result: dict[str, Any],
    execution_id: str,
    cache_service: Any,
) -> dict[str, Any] | None:
    """Worker entry point: create the embed for a finished run bound to a chat.

    Returns None for runs without a chat (direct API runs keep only the
    `test_result` payload). Tested embeds are the run's target embed plus any
    `tested_embed_ids` the request carried; revisions come from the result.
    """
    chat_id = payload.get("chat_id")
    message_id = payload.get("message_id")
    user_id = payload.get("user_id")
    user_id_hash = payload.get("user_id_hash")
    if not (chat_id and message_id and user_id and user_id_hash):
        return None
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.services.embed_service import EmbedService
    from backend.core.api.app.utils.encryption import EncryptionService

    encryption_service = EncryptionService(cache_service=cache_service)
    await encryption_service.initialize()
    directus_service = DirectusService(cache_service=cache_service, encryption_service=encryption_service)
    profile = await directus_service.get_user_fields_direct(str(user_id), ["vault_key_id"])
    vault_key_id = (profile or {}).get("vault_key_id")
    if not vault_key_id:
        raise RuntimeError("Test result embed owner is missing a Vault key")
    tested = [str(item) for item in payload.get("tested_embed_ids") or [] if item]
    if payload.get("target_embed_id"):
        tested.append(str(payload["target_embed_id"]))
    embed_service = EmbedService(
        cache_service=cache_service,
        directus_service=directus_service,
        encryption_service=encryption_service,
    )
    return await create_test_result_embed(
        embed_service,
        result=test_result,
        chat_id=str(chat_id),
        message_id=str(message_id),
        user_id=str(user_id),
        user_id_hash=str(user_id_hash),
        user_vault_key_id=str(vault_key_id),
        execution_id=execution_id,
        project_id=(payload.get("test_run") or {}).get("project_id"),
        tested_embed_ids=tested,
        log_prefix=f"[TestResultEmbed] [execution:{execution_id[:8]}]",
        embed_id=run_result_embed_id(execution_id),
    )
