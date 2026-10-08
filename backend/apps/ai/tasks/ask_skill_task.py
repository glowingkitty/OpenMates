# backend/apps/ai/tasks/ask_skill_task.py
# Celery task for the AI App's "ask" skill.
#
# IMPORTANT CONTEXT:
# The tasks defined in this file are executed by the 'task-worker' Docker service.
# This worker service has the broader 'backend' codebase (including 'backend/core'
# and 'backend/apps') mounted, allowing it to import modules like
# 'backend.core.api.app.tasks.celery_config'.
# The 'celery_app' imported here is the central Celery application instance
# that the 'task-worker' is configured to use. This is how tasks defined here
# are registered with and executed by that worker.

from backend.shared.python_utils.chat_metadata_recovery import persist_generated_metadata
from backend.shared.python_utils.recent_work_summary_client import write_response_summary_completion
from backend.shared.python_utils.chat_failure_notifications import (
    EXPECTED_REJECTIONS,
    failure_stage,
    notify_chat_failure,
    notify_chat_failure_sync,
    terminal_class as classify_terminal_result,
)
from backend.shared.python_utils.team_log_correlation import team_correlation_fields

import logging
import asyncio
import time
import os
import uuid
import hashlib
import hmac
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import ValidationError
from celery.exceptions import Ignore, SoftTimeLimitExceeded
from celery.states import REVOKED as TASK_STATE_REVOKED # Module-level import

# Import Celery app instance
from backend.core.api.app.tasks import celery_config

# Import services to be instantiated directly in the task
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService # Assuming this is the correct path
from backend.core.api.app.services.skill_registry import build_skill_registry
from backend.core.api.app.services.chat_recovery_cutover import (
    legacy_completion_requires_persistence as completion_requires_persistence,
)
from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService
from backend.shared.python_utils.chat_recovery_context import (
    RecoveryOutputContext, RequiredRecoveryOutputError, active_recovery_output_context,
)
from backend.core.api.app.services.sub_chat_orchestration_service import SubChatOrchestrationService
from backend.core.api.app.services.user_task_queue_service import UserTaskQueueService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.log_sanitization import sanitize_request_data_for_logging

from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.shared.python_schemas.app_metadata_schemas import AppYAML
from backend.apps.ai.skills.ask_skill import AskSkillDefaultConfig
from backend.apps.ai.utils.instruction_loader import load_base_instructions
from backend.apps.ai.utils.user_task_turn_finalization import finalize_user_task_turn
from backend.apps.ai.utils.mate_utils import load_mates_config, MateConfig
from backend.apps.ai.utils.model_selector import DEFAULT_FALLBACK_MODEL
from backend.apps.ai.processing.preprocessor import handle_preprocessing, PreprocessingResult
from backend.apps.ai.processing.summary_billing import (
    SummaryBillingAmbiguousError,
    SummaryBillingDuplicateError,
    SummaryBillingError,
    SummaryBillingLimitError,
    SummaryBillingOperation,
    SummaryBillingUnsupportedFallbackError,
    selected_main_cache_tariff_active,
)
from backend.apps.ai.processing.plan_focus_routing import route_plan_focus
from backend.apps.ai.processing.focus_phase_history import filter_focus_phase_history
from backend.apps.ai.processing.artifact_ledger import (
    build_historical_artifact_context,
    load_and_merge_artifact_ledger,
    recover_inline_upload_artifacts,
)
from backend.apps.ai.processing.postprocessor import (
    handle_postprocessing,
    PostProcessingResult,
    extract_available_skills,
)
from backend.shared.python_utils.learning_mode import (
    filter_learning_mode_suggestions,
    is_learning_mode_enabled,
    learning_mode_context_from_preferences,
)
from backend.shared.python_utils.tracing.ai_observability import (
    AICompletionTiming,
    AI_QUEUE_ENQUEUED_AT_HEADER,
    ai_phase_span,
    record_ai_completion_timing,
    record_ai_queue_span,
)
from .stream_consumer import _consume_main_processing_stream, _persist_sealed_typed_output

# Import override parser for @ mentioning syntax (e.g., @ai-model:claude-opus-4-5)
from backend.core.api.app.utils.override_parser import parse_overrides, parse_overrides_from_messages, UserOverrides

# Import embed service for cleanup on task failure
from backend.core.api.app.services.embed_service import EmbedService

# Import chat compressor for long chat history summarization
# Architecture context: See docs/architecture/chat-compression.md
from backend.apps.ai.processing.chat_compressor import (
    should_compress,
    compress_chat_history,
    get_admin_compression_threshold,
    COMPRESSION_SUMMARY_CATEGORY,
    model_compression_threshold,
)
from backend.core.api.app.schemas.chat import AIHistoryMessage, MessageInCache


logger = logging.getLogger(__name__)


def _log_team_ai_pipeline_stage(request_data: AskSkillRequest, task_id: str, stage: str, status: str) -> None:
    if request_data.team_id:
        logger.info(
            "Team AI pipeline correlation %s stage=%s status=%s",
            team_correlation_fields(
                team_id=request_data.team_id, chat_id=request_data.chat_id,
                message_id=request_data.message_id, task_id=task_id,
            ),
            stage, status,
        )


async def _publish_project_authoring_availability(request_data: AskSkillRequest, task_id: str,
                                                  cache_service: Any, directus_service: Any) -> bool:
    """Permit one recommendation assessment for a completed response; never author."""
    from backend.core.api.app.services.project_recommendation_service import (
        ProjectRecommendationService, RECOMMENDATION_TTL,
    )
    from backend.core.api.app.services.project_write_authorization_service import ProjectWriteAuthorizationService
    if any(getattr(request_data, flag, False) for flag in ("is_external", "is_incognito", "is_anonymous")):
        return False
    project = getattr(request_data, "active_project_focus", None) or {}
    project_id = project.get("project_id") or project.get("id")
    from backend.shared.python_utils.recent_work_summary_client import authoritative_context_turn_id
    from backend.apps.ai.tasks.async_skill_continuation import async_skill_latest_user_turn_key
    message_id = authoritative_context_turn_id(request_data)
    latest_turn_key = async_skill_latest_user_turn_key(request_data.user_id, request_data.chat_id)
    if not project_id or not message_id:
        return False
    try:
        authorization = ProjectWriteAuthorizationService(directus_service, cache_service)
        binding = await cache_service.get(authorization._focus_key(request_data.user_id, request_data.chat_id))
        if (not isinstance(binding, dict) or binding.get("project_id") != project_id
                or binding.get("team_id") != request_data.team_id):
            return False
        await authorization._require_chat_access(request_data.user_id, request_data.chat_id, request_data.team_id)
        await authorization._require_project_access(request_data.user_id, project_id, request_data.team_id, write=False)
        if await cache_service.get(latest_turn_key) != message_id:
            return False
        stored = await cache_service.set(
            ProjectRecommendationService.response_key(request_data.user_id, request_data.chat_id, message_id),
            {"project_id": project_id, "team_id": request_data.team_id}, ttl=RECOMMENDATION_TTL,
        )
        if not stored or await cache_service.get(latest_turn_key) != message_id:
            return False
        await cache_service.publish_event(f"user_cache_events:{request_data.user_id}", {
            "event_type": "project_authoring_available", "payload": {
                "chat_id": request_data.chat_id, "project_id": project_id,
                "user_message_id": message_id, "assistant_message_id": getattr(request_data, "continuation_message_id", None) or task_id,
            },
        })
        return True
    except Exception:
        return False


def _validated_queued_messages(request_data: AskSkillRequest, lease: dict) -> tuple[list[str], list[str]]:
    """Reject a mixed or malformed leased batch instead of silently dropping members."""
    messages = lease.get("messages")
    raw_messages = lease.get("raw_messages")
    if (not isinstance(messages, list) or not isinstance(raw_messages, list)
            or not 1 <= len(messages) <= 20 or len(messages) != len(raw_messages)):
        raise RequiredRecoveryOutputError("Queued batch has invalid member count")
    scope_fields = (
        "chat_id", "user_id", "user_id_hash", "is_incognito", "is_external",
        "is_anonymous", "team_id", "team_id_hash", "team_workspace_type",
        "team_object_id_hash",
    )
    ids: list[str] = []
    contents: list[str] = []
    for member in messages:
        if not isinstance(member, dict):
            raise RequiredRecoveryOutputError("Queued batch contains a malformed member")
        if any(member.get(field) != getattr(request_data, field, None) for field in scope_fields):
            raise RequiredRecoveryOutputError("Queued batch owner, chat, Team or mode mismatch")
        if member.get("recovery_task_id") or member.get("recovery_preflight_id"):
            raise RequiredRecoveryOutputError("Durable recovery turn cannot enter legacy queue")
        message_id = member.get("message_id")
        history = member.get("message_history")
        if (not isinstance(message_id, str) or not 1 <= len(message_id) <= 255
                or message_id in ids or not isinstance(history, list) or not history):
            raise RequiredRecoveryOutputError("Queued batch member identity is invalid")
        current = history[-1]
        if (not isinstance(current, dict) or current.get("role") != "user"
                or current.get("message_id") != message_id
                or not isinstance(current.get("content"), str) or not current["content"]):
            raise RequiredRecoveryOutputError("Queued batch member has no matching user content")
        ids.append(message_id)
        contents.append(current["content"])
    return ids, contents


def _legacy_queued_batch_proof(
    request_data: AskSkillRequest, lease: dict, message_ids: list[str],
) -> dict:
    """Bind the exact Redis bytes to one immutable, domain-separated legacy batch."""
    secret = os.getenv("INTERNAL_API_SHARED_TOKEN")
    if not secret or len(secret) < 16:
        raise RequiredRecoveryOutputError("Queued batch signing authority unavailable")
    key = secret.encode("utf-8")
    raw_messages = lease["raw_messages"]
    members = [
        {
            "message_id": message_id,
            "chat_id": request_data.chat_id,
            "hashed_user_id": request_data.user_id_hash,
            "payload_commitment": hmac.new(
                key, b"openmates:legacy-queue-member:v1\0" + raw.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest(),
        }
        for message_id, raw in zip(message_ids, raw_messages)
    ]
    aggregate = json.dumps({
        "actor_user_id": request_data.user_id,
        "chat_id": request_data.chat_id,
        "members": [
            {"message_id": member["message_id"],
             "payload_commitment": member["payload_commitment"]}
            for member in members
        ],
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    commitment = hmac.new(
        key, b"openmates:legacy-queue-batch:v1\0" + aggregate,
        hashlib.sha256,
    ).hexdigest()
    first_message_id = message_ids[0]
    return {
        "protocol_version": 1,
        "actor_user_id": request_data.user_id,
        "hashed_user_id": request_data.user_id_hash,
        "hashed_team_id": request_data.team_id_hash,
        "chat_id": request_data.chat_id,
        "first_message_id": first_message_id,
        "task_identity": hashlib.sha256(
            f"{request_data.user_id}:{request_data.chat_id}:{first_message_id}".encode()
        ).hexdigest(),
        "celery_task_id": str(uuid.uuid5(uuid.NAMESPACE_URL, commitment)),
        "members": members,
        "batch_commitment": commitment,
    }


def _verify_legacy_batch_proof(
    proof: object, request_data: AskSkillRequest, task_id: str,
) -> dict:
    if not isinstance(proof, dict):
        raise RequiredRecoveryOutputError("Queued legacy task lacks batch proof")
    members = proof.get("members")
    if not isinstance(members, list) or not 1 <= len(members) <= 20:
        raise RequiredRecoveryOutputError("Queued legacy batch member count invalid")
    if (proof.get("actor_user_id") != request_data.user_id
            or proof.get("hashed_user_id") != request_data.user_id_hash
            or proof.get("hashed_team_id") != request_data.team_id_hash
            or proof.get("chat_id") != request_data.chat_id
            or proof.get("first_message_id") != request_data.message_id
            or proof.get("task_identity") != request_data.legacy_cutover_task_id
            or proof.get("celery_task_id") != task_id):
        raise RequiredRecoveryOutputError("Queued legacy task identity mismatch")
    ids = [member.get("message_id") for member in members if isinstance(member, dict)]
    if (len(ids) != len(members) or any(not isinstance(item, str) for item in ids)
            or len(set(ids)) != len(ids) or ids[0] != request_data.message_id):
        raise RequiredRecoveryOutputError("Queued legacy member identities invalid")
    if any(
        member.get("chat_id") != request_data.chat_id
        or member.get("hashed_user_id") != request_data.user_id_hash
        or not isinstance(member.get("payload_commitment"), str)
        or len(member["payload_commitment"]) != 64
        for member in members
    ):
        raise RequiredRecoveryOutputError("Queued legacy member scope invalid")
    secret = os.getenv("INTERNAL_API_SHARED_TOKEN")
    if not secret or len(secret) < 16:
        raise RequiredRecoveryOutputError("Queued batch signing authority unavailable")
    aggregate = json.dumps({
        "actor_user_id": request_data.user_id,
        "chat_id": request_data.chat_id,
        "members": [
            {"message_id": member["message_id"],
             "payload_commitment": member["payload_commitment"]}
            for member in members
        ],
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    expected = hmac.new(
        secret.encode("utf-8"), b"openmates:legacy-queue-batch:v1\0" + aggregate,
        hashlib.sha256,
    ).hexdigest()
    if (not isinstance(proof.get("batch_commitment"), str)
            or not hmac.compare_digest(proof["batch_commitment"], expected)
            or task_id != str(uuid.uuid5(uuid.NAMESPACE_URL, expected))):
        raise RequiredRecoveryOutputError("Queued legacy batch commitment mismatch")
    return proof


async def _seal_legacy_queue_handoff(
    handoff: dict, *, vault_key_id: str, cache_service: CacheService,
    encryption_service: Optional[EncryptionService] = None,
) -> dict:
    encryption_service = encryption_service or EncryptionService(cache_service=cache_service)
    plaintext = json.dumps(handoff, separators=(",", ":"))
    ciphertext, _ = await encryption_service.encrypt_with_user_key(
        plaintext, vault_key_id,
    )
    if not ciphertext.startswith("vault:v"):
        raise RequiredRecoveryOutputError("Queued handoff Vault encryption failed")
    return {
        "task_id": handoff["task_id"],
        "lease_token": handoff["lease"]["token"],
        "vault_key_id": vault_key_id,
        "ciphertext": ciphertext,
    }


async def _open_legacy_queue_handoff(
    sealed: dict, cache_service: CacheService,
) -> dict:
    if (not isinstance(sealed.get("task_id"), str)
            or not isinstance(sealed.get("lease_token"), str)
            or not isinstance(sealed.get("vault_key_id"), str)
            or not isinstance(sealed.get("ciphertext"), str)
            or not sealed["ciphertext"].startswith("vault:v")):
        raise RequiredRecoveryOutputError("Queued handoff has no Vault envelope")
    plaintext = await EncryptionService(cache_service=cache_service).decrypt_with_user_key(
        sealed["ciphertext"], sealed["vault_key_id"],
    )
    if not plaintext:
        raise RequiredRecoveryOutputError("Queued handoff Vault envelope cannot be opened")
    handoff = json.loads(plaintext)
    if (not isinstance(handoff, dict)
            or handoff.get("task_id") != sealed["task_id"]
            or handoff.get("lease", {}).get("token") != sealed["lease_token"]):
        raise RequiredRecoveryOutputError("Queued handoff Vault identity mismatch")
    return handoff


async def _advance_completed_legacy_followers(
    *, cache_service: CacheService, directus_service: DirectusService,
    chat_id: str, task_id: str, actor_user_id: str, hashed_team_id: Optional[str],
    completed_verified: bool = False,
) -> str:
    """Move followers behind a completed batch under the same active-task fence."""
    sealed_context = await cache_service.get_completed_queue_context(chat_id, task_id)
    if (not isinstance(sealed_context, dict)
            or not isinstance(sealed_context.get("vault_key_id"), str)
            or not isinstance(sealed_context.get("ciphertext"), str)
            or not sealed_context["ciphertext"].startswith("vault:v")):
        raise RequiredRecoveryOutputError("Completed queued turn has no Vault context")
    encryption_service = EncryptionService(cache_service=cache_service)
    plaintext = await encryption_service.decrypt_with_user_key(
        sealed_context["ciphertext"], sealed_context["vault_key_id"],
    )
    if not plaintext:
        raise RequiredRecoveryOutputError("Completed queued turn context cannot be opened")
    context = json.loads(plaintext)
    if (not isinstance(context, dict) or context.get("task_id") != task_id
            or context.get("chat_id") != chat_id
            or context.get("owner_id") != actor_user_id
            or context.get("hashed_team_id") != hashed_team_id
            or not isinstance(context.get("assistant_response"), str)):
        raise RequiredRecoveryOutputError("Completed queued turn has no verified follower context")
    prior_request = AskSkillRequest(**context["request_data_dict"])
    prior_proof = _verify_legacy_batch_proof(
        context.get("legacy_batch_proof"), prior_request, task_id,
    )
    if (prior_request.user_id != actor_user_id
            or prior_request.team_id_hash != hashed_team_id
            or prior_request.chat_id != chat_id):
        raise RequiredRecoveryOutputError("Completed queued follower scope changed")
    if not completed_verified:
        completed = await ChatRecoveryService(directus_service).execute(
            "prepare_legacy_batch", prior_proof,
        )
        if (completed.get("task_identity") != prior_proof["task_identity"]
                or completed.get("status") != "COMPLETED"
                or completed.get("execution_claimed") is not True
                or completed.get("idempotent") is not True):
            raise RequiredRecoveryOutputError("Queued follower completion is not authoritative")
    active_task_id = await cache_service.get_active_ai_task(chat_id)
    if active_task_id not in (task_id, None):
        raise RequiredRecoveryOutputError("Completed queued follower active fence changed")
    follower_lease = None
    for _attempt in range(3):
        follower_lease = await cache_service.lease_queued_message_prefix(chat_id, limit=20)
        if follower_lease:
            break
        state = await cache_service.complete_active_ai_task_if_queue_empty(chat_id, task_id)
        if state == 1 or state == 2:
            return task_id
    if follower_lease is None:
        raise RequiredRecoveryOutputError("Completed queued follower raced with active task release")
    ids, contents = _validated_queued_messages(prior_request, follower_lease)
    message_id = ids[0]
    history = [
        item.model_dump() if hasattr(item, "model_dump") else dict(item)
        for item in prior_request.message_history
    ]
    if context["assistant_response"]:
        history.append({
            "role": "assistant", "content": context["assistant_response"],
            "created_at": int(time.time()), "sender_name": "assistant",
        })
    history.append({
        "role": "user", "message_id": message_id,
        "content": "\n\n".join(contents), "created_at": int(time.time()),
        "sender_name": "user",
    })
    next_request_data = prior_request.model_dump()
    next_request_data.update({
        "message_id": message_id,
        "current_user_content": "\n\n".join(contents),
        "message_history": history,
        "chat_has_title": follower_lease["messages"][0].get("chat_has_title", True),
        "active_focus_id": follower_lease["messages"][0].get("active_focus_id"),
        "root_user_message_id": message_id,
        "agentic_context_ref": follower_lease["messages"][-1].get("agentic_context_ref"),
        "agentic_context_request_id": follower_lease["messages"][-1].get("agentic_context_request_id"),
        "agentic_context_turn_id": follower_lease["messages"][-1].get("agentic_context_turn_id"),
    })
    next_request = AskSkillRequest(**next_request_data)
    next_proof = _legacy_queued_batch_proof(next_request, follower_lease, ids)
    next_request.legacy_cutover_task_id = next_proof["task_identity"]
    next_task_id = next_proof["celery_task_id"]
    next_handoff = {
        "task_id": next_task_id, "chat_id": chat_id,
        "owner_id": actor_user_id, "hashed_team_id": hashed_team_id,
        "request_data_dict": next_request.model_dump(),
        "skill_config_dict": context["skill_config_dict"],
        "legacy_batch_proof": next_proof,
        "lease": {
            "token": follower_lease["token"],
            "raw_messages": follower_lease["raw_messages"],
        },
    }
    sealed_next = await _seal_legacy_queue_handoff(
        next_handoff, vault_key_id=sealed_context["vault_key_id"],
        cache_service=cache_service,
    )
    if not await cache_service.activate_completed_queue_followers(
        actor_user_id, chat_id, task_id, next_task_id, sealed_next,
        allow_missing_active=active_task_id is None,
    ):
        current = await cache_service.get_active_ai_task(chat_id)
        pending = await cache_service.get_paused_queue_handoff(chat_id)
        if current != next_task_id or pending is None:
            raise RequiredRecoveryOutputError("Completed queued follower transfer lost its fence")
        recovered = await _open_legacy_queue_handoff(pending, cache_service)
        if recovered != next_handoff:
            raise RequiredRecoveryOutputError("Completed queued follower handoff changed")
    resumed_id = await resume_legacy_queued_handoff(
        cache_service=cache_service, directus_service=directus_service,
        chat_id=chat_id, actor_user_id=actor_user_id,
        hashed_team_id=hashed_team_id,
    )
    if resumed_id != next_task_id:
        raise RequiredRecoveryOutputError("Completed queued follower was not dispatched")
    return next_task_id


async def resume_legacy_queued_handoff(
    *, cache_service: CacheService, directus_service: DirectusService,
    chat_id: str, actor_user_id: str, hashed_team_id: Optional[str],
) -> Optional[str]:
    """Retry only the exact first paused batch; later queue entries remain followers."""
    sealed_handoff = await cache_service.get_paused_queue_handoff(chat_id)
    if sealed_handoff is None:
        active_task_id = await cache_service.get_active_ai_task(chat_id)
        context = await cache_service.get_completed_queue_context(chat_id, active_task_id)
        if context and (active_task_id is None or context.get("task_id") == active_task_id):
            return await _advance_completed_legacy_followers(
                cache_service=cache_service, directus_service=directus_service,
                chat_id=chat_id, task_id=context["task_id"],
                actor_user_id=actor_user_id, hashed_team_id=hashed_team_id,
            )
        return None
    handoff = await _open_legacy_queue_handoff(sealed_handoff, cache_service)
    task_id = handoff.get("task_id")
    if (handoff.get("chat_id") != chat_id
            or handoff.get("owner_id") != actor_user_id
            or handoff.get("hashed_team_id") != hashed_team_id
            or not isinstance(task_id, str)
            or await cache_service.get_active_ai_task(chat_id) != task_id):
        raise RequiredRecoveryOutputError("Paused queued handoff scope or active fence changed")
    queued_lease = await cache_service.lease_queued_message_prefix(chat_id, limit=20)
    if (queued_lease is None
            or queued_lease.get("token") != handoff.get("lease", {}).get("token")
            or queued_lease.get("raw_messages") != handoff.get("lease", {}).get("raw_messages")):
        raise RequiredRecoveryOutputError("Paused queued prefix changed before replay")
    request_data = AskSkillRequest(**handoff["request_data_dict"])
    ids, _ = _validated_queued_messages(request_data, queued_lease)
    proof = _legacy_queued_batch_proof(request_data, queued_lease, ids)
    if proof != handoff.get("legacy_batch_proof"):
        raise RequiredRecoveryOutputError("Paused queued batch proof changed")
    _verify_legacy_batch_proof(proof, request_data, task_id)
    prepared = await ChatRecoveryService(directus_service).execute(
        "prepare_legacy_batch", proof,
    )
    if prepared.get("task_identity") != proof["task_identity"]:
        raise RequiredRecoveryOutputError("Paused queued batch admission unavailable")
    if prepared.get("status") in {"CLAIMED", "COMPLETED"}:
        # The exact immutable batch reached the worker after broker acceptance,
        # but this Redis prefix may not have been ACKed before the sender died.
        # Reconcile the unchanged lease without submitting another paid task.
        if (prepared.get("execution_claimed") is not True
                or prepared.get("idempotent") is not True):
            raise RequiredRecoveryOutputError("Paused queued batch claim is unverified")
        if not await cache_service.acknowledge_queued_message_prefix(
            chat_id, queued_lease,
        ):
            raise RequiredRecoveryOutputError("Paused queued prefix ACK failed")
        if prepared["status"] == "COMPLETED":
            return await _advance_completed_legacy_followers(
                cache_service=cache_service, directus_service=directus_service,
                chat_id=chat_id, task_id=task_id,
                actor_user_id=actor_user_id, hashed_team_id=hashed_team_id,
                completed_verified=True,
            )
        return task_id
    if (prepared.get("status") != "PREPARED"
            or prepared.get("execution_claimed") is not False):
        raise RequiredRecoveryOutputError("Paused queued batch admission unavailable")
    result = celery_config.app.send_task(
        name="apps.ai.tasks.skill_ask",
        kwargs={
            "request_data_dict": handoff["request_data_dict"],
            "skill_config_dict": handoff["skill_config_dict"],
            "legacy_batch_proof": proof,
        },
        queue="app_ai", task_id=task_id,
    )
    if not result or result.id != task_id:
        raise RuntimeError("Paused queued broker returned a different task ID")
    if not await cache_service.acknowledge_queued_message_prefix(
        chat_id, queued_lease,
    ):
        raise RequiredRecoveryOutputError("Paused queued prefix ACK failed")
    return task_id


def _bounded_identity_component(value: object) -> Optional[str]:
    if not isinstance(value, str) or not value or len(value) > 255:
        return None
    return value


def _bounded_recovery_failure_category(value: object) -> Optional[str]:
    if not isinstance(value, str) or not value or len(value) > 64:
        return None
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789_:-"
    if value[0] not in "abcdefghijklmnopqrstuvwxyz0123456789" or any(
        character not in allowed for character in value
    ):
        return None
    return value


def _validation_failure_identity(
    request_data_dict: object,
    task_id: object,
) -> Optional[str]:
    """Build a content-free notification identity from unvalidated task input."""
    if isinstance(request_data_dict, dict):
        chat_id = _bounded_identity_component(request_data_dict.get("chat_id"))
        message_id = _bounded_identity_component(request_data_dict.get("message_id"))
        if chat_id and message_id:
            return f"{chat_id}:{message_id}"
    return _bounded_identity_component(task_id)


def _recovery_unclaimed_result(claim: dict[str, Any]) -> dict[str, Any]:
    """Classify a durable recovery claim that another operation settled."""
    if claim.get("state") == "FAILED":
        failure_category = _bounded_recovery_failure_category(
            claim.get("failure_category")
        )
        failure_category = failure_category or "unclassified"
        was_cancelled = failure_category == "user_cancelled"
        is_expected = failure_category in EXPECTED_REJECTIONS
        failure_reason = (
            "recovery_claim_excluded" if is_expected else "recovery_claim_failed"
        )
        if was_cancelled:
            failure_reason = "recovery_claim_cancelled"
        result = {
            "status": "recovery_inference_failed",
            "failure_reason": failure_reason,
            "failure_category": failure_category,
            "preprocessing_summary": {},
            "main_processing_output": None,
            "postprocessing_summary": {},
            "interrupted_by_soft_time_limit": False,
            "interrupted_by_revocation": was_cancelled,
            "_celery_task_state": "FAILURE",
        }
        return result
    return {
        "status": "duplicate_recovery_task_ignored",
        "preprocessing_summary": {},
        "main_processing_output": None,
        "postprocessing_summary": {},
        "interrupted_by_soft_time_limit": False,
        "interrupted_by_revocation": False,
        "_celery_task_state": "SUCCESS",
    }


# Note: per-task_id dedup is now performed by `DedupedTask.__call__` (the
# Celery base class hooked in via `task_cls=` on the Celery app, see
# backend/core/api/app/tasks/base_task.py). It runs BEFORE this task body
# executes so duplicate broker deliveries (caused by task_acks_late=True +
# task_reject_on_worker_lost=True + autoreload connection cycles) are caught
# globally for every Celery task, not just this one.


async def _cleanup_processing_embeds_on_task_failure(
    task_id: str,
    chat_id: str,
    message_id: str,
    user_id: str,
    user_id_hash: str,
    user_vault_key_id: str,
    error_message: str,
    cache_service: Optional[CacheService] = None,
    directus_service: Optional[DirectusService] = None,
    encryption_service: Optional[EncryptionService] = None,
    use_cancelled_status: bool = False
) -> int:
    """
    Clean up processing embeds when a task fails unexpectedly.
    
    This function finds all embeds in "processing" status that were created by this task
    and marks them as "error" (or "cancelled" if task was revoked by user) so the frontend
    can display the failure state properly.
    
    CRITICAL: This prevents embeds from being stuck in "processing" forever when:
    - Postprocessing LLM fails
    - Task is revoked or times out
    - Any unexpected exception occurs
    
    Args:
        task_id: The Celery task ID (used to find related embeds)
        chat_id: The chat ID where embeds were created
        message_id: The message ID associated with the embeds
        user_id: The user ID (for cache access)
        user_id_hash: The hashed user ID (for Directus storage)
        user_vault_key_id: The vault key ID for encryption
        error_message: Error message to include in the embed status
        cache_service: Optional CacheService instance
        directus_service: Optional DirectusService instance
        encryption_service: Optional EncryptionService instance
        use_cancelled_status: If True, mark embeds as "cancelled" instead of "error" (for user-initiated cancellation)
        
    Returns:
        Number of embeds that were cleaned up
    """
    log_prefix = f"[Task ID: {task_id}, ChatID: {chat_id}] EMBED_CLEANUP"
    cleaned_count = 0
    
    try:
        # Create service instances if not provided
        if not cache_service:
            cache_service = CacheService()
        if not directus_service:
            directus_service = DirectusService()
            await directus_service.ensure_auth_token()
        if not encryption_service:
            encryption_service = EncryptionService()
        
        # Create embed service for cleanup operations
        embed_service = EmbedService(cache_service, directus_service, encryption_service)
        
        # Get all embeds from cache for this chat that might be in processing state
        # We use the cache key pattern to find embeds created during this task
        import hashlib
        hashed_chat_id = hashlib.sha256(chat_id.encode()).hexdigest()
        hashed_task_id = hashlib.sha256(task_id.encode()).hexdigest()
        
        # Query cache for processing embeds associated with this task
        # The embed cache key pattern: embed:{embed_id}
        # We need to scan for embeds with hashed_task_id matching this task
        client = await cache_service.client
        if not client:
            logger.warning(f"{log_prefix} Redis client not available for embed cleanup")
            return 0
        
        # Scan for embed keys
        cursor = 0
        embed_keys = []
        while True:
            cursor, keys = await client.scan(cursor, match="embed:*", count=100)
            if keys:
                embed_keys.extend(keys)
            if cursor == 0:
                break
        
        logger.info(f"{log_prefix} Scanning {len(embed_keys)} embed cache entries for processing embeds")
        
        for key in embed_keys:
            try:
                key_str = key.decode('utf-8') if isinstance(key, bytes) else key
                embed_data_str = await client.get(key_str)
                if not embed_data_str:
                    continue
                    
                import json
                embed_data = json.loads(embed_data_str.decode('utf-8') if isinstance(embed_data_str, bytes) else embed_data_str)
                
                # Check if this embed:
                # 1. Is in "processing" status
                # 2. Belongs to this chat
                # 3. Was created by this task (hashed_task_id matches)
                embed_status = embed_data.get("status")
                embed_hashed_chat_id = embed_data.get("hashed_chat_id")
                embed_hashed_task_id = embed_data.get("hashed_task_id")
                
                if (embed_status == "processing" and 
                    embed_hashed_chat_id == hashed_chat_id and
                    embed_hashed_task_id == hashed_task_id):
                    
                    embed_id = embed_data.get("embed_id") or key_str.replace("embed:", "")
                    app_id = embed_data.get("app_id", "unknown")
                    skill_id = embed_data.get("skill_id", "unknown")
                    
                    target_status = "cancelled" if use_cancelled_status else "error"
                    logger.info(
                        f"{log_prefix} Found processing embed {embed_id} (app={app_id}, skill={skill_id}) - marking as {target_status}"
                    )
                    
                    # Update embed to error or cancelled status
                    try:
                        if use_cancelled_status:
                            await embed_service.update_embed_status_to_cancelled(
                                embed_id=embed_id,
                                app_id=app_id,
                                skill_id=skill_id,
                                chat_id=chat_id,
                                message_id=message_id,
                                user_id=user_id,
                                user_id_hash=user_id_hash,
                                user_vault_key_id=user_vault_key_id,
                                task_id=task_id,
                                log_prefix=log_prefix
                            )
                        else:
                            await embed_service.update_embed_status_to_error(
                                embed_id=embed_id,
                                app_id=app_id,
                                skill_id=skill_id,
                                error_message=f"Task failed: {error_message}",
                                chat_id=chat_id,
                                message_id=message_id,
                                user_id=user_id,
                                user_id_hash=user_id_hash,
                                user_vault_key_id=user_vault_key_id,
                                task_id=task_id,
                                log_prefix=log_prefix
                            )
                        cleaned_count += 1
                        logger.info(f"{log_prefix} Successfully marked embed {embed_id} as {target_status}")
                    except Exception as update_error:
                        logger.error(f"{log_prefix} Failed to update embed {embed_id} to error: {update_error}")
                        
            except Exception as embed_error:
                logger.warning(f"{log_prefix} Error processing embed key {key}: {embed_error}")
                continue
        
        if cleaned_count > 0:
            logger.info(f"{log_prefix} Cleaned up {cleaned_count} processing embed(s)")
        else:
            logger.debug(f"{log_prefix} No processing embeds found to clean up")
            
    except Exception as e:
        logger.error(f"{log_prefix} Error during embed cleanup: {e}", exc_info=True)
    
    return cleaned_count


async def _cleanup_on_task_failure(
    task_id: str,
    chat_id: str,
    message_id: str,
    user_id: str,
    user_id_hash: str,
    user_vault_key_id: str,
    error_message: str,
    cache_service: Optional[CacheService] = None,
    directus_service: Optional[DirectusService] = None,
    encryption_service: Optional[EncryptionService] = None,
    use_cancelled_status: bool = False
) -> None:
    """
    Comprehensive cleanup when a task fails unexpectedly.
    
    This function performs two critical cleanup operations:
    1. Clears the active_ai_task marker so the typing indicator stops
    2. Marks processing embeds as error (or cancelled) so they don't get stuck
    
    CRITICAL: This ensures that when a task fails for any reason (timeout, exception,
    revocation, CMS errors, etc.), the user can immediately send new messages
    and the UI reflects the failure properly.
    
    Args:
        task_id: The Celery task ID
        chat_id: The chat ID where the task was running
        message_id: The message ID associated with the task
        user_id: The user ID (for cache access)
        user_id_hash: The hashed user ID (for Directus storage)
        user_vault_key_id: The vault key ID for encryption
        error_message: Error message describing the failure
        cache_service: Optional CacheService instance
        directus_service: Optional DirectusService instance
        encryption_service: Optional EncryptionService instance
        use_cancelled_status: If True, mark embeds as "cancelled" instead of "error"
    """
    log_prefix = f"[Task ID: {task_id}, ChatID: {chat_id}] TASK_CLEANUP"
    
    # Create cache service if not provided
    if not cache_service:
        cache_service = CacheService()
    
    # 1. Clear active_ai_task marker - this is critical for stopping the typing indicator
    try:
        cleared = await cache_service.clear_active_ai_task(chat_id)
        if cleared:
            logger.info(f"{log_prefix} Cleared active_ai_task marker after failure: {error_message}")
        else:
            logger.warning(f"{log_prefix} Failed to clear active_ai_task marker (may not exist)")
        from backend.apps.ai.tasks.async_skill_continuation import (
            dispatch_deferred_async_skill_continuations,
        )
        await dispatch_deferred_async_skill_continuations(
            cache_service=cache_service,
            user_id=user_id,
            chat_id=chat_id,
        )
    except Exception as e:
        logger.error(f"{log_prefix} Error clearing active_ai_task marker: {e}", exc_info=True)
    
    # 2. Clean up processing embeds
    try:
        cleaned_count = await _cleanup_processing_embeds_on_task_failure(
            task_id=task_id,
            chat_id=chat_id,
            message_id=message_id,
            user_id=user_id,
            user_id_hash=user_id_hash,
            user_vault_key_id=user_vault_key_id,
            error_message=error_message,
            cache_service=cache_service,
            directus_service=directus_service,
            encryption_service=encryption_service,
            use_cancelled_status=use_cancelled_status
        )
        if cleaned_count > 0:
            logger.info(f"{log_prefix} Cleaned up {cleaned_count} processing embed(s)")
    except Exception as e:
        logger.error(f"{log_prefix} Error cleaning up embeds: {e}", exc_info=True)


# Note: Avoid internal API lookups per task to keep latency low. We rely on
# the worker-local ConfigManager (see celery_config) and fail fast if configs are missing.

# Critical apps that should normally be available for full functionality
# If these are missing, the AI will have reduced capabilities
CRITICAL_APPS = ["web", "ai"]


def _check_critical_apps_availability(
    discovered_apps_metadata: Dict[str, AppYAML],
    task_id: str
) -> None:
    """
    Check if critical apps are available and log warnings if they're missing.
    
    This helps diagnose issues where important apps (like 'web') are unavailable,
    which would cause the AI to be instructed about capabilities it doesn't have.
    
    Args:
        discovered_apps_metadata: Dict of discovered app_id -> AppYAML
        task_id: Task ID for logging
    """
    available_app_ids = set(discovered_apps_metadata.keys())
    missing_critical_apps = []
    
    for critical_app in CRITICAL_APPS:
        if critical_app not in available_app_ids:
            missing_critical_apps.append(critical_app)
    
    if missing_critical_apps:
        logger.warning(
            f"[Task ID: {task_id}] [CRITICAL_APPS] WARNING: Critical app(s) NOT AVAILABLE: {', '.join(missing_critical_apps)}. "
            f"Available apps: {', '.join(available_app_ids) if available_app_ids else 'None'}. "
            f"This may indicate app containers are not running or not healthy. "
            f"The AI will NOT have access to these apps' skills (e.g., web-search, web-read if 'web' is missing). "
            f"Check docker-compose logs and the /v1/health endpoint."
        )
    else:
        logger.debug(
            f"[Task ID: {task_id}] [CRITICAL_APPS] All critical apps available: {', '.join(CRITICAL_APPS)}"
        )


async def _fetch_and_cache_apps_metadata(
    cache_service_instance: CacheService,
    task_id: str
) -> Dict[str, AppYAML]:
    """
    Fallback mechanism to rebuild discovered apps metadata when cache is empty.
    
    This handles cases where the cache has expired or been flushed. Celery workers already
    build an in-process SkillRegistry at startup, so rebuilding metadata from the same
    filesystem source keeps worker behavior independent of API-only routes.
    
    CRITICAL: Without this fallback, the LLM has NO tools available (no web search, etc.)
    when the cache expires. This resulted in the LLM hallucinating search results instead
    of actually executing tool calls.
    
    Args:
        cache_service_instance: CacheService instance for caching
        task_id: Task ID for logging
        
    Returns:
        Dict of app_id -> AppYAML, or empty dict if fetch fails
    """
    log_prefix = f"[Task ID: {task_id}]"
    
    try:
        logger.info(f"{log_prefix} Rebuilding discovered_apps_metadata from local app registry")
        _, discovered_apps_metadata = build_skill_registry()
        
        if not discovered_apps_metadata:
            logger.warning(f"{log_prefix} Local registry returned empty apps metadata")
            return {}

        if cache_service_instance:
            try:
                await cache_service_instance.set_discovered_apps_metadata(discovered_apps_metadata)
                logger.info(f"{log_prefix} Successfully re-cached discovered_apps_metadata ({len(discovered_apps_metadata)} apps)")
            except Exception as e_cache:
                logger.error(f"{log_prefix} Failed to re-cache discovered_apps_metadata: {e_cache}")
        
        return discovered_apps_metadata

    except Exception as e:
        logger.error(f"{log_prefix} Unexpected error rebuilding apps metadata: {e}", exc_info=True)
        return {}


# Custom exception for retry logic
class ChatNotFoundError(Exception):
    """Custom exception to trigger Celery retry when a chat is not found in the database."""
    pass


async def _update_user_task_execution_state(
    request_data: AskSkillRequest,
    directus_service: Optional[DirectusService],
    *,
    ai_execution_state: str,
    status: Optional[str] = None,
    blocked_reason_code: Optional[str] = None,
    completed_at: Optional[int] = None,
) -> bool:
    """Best-effort product task state update for AI asks launched from Tasks V1."""
    user_task_id = getattr(request_data, "user_task_id", None)
    if not user_task_id or not directus_service:
        return True

    now = int(time.time())
    team_id = getattr(request_data, "team_id", None)
    if ai_execution_state == "running":
        claimed = await directus_service.user_task.claim_queued_ai_task_execution(
            user_task_id,
            request_data.user_id,
            team_id=team_id,
            now=now,
        )
        if not claimed:
            logger.info("User task %s is no longer queued; skipping delayed dispatch", user_task_id)
            return False
        return True

    patch: dict[str, Any] = {
        "ai_execution_state": ai_execution_state,
        "updated_at": now,
    }
    if status:
        patch["status"] = status
    if blocked_reason_code:
        patch["blocked_reason_code"] = blocked_reason_code
    if completed_at is not None:
        patch["completed_at"] = completed_at

    try:
        current_task = await directus_service.user_task.get_task(user_task_id, request_data.user_id, team_id)
        if not current_task:
            logger.warning("User task %s was not found while updating execution state", user_task_id)
            return False
        current_version = current_task.get("version")
        if current_version is None:
            logger.warning("User task %s has no version while updating execution state", user_task_id)
            return False
        updated_task = await directus_service.user_task.update_task_if_version(
            user_task_id,
            request_data.user_id,
            {**patch, "version": int(current_version)},
            int(current_version),
            team_id=team_id,
        )
        if not updated_task:
            logger.warning("User task %s changed before execution state update", user_task_id)
            return False
        logger.info(
            "[Task ID: %s] Updated user task %s execution state to %s",
            getattr(request_data, "message_id", "unknown"),
            user_task_id,
            ai_execution_state,
        )
        if status in {"blocked", "done"} or ai_execution_state in {"failed", "cancelled"}:
            await UserTaskQueueService(directus_service.user_task).admission_service.admit_available(
                request_data.user_id,
                team_id=team_id,
                now=now,
                preferred_chat_id=current_task.get("primary_chat_id"),
            )
        return True
    except Exception as exc:
        logger.warning(
            "Failed to update user task %s execution state to %s: %s",
            user_task_id,
            ai_execution_state,
            exc,
            exc_info=True,
        )
        return False


async def _finalize_user_task_execution(
    request_data: AskSkillRequest,
    directus_service: Optional[DirectusService],
) -> None:
    """Only explicit Task tools complete work; a finished reply ends its attempt."""
    user_task_id = getattr(request_data, "user_task_id", None)
    if not user_task_id or not directus_service:
        return

    try:
        team_id = getattr(request_data, "team_id", None)
        await finalize_user_task_turn(
            directus_service.user_task,
            task_id=user_task_id, user_id=request_data.user_id, chat_id=request_data.chat_id,
            team_id=team_id, now=int(time.time()),
        )
    except Exception as exc:
        logger.warning(
            "Failed to finalize user task %s inference attempt: %s",
            user_task_id,
            exc,
            exc_info=True,
        )


async def _update_user_task_execution_state_with_new_directus(
    request_data: AskSkillRequest,
    *,
    ai_execution_state: str,
    status: Optional[str] = None,
    blocked_reason_code: Optional[str] = None,
    completed_at: Optional[int] = None,
) -> None:
    """Update a product task from sync-wrapper failure paths with owned Directus lifecycle."""
    if not getattr(request_data, "user_task_id", None):
        return

    directus_service = DirectusService()
    try:
        await _update_user_task_execution_state(
            request_data,
            directus_service,
            ai_execution_state=ai_execution_state,
            status=status,
            blocked_reason_code=blocked_reason_code,
            completed_at=completed_at,
        )
    finally:
        await directus_service.close()


async def _mark_recovery_inference_failed(
    request_data: AskSkillRequest,
    task_id: str,
    failure_category: str,
) -> None:
    inference_task_id = request_data.resolved_recovery_inference_task_id()
    if not inference_task_id:
        return
    directus_service = DirectusService()
    try:
        await ChatRecoveryService(directus_service).execute(
            "mark_inference_failed",
            {
                "protocol_version": 1,
                "inference_task_id": inference_task_id,
                "failure_category": failure_category,
            },
        )
    finally:
        await directus_service.close()


async def _mark_sub_chat_terminal_failure(
    request_data: AskSkillRequest,
    task_id: str,
    *,
    cancelled: bool,
    pause_parent: bool = False,
) -> None:
    """Settle child lifecycle; a required durable-save failure stops synthesis."""
    if not request_data.orchestration_id:
        return
    if not request_data.is_sub_chat:
        directus_service = DirectusService()
        try:
            await SubChatOrchestrationService(directus_service).execute(
                "transition_root",
                {
                    "protocol_version": 1,
                    "orchestration_id": request_data.orchestration_id,
                    "hashed_user_id": request_data.user_id_hash,
                    "state": "cancelled" if cancelled else "failed",
                },
            )
        finally:
            await directus_service.close()
        return
    if pause_parent:
        directus_service = DirectusService()
        try:
            await SubChatOrchestrationService(directus_service).execute(
                "transition_child", {
                    "protocol_version": 1,
                    "orchestration_id": request_data.orchestration_id,
                    "hashed_user_id": request_data.user_id_hash,
                    "child_chat_id": request_data.chat_id,
                    "state": "failed",
                },
            )
        finally:
            await directus_service.close()
        return
    from backend.apps.ai.tasks.stream_consumer import (
        _record_sub_chat_completion_and_maybe_continue_parent,
    )

    cache_service = CacheService()
    try:
        await cache_service.client
        await _record_sub_chat_completion_and_maybe_continue_parent(
            cache_service=cache_service,
            request_data=request_data,
            task_id=task_id,
            summary=(
                "Sub-chat was cancelled before completion."
                if cancelled
                else "Sub-chat failed before completion."
            ),
            log_prefix=f"[Task ID: {task_id}]",
            terminal_state="cancelled" if cancelled else "failed",
        )
    finally:
        await cache_service.close()


async def _publish_recovery_output_pause(request_data: AskSkillRequest, task_id: str) -> None:
    """Tell capable clients that dependent work stopped at the durable-save gate."""
    cache_service = CacheService()
    try:
        root_chat_id = request_data.root_chat_id or request_data.chat_id
        await cache_service.publish_event(f"chat_stream::{root_chat_id}", {
            "type": "recovery_output_paused", "chat_id": root_chat_id,
            "child_chat_id": request_data.chat_id if request_data.is_sub_chat else None,
            "user_id_uuid": request_data.user_id,
            "user_id_hash": request_data.user_id_hash,
            "message_id": request_data.message_id,
            "task_id": task_id,
            "reason_code": "durable_output_unavailable",
        })
    finally:
        await cache_service.close()


async def _finalize_legacy_cutover_admission(
    request_data: AskSkillRequest,
    inference_completed: bool,
) -> None:
    task_identity = request_data.legacy_cutover_task_id
    if not task_identity:
        return
    operation = (
        "mark_legacy_inference_completed"
        if inference_completed
        else "release_legacy_inference"
    )
    directus_service = DirectusService()
    try:
        await ChatRecoveryService(directus_service).execute(
            operation,
            {"protocol_version": 1, "task_identity": task_identity},
        )
    finally:
        await directus_service.close()


class RecoveryCheckpointPersistenceError(RuntimeError):
    """A required client-key-sealed checkpoint was not durably saved."""


async def _compress_for_selected_model(
    *,
    task_id: str,
    request_data: AskSkillRequest,
    selected_model_id: str,
    cache_service: CacheService,
    encryption_service: EncryptionService,
    user_vault_key_id: str,
    secrets_manager: SecretsManager,
    directus_service: DirectusService | None = None,
) -> bool:
    """Compress once the actual main model is known; failures remain non-fatal."""
    if not request_data.message_history or request_data.is_external:
        return False

    history = [
        {
            "role": msg.role,
            "content": msg.content,
            "created_at": msg.created_at,
            "message_id": getattr(msg, "message_id", None),
            "category": getattr(msg, "category", None),
            "sender_name": getattr(msg, "sender_name", None),
        }
        for msg in request_data.message_history
    ]
    admin_threshold = await get_admin_compression_threshold(cache_service, request_data.user_id)
    threshold = model_compression_threshold(
        selected_model_id, celery_config.config_manager, threshold_override=admin_threshold
    )
    recovery_checkpoint_fixture = False
    if os.getenv("OPENMATES_STORAGE_CAPACITY_FIXTURES") == "true":
        from backend.shared.testing.mock_context import get_mock_group, is_mock_active
        if is_mock_active() and get_mock_group() == "storage_capacity_v1" \
                and any("STORAGE_CAPACITY_SCENARIO:recovery_checkpoint" in msg.content
                        for msg in request_data.message_history if msg.role == "user"):
            threshold = 1
            recovery_checkpoint_fixture = True
    if admin_threshold is not None:
        logger.info("[Task ID: %s] Using admin compression threshold: %s tokens", task_id, threshold)
    if not should_compress(history, threshold):
        logger.info(
            "[Task ID: %s] Model-aware compression skipped for %s (threshold=%s)",
            task_id,
            selected_model_id,
            threshold,
        )
        return False

    # The selected answer model determines whether the separate summary price
    # is active. Workflows, anonymous turns and orchestrated subchats keep
    # their existing bundled compression and budget behavior.
    summary_billing = None
    from backend.apps.ai.processing.main_processor import _normal_chat_cache_pricing_scope
    if (_normal_chat_cache_pricing_scope(request_data)
            and selected_main_cache_tariff_active(selected_model_id)):
        summary_billing = SummaryBillingOperation(task_id=task_id, request_data=request_data)

    channel = f"ai_typing_indicator_events::{request_data.user_id_hash}"
    if request_data.user_id_hash:
        await cache_service.publish_event(channel, {
            "type": "chat_compression_started",
            "event_for_client": "chat_compression_started",
            "task_id": task_id,
            "chat_id": request_data.chat_id,
            "user_id_uuid": request_data.user_id,
            "user_id_hash": request_data.user_id_hash,
        })

    try:
        with ai_phase_span("compression"):
            result = await compress_chat_history(
                message_history=history,
                task_id=task_id,
                secrets_manager=secrets_manager,
                compression_threshold=threshold,
                force=recovery_checkpoint_fixture,
                **({"billing_operation": summary_billing} if summary_billing else {}),
            )
    except (SummaryBillingLimitError, SummaryBillingUnsupportedFallbackError):
        if summary_billing:
            await summary_billing.release_failed()
        logger.info("[Task ID: %s] Summary skipped before the next provider dispatch", task_id)
        return False
    except SummaryBillingDuplicateError:
        logger.warning("[Task ID: %s] Summary reservation already exists; no provider replay", task_id)
        return False
    except SummaryBillingAmbiguousError:
        logger.exception("[Task ID: %s] Summary cost is uncertain; hold retained for review", task_id)
        return False
    except SummaryBillingError:
        if summary_billing and summary_billing.dispatched:
            logger.exception("[Task ID: %s] Summary billing failed after dispatch; hold retained", task_id)
            return False
        raise
    if not result.was_compressed or not result.summary_content:
        if summary_billing:
            await summary_billing.release_failed()
        if result.error and request_data.user_id_hash:
            await cache_service.publish_event(channel, {
                "type": "chat_compression_completed",
                "event_for_client": "chat_compression_completed",
                "task_id": task_id,
                "chat_id": request_data.chat_id,
                "user_id_uuid": request_data.user_id,
                "user_id_hash": request_data.user_id_hash,
                "error": result.error,
            })
        return False

    if request_data.resolved_recovery_inference_task_id() and (
        not result.compressed_up_to_message_id or not result.covered_message_ids
    ):
        raise RecoveryCheckpointPersistenceError("Recovery checkpoint lacks a stable source message manifest")
    checkpoint_boundary = result.compressed_up_to_message_id or str(result.compressed_up_to_timestamp)
    summary_operation_identity = request_data.resolved_recovery_inference_task_id() or task_id
    summary_message_id = str(uuid.uuid5(
        uuid.NAMESPACE_URL, f"openmates:compression:{summary_operation_identity}:{checkpoint_boundary}",
    ))
    summary_receipt = None
    if summary_billing:
        try:
            summary_receipt = await summary_billing.record_intent(summary_message_id=summary_message_id)
        except SummaryBillingError as exc:
            raise RecoveryCheckpointPersistenceError("Summary billing intent was not durably recorded") from exc
    summary_timestamp = int(time.time())
    encrypted_summary, _ = await encryption_service.encrypt_with_user_key(
        result.summary_content,
        user_vault_key_id,
    )
    summary_cache_message = MessageInCache(
        id=summary_message_id,
        chat_id=request_data.chat_id,
        role="system",
        category=COMPRESSION_SUMMARY_CATEGORY,
        sender_name=None,
        encrypted_content=encrypted_summary,
        created_at=summary_timestamp,
        status="sent",
    )
    cache_messages = [summary_cache_message.model_dump_json()]
    compressed_history = [AIHistoryMessage(
        content=result.summary_content,
        role="system",
        category=COMPRESSION_SUMMARY_CATEGORY,
        created_at=summary_timestamp,
    )]
    for recent in result.recent_messages or []:
        recent_content = recent.get("content", "")
        recent_message_id = next(
            (value for value in (
                recent.get("message_id"), recent.get("client_message_id"), recent.get("id"),
            ) if isinstance(value, str) and value),
            None,
        )
        encrypted_recent, _ = await encryption_service.encrypt_with_user_key(
            recent_content,
            user_vault_key_id,
        )
        cache_messages.append(MessageInCache(
            id=recent_message_id or f"recent_{uuid.uuid4().hex[:8]}",
            chat_id=request_data.chat_id,
            role=recent.get("role", "user"),
            category=recent.get("category"),
            sender_name=recent.get("sender_name"),
            encrypted_content=encrypted_recent,
            created_at=recent.get("created_at", summary_timestamp),
            status="sent",
        ).model_dump_json())
        compressed_history.append(AIHistoryMessage(
            message_id=recent_message_id,
            content=recent_content,
            role=recent.get("role", "user"),
            category=recent.get("category"),
            created_at=recent.get("created_at", summary_timestamp),
        ))

    if request_data.resolved_recovery_inference_task_id():
        if directus_service is None:
            raise RecoveryCheckpointPersistenceError("Checkpoint lacks durable recovery service")
        try:
            await _persist_sealed_typed_output(
                directus_service=directus_service,
                request_data=request_data,
                cache_service=cache_service,
                inference_task_id=request_data.resolved_recovery_inference_task_id(),
                subject_id=summary_message_id,
                output_kind="checkpoint", output_version=1,
                content={
                    "summary_message_id": summary_message_id,
                    "summary_content": result.summary_content,
                    "compressed_message_count": result.compressed_message_count,
                    "summary_token_estimate": result.summary_token_estimate,
                    "compressed_up_to_timestamp": result.compressed_up_to_timestamp,
                    "compressed_up_to_message_id": result.compressed_up_to_message_id,
                    "covered_message_ids": result.covered_message_ids,
                },
            )
        except Exception as exc:
            raise RecoveryCheckpointPersistenceError("Checkpoint recovery save failed") from exc

    try:
        await cache_service.set_ai_messages_history(
            user_id=request_data.user_id,
            chat_id=request_data.chat_id,
            encrypted_messages_json_list=cache_messages,
        )
    except Exception as exc:
        if summary_billing and summary_billing.intent_recorded:
            raise RecoveryCheckpointPersistenceError("Summary checkpoint application failed after billing intent") from exc
        raise
    request_data.message_history = compressed_history
    if summary_billing and summary_receipt is not None:
        try:
            await summary_billing.settle(receipt=summary_receipt)
        except SummaryBillingAmbiguousError:
            logger.exception("[Task ID: %s] Summary settlement pending; durable intent and hold retained", task_id)
    logger.info(
        "[Task ID: %s] Model-aware compression for %s replaced %s messages with %s context messages",
        task_id,
        selected_model_id,
        len(history),
        len(compressed_history),
    )
    if request_data.user_id_hash:
        await cache_service.publish_event(channel, {
            "type": "chat_compression_completed",
            "event_for_client": "chat_compression_completed",
            "task_id": task_id,
            "chat_id": request_data.chat_id,
            "user_id_uuid": request_data.user_id,
            "user_id_hash": request_data.user_id_hash,
            "compressed_message_count": result.compressed_message_count,
            "summary_token_estimate": result.summary_token_estimate,
            "compressed_up_to_timestamp": result.compressed_up_to_timestamp,
            "compressed_up_to_message_id": result.compressed_up_to_message_id,
            "covered_message_ids": result.covered_message_ids,
            "summary_message_id": summary_message_id,
            "summary_content": result.summary_content,
        })
    return True


async def _async_process_ai_skill_ask_task(
    task_id: str, # task_id is still needed
    request_data: AskSkillRequest,
    skill_config: AskSkillDefaultConfig,
    completion_timing: Optional[AICompletionTiming] = None,
    legacy_batch_proof: Optional[dict] = None,
):
    """
    Asynchronous core logic for processing the AI skill ask task.
    Initializes services and performs the main processing steps.
    Returns a dictionary with processing results and status flags.
    """
    logger.info(f"[Task ID: {task_id}] Async task execution started.")
    # Phase transition JSON is stored as an encrypted system message for chat UI.
    # The phase state is supplied separately, so these notices need no model role.
    request_data.message_history = filter_focus_phase_history(
        request_data.message_history, chat_id=request_data.chat_id,
    )
    # These fields are client-constructible on the request model, so never trust
    # their inbound values. Only a validated marker below may repopulate them.
    request_data.live_mock_mode = None
    request_data.live_mock_group = None

    # Local flags for interruption, to be returned
    task_was_revoked = False
    task_was_soft_limited = False

    # --- Initialize services ---
    # PERFORMANCE OPTIMIZATION: Use worker-level cache service for connection pooling
    # This eliminates ~100-200ms of Redis connection overhead per task
    secrets_manager = None
    cache_service_instance = None
    directus_service_instance = None
    encryption_service_instance = None

    try:
        with ai_phase_span("setup"):
            secrets_manager = SecretsManager()
            await secrets_manager.initialize()
            logger.info(f"[Task ID: {task_id}] SecretsManager initialized.")

            # PERFORMANCE OPTIMIZATION: Try to use worker-level cache service first
            # Falls back to creating a new instance if the worker-level service is unavailable
            try:
                from backend.core.api.app.tasks.celery_config import get_worker_cache_service
                cache_service_instance = await get_worker_cache_service()
                logger.info(f"[Task ID: {task_id}] Using worker-level CacheService (connection pooling)")
            except Exception as e:
                logger.warning(f"[Task ID: {task_id}] Could not get worker-level CacheService ({e}), creating new instance")
                cache_service_instance = CacheService()
                await cache_service_instance.client
                logger.info(f"[Task ID: {task_id}] CacheService initialized (new instance)")

            encryption_service_instance = EncryptionService(
                cache_service=cache_service_instance
            )
            logger.info(f"[Task ID: {task_id}] EncryptionService initialized.")

            directus_service_instance = DirectusService(
                cache_service=cache_service_instance,
                encryption_service=encryption_service_instance
            )
            logger.info(f"[Task ID: {task_id}] DirectusService initialized.")

        from backend.shared.python_utils.recent_work_summary_client import restore_private_context_payload, bind_restored_context_turn
        from backend.shared.python_utils.recent_work_summary_cache import PRIVATE_CONTEXT_FIELDS
        transient = await restore_private_context_payload(request_data.model_dump())
        bind_restored_context_turn(request_data, transient)
        for field in PRIVATE_CONTEXT_FIELDS:
            setattr(request_data, field, transient.get(field, None if field == "accepted_plan_context" else []))

        if request_data.is_sub_chat_continuation and request_data.recovery_consumed_child_ids:
            if not request_data.recovery_preflight_id or not request_data.orchestration_id:
                raise RequiredRecoveryOutputError("Parent continuation lacks durable child recovery identity")
            recovery_service = ChatRecoveryService(directus_service_instance)
            for child_chat_id in request_data.recovery_consumed_child_ids:
                await recovery_service.execute("mark_child_parent_consumed", {
                    "protocol_version": 1,
                    "hashed_user_id": request_data.user_id_hash,
                    "child_chat_id": child_chat_id,
                    "root_chat_id": request_data.root_chat_id or request_data.chat_id,
                    "continuation_task_id": task_id,
                })
                if not await cache_service_instance.release_active_ai_child_context(
                    request_data.user_id_hash, child_chat_id,
                ):
                    raise RequiredRecoveryOutputError("Parent consumed child but its working context could not be released")

        if request_data.is_sub_chat:
            if not all((
                request_data.orchestration_id,
                request_data.root_chat_id,
                request_data.root_turn_id,
                request_data.orchestration_dispatch_token,
            )):
                raise RuntimeError("Sub-chat task is missing its durable orchestration envelope")
            child_claim = await SubChatOrchestrationService(directus_service_instance).execute(
                "claim_child",
                {
                    "protocol_version": 1,
                    "orchestration_id": request_data.orchestration_id,
                    "hashed_user_id": request_data.user_id_hash,
                    "child_chat_id": request_data.chat_id,
                    "dispatch_token": request_data.orchestration_dispatch_token,
                    "inference_task_id": task_id,
                    "is_continuation": bool(
                        request_data.is_sub_chat_continuation
                        or request_data.is_focus_mode_continuation
                        or request_data.is_app_settings_memories_continuation
                        or request_data.is_connected_account_permission_continuation
                        or request_data.is_async_skill_continuation
                    ),
                },
            )
            if child_claim.get("depth") != request_data.sub_chat_depth:
                raise RuntimeError("Sub-chat task depth does not match its durable orchestration record")
            if not child_claim.get("claimed"):
                logger.info(
                    "[Task ID: %s] Skipping duplicate child delivery in state=%s",
                    task_id,
                    child_claim.get("state"),
                )
                return {
                    "status": "duplicate_sub_chat_task_ignored",
                    "preprocessing_summary": {},
                    "main_processing_output": None,
                    "postprocessing_summary": {},
                    "interrupted_by_soft_time_limit": False,
                    "interrupted_by_revocation": False,
                    "_celery_task_state": "SUCCESS",
                }
            if request_data.recovery_preflight_id and not request_data.is_sub_chat_continuation:
                first_message = request_data.message_history[0] if request_data.message_history else None
                if (first_message is None or first_message.role != "user"
                        or first_message.message_id != request_data.message_id):
                    raise RequiredRecoveryOutputError("Child prompt lacks stable recovery identity")
                await _persist_sealed_typed_output(
                    directus_service=directus_service_instance, request_data=request_data,
                    cache_service=cache_service_instance, inference_task_id=task_id,
                    subject_id=request_data.message_id, output_kind="message", output_version=1,
                    message_role="user",
                    content={"role": "user", "content": first_message.content,
                             "category": None, "model_name": None,
                             "created_at": first_message.created_at},
                )

        if request_data.recovery_task_id:
            if request_data.recovery_task_id != task_id:
                raise RuntimeError("Celery task ID does not match durable recovery task identity")
            claim = await ChatRecoveryService(directus_service_instance).execute(
                "claim_inference",
                {"protocol_version": 1, "inference_task_id": task_id},
            )
            if not claim.get("claimed"):
                logger.info(
                    "[Task ID: %s] Skipping duplicate recovery task delivery in state=%s",
                    task_id,
                    claim.get("state"),
                )
                return _recovery_unclaimed_result(claim)

        user_task_claimed = await _update_user_task_execution_state(
            request_data,
            directus_service_instance,
            ai_execution_state="running",
            status="in_progress",
        )
        if request_data.user_task_id and not user_task_claimed:
            return {
                "status": "stale_user_task_dispatch_ignored",
                "preprocessing_summary": {},
                "main_processing_output": None,
                "postprocessing_summary": {},
                "interrupted_by_soft_time_limit": False,
                "interrupted_by_revocation": False,
                "_celery_task_state": "SUCCESS",
            }

    except Exception as e:
        logger.error(f"[Task ID: {task_id}] Failed to initialize services: {e}", exc_info=True)
        
        # Notify the API via Redis stream that a fatal error occurred
        if cache_service_instance:
            try:
                error_payload = {
                    "type": "ai_message_chunk",
                    "task_id": task_id,
                    "chat_id": request_data.chat_id,
                    "full_content_so_far": f"Error: {str(e)}",
                    "is_final_chunk": True,
                    "error": True
                }
                await cache_service_instance.publish_event(f"chat_stream::{request_data.chat_id}", error_payload)
            except Exception:
                pass
                
        if isinstance(e, RequiredRecoveryOutputError):
            raise
        raise RuntimeError(f"Service initialization failed: {e}")

    # NOTE: Idempotency dedup is performed by `DedupedTask.__call__` (the
    # Celery base class hooked in via `task_cls=` on the Celery app, see
    # backend/core/api/app/tasks/base_task.py). It runs sync-redis SET NX
    # BEFORE this async helper is even reached, so duplicate broker
    # deliveries never get this far. Do NOT re-add an async dedup here —
    # the worker-level CacheService caches a redis.asyncio client bound to
    # a stale loop on task redelivery, which silently broke the previous
    # in-place async guard (commit 04d3994cf).

    # --- Load configurations from cache (preloaded by main API server at startup) ---
    # The main API server preloads these into the shared Dragonfly cache during startup.
    # Task workers read from cache to avoid disk I/O and ensure consistency across containers.
    # Fallback to disk loading if cache is empty (e.g., cache expired or server restarted).
    
    base_instructions: Dict[str, Any] = {}
    try:
        if cache_service_instance:
            cached_base_instructions = await cache_service_instance.get_base_instructions()
            if cached_base_instructions:
                base_instructions = cached_base_instructions
                logger.info(f"[Task ID: {task_id}] Successfully loaded base_instructions from cache (preloaded by main API server).")
            else:
                # Fallback: Cache is empty (expired or server restarted) - load from disk and re-cache
                logger.warning(f"[Task ID: {task_id}] base_instructions not found in cache. Loading from disk and re-caching...")
                base_instructions = load_base_instructions()
                if base_instructions:
                    try:
                        await cache_service_instance.set_base_instructions(base_instructions)
                        logger.info(f"[Task ID: {task_id}] Re-cached base_instructions after disk load.")
                    except Exception as e:
                        logger.warning(f"[Task ID: {task_id}] Failed to re-cache base_instructions: {e}")
        else:
            # No cache service available, load from disk
            logger.warning(f"[Task ID: {task_id}] CacheService not available. Loading base_instructions from disk...")
            base_instructions = load_base_instructions()
    except Exception as e:
        logger.error(f"[Task ID: {task_id}] Error loading base_instructions: {e}", exc_info=True)
        # Fallback to disk loading
        base_instructions = load_base_instructions()
    
    if not base_instructions:
        logger.error(f"[Task ID: {task_id}] Failed to load base_instructions.yml from cache or disk. Aborting task.")
        # Sync wrapper handles Celery state update
        raise RuntimeError("base_instructions.yml not found or empty.")

    all_mates_configs: List[MateConfig] = []
    try:
        if cache_service_instance:
            cached_mates_configs = await cache_service_instance.get_mates_configs()
            if cached_mates_configs:
                all_mates_configs = cached_mates_configs
                logger.info(f"[Task ID: {task_id}] Successfully loaded {len(all_mates_configs)} mates_configs from cache (preloaded by main API server).")
            else:
                # Fallback: Cache is empty (expired or server restarted) - load from disk and re-cache
                logger.warning(f"[Task ID: {task_id}] mates_configs not found in cache. Loading from disk and re-caching...")
                all_mates_configs = load_mates_config()
                if all_mates_configs:
                    try:
                        await cache_service_instance.set_mates_configs(all_mates_configs)
                        logger.info(f"[Task ID: {task_id}] Re-cached {len(all_mates_configs)} mates_configs after disk load.")
                    except Exception as e:
                        logger.warning(f"[Task ID: {task_id}] Failed to re-cache mates_configs: {e}")
        else:
            # No cache service available, load from disk
            logger.warning(f"[Task ID: {task_id}] CacheService not available. Loading mates_configs from disk...")
            all_mates_configs = load_mates_config()
    except Exception as e:
        logger.error(f"[Task ID: {task_id}] Error loading mates_configs: {e}", exc_info=True)
        # Fallback to disk loading
        all_mates_configs = load_mates_config()
    
    if not all_mates_configs:
        logger.critical(f"[Task ID: {task_id}] Failed to load mates from cache or disk. Aborting task.")
        # Sync wrapper handles Celery state update
        raise RuntimeError("mates/ directory not found, empty, or invalid.")

    # --- Load discovered_apps_metadata from cache (with fallback to API) ---
    # CRITICAL: Without discovered_apps_metadata, the LLM has NO tools available (no web search, etc.)
    # This can result in the LLM hallucinating tool results instead of actually calling them.
    discovered_apps_metadata: Dict[str, AppYAML] = {}
    try:
        if cache_service_instance:
            cached_metadata = await cache_service_instance.get_discovered_apps_metadata()
            if cached_metadata:
                discovered_apps_metadata = cached_metadata
                # Log discovered apps and their skills for debugging
                app_names = list(discovered_apps_metadata.keys())
                logger.info(f"[Task ID: {task_id}] Loaded discovered_apps_metadata from cache: {len(app_names)} apps ({', '.join(app_names) if app_names else 'None'})")
                for app_id, metadata in discovered_apps_metadata.items():
                    skill_ids = [skill.id for skill in metadata.skills] if metadata.skills else []
                    skill_identifiers = [f"{app_id}.{skill_id}" for skill_id in skill_ids]
                    logger.debug(f"[Task ID: {task_id}]   App '{app_id}': Skills: {', '.join(skill_identifiers) if skill_identifiers else 'None'}")
                
                # Check for critical apps that should normally be available
                _check_critical_apps_availability(discovered_apps_metadata, task_id)
            else:
                # FALLBACK: Cache is empty (expired or flushed) - fetch from API and re-cache
                # This prevents the LLM from having no tools available due to cache expiration
                logger.warning(f"[Task ID: {task_id}] discovered_apps_metadata not found in cache. Attempting fallback to API...")
                discovered_apps_metadata = await _fetch_and_cache_apps_metadata(cache_service_instance, task_id)
                
                if discovered_apps_metadata:
                    app_names = list(discovered_apps_metadata.keys())
                    logger.info(f"[Task ID: {task_id}] Fetched discovered_apps_metadata from API fallback: {len(app_names)} apps ({', '.join(app_names) if app_names else 'None'})")
                    
                    # Warn if only one app is discovered (likely indicates other apps are not running/available)
                    if len(app_names) == 1:
                        logger.warning(
                            f"[Task ID: {task_id}] Only one app discovered ({app_names[0]}). "
                            f"Other app containers may not be running or responding to /metadata endpoint."
                        )
                    
                    for app_id, metadata in discovered_apps_metadata.items():
                        skill_ids = [skill.id for skill in metadata.skills] if metadata.skills else []
                        skill_identifiers = [f"{app_id}-{skill_id}" for skill_id in skill_ids]
                        logger.debug(f"[Task ID: {task_id}]   App '{app_id}': Skills: {', '.join(skill_identifiers) if skill_identifiers else 'None'}")
                    
                    # Check for critical apps that should normally be available
                    _check_critical_apps_availability(discovered_apps_metadata, task_id)
                else:
                    logger.error(
                        f"[Task ID: {task_id}] CRITICAL: Failed to load discovered_apps_metadata from both cache and API. "
                        f"LLM will have NO tools available! This will cause the LLM to hallucinate tool results instead of actually calling them. "
                        f"Check that the API service is running and /apps/metadata endpoint is accessible."
                    )
        else:
            logger.error(f"[Task ID: {task_id}] CacheService instance not available for loading discovered_apps_metadata.")
    except Exception as e_cache_get:
        logger.error(f"[Task ID: {task_id}] Error calling get_discovered_apps_metadata: {e_cache_get}", exc_info=True)

    # --- Fetch user_vault_key_id and warm cache ---
    # This supports internal users (Web App) who may not have logged in via web app to trigger cache warming.
    # We ALWAYS need the user record and credits for the pre-processing credit check.
    # Credits are encrypted, so the vault_key_id is mandatory for all billable requests.
    user_vault_key_id: Optional[str] = None
    if getattr(request_data, "is_anonymous", False):
        logger.info(f"[Task ID: {task_id}] Anonymous free-usage request. Skipping Directus user cache warmup and vault-key lookup.")
    elif cache_service_instance and request_data.user_id:
        cached_user_data = await cache_service_instance.get_user_by_id(request_data.user_id)
        
        cache_missing_required_billing_fields = (
            not cached_user_data
            or not cached_user_data.get("vault_key_id")
            or not cached_user_data.get("encrypted_credit_balance")
        )
        if cache_missing_required_billing_fields:
            # ON-DEMAND CACHE WARMING: User not in cache, or cache was seeded by
            # a lightweight API-key auth path without vault/billing fields.
            # This is required for both internal and external requests to check balance.
            if cached_user_data:
                logger.warning(
                    f"[Task ID: {task_id}] Cached user data is missing vault/billing fields; "
                    f"refreshing from Directus for user_id: {request_data.user_id}"
                )
            else:
                logger.info(f"[Task ID: {task_id}] User not in cache, warming cache for user_id: {request_data.user_id}")
            try:
                if directus_service_instance:
                    # Fetch user data using /users/{id} endpoint (NOT /items/users which requires special permissions)
                    # The get_user_fields_direct method correctly uses the /users/{id} endpoint
                    # which the admin token can access for any user
                    user_record = await directus_service_instance.get_user_fields_direct(
                        request_data.user_id,
                        fields=['id', 'vault_key_id', 'encrypted_username', 'encrypted_credit_balance']
                    )
                    
                    if user_record:
                        cache_data = {
                            'id': user_record.get('id') or request_data.user_id,
                            'user_id': user_record.get('id') or request_data.user_id,
                            'vault_key_id': user_record.get('vault_key_id'),
                            'encrypted_username': user_record.get('encrypted_username'),
                            'encrypted_credit_balance': user_record.get('encrypted_credit_balance'),
                            '_api_warmed': True
                        }
                        
                        # MANDATORY: Decrypt credits for the cache so preprocessor can check balance
                        # Field name is 'encrypted_credit_balance' (not 'encrypted_credits')
                        if user_record.get('encrypted_credit_balance') and user_record.get('vault_key_id'):
                            try:
                                decrypted_credits_str = await directus_service_instance.encryption_service.decrypt_with_user_key(
                                    user_record.get('encrypted_credit_balance'), 
                                    user_record.get('vault_key_id')
                                )
                                if decrypted_credits_str:
                                    cache_data['credits'] = int(decrypted_credits_str)
                                    logger.info(f"[Task ID: {task_id}] Successfully decrypted credits for user {request_data.user_id}: {cache_data['credits']}")
                            except Exception as e_dec:
                                logger.error(f"[Task ID: {task_id}] Failed to decrypt credits: {e_dec}")
                                # If we can't decrypt credits, we can't safely proceed
                                raise RuntimeError(f"Could not decrypt user credits: {e_dec}")
                        
                        await cache_service_instance.set_user(cache_data, user_id=request_data.user_id)
                        cached_user_data = cache_data
                    else:
                        logger.error(f"[Task ID: {task_id}] User not found in Directus: {request_data.user_id}")
                        raise RuntimeError(f"User not found: {request_data.user_id}")
                else:
                    raise RuntimeError("DirectusService not available for cache warming")
            except Exception as e:
                logger.error(f"[Task ID: {task_id}] Cache warming failed: {e}", exc_info=True)
                # Notify the API via Redis stream so it doesn't hang
                if cache_service_instance:
                    try:
                        error_payload = {
                            "type": "ai_message_chunk",
                            "task_id": task_id,
                            "chat_id": request_data.chat_id,
                            "full_content_so_far": "Error: User identification or credit check failed.",
                            "is_final_chunk": True,
                            "error": True
                        }
                        await cache_service_instance.publish_event(f"chat_stream::{request_data.chat_id}", error_payload)
                    except Exception:
                        pass
                raise RuntimeError(f"Failed to identify user or check credits: {e}")

        from backend.shared.python_utils.recent_work_summary_client import mark_response_summary_active
        await mark_response_summary_active(request_data, task_id)
        user_vault_key_id = cached_user_data.get("vault_key_id")
        if not user_vault_key_id:
            logger.error(f"[Task ID: {task_id}] vault_key_id not found for user {request_data.user_id}. Aborting.")
            raise RuntimeError("User vault key ID not found.")
            
    elif not cache_service_instance:
        logger.error(f"[Task ID: {task_id}] CacheService not available.")
        raise RuntimeError("CacheService not available.")
    elif not request_data.user_id:
        logger.error(f"[Task ID: {task_id}] user_id is missing.")
        raise RuntimeError("user_id is missing.")

    # Preserve only the reference-to-embed mapping needed by later skill calls.
    # The payload is Vault-encrypted and contains no artifact bytes or extracted content.
    recovered_inline_artifacts = await recover_inline_upload_artifacts(
        cache_service=cache_service_instance,
        chat_id=request_data.chat_id,
        message_history=request_data.message_history,
    )
    current_artifact_index = {
        **recovered_inline_artifacts,
        **(request_data.embed_file_path_index or {}),
    }
    request_data.embed_file_path_index = await load_and_merge_artifact_ledger(
        cache_service=cache_service_instance,
        encryption_service=encryption_service_instance,
        user_vault_key_id=user_vault_key_id,
        user_id_hash=request_data.user_id_hash,
        chat_id=request_data.chat_id,
        current_index=current_artifact_index,
        persist=not request_data.is_incognito and not request_data.is_external,
    ) or None
    request_data.historical_artifact_context = None
    if request_data.embed_file_path_index and user_vault_key_id:
        try:
            from backend.core.api.app.services.embed_service import EmbedService

            request_data.historical_artifact_context = await build_historical_artifact_context(
                embed_service=EmbedService(
                    cache_service=cache_service_instance,
                    directus_service=directus_service_instance,
                    encryption_service=encryption_service_instance,
                ),
                user_vault_key_id=user_vault_key_id,
                current_user_content=request_data.current_user_content,
                artifact_index=request_data.embed_file_path_index,
                log_prefix=f"[Task ID: {task_id}] ",
            )
        except Exception as exc:
            logger.warning(
                "[Task ID: %s] Historical artifact context unavailable; continuing (%s)",
                task_id,
                type(exc).__name__,
            )

    # Parse app settings/memories metadata from client
    # CLIENT IS THE SOURCE OF TRUTH - only the client can decrypt this data
    # Format from client: ["code-preferred_technologies", "travel-trips", ...]
    # Convert to dict format for preprocessor: { "app_id": ["item_type1", "item_type2"], ... }
    user_app_memories_metadata: Dict[str, List[str]] = {}
    if request_data.app_settings_memories_metadata:
        for key in request_data.app_settings_memories_metadata:
            if not isinstance(key, str):
                logger.warning(f"[Task ID: {task_id}] Invalid app_settings_memories_metadata key (not a string): {key}")
                continue
            
            # Parse "app_id-item_type" format
            dash_index = key.find('-')
            if dash_index == -1:
                logger.warning(f"[Task ID: {task_id}] Invalid app_settings_memories_metadata key format (no hyphen): {key}")
                continue
            
            app_id = key[:dash_index]
            item_type = key[dash_index + 1:]
            
            if not app_id or not item_type:
                logger.warning(f"[Task ID: {task_id}] Invalid app_settings_memories_metadata key (empty parts): {key}")
                continue
            
            if app_id not in user_app_memories_metadata:
                user_app_memories_metadata[app_id] = []
            if item_type not in user_app_memories_metadata[app_id]:
                user_app_memories_metadata[app_id].append(item_type)
        
        if user_app_memories_metadata:
            logger.info(f"[Task ID: {task_id}] Parsed client-provided app_settings_memories_metadata: {len(user_app_memories_metadata)} apps, {sum(len(keys) for keys in user_app_memories_metadata.values())} total keys")
        else:
            logger.debug(f"[Task ID: {task_id}] Client provided app_settings_memories_metadata but no valid keys found.")
    else:
        logger.debug(f"[Task ID: {task_id}] No app_settings_memories_metadata provided by client.")

    # --- Step 0: Parse User Overrides (@ Mentioning) ---
    # Parse user messages for override syntax like @ai-model:claude-opus, @mate:coder, etc.
    # These overrides allow users to manually select AI models, mates, skills, or focus modes.
    # The overrides are applied later in preprocessing to skip automatic selection where specified.
    user_overrides: Optional[UserOverrides] = None
    try:
        if request_data.message_history:
            # Convert AIHistoryMessage objects to dicts for parsing
            message_dicts = [
                {"role": msg.role, "content": msg.content}
                for msg in request_data.message_history
            ]
            user_overrides, cleaned_messages = parse_overrides_from_messages(
                message_dicts,
                log_prefix=f"[Task ID: {task_id}]"
            )

            if user_overrides and user_overrides.has_overrides:
                logger.info(
                    f"[Task ID: {task_id}] USER_OVERRIDE: Detected user overrides. "
                    f"model_id={user_overrides.model_id}, "
                    f"model_provider={user_overrides.model_provider}, "
                    f"mate_id={user_overrides.mate_id}, "
                    f"skills={user_overrides.skills}, "
                    f"focus_modes={user_overrides.focus_modes}"
                )

                # Update the last user message with cleaned content (override syntax removed)
                # This ensures the LLM sees the actual query without the override commands
                if cleaned_messages:
                    for i in range(len(request_data.message_history) - 1, -1, -1):
                        if request_data.message_history[i].role == "user":
                            # Update the content of the Pydantic model directly
                            request_data.message_history[i].content = cleaned_messages[i]["content"]
                            logger.debug(
                                f"[Task ID: {task_id}] Updated last user message content "
                                f"after removing override syntax. New length: {len(cleaned_messages[i]['content'])}"
                            )
                            break

        if (not user_overrides or not user_overrides.has_overrides) and request_data.current_user_content:
            user_overrides = parse_overrides(
                request_data.current_user_content,
                log_prefix=f"[Task ID: {task_id}]",
            )
            if user_overrides.has_overrides:
                request_data.current_user_content = user_overrides.cleaned_message
                logger.info(
                    f"[Task ID: {task_id}] USER_OVERRIDE: Detected user overrides in current_user_content. "
                    f"model_id={user_overrides.model_id}, "
                    f"model_provider={user_overrides.model_provider}, "
                    f"mate_id={user_overrides.mate_id}, "
                    f"skills={user_overrides.skills}, "
                    f"focus_modes={user_overrides.focus_modes}"
                )
    except Exception as e_override:
        logger.warning(
            f"[Task ID: {task_id}] Failed to parse user overrides (non-fatal): {e_override}. "
            f"Proceeding without overrides."
        )
        user_overrides = None

    # --- TEST MOCK/RECORD DETECTION ---
    # Detect <<<TEST_MOCK:fixture_id>>> or <<<TEST_RECORD:fixture_id>>> markers in the
    # last user message. When found, skip real LLM inference and replay pre-recorded
    # fixture data through the same Redis channels. Everything else (encryption, billing,
    # postprocessing, persistence) remains real.
    # SECURITY: Only works when SERVER_ENVIRONMENT != "production".
    _test_marker = None  # None or (mode, fixture_id, speed_override)
    _fixture_recorder = None  # FixtureRecorder instance for record mode
    if os.getenv("SERVER_ENVIRONMENT", "production") != "production":
        from backend.apps.ai.testing.mock_replay import detect_marker, strip_marker
        if request_data.message_history:
            last_user_msg = next(
                (m for m in reversed(request_data.message_history) if m.role == "user"),
                None,
            )
            if last_user_msg:
                _test_marker = detect_marker(last_user_msg.content)
                if _test_marker:
                    last_user_msg.content = strip_marker(last_user_msg.content)
                    logger.info(
                        f"[Task ID: {task_id}] TEST {_test_marker[0].upper()}: "
                        f"fixture='{_test_marker[1]}', speed_override={_test_marker[2]}"
                    )
                    if _test_marker[0] == "record":
                        from backend.apps.ai.testing.fixture_recorder import FixtureRecorder
                        _fixture_recorder = FixtureRecorder(_test_marker[1], request_data)
                        # Bind the recorder to the current async context so main_processor's
                        # _publish_skill_status can capture skill_execution events without
                        # needing the recorder plumbed through the whole call chain.
                        # See backend/apps/ai/testing/mock_replay.py for the ContextVar.
                        from backend.apps.ai.testing.mock_replay import set_active_fixture_recorder
                        set_active_fixture_recorder(_fixture_recorder)

    # Detect signed, server-authorized live replay/record markers. Unlike TEST_MOCK,
    # live mock runs the full pipeline and intercepts only external provider calls.
    _live_marker = None
    from backend.shared.testing.mock_context import resolve_live_marker_or_raise, strip_live_marker, activate_mock_mode

    if request_data.message_history:
        last_user_msg = next(
            (m for m in reversed(request_data.message_history) if m.role == "user"),
            None,
        )
        if last_user_msg:
            marker_content = last_user_msg.content
            _live_marker = resolve_live_marker_or_raise(marker_content, request_data.user_id)
            if _live_marker and _test_marker:
                raise RuntimeError("Cannot combine TEST_MOCK/TEST_RECORD with TEST_LIVE marker")
            if _live_marker:
                live_mode, live_group, live_run_id = _live_marker
                last_user_msg.content = strip_live_marker(last_user_msg.content)
                if request_data.current_user_content:
                    request_data.current_user_content = strip_live_marker(request_data.current_user_content)
                candidate_root = None
                candidate_base = Path(
                    os.getenv("LIVE_MOCK_CANDIDATE_ROOT", "/tmp/openmates-live-mock-candidates")
                )
                if live_mode in {"record", "mock"} and live_run_id:
                    candidate_root = candidate_base / live_run_id / "cache"
                activate_mock_mode(
                    live_mode,
                    live_group,
                    candidate_root=candidate_root,
                    candidate_run_id=live_run_id,
                    task_id=task_id,
                )
                request_data.live_mock_mode = live_mode
                request_data.live_mock_group = live_group
                logger.info(
                    f"[Task ID: {task_id}] LIVE {live_mode.upper()}: "
                    f"group='{live_group}' — full pipeline with cached API responses"
                )

    # --- MOCK BRANCH: Skip compression + preprocessing + main processing ---
    # When a TEST_MOCK marker is detected, replay pre-recorded fixture data and jump
    # directly to postprocessing. All variables that postprocessing depends on are set
    # from the fixture.
    if _test_marker and _test_marker[0] == "mock":
        from backend.apps.ai.testing.mock_replay import replay_fixture
        compression_performed = False
        mock_result = await replay_fixture(
            fixture_id=_test_marker[1],
            task_id=task_id,
            request_data=request_data,
            cache_service=cache_service_instance,
            speed_override=_test_marker[2],
            directus_service=directus_service_instance,
            encryption_service=encryption_service_instance,
            user_vault_key_id=user_vault_key_id,
        )
        preprocessing_result = mock_result["preprocessing_result"]
        aggregated_final_response = mock_result["aggregated_final_response"]
        thinking_content = mock_result.get("thinking_content", [])
        main_processor_debug_metadata = mock_result.get("main_processor_debug_metadata", {})
        revoked_in_consumer = False
        soft_limited_in_consumer = False
        task_was_revoked = False
        task_was_soft_limited = False

        # Persist server provider/region on preprocessing_result for billing
        preprocessing_result.server_provider_name = "Mock"
        preprocessing_result.server_region = None

        logger.info(
            f"[Task ID: {task_id}] MOCK replay complete. "
            f"Response: {len(aggregated_final_response)} chars. "
            f"Skipping to queue processing + postprocessing."
        )
    else:
        # ═══ NORMAL FLOW: real compression + preprocessing + main processing ═══

        compression_performed = False
        # --- Step 1: Preprocessing ---
        # The synchronous wrapper (process_ai_skill_ask_task) will call self.update_state for PROGRESS.
        logger.info(f"[Task ID: {task_id}] Starting preprocessing step...")
        logger.info(f"[Task ID: {task_id}] Chat has title flag from request_data: {request_data.chat_has_title}")

        preprocessing_result: Optional[PreprocessingResult] = None
        try:
            if not cache_service_instance:
                logger.error(f"[Task ID: {task_id}] CacheService instance is not available. Cannot proceed with preprocessing credit check.")
                raise RuntimeError("CacheService not available for preprocessing.")

            # Build the preprocessing stream channel so the preprocessor can emit real-time step events.
            # Channel format: preprocessing_stream::{user_id_hash}
            # The frontend WebSocket listener subscribes to this channel via user_id_hash.
            # is_new_chat is True when the chat has no title yet (first message in a new chat).
            # This drives whether the "Generating chat title..." step is shown.
            preprocessing_stream_channel = (
                f"preprocessing_stream::{request_data.user_id_hash}"
                if request_data.user_id_hash and not request_data.is_external
                else None
            )
            is_new_chat_for_preprocessing = not request_data.chat_has_title

            # A continuation may carry an opaque reference created by the original
            # worker. Recheck the current Project focus before comparing contexts:
            # a Project consent can expose private specialists and rules mid-turn.
            if request_data.preprocessing_resume_ref and (
                request_data.is_async_skill_continuation
                or request_data.is_focus_mode_continuation
                or request_data.is_app_settings_memories_continuation
                or request_data.is_connected_account_permission_continuation
                or request_data.is_sub_chat_continuation
            ) and not request_data.is_incognito:
                from backend.core.api.app.services.project_write_authorization_service import ProjectWriteAuthorizationService
                try:
                    request_data.active_project_focus = await ProjectWriteAuthorizationService(
                        directus_service_instance, cache_service_instance,
                    ).get_active_focus(user_id=request_data.user_id, chat_id=request_data.chat_id)
                except Exception:
                    logger.warning("[Task ID: %s] Fresh Project context unavailable; rerouting", task_id)
                    request_data.preprocessing_resume_ref = None
                    request_data.active_project_focus = None
                if request_data.active_project_focus:
                    focus = request_data.active_project_focus
                    request_data.current_project = {
                        key: focus.get(key) for key in (
                            "project_id", "project_id_hash", "team_id", "team_id_hash"
                        )
                    }

            from backend.apps.ai.tasks.preprocessing_resume import (
                load_preprocessing_resume, store_preprocessing_resume,
            )
            resume = await load_preprocessing_resume(cache_service_instance, request_data)
            selected_app_ids = resume[1] if resume and resume[2] else None
            if resume and not resume[2]:
                from backend.apps.ai.processing.preprocessor import check_preprocessing_credits
                credit_rejection = await check_preprocessing_credits(
                    request_data, cache_service_instance, directus_service_instance,
                    encryption_service_instance,
                )
                preprocessing_result = credit_rejection or resume[0]
                request_data._preselected_rule_project_activation = (
                    (request_data.active_project_focus or {}).get("activation_id")
                )
                logger.info("[Task ID: %s] Reused current-turn preprocessing decisions", task_id)

            if preprocessing_result is None:
                with ai_phase_span("preprocess"):
                    _log_team_ai_pipeline_stage(request_data, task_id, "preprocess", "started")
                    preprocessing_result = await handle_preprocessing(
                        request_data=request_data,
                        skill_config=skill_config,
                        base_instructions=base_instructions,
                        cache_service=cache_service_instance,
                        secrets_manager=secrets_manager,
                        directus_service=directus_service_instance,
                        encryption_service=encryption_service_instance,
                        user_app_settings_and_memories_metadata=user_app_memories_metadata,
                        discovered_apps_metadata=discovered_apps_metadata,
                        user_overrides=user_overrides,
                        preprocessing_stream_channel=preprocessing_stream_channel,
                        is_new_chat=is_new_chat_for_preprocessing,
                        selected_app_ids=selected_app_ids,
                    )
                    _log_team_ai_pipeline_stage(request_data, task_id, "preprocess", "completed")
                new_ref = await store_preprocessing_resume(
                    cache_service_instance, request_data, preprocessing_result,
                )
                if new_ref:
                    request_data.preprocessing_resume_ref = new_ref

            # --- TEST RECORD: capture preprocessing result ---
            if _fixture_recorder and preprocessing_result:
                _fixture_recorder.record_preprocessing(preprocessing_result)

            # --- Cache debug data for preprocessing stage ---
            # This caches the last 10 requests for debugging purposes (encrypted, 30-minute TTL)
            # IMPORTANT: Store FULL content to enable proper debugging of the AI decision process
            try:
                if cache_service_instance and encryption_service_instance:
                    # Prepare preprocessor input data with FULL message history for debugging
                    # Convert message history to serializable format
                    message_history_serialized = None
                    if request_data.message_history:
                        message_history_serialized = [
                            msg.model_dump() if hasattr(msg, 'model_dump') else (
                                {"role": msg.role, "content": msg.content, "created_at": msg.created_at, 
                                 "sender_name": getattr(msg, 'sender_name', None), "category": getattr(msg, 'category', None)}
                                if hasattr(msg, 'role') else msg
                            )
                            for msg in request_data.message_history
                        ]
                
                    preprocessor_input = {
                        "chat_id": request_data.chat_id,
                        "message_id": request_data.message_id,
                        "user_id": request_data.user_id,
                        "user_id_hash": request_data.user_id_hash,
                        "chat_has_title": request_data.chat_has_title,
                        "mate_id": request_data.mate_id,
                        "active_focus_id": request_data.active_focus_id,
                        "user_preferences": request_data.user_preferences,
                        # FULL message history for debugging
                        "message_history": message_history_serialized,
                        "message_history_count": len(request_data.message_history) if request_data.message_history else 0,
                        # Skill config
                        "skill_config": skill_config.model_dump() if skill_config else None,
                        # Discovered apps metadata
                        "discovered_apps_count": len(discovered_apps_metadata) if discovered_apps_metadata else 0,
                        "discovered_app_ids": list(discovered_apps_metadata.keys()) if discovered_apps_metadata else [],
                        # Base instructions: include full preprocessor tool definitions for debugging
                        # (the tool description contains the rendered system prompt for preprocessing)
                        "base_instructions_keys": list(base_instructions.keys()) if base_instructions else [],
                        "preprocessor_tool_definition": base_instructions.get("preprocess_request_tool") if base_instructions else None,
                        "preprocessor_fast_tool_definition": base_instructions.get("fast_preprocess_request_tool") if base_instructions else None,
                        # App memories metadata from client (what's available to choose from)
                        # Raw format from client: ["code-preferred_technologies", "travel-trips", ...]
                        "app_settings_memories_metadata_from_client": request_data.app_settings_memories_metadata,
                        "app_settings_memories_metadata_from_client_count": len(request_data.app_settings_memories_metadata) if request_data.app_settings_memories_metadata else 0,
                        # Parsed format used by preprocessor: { "app_id": ["item_type1", "item_type2"], ... }
                        "user_app_memories_metadata_parsed": user_app_memories_metadata,
                        "user_app_memories_metadata_parsed_apps_count": len(user_app_memories_metadata) if user_app_memories_metadata else 0,
                        "user_app_memories_metadata_parsed_total_keys": sum(len(keys) for keys in user_app_memories_metadata.values()) if user_app_memories_metadata else 0,
                    }
                
                    # Prepare preprocessor output data (full model dump)
                    preprocessor_output = preprocessing_result.model_dump() if preprocessing_result else None
                
                    await cache_service_instance.cache_debug_request_entry(
                        encryption_service=encryption_service_instance,
                        task_id=task_id,
                        chat_id=request_data.chat_id,
                        user_id=request_data.user_id,
                        stage="preprocessor",
                        input_data=preprocessor_input,
                        output_data=preprocessor_output,
                    )
                    logger.debug(f"[Task ID: {task_id}] Cached preprocessor debug data (admin only)")
            except Exception as e_debug:
                # Don't fail the task if debug caching fails - just log the error
                logger.warning(f"[Task ID: {task_id}] Failed to cache preprocessor debug data (non-fatal): {e_debug}")

            # Note: We no longer handle harmful content rejection here.
            # Instead, we let it flow through to the stream consumer which will handle it properly
            # with the normal streaming flow, ensuring the frontend gets proper completion signals.
        except Exception as e:
            logger.error(f"[Task ID: {task_id}] Error during preprocessing: {e}", exc_info=True)
            raise RuntimeError(f"Preprocessing failed: {e}")

        if user_overrides:
            available_focus_modes = set()
            for app_id, app_metadata in (discovered_apps_metadata or {}).items():
                focuses = getattr(app_metadata, "focuses", None) or []
                for focus in focuses:
                    focus_id = getattr(focus, "id", None)
                    if focus_id:
                        available_focus_modes.add(f"{app_id}-{focus_id}")
            latest_message = user_overrides.cleaned_message
            plan_route = route_plan_focus(
                latest_message,
                plan_requested=user_overrides.plan_requested,
                available_focus_modes=available_focus_modes,
            )
            # Project focus takes precedence over automatic catalog planning.
            project_focus_selected = bool(request_data.active_project_focus) or any(
                focus.startswith("project-")
                for focus in (preprocessing_result.relevant_focus_modes or [])
            )
            if (
                plan_route.should_plan
                and plan_route.active_focus_id
                and not request_data.active_focus_id
                and not project_focus_selected
                and not getattr(preprocessing_result, "user_requested_focus_only", False)
            ):
                request_data.active_focus_id = plan_route.active_focus_id
                logger.info(
                    f"[Task ID: {task_id}] PLAN_ROUTING: Set active_focus_id='{plan_route.active_focus_id}' "
                    f"reason={plan_route.reason}"
                )

        # --- Billing preflight validation ---
        # Ensure that we have pricing info configured for the selected provider/model BEFORE we start streaming.
        # Skip preflight entirely if preprocessing says we cannot proceed (e.g., insufficient credits, harmful content).
        if preprocessing_result and preprocessing_result.can_proceed:
            try:
                if not preprocessing_result.selected_main_llm_model_id:
                    raise RuntimeError("Selected main LLM model id missing from preprocessing result.")

                full_model_id: str = preprocessing_result.selected_main_llm_model_id

                # Validate provider pricing exists via local worker ConfigManager only.
                if not celery_config.config_manager:
                    raise RuntimeError("Global ConfigManager not initialized in worker. Provider pricing unavailable.")

                # Expected format: "provider/model_name" (e.g., "openai/gpt-5").
                # If a stale client/config emits a raw model id, recover to a billable fallback
                # instead of dropping the user request before any response can stream.
                if "/" not in full_model_id:
                    resolved_provider = celery_config.config_manager.find_provider_for_model(full_model_id)
                    if resolved_provider:
                        full_model_id = f"{resolved_provider}/{full_model_id}"
                    else:
                        logger.warning(
                            f"[Task ID: {task_id}] Billing preflight received unresolved model id "
                            f"'{full_model_id}'. Falling back to {DEFAULT_FALLBACK_MODEL}."
                        )
                        full_model_id = DEFAULT_FALLBACK_MODEL

                provider_prefix, model_suffix = full_model_id.split("/", 1)  # Keep nested model ids intact for pricing lookup
                preprocessing_result.selected_main_llm_model_id = full_model_id

                provider_pricing_cfg = celery_config.config_manager.get_provider_config(provider_prefix)
                if not provider_pricing_cfg:
                    raise RuntimeError(
                        f"Pricing configuration missing for provider '{provider_prefix}'. Ensure '/app/backend/providers/{provider_prefix}.yml' is mounted for the worker."
                    )

                model_pricing_details = celery_config.config_manager.get_model_pricing(provider_prefix, model_suffix)
                if not model_pricing_details:
                    logger.warning(
                        f"[Task ID: {task_id}] Pricing details missing for model '{model_suffix}' "
                        f"under provider '{provider_prefix}'. Falling back to {DEFAULT_FALLBACK_MODEL}."
                    )
                    provider_prefix, model_suffix = DEFAULT_FALLBACK_MODEL.split("/", 1)
                    provider_pricing_cfg = celery_config.config_manager.get_provider_config(provider_prefix)
                    model_pricing_details = celery_config.config_manager.get_model_pricing(provider_prefix, model_suffix)
                    if not provider_pricing_cfg or not model_pricing_details:
                        raise RuntimeError(
                            f"Pricing details missing for fallback model '{DEFAULT_FALLBACK_MODEL}'. "
                            "Billing preflight cannot safely continue."
                        )
                    preprocessing_result.selected_main_llm_model_id = DEFAULT_FALLBACK_MODEL

                logger.info(
                    f"[Task ID: {task_id}] Billing preflight validation passed for provider='{provider_prefix}', model='{model_suffix}'."
                )
            except Exception as billing_preflight_exc:
                logger.critical(
                    f"[Task ID: {task_id}] Billing preflight validation failed: {billing_preflight_exc}",
                    exc_info=True,
                )
                # Fail early to prevent unbillable processing
                raise RuntimeError(f"Billing preflight failed: {billing_preflight_exc}")
        else:
            logger.info(f"[Task ID: {task_id}] Skipping billing preflight: preprocessing.can_proceed is False (reason: {getattr(preprocessing_result, 'rejection_reason', None)}).")

        # Compress only after the exact answer model is known. Admin overrides still
        # take precedence, and any compression/provider failure remains non-fatal.
        if (
            preprocessing_result
            and preprocessing_result.can_proceed
            and preprocessing_result.selected_main_llm_model_id
            and cache_service_instance
            and encryption_service_instance
            and user_vault_key_id
        ):
            try:
                compression_performed = await _compress_for_selected_model(
                    task_id=task_id,
                    request_data=request_data,
                    selected_model_id=preprocessing_result.selected_main_llm_model_id,
                    cache_service=cache_service_instance,
                    encryption_service=encryption_service_instance,
                    user_vault_key_id=user_vault_key_id,
                    secrets_manager=secrets_manager,
                    directus_service=directus_service_instance,
                )
            except Exception as compression_error:
                if isinstance(compression_error, RecoveryCheckpointPersistenceError):
                    raise
                logger.error(
                    "[Task ID: %s] Model-aware chat compression failed non-fatally: %s",
                    task_id,
                    compression_error,
                    exc_info=True,
                )

        # --- Handle Title and Mates Update (after preprocessing) ---
        # Note: We now handle title/mates updates for both successful and harmful content cases
        # since harmful content still gets processed through the stream consumer
        # Title and metadata will be sent via ai_typing_started event below

        # --- Notify client that main processing (typing) is starting ---
        # Note: We send typing indicator for successful and harmful content cases
        # since harmful content gets processed through the stream consumer with a predefined response.
        # SKIP for insufficient_credits: these generate a system notice (not an assistant response),
        # so showing a typing indicator would misleadingly look like a regular assistant is responding.
        should_send_typing = (
            preprocessing_result.rejection_reason != "insufficient_credits"
            and preprocessing_result.rejection_reason != "internal_error_llm_preprocessing_failed"
        ) if preprocessing_result else True
        if preprocessing_result and cache_service_instance and should_send_typing:
            try:
                # Use category from preprocessing_result for typing indicator
                typing_category = preprocessing_result.category or "general_knowledge" # Default if category is None
                # Get model_name from preprocessing_result
                # CRITICAL: For error messages (e.g. insufficient credits), we don't show a model name
                model_name = preprocessing_result.selected_main_llm_model_name if preprocessing_result.can_proceed else None
            
                # Extract provider from the selected_main_llm_model_id (format: "provider/model")
                # Then get the actual server (e.g., Cerebras) from the provider config
                # CRITICAL: We must always extract a real server/provider name, never default to "AI"
                provider_name = None  # Will be set from config
                server_region = None  # Will be set from config (e.g., "EU", "US", "APAC")
            
                if preprocessing_result.selected_main_llm_model_id:
                    logger.info(f"[Task ID: {task_id}] Starting provider name extraction from model_id: '{preprocessing_result.selected_main_llm_model_id}'")
                    model_id_parts = preprocessing_result.selected_main_llm_model_id.split("/", 1)
                    if len(model_id_parts) == 2:
                        provider_id = model_id_parts[0]
                        model_id = model_id_parts[1]
                        logger.debug(f"[Task ID: {task_id}] Parsed provider_id='{provider_id}', model_id='{model_id}'")
                    
                        # Get the actual server running the model from ConfigManager
                        if celery_config.config_manager:
                            provider_config = celery_config.config_manager.get_provider_config(provider_id)
                            if provider_config and 'models' in provider_config:
                                logger.debug(f"[Task ID: {task_id}] Provider config found for '{provider_id}', has {len(provider_config['models'])} model(s)")
                                # Find the model in the provider config
                                model_found = False
                                available_model_ids = [m.get('id') for m in provider_config['models']]
                                logger.debug(f"[Task ID: {task_id}] Searching for model_id='{model_id}' in available models: {available_model_ids}")
                                for model_cfg in provider_config['models']:
                                    if model_cfg.get('id') == model_id:
                                        model_found = True
                                        # Get the default_server (e.g., "cerebras")
                                        default_server_id = model_cfg.get('default_server')
                                        logger.debug(f"[Task ID: {task_id}] Model '{model_id}' has default_server='{default_server_id}', servers list exists: {'servers' in model_cfg}")
                                    
                                        if default_server_id and 'servers' in model_cfg:
                                            # Find the server entry and get its name
                                            server_found = False
                                            servers_list = model_cfg['servers']
                                            logger.debug(f"[Task ID: {task_id}] Searching for server '{default_server_id}' in {len(servers_list)} server(s): {[s.get('id') for s in servers_list]}")
                                        
                                            for server in servers_list:
                                                server_id = server.get('id')
                                                logger.debug(f"[Task ID: {task_id}] Checking server id '{server_id}' against default_server '{default_server_id}' (match: {server_id == default_server_id})")
                                                if server_id == default_server_id:
                                                    provider_name = server.get('name')
                                                    server_region = server.get('region')  # e.g., "EU", "US", "APAC"
                                                    logger.debug(f"[Task ID: {task_id}] Server match found! Server name: '{provider_name}', region: '{server_region}'")
                                                    if not provider_name:
                                                        # Server name not set, use capitalized server ID
                                                        provider_name = default_server_id.capitalize()
                                                        logger.warning(f"[Task ID: {task_id}] Server '{default_server_id}' found but has no 'name' field, using capitalized ID '{provider_name}'")
                                                    else:
                                                        logger.info(f"[Task ID: {task_id}] ✅ Successfully extracted server name '{provider_name}', region '{server_region}' for default_server '{default_server_id}' in model '{model_id}'")
                                                    server_found = True
                                                    break
                                            if not server_found:
                                                # Server not found in servers list, use capitalized server ID
                                                provider_name = default_server_id.capitalize()
                                                logger.warning(f"[Task ID: {task_id}] Server '{default_server_id}' not found in servers list for model '{model_id}'. Available server IDs: {[s.get('id') for s in servers_list]}. Using capitalized ID '{provider_name}'")
                                        else:
                                            # Model found but no default_server or servers configured
                                            # Fallback to provider name from provider config
                                            provider_name = provider_config.get('name') or provider_id.capitalize()
                                            if not default_server_id:
                                                logger.warning(f"[Task ID: {task_id}] Model '{model_id}' has no default_server configured, using provider name '{provider_name}'")
                                            else:
                                                logger.warning(f"[Task ID: {task_id}] Model '{model_id}' has no servers list configured, using provider name '{provider_name}'")
                                        break
                            
                                if not model_found:
                                    # Model not found in config, fallback to provider name from provider config
                                    provider_name = provider_config.get('name') or provider_id.capitalize()
                                    logger.warning(f"[Task ID: {task_id}] Model '{model_id}' not found in provider '{provider_id}' config, using provider name '{provider_name}'")
                            elif provider_config:
                                # Provider config exists but no models list, use provider name
                                provider_name = provider_config.get('name') or provider_id.capitalize()
                                logger.warning(f"[Task ID: {task_id}] Provider '{provider_id}' config has no models list, using provider name '{provider_name}'")
                            else:
                                # Provider config not found, use capitalized provider ID as fallback
                                provider_name = provider_id.capitalize()
                                logger.warning(f"[Task ID: {task_id}] Provider config not found for '{provider_id}', using capitalized provider ID '{provider_name}'")
                        else:
                            # ConfigManager not available, use capitalized provider ID as fallback
                            provider_name = provider_id.capitalize()
                            logger.warning(f"[Task ID: {task_id}] ConfigManager not available, using capitalized provider ID '{provider_name}'")
                    
                        logger.debug(f"[Task ID: {task_id}] Final provider name: '{provider_name}' from model_id '{preprocessing_result.selected_main_llm_model_id}'")
                    else:
                        # Model ID doesn't have expected format (provider/model)
                        # Try to extract provider from the beginning of the string
                        logger.warning(f"[Task ID: {task_id}] Model ID '{preprocessing_result.selected_main_llm_model_id}' doesn't have expected format 'provider/model'.")
                        # Use the first part as provider ID if it exists
                        if model_id_parts and len(model_id_parts) > 0:
                            potential_provider = model_id_parts[0]
                            provider_name = potential_provider.capitalize()
                            logger.warning(f"[Task ID: {task_id}] Using extracted provider ID '{provider_name}' from malformed model ID")
                        else:
                            # Last resort: use the whole model ID as provider name
                            provider_name = preprocessing_result.selected_main_llm_model_id.capitalize()
                            logger.warning(f"[Task ID: {task_id}] Using entire model ID as provider name '{provider_name}'")
                else:
                    # selected_main_llm_model_id is None - this is a critical error, but we still need a fallback
                    logger.error(f"[Task ID: {task_id}] selected_main_llm_model_id is None or empty! Cannot determine provider name. This should not happen.")
                    # Try to get provider name from category or other sources
                    # As absolute last resort, use the category name
                    if preprocessing_result.category:
                        provider_name = preprocessing_result.category.capitalize()
                        logger.warning(f"[Task ID: {task_id}] Using category '{provider_name}' as provider name fallback")
                    else:
                        # This should never happen in normal operation
                        provider_name = "Unknown"
                        logger.error(f"[Task ID: {task_id}] No provider name could be determined! Using 'Unknown' as last resort.")
            
                # Final validation - ensure we have a provider name
                if not provider_name:
                    logger.error(f"[Task ID: {task_id}] CRITICAL: provider_name is still None after all extraction attempts!")
                    provider_name = "Unknown"
            
                # Persist server provider/region on preprocessing_result so stream_consumer.py
                # can include them in usage_details for billing persistence to the usage collection
                preprocessing_result.server_provider_name = provider_name
                preprocessing_result.server_region = server_region
            
                # Log the final provider name and server region that will be sent to client
                logger.info(f"[Task ID: {task_id}] Provider name to send to client: '{provider_name}', server region: '{server_region}'")
            
                # CROSS-DEVICE FIX: Fetch encrypted_chat_key so secondary devices can
                # decrypt messages without generating a wrong random key.
                # The ai_typing_started event arrives BEFORE the AI response, so this
                # gives secondary devices the key early enough to avoid queuing issues.
                #
                # For NEW chats, the cache may not have the key yet (the client's
                # sendEncryptedStoragePackage/persist_encrypted_chat_metadata Celery task
                # may not have completed). Fall back to Directus if cache misses.
                encrypted_chat_key_for_typing: str | None = None
                try:
                    chat_list_item = await cache_service_instance.get_chat_list_item_data(
                        request_data.user_id, request_data.chat_id
                    )
                    if chat_list_item and hasattr(chat_list_item, 'encrypted_chat_key'):
                        encrypted_chat_key_for_typing = chat_list_item.encrypted_chat_key
                        logger.debug(f"[Task ID: {task_id}] Retrieved encrypted_chat_key from cache for typing event")
                except Exception as e_key:
                    logger.warning(f"[Task ID: {task_id}] Could not fetch encrypted_chat_key from cache for typing event: {e_key}")

                # Fallback: If cache miss (common for new chats), try Directus directly
                if not encrypted_chat_key_for_typing:
                    try:
                        ds = DirectusService()
                        chat_data = await ds.get_items('chats', {
                            'filter[id][_eq]': request_data.chat_id,
                            'fields': 'encrypted_chat_key',
                            'limit': 1
                        })
                        if chat_data and chat_data[0].get('encrypted_chat_key'):
                            encrypted_chat_key_for_typing = chat_data[0]['encrypted_chat_key']
                            logger.info(f"[Task ID: {task_id}] Retrieved encrypted_chat_key from Directus fallback for typing event")
                        else:
                            logger.info(f"[Task ID: {task_id}] encrypted_chat_key not yet in Directus for chat {request_data.chat_id} (very new chat)")
                    except Exception as e_db:
                        logger.warning(f"[Task ID: {task_id}] Could not fetch encrypted_chat_key from Directus for typing event: {e_db}")
            
                # Build typing payload with conditional metadata (only for new chats)
                typing_payload_data = { 
                    "type": "ai_processing_started_event", 
                    "event_for_client": "ai_typing_started", 
                    "task_id": task_id, # This is the AI's message_id for the new message being generated
                    "chat_id": request_data.chat_id,
                    "user_id_uuid": request_data.user_id, # Actual user ID for routing
                    "user_id_hash": request_data.user_id_hash, # Hashed user ID for logging/internal use
                    "user_message_id": request_data.message_id, # ID of the user message that triggered this AI response
                    "category": typing_category, # Send category instead of mate_name
                    "model_name": model_name, # Add model_name to the payload
                    "provider_name": provider_name, # Add provider_name to the payload
                    "server_region": server_region, # Add server region to the payload (e.g., "EU", "US", "APAC")
                    # CRITICAL: Include is_continuation flag so client knows to skip re-persisting the user message
                    # When this is True, the user message was already persisted before the app settings/memories
                    # or focus mode deferred activation pause
                    "is_continuation": request_data.is_app_settings_memories_continuation or request_data.is_focus_mode_continuation or request_data.is_sub_chat_continuation or request_data.is_async_skill_continuation,
                }
                if request_data.is_async_skill_continuation:
                    typing_payload_data.update(
                        {
                            "is_async_skill_continuation": True,
                            "original_user_message_id": request_data.original_user_message_id or request_data.message_id,
                            "async_skill_task_id": request_data.async_skill_task_id,
                        }
                    )
            
                # Include encrypted_chat_key so secondary devices can cache it early
                if encrypted_chat_key_for_typing:
                    typing_payload_data["encrypted_chat_key"] = encrypted_chat_key_for_typing
            
                # Log the complete typing payload for debugging
                logger.info(f"[Task ID: {task_id}] Typing payload BEFORE adding title/icon: category={typing_category}, model_name={model_name}, provider_name={provider_name}, server_region={server_region}")
            
                # Jev can choose bounded icon/category metadata before main inference,
                # while the generated title intentionally arrives from postprocessing.
                if preprocessing_result.icon_names:
                    typing_payload_data["icon_names"] = preprocessing_result.icon_names
                    logger.info(
                        f"[Task ID: {task_id}] NEW CHAT: Including icon metadata in typing event "
                        f"(icon_count={len(preprocessing_result.icon_names)})"
                    )
                if preprocessing_result.title:
                    typing_payload_data["title"] = preprocessing_result.title
                    logger.info(
                        f"[Task ID: {task_id}] Including fallback-generated title in typing event "
                        f"(title_length={len(preprocessing_result.title)})"
                    )
                if not preprocessing_result.title and not preprocessing_result.icon_names:
                    logger.debug(f"[Task ID: {task_id}] FOLLOW-UP MESSAGE: No title/icon_names generated (chat already has metadata)")
            
                # CRITICAL: Skip WebSocket events for external requests (REST API)
                # This prevents typing indicators from popping up in the web app when a user makes an API call.
                if not request_data.is_external:
                    initial_metadata_job = await persist_generated_metadata(
                        request=request_data, task_id=task_id, stage="initial",
                        metadata={"title": preprocessing_result.title,
                                  "category": typing_category if not request_data.chat_has_title else None,
                                  "icon": (preprocessing_result.icon_names or [None])[0] if not request_data.chat_has_title else None},
                    )
                    if initial_metadata_job:
                        typing_payload_data["metadata_recovery_job"] = initial_metadata_job
                    typing_indicator_channel = f"ai_typing_indicator_events::{request_data.user_id_hash}" # Channel uses hashed ID
                    await cache_service_instance.publish_event(typing_indicator_channel, typing_payload_data)
                    logger.info(f"[Task ID: {task_id}] Published '{typing_payload_data['event_for_client']}' event to Redis channel '{typing_indicator_channel}' with metadata for encryption.")

                    # --- TEST RECORD: capture typing_started event ---
                    if _fixture_recorder:
                        _fixture_recorder.record_typing_started(
                            category=typing_payload_data.get("category"),
                            model_name=typing_payload_data.get("model_name"),
                            provider_name=typing_payload_data.get("provider_name"),
                            server_region=typing_payload_data.get("server_region"),
                            icon_names=typing_payload_data.get("icon_names"),
                        )
                else:
                    logger.info(f"[Task ID: {task_id}] External request detected. Skipping '{typing_payload_data['event_for_client']}' Redis publish for Web App.")
            except Exception as e_typing_pub:
                event_name_for_log = typing_payload_data.get('event_for_client', 'ai_typing_started') if 'typing_payload_data' in locals() else 'ai_typing_started'
                logger.error(f"[Task ID: {task_id}] Failed to publish event for '{event_name_for_log}' to Redis: {e_typing_pub}", exc_info=True)
        elif not cache_service_instance and preprocessing_result and preprocessing_result.can_proceed: 
            logger.warning(f"[Task ID: {task_id}] Cache service not available. Skipping 'ai_typing_started' Redis publish.")


        # --- Step 2: Main Processing (with streaming) ---
        # Sync wrapper handles Celery state update for progress
        logger.info(f"[Task ID: {task_id}] Starting main processing step (streaming)...")

        # Old debug log for "Main-processing Input (from PreprocessingResult)" is removed.
        # llm_utils.py logs the input to the main processing LLM call.
    
        aggregated_final_response: str = ""
        revoked_in_consumer = False
        soft_limited_in_consumer = False
        thinking_content: list = []  # Accumulated thinking chunks from the stream (for debug cache only)

        try:
            skill_config_dict = skill_config.model_dump(mode="json") if hasattr(skill_config, "model_dump") else {}
            with ai_phase_span("main"):
                _log_team_ai_pipeline_stage(request_data, task_id, "main", "started")
                aggregated_final_response, revoked_in_consumer, soft_limited_in_consumer, thinking_content, main_processor_debug_metadata = await _consume_main_processing_stream(  # type: ignore[assignment]
                    task_id=task_id,
                    request_data=request_data,
                    preprocessing_result=preprocessing_result,
                    base_instructions=base_instructions,
                    directus_service=directus_service_instance,
                    encryption_service=encryption_service_instance,
                    user_vault_key_id=user_vault_key_id,
                    all_mates_configs=all_mates_configs,
                    discovered_apps_metadata=discovered_apps_metadata,
                    cache_service=cache_service_instance,
                    secrets_manager=secrets_manager,
                    # Pass always-include skills from skill config - these skills are ALWAYS available
                    # to the main LLM regardless of preprocessing preselection.
                    # This is a safety net for critical skills like web-search that should be available
                    # for follow-up queries even when preprocessing fails to detect the user's intent.
                    always_include_skills=skill_config.always_include_skills if skill_config else None,
                    user_overrides=user_overrides,  # Pass user overrides for skip-permission logic on mentioned keys
                    skill_config_dict=skill_config_dict,
                    completion_timing=completion_timing,
                )
                _log_team_ai_pipeline_stage(request_data, task_id, "main", "completed")
            logger.info(f"[Task ID: {task_id}] Main processing stream consumed.")

            # --- TEST RECORD: capture final response and save fixture ---
            if _fixture_recorder:
                # Extract usage data from debug metadata if available
                _rec_usage = main_processor_debug_metadata or {}
                _fixture_recorder.record_usage(
                    model_name=preprocessing_result.selected_main_llm_model_name if preprocessing_result else None,
                )
                if thinking_content:
                    _fixture_recorder.record_thinking_content("".join(thinking_content))
                _fixture_recorder.set_response(aggregated_final_response)
                try:
                    fixture_path = _fixture_recorder.save()
                    logger.info(f"[Task ID: {task_id}] TEST RECORD: Fixture saved to {fixture_path}")
                except Exception as e_rec:
                    logger.error(f"[Task ID: {task_id}] TEST RECORD: Failed to save fixture: {e_rec}", exc_info=True)

            # --- Cache debug data for main processor stage ---
            # This caches the last 10 requests for debugging purposes (encrypted, 30-minute TTL)
            # IMPORTANT: Store FULL content to enable proper debugging of the AI decision process
            try:
                if cache_service_instance and encryption_service_instance:
                    # Safely serialize preprocessing_result to avoid serialization errors
                    # Use mode='json' for JSON-safe output, catching any serialization issues
                    preprocessing_result_dict = None
                    if preprocessing_result:
                        try:
                            preprocessing_result_dict = preprocessing_result.model_dump(mode='json')
                        except Exception as e_serialize:
                            logger.error(f"[Task ID: {task_id}] Failed to serialize preprocessing_result for debug cache: {e_serialize}")
                            # Fallback: try to capture key fields manually
                            preprocessing_result_dict = {
                                "serialization_error": str(e_serialize),
                                "can_proceed": getattr(preprocessing_result, 'can_proceed', None),
                                "category": getattr(preprocessing_result, 'category', None),
                            }
                
                    # Prepare main processor input data with FULL preprocessing result
                    # and debug metadata from main_processor (system prompt, tools, message history)
                    main_processor_input = {
                        "chat_id": request_data.chat_id,
                        "task_id": task_id,
                        # Full preprocessing result that drives main processor behavior
                        "preprocessing_result": preprocessing_result_dict,
                        # Key fields extracted for quick reference
                        "preprocessing_can_proceed": preprocessing_result.can_proceed if preprocessing_result else None,
                        "preprocessing_selected_model": preprocessing_result.selected_main_llm_model_id if preprocessing_result else None,
                        "preprocessing_category": preprocessing_result.category if preprocessing_result else None,
                        "preprocessing_preselected_skills": preprocessing_result.relevant_app_skills if preprocessing_result else [],
                        "preprocessing_chat_summary": preprocessing_result.chat_summary if preprocessing_result else None,
                        "preprocessing_chat_tags": preprocessing_result.chat_tags if preprocessing_result else [],
                        # Context info
                        "message_history_count": len(request_data.message_history) if request_data.message_history else 0,
                        "discovered_apps_count": len(discovered_apps_metadata) if discovered_apps_metadata else 0,
                        "discovered_app_ids": list(discovered_apps_metadata.keys()) if discovered_apps_metadata else [],
                        "always_include_skills": skill_config.always_include_skills if skill_config else None,
                        "user_vault_key_id": user_vault_key_id,
                        "mates_count": len(all_mates_configs) if all_mates_configs else 0,
                        # --- Debug metadata from main_processor (P0/P1/P2 enrichment) ---
                        # Full system prompt sent to the LLM (the most important missing piece for debugging)
                        "system_prompt": main_processor_debug_metadata.get("system_prompt") if main_processor_debug_metadata else None,
                        "system_prompt_char_count": main_processor_debug_metadata.get("system_prompt_char_count", 0) if main_processor_debug_metadata else 0,
                        # Tool names and description previews available to the LLM
                        "available_tools": main_processor_debug_metadata.get("available_tools") if main_processor_debug_metadata else None,
                        "available_tools_count": main_processor_debug_metadata.get("available_tools_count", 0) if main_processor_debug_metadata else 0,
                        # Truncated message history (first + last 3 messages) sent to the LLM
                        "message_history_sent_to_llm": main_processor_debug_metadata.get("message_history_sent_to_llm") if main_processor_debug_metadata else None,
                        "message_history_sent_to_llm_total": main_processor_debug_metadata.get("message_history_total_count", 0) if main_processor_debug_metadata else 0,
                    }
                
                    # Prepare main processor output data with FULL response
                    thinking_text = "".join(thinking_content) if thinking_content else None
                    main_processor_output = {
                        # FULL AI response for debugging
                        "full_response": aggregated_final_response,
                        "response_length": len(aggregated_final_response) if aggregated_final_response else 0,
                        "revoked_in_consumer": revoked_in_consumer,
                        "soft_limited_in_consumer": soft_limited_in_consumer,
                        # Thinking content from reasoning models (Gemini, Anthropic) — displayed in separate section
                        "thinking_content": thinking_text,
                        "thinking_length": len(thinking_text) if thinking_text else 0,
                    }
                
                    await cache_service_instance.cache_debug_request_entry(
                        encryption_service=encryption_service_instance,
                        task_id=task_id,
                        chat_id=request_data.chat_id,
                        user_id=request_data.user_id,
                        stage="main_processor",
                        input_data=main_processor_input,
                        output_data=main_processor_output,
                    )
                    logger.info(f"[Task ID: {task_id}] Cached main_processor debug data (admin only)")
            except Exception as e_debug:
                # Don't fail the task if debug caching fails - log at ERROR level with full traceback
                logger.error(f"[Task ID: {task_id}] Failed to cache main_processor debug data (non-fatal): {e_debug}", exc_info=True)

            # Sync wrapper handles Celery state update for progress
            task_was_revoked = revoked_in_consumer # Update overall flag
            task_was_soft_limited = soft_limited_in_consumer # Update overall flag

        except SoftTimeLimitExceeded:
            logger.warning(f"[Task ID: {task_id}] Soft time limit exceeded during task execution (around _consume_main_processing_stream call).")
            task_was_soft_limited = True # Set overall flag
            raise # Re-raise for sync wrapper to handle Celery state
        except Exception as e:
            # Check for revocation if an unexpected error occurs
            # Use .state == 'REVOKED' for checking revocation status
            if celery_config.app.AsyncResult(task_id).state == TASK_STATE_REVOKED:
                logger.warning(f"[Task ID: {task_id}] Task revoked during or after main processing stream execution.")
                task_was_revoked = True # Set overall flag
            else:
                logger.error(f"[Task ID: {task_id}] Error during main processing stream execution: {e}", exc_info=True)
            raise RuntimeError(f"Main processing stream execution failed: {e}") # Re-raise for sync wrapper

    if legacy_batch_proof is not None:
        if cache_service_instance is None:
            raise RequiredRecoveryOutputError("Queued completion context cache unavailable")
        completion_plaintext = json.dumps({
                "task_id": task_id,
                "chat_id": request_data.chat_id,
                "owner_id": request_data.user_id,
                "hashed_team_id": request_data.team_id_hash,
                "request_data_dict": request_data.model_dump(),
                "skill_config_dict": skill_config.model_dump(),
                "legacy_batch_proof": legacy_batch_proof,
                "assistant_response": aggregated_final_response,
            }, separators=(",", ":"))
        completion_ciphertext, _ = await encryption_service_instance.encrypt_with_user_key(
            completion_plaintext, user_vault_key_id,
        )
        if not completion_ciphertext.startswith("vault:v"):
            raise RequiredRecoveryOutputError("Queued completion Vault encryption failed")
        await cache_service_instance.store_completed_queue_context(
            request_data.user_id, request_data.chat_id, task_id,
            user_vault_key_id, completion_ciphertext,
        )

    # --- Queue Processing (after main processing, before post-processing) ---
    # Process queued messages immediately after main processing completes
    # This allows the next message to start processing while post-processing continues in parallel
    # Post-processing is independent (only generates suggestions) and doesn't conflict with starting new tasks
    if cache_service_instance:
        # Check for queued messages and process them
        # This implements the queue system: when main processing completes, process any queued messages
        queued_lease = None
        for _attempt in range(3):
            queued_lease = await cache_service_instance.lease_queued_message_prefix(
                request_data.chat_id, limit=20,
            )
            if queued_lease:
                break
            empty_status = await cache_service_instance.complete_active_ai_task_if_queue_empty(
                request_data.chat_id, task_id,
            )
            if empty_status != 0:
                break
        else:
            raise RequiredRecoveryOutputError(
                "Queued message raced with active task completion repeatedly"
            )
        queued_messages = queued_lease["messages"] if queued_lease else []
        
        if queued_messages and len(queued_messages) > 0:
            logger.info(f"[Task ID: {task_id}] Found {len(queued_messages)} queued message(s) for chat {request_data.chat_id}. Processing combined message (post-processing will continue in parallel).")
            
            # Combine multiple queued messages into one
            # If user sent "Also explain docker" then "and Ruby", combine to "Also explain docker\n\nand Ruby"
            combined_message_ids, combined_content_parts = _validated_queued_messages(
                request_data, queued_lease,
            )
            combined_user_id = request_data.user_id
            combined_user_id_hash = request_data.user_id_hash
            combined_chat_id = request_data.chat_id
            combined_active_focus_id = None
            combined_chat_has_title = True  # Default to True since we're in an existing chat
            
            combined_active_focus_id = queued_messages[0].get("active_focus_id")
            combined_chat_has_title = queued_messages[0].get("chat_has_title", True)
            
            if combined_content_parts:
                # Combine messages with double newline separator
                combined_content = "\n\n".join(combined_content_parts)
                
                # Create a new combined message ID (use the first message's ID as base)
                combined_message_id = combined_message_ids[0] if combined_message_ids else f"{combined_chat_id}-{uuid.uuid4()}"
                
                logger.info(f"[Task ID: {task_id}] Combined {len(combined_content_parts)} queued messages into one. Combined content length: {len(combined_content)}")
                
                # Get updated message history including the just-completed AI response
                # This ensures the combined message has full context
                # Start with the original request's message history
                updated_message_history = []
                if request_data.message_history:
                    # Convert AIHistoryMessage objects to dicts for easier manipulation
                    for msg in request_data.message_history:
                        if isinstance(msg, dict):
                            updated_message_history.append(msg)
                        else:
                            # AIHistoryMessage Pydantic model - convert to dict
                            updated_message_history.append({
                                "role": msg.role,
                                "message_id": getattr(msg, "message_id", None),
                                "content": msg.content,
                                "created_at": msg.created_at,
                                "sender_name": getattr(msg, 'sender_name', msg.role),
                                "category": getattr(msg, 'category', None)
                            })
                
                # Add the completed AI response to history
                if aggregated_final_response:
                    updated_message_history.append({
                        "role": "assistant",
                        "content": aggregated_final_response,
                        "created_at": int(time.time()),
                        "sender_name": "assistant"
                    })
                
                # Add the combined user message(s) to history
                updated_message_history.append({
                    "role": "user",
                    "message_id": combined_message_id,
                    "content": combined_content,
                    "created_at": int(time.time()),
                    "sender_name": "user"
                })
                
                # Create a new AskSkillRequest for the combined message
                # Import the necessary modules
                from backend.apps.ai.skills.ask_skill import AskSkillRequest as AskSkillRequestType
                
                # Convert dict history back to AIHistoryMessage objects
                history_objects = []
                for msg_dict in updated_message_history:
                    history_objects.append(AIHistoryMessage(
                        role=msg_dict.get("role", "user"),
                        message_id=msg_dict.get("message_id"),
                        content=msg_dict.get("content", ""),
                        created_at=msg_dict.get("created_at", int(time.time())),
                        sender_name=msg_dict.get("sender_name", msg_dict.get("role", "user")),
                        category=msg_dict.get("category")
                    ))
                
                # Preserve the current task's selected mate for follow-up messages.
                # Without this, the preprocessor would re-select a mate based on category,
                # potentially switching to a different persona mid-conversation.
                current_mate_id = preprocessing_result.selected_mate_id if preprocessing_result else None
                
                combined_request = AskSkillRequestType(
                    chat_id=combined_chat_id,
                    message_id=combined_message_id,
                    user_id=combined_user_id or request_data.user_id,
                    user_id_hash=combined_user_id_hash or request_data.user_id_hash,
                    message_history=history_objects,
                    current_user_content=combined_content,
                    agentic_context_ref=queued_messages[-1].get("agentic_context_ref"),
                    agentic_context_request_id=queued_messages[-1].get("agentic_context_request_id"),
                    agentic_context_turn_id=queued_messages[-1].get("agentic_context_turn_id"),
                    chat_has_title=combined_chat_has_title,
                    mate_id=current_mate_id,  # Preserve current mate instead of forcing re-selection
                    active_focus_id=combined_active_focus_id or request_data.active_focus_id,
                    user_preferences={},
                    embed_file_path_index=request_data.embed_file_path_index,
                    has_image_upload_embed=getattr(request_data, "has_image_upload_embed", False),
                    is_incognito=request_data.is_incognito,
                    is_external=request_data.is_external,
                    is_anonymous=request_data.is_anonymous,
                    team_id=request_data.team_id,
                    team_id_hash=request_data.team_id_hash,
                    team_workspace_type=request_data.team_workspace_type,
                    team_object_id_hash=request_data.team_object_id_hash,
                )
                
                # Dispatch a new Celery task for the combined queued message
                # This will be processed immediately, while post-processing continues in parallel
                try:
                    # Get skill config (same as original task)
                    skill_config_dict = skill_config.model_dump() if hasattr(skill_config, 'model_dump') else {}
                    
                    # Dispatch new task via Celery
                    with ai_phase_span("queue_handoff"):
                        legacy_batch_proof = None
                        if (not combined_request.is_incognito
                                and not combined_request.is_external
                                and not combined_request.is_anonymous):
                            if (not request_data.legacy_cutover_task_id
                                    or request_data.recovery_task_id):
                                raise RequiredRecoveryOutputError(
                                    "Queued saved turn lacks epoch-0 admission authority"
                                )
                            legacy_batch_proof = _legacy_queued_batch_proof(
                                combined_request, queued_lease, combined_message_ids,
                            )
                            combined_request.legacy_cutover_task_id = (
                                legacy_batch_proof["task_identity"]
                            )
                            combined_request.root_user_message_id = combined_message_id
                            queued_task_id = legacy_batch_proof["celery_task_id"]
                        else:
                            queued_task_id = str(uuid.uuid5(
                                uuid.NAMESPACE_URL,
                                "volatile-queue:" + hashlib.sha256(
                                    json.dumps({
                                        "user_id": combined_request.user_id,
                                        "chat_id": combined_request.chat_id,
                                        "raw": queued_lease["raw_messages"],
                                    }, sort_keys=True, separators=(",", ":")).encode()
                                ).hexdigest(),
                            ))
                        queued_headers = {}
                        from backend.shared.python_utils.volatile_embed_authority import (
                            MAIN_HEADER, AuthenticatedVolatileAI,
                            active_volatile_ai_context, make_main_header,
                            require_live_incognito_session,
                        )
                        volatile_parent = active_volatile_ai_context.get()
                        if combined_request.is_incognito or combined_request.is_external:
                            if (
                                volatile_parent is None
                                or combined_request.user_id != volatile_parent.owner_id
                                or combined_request.chat_id != volatile_parent.chat_id
                            ):
                                raise RequiredRecoveryOutputError(
                                    "Queued volatile turn lacks authenticated parent"
                                )
                            if volatile_parent.mode == "incognito":
                                await require_live_incognito_session(
                                    volatile_parent.session_nonce or "",
                                    volatile_parent.owner_hash,
                                )
                            queued_headers[MAIN_HEADER] = make_main_header(
                                AuthenticatedVolatileAI(
                                    owner_id=combined_request.user_id,
                                    owner_hash=combined_request.user_id_hash,
                                    mode=volatile_parent.mode,
                                    chat_id=combined_request.chat_id,
                                    message_id=combined_request.message_id,
                                    session_nonce=volatile_parent.session_nonce,
                                    hashed_team_id=volatile_parent.hashed_team_id,
                                ),
                                owner_id=combined_request.user_id,
                                owner_hash=combined_request.user_id_hash,
                                chat_id=combined_request.chat_id,
                                message_id=combined_request.message_id,
                                main_task_id=queued_task_id,
                                hashed_team_id=combined_request.team_id_hash,
                                expires_at=volatile_parent.expires_at,
                            )
                        if legacy_batch_proof is not None:
                            paused_handoff = {
                                "task_id": queued_task_id,
                                "chat_id": combined_chat_id,
                                "owner_id": combined_request.user_id,
                                "hashed_team_id": combined_request.team_id_hash,
                                "request_data_dict": combined_request.model_dump(),
                                "skill_config_dict": skill_config_dict,
                                "legacy_batch_proof": legacy_batch_proof,
                                "lease": {
                                    "token": queued_lease["token"],
                                    "raw_messages": queued_lease["raw_messages"],
                                },
                            }
                            sealed_handoff = await _seal_legacy_queue_handoff(
                                paused_handoff, vault_key_id=user_vault_key_id,
                                cache_service=cache_service_instance,
                                encryption_service=encryption_service_instance,
                            )
                            paused_handoff_created = await cache_service_instance.store_paused_queue_handoff(
                                combined_request.user_id, combined_chat_id,
                                task_id, sealed_handoff,
                            )
                        if not await cache_service_instance.transfer_active_ai_task(
                            combined_chat_id, task_id, queued_task_id,
                        ):
                            if legacy_batch_proof is not None and paused_handoff_created:
                                await cache_service_instance.discard_paused_queue_handoff_if_matches(
                                    combined_chat_id, queued_task_id,
                                )
                            raise RequiredRecoveryOutputError(
                                "Queued handoff lost the active chat task fence"
                            )
                        if legacy_batch_proof is not None:
                            resumed_id = await resume_legacy_queued_handoff(
                                cache_service=cache_service_instance,
                                directus_service=directus_service_instance,
                                chat_id=combined_chat_id,
                                actor_user_id=combined_request.user_id,
                                hashed_team_id=combined_request.team_id_hash,
                            )
                            if resumed_id != queued_task_id:
                                raise RequiredRecoveryOutputError(
                                    "Queued legacy handoff was not dispatched"
                                )
                        else:
                            try:
                                new_task_result = celery_config.app.send_task(
                                    name='apps.ai.tasks.skill_ask',
                                    kwargs={
                                        "request_data_dict": combined_request.model_dump(),
                                        "skill_config_dict": skill_config_dict,
                                        "legacy_batch_proof": legacy_batch_proof,
                                    },
                                    queue='app_ai',
                                    task_id=queued_task_id,
                                    headers=queued_headers,
                                )
                                if not new_task_result or new_task_result.id != queued_task_id:
                                    raise RuntimeError("Queued broker dispatch returned a different task ID")
                            except Exception:
                                await cache_service_instance.clear_active_ai_task_if_matches(
                                    combined_chat_id, queued_task_id,
                                )
                                raise
                            if not await cache_service_instance.acknowledge_queued_message_prefix(
                                combined_chat_id, queued_lease,
                            ):
                                raise RequiredRecoveryOutputError(
                                    "Queued broker accepted task but exact prefix ACK failed"
                                )
                    
                    logger.info(f"[Task ID: {task_id}] Dispatched new Celery task {queued_task_id} for combined queued message(s) in chat {combined_chat_id} (post-processing continues in parallel)")
                    
                except Exception as e_queue:
                    logger.error(f"[Task ID: {task_id}] Failed to dispatch queued message task: {e_queue}", exc_info=True)
                    await cache_service_instance.publish_event(
                        f"chat_stream::{combined_chat_id}", {
                            "type": "error",
                            "code": "ai_dispatch_failed",
                            "message": "Queued message remains saved for retry; AI start was not confirmed.",
                            "chat_id": combined_chat_id,
                            "user_message_id": combined_message_id,
                            "message_id": combined_message_id,
                            "retryable": True,
                        },
                    )
                    await cache_service_instance.publish_event(
                        f"chat_stream::{combined_chat_id}", {
                            "type": "queued_handoff_paused",
                            "chat_id": combined_chat_id,
                            "user_id_uuid": request_data.user_id,
                            "user_id_hash": request_data.user_id_hash,
                            "reason_code": "queued_handoff_unavailable",
                        },
                    )
            else:
                logger.warning(f"[Task ID: {task_id}] Queued messages found but could not extract content for combining")
        else:
            logger.debug(f"[Task ID: {task_id}] No queued messages found for chat {request_data.chat_id}")

        # The queue handoff above clears this task's active marker when no newer
        # user turn is queued. Only then can a completed async job start its own
        # continuation without racing the original response.
        from backend.apps.ai.tasks.async_skill_continuation import (
            dispatch_deferred_async_skill_continuations,
        )
        await dispatch_deferred_async_skill_continuations(
            cache_service=cache_service_instance,
            user_id=request_data.user_id,
            chat_id=request_data.chat_id,
        )

    # --- Step 3: Post-Processing (Generate Suggestions and Metadata) ---
    # Post-processing continues even when revoked - we still have a partial response to process
    # Only skip if there's no response content at all.
    # CRITICAL: Skip post-processing for external requests (REST API)
    # External requests only care about the main response content, not suggestions or summary.
    # This also prevents 'post_processing_completed' events from being broadcasted to the web app.
    postprocessing_result: Optional[PostProcessingResult] = None
    if not task_was_soft_limited and aggregated_final_response and not request_data.is_external:
        logger.info(f"[Task ID: {task_id}] Starting post-processing step...")

        # Get the last user message from request_data
        last_user_message = ""
        if request_data.message_history and len(request_data.message_history) > 0:
            # Find the last user message in history
            # Note: message_history contains AIHistoryMessage Pydantic models, not dicts
            for msg in reversed(request_data.message_history):
                if msg.role == "user":
                    last_user_message = msg.content
                    break

        # Get chat summary and tags from preprocessing result (generated from full chat history)
        # CRITICAL: Check if preprocessing failed before accessing fields
        # If preprocessing failed (can_proceed=False or error_message set), chat_summary will be None/empty
        preprocessing_failed = (
            not preprocessing_result 
            or not preprocessing_result.can_proceed 
            or preprocessing_result.error_message is not None
        )
        
        chat_summary = preprocessing_result.chat_summary if preprocessing_result and not preprocessing_failed else None
        chat_tags = preprocessing_result.chat_tags if preprocessing_result and not preprocessing_failed else []

        # Extract available app IDs from discovered_apps_metadata for post-processing validation
        # NOTE: This must be defined before the preprocessing_failed branch, because
        # the debug caching code below references it regardless of which branch is taken.
        available_app_ids = list(discovered_apps_metadata.keys()) if discovered_apps_metadata else []

        # A technical preprocessing failure still blocks metadata work, but summary/tags
        # are no longer foreground requirements: the postprocessor creates them after
        # answer delivery from full history plus the completed response.
        if preprocessing_failed:
            failure_reason = (
                preprocessing_result.error_message
                if preprocessing_result and preprocessing_result.error_message
                else "Preprocessing failed (can_proceed=False)"
            )
            logger.error(
                f"[Task ID: {task_id}] CRITICAL: Preprocessing failed - cannot generate suggestions. "
                f"Failure reason: {failure_reason}. "
                f"Preprocessing result available: {preprocessing_result is not None}. "
                f"Can proceed: {preprocessing_result.can_proceed if preprocessing_result else 'N/A'}. "
                f"Raw LLM response from preprocessing: {preprocessing_result.raw_llm_response if preprocessing_result else 'N/A'}. "
                f"Chat ID: {request_data.chat_id}. "
                f"Message ID: {request_data.message_id}. "
                f"Message history length: {len(request_data.message_history) if request_data.message_history else 0}. "
                f"This indicates the preprocessing LLM call failed or returned an error."
            )
            # Skip post-processing but log the error for debugging
            postprocessing_result = None
        else:
            if not available_app_ids:
                logger.warning(f"[Task ID: {task_id}] No available app IDs found in discovered_apps_metadata for post-processing validation")


            # Extract production skills for natural-language suggestion generation.
            # These are injected into the postprocessor prompt so the LLM can suggest
            # useful next actions that the normal preprocessing router can auto-detect.
            available_skills_for_postproc = extract_available_skills(
                discovered_apps_metadata
            ) if discovered_apps_metadata else []
            logger.debug(
                f"[Task ID: {task_id}] Extracted {len(available_skills_for_postproc)} skills "
                "for post-processing suggestion context"
            )

            # Build full message history for post-processing (same format as preprocessing)
            # This allows post-processing to generate summaries from the full chat history
            # instead of relying on a condensed 20-word summary from preprocessing
            postprocessing_message_history = []
            if request_data.message_history:
                postprocessing_message_history = [
                    msg.model_dump() if hasattr(msg, 'model_dump') else msg
                    for msg in request_data.message_history
                ]

            # Extract language info for suggestion generation:
            # - output_language: the conversation/chat language detected by preprocessor (for follow-up suggestions)
            # - user_system_language: the user's UI/system language from their profile (for new chat suggestions)
            # This ensures new chat suggestions are always in the user's system language,
            # preventing a mixed-language welcome screen for multilingual users.
            chat_output_language = preprocessing_result.output_language if preprocessing_result else "en"
            user_system_language = request_data.user_preferences.get("language", "en") if request_data.user_preferences else "en"
            follow_up_suggestions_enabled = (request_data.user_preferences or {}).get("follow_up_suggestions_enabled", True) is not False
            quick_tips_enabled = (request_data.user_preferences or {}).get("quick_tips_enabled", True) is not False
            effective_learning_mode_context = (
                getattr(request_data, "learning_mode", None)
                or learning_mode_context_from_preferences(request_data.user_preferences)
            )

            # Phase 1: Post-processing with category selection
            # OPE-265: Determine current chat title for post-processing title update evaluation.
            # For new chats, use the preprocessing title. For follow-ups, use the client-provided title.
            current_title_for_postproc = None
            if preprocessing_result and preprocessing_result.title:
                current_title_for_postproc = preprocessing_result.title
            elif getattr(request_data, 'current_chat_title', None):
                current_title_for_postproc = request_data.current_chat_title

            with ai_phase_span("postprocess"):
                _log_team_ai_pipeline_stage(request_data, task_id, "postprocess", "started")
                postprocessing_result = await handle_postprocessing(
                    task_id=task_id,
                    user_message=last_user_message,
                    assistant_response=aggregated_final_response,
                    chat_summary=chat_summary,
                    chat_tags=chat_tags,
                    message_history=postprocessing_message_history,
                    base_instructions=base_instructions,
                    secrets_manager=secrets_manager,
                    cache_service=cache_service_instance,
                    available_app_ids=available_app_ids,

                    available_skills=available_skills_for_postproc,
                    is_incognito=getattr(request_data, 'is_incognito', False),  # Pass incognito flag
                    is_sub_chat=getattr(request_data, 'is_sub_chat', False),  # Pass sub-chat flag
                    output_language=chat_output_language,
                    user_system_language=user_system_language,
                    current_chat_title=current_title_for_postproc,  # OPE-265: For title update evaluation
                    follow_up_suggestions_enabled=follow_up_suggestions_enabled,
                    quick_tips_enabled=quick_tips_enabled,
                    learning_mode_context=effective_learning_mode_context,
                    learning_focus_context=(
                        {"focus_id": request_data.active_focus_id,
                         "phase": (getattr(request_data, "focus_phase_state", None) or {}).get(request_data.active_focus_id)}
                        if request_data.active_focus_id in {
                            "study-learn_topic", "study-test_knowledge", "study-socratic_questioning", "code-learn_by_building"
                        } else None
                    ),
                    decision_model_id=getattr(skill_config.default_llms, "decision_model", None),
                )
                _log_team_ai_pipeline_stage(request_data, task_id, "postprocess", "completed")

            if postprocessing_result and is_learning_mode_enabled(effective_learning_mode_context):
                postprocessing_result.follow_up_request_suggestions = filter_learning_mode_suggestions(
                    postprocessing_result.follow_up_request_suggestions
                )
                postprocessing_result.new_chat_request_suggestions = filter_learning_mode_suggestions(
                    postprocessing_result.new_chat_request_suggestions
                )



        if postprocessing_result and cache_service_instance:
            if not task_was_revoked and not task_was_soft_limited:
                # This new copy uses only the completed response's generated
                # summary. Never reactivate an older client/preprocessing copy.
                await write_response_summary_completion(request_data, task_id, postprocessing_result.chat_summary)
                await _publish_project_authoring_availability(
                    request_data, task_id, cache_service_instance, directus_service_instance,
                )
            # Publish post-processing results to Redis for WebSocket delivery to client
            # Client will encrypt with chat-specific key and sync back to Directus
            # chat_summary: prefer post-processing version (includes latest exchange) over preprocessing
            # chat_tags: prefer the post-answer version generated from full history
            final_chat_summary = (
                postprocessing_result.chat_summary
                or chat_summary
                or getattr(request_data, "current_chat_summary", None)
                or ""
            )
            source_title_v = getattr(request_data, 'current_chat_title_v', None)
            source_metadata_v = getattr(request_data, 'current_chat_metadata_v', None)
            if preprocessing_result and preprocessing_result.title and not request_data.chat_has_title:
                source_title_v = max(int(source_title_v or 0), 1)
                source_metadata_v = max(int(source_metadata_v or 0), source_title_v)
            if postprocessing_result.chat_summary:
                logger.info(f"[Task ID: {task_id}] Using post-processing chat_summary (length: {len(postprocessing_result.chat_summary)})")
            else:
                logger.info(f"[Task ID: {task_id}] Falling back to preprocessing chat_summary (post-processing didn't provide one)")

            postprocessing_payload = {
                "type": "post_processing_completed",
                "event_for_client": "post_processing_completed",
                "task_id": task_id,
                "chat_id": request_data.chat_id,
                "user_id_uuid": request_data.user_id,
                "user_id_hash": request_data.user_id_hash,
                "follow_up_request_suggestions": postprocessing_result.follow_up_request_suggestions,
                "new_chat_request_suggestions": postprocessing_result.new_chat_request_suggestions,
                "chat_summary": final_chat_summary,  # Prefer post-processing summary (includes latest exchange), fall back to preprocessing
                "share_cta_text": postprocessing_result.share_cta_text,
                "chat_tags": postprocessing_result.chat_tags or chat_tags,
                "harmful_response": postprocessing_result.harmful_response,
                "top_recommended_apps_for_user": postprocessing_result.top_recommended_apps_for_user,
                "quick_tip_slugs": postprocessing_result.quick_tip_slugs,
                "task_proposals": [proposal.model_dump() for proposal in postprocessing_result.task_proposals],
                "task_update_proposals": [proposal.model_dump() for proposal in postprocessing_result.task_update_proposals],
                "source_title_v": source_title_v,
                "source_metadata_v": source_metadata_v,
            }

            # OPE-265: Include updated title only when the postprocessor determined a title change is needed
            if postprocessing_result.updated_chat_title:
                postprocessing_payload["updated_chat_title"] = postprocessing_result.updated_chat_title
                logger.info(f"[Task ID: {task_id}] Including updated_chat_title in post-processing payload: '{postprocessing_result.updated_chat_title}'")

            # The final delivery consolidates every generated field so a lost
            # typing event cannot strand the title/category/icon independently.
            final_metadata_job = await persist_generated_metadata(
                request=request_data, task_id=task_id, stage="postprocessing",
                metadata={"title": postprocessing_result.updated_chat_title or preprocessing_result.title,
                          "summary": final_chat_summary,
                          "category": (preprocessing_result.category or "general_knowledge") if not request_data.chat_has_title else None,
                          "icon": (preprocessing_result.icon_names or [None])[0] if not request_data.chat_has_title else None},
            )
            if final_metadata_job:
                postprocessing_payload["metadata_recovery_job"] = final_metadata_job
            postprocessing_channel = f"ai_typing_indicator_events::{request_data.user_id_hash}"
            with ai_phase_span("postprocess.delivery"):
                await cache_service_instance.publish_event(postprocessing_channel, postprocessing_payload)
            logger.info(f"[Task ID: {task_id}] Published post-processing results to Redis channel '{postprocessing_channel}'")

            # --- Cache daily inspiration topic suggestions ---
            # Store the LLM-generated topic suggestions for later use in personalized daily inspiration generation.
            # These are cached server-side (rolling 50, 24h TTL) and used by the daily generation job/trigger.
            # Non-fatal: if caching fails, daily inspiration generation will proceed without personalization.
            if (
                postprocessing_result.daily_inspiration_topic_suggestions
                and request_data.user_id
                and not getattr(request_data, 'is_incognito', False)
            ):
                try:
                    await cache_service_instance.store_inspiration_topic_suggestions(
                        user_id=request_data.user_id,
                        new_suggestions=postprocessing_result.daily_inspiration_topic_suggestions,
                    )
                    logger.debug(
                        f"[Task ID: {task_id}] Stored {len(postprocessing_result.daily_inspiration_topic_suggestions)} "
                        f"daily inspiration topic suggestions for user {request_data.user_id[:8]}..."
                    )
                except Exception as e_topics:
                    # Non-fatal: daily inspiration personalization is a best-effort feature
                    logger.warning(
                        f"[Task ID: {task_id}] Failed to cache daily inspiration topic suggestions "
                        f"(non-fatal, will not affect main response): {e_topics}"
                    )

            # --- Trigger first-run daily inspiration generation ---
            # After the first ever paid request, generate 3 inspirations immediately so the
            # user sees them on their next app open without waiting for the daily job.
            # Guarded by a first-run flag in cache to prevent re-triggering on every request.
            if (
                request_data.user_id
                and not getattr(request_data, 'is_incognito', False)
                and cache_service_instance
                and secrets_manager
            ):
                try:
                    from backend.core.api.app.tasks.daily_inspiration_tasks import trigger_first_run_inspirations
                    # Resolve the user's UI language so first-run inspirations are generated
                    # in their preferred locale (phrases + Brave search localisation).
                    _inspiration_language = (
                        request_data.user_preferences.get("language", "en")
                        if request_data.user_preferences else "en"
                    ) or "en"
                    await trigger_first_run_inspirations(
                        user_id=request_data.user_id,
                        cache_service=cache_service_instance,
                        secrets_manager=secrets_manager,
                        task_id=task_id,
                        language=_inspiration_language,
                        directus_service=directus_service_instance,
                    )
                except Exception as e_first_run:
                    # Non-fatal: daily inspiration generation is a best-effort feature
                    logger.warning(
                        f"[Task ID: {task_id}] First-run daily inspiration trigger failed "
                        f"(non-fatal): {e_first_run}"
                    )

        # --- Cache debug data for postprocessor stage ---
        # This caches the last 10 requests for debugging purposes (encrypted, 30-minute TTL)
        # IMPORTANT: Store FULL content to enable proper debugging of the AI decision process
        try:
            if cache_service_instance and encryption_service_instance:
                # Prepare postprocessor input data with FULL content
                postprocessor_input = {
                    "chat_id": request_data.chat_id,
                    "task_id": task_id,
                    # FULL user message that was processed
                    "last_user_message": last_user_message,
                    "last_user_message_length": len(last_user_message) if last_user_message else 0,
                    # FULL assistant response that was generated
                    "assistant_response": aggregated_final_response,
                    "assistant_response_length": len(aggregated_final_response) if aggregated_final_response else 0,
                    # Chat summary: prefer post-processing (includes latest exchange), fall back to preprocessing
                    "chat_summary": final_chat_summary if postprocessing_result else chat_summary,
                    "chat_summary_length": len(final_chat_summary) if (postprocessing_result and final_chat_summary) else (len(chat_summary) if chat_summary else 0),
                    "chat_summary_source": "post-processing" if (postprocessing_result and postprocessing_result.chat_summary) else "preprocessing",
                    # Chat tags from preprocessing
                    "chat_tags": chat_tags,
                    # Available apps for recommendations
                    "available_app_ids": available_app_ids,
                    "available_app_ids_count": len(available_app_ids) if available_app_ids else 0,
                    "is_incognito": getattr(request_data, 'is_incognito', False),
                }
                
                # Prepare postprocessor output data (full model dump)
                postprocessor_output = postprocessing_result.model_dump() if postprocessing_result else None
                
                await cache_service_instance.cache_debug_request_entry(
                    encryption_service=encryption_service_instance,
                    task_id=task_id,
                    chat_id=request_data.chat_id,
                    user_id=request_data.user_id,
                    stage="postprocessor",
                    input_data=postprocessor_input,
                    output_data=postprocessor_output,
                )
                logger.debug(f"[Task ID: {task_id}] Cached postprocessor debug data (admin only)")
        except Exception as e_debug:
            # Don't fail the task if debug caching fails - just log the error
            logger.warning(f"[Task ID: {task_id}] Failed to cache postprocessor debug data (non-fatal): {e_debug}")

            logger.info(f"[Task ID: {task_id}] Post-processing step completed.")
    else:
        reason = "request is external" if request_data.is_external else "no response content or soft-limited"
        logger.info(f"[Task ID: {task_id}] Skipping post-processing (reason: {reason}, task_was_soft_limited={task_was_soft_limited}, has_response={bool(aggregated_final_response)})")

    # Determine final status based on local flags
    final_status_message = "completed"
    log_final_status = "successfully"

    if task_was_soft_limited: # Use local flag
        final_status_message = "completed_partially_soft_limit"
        log_final_status = "partially completed (interrupted by soft time limit)"
    # Check task_was_revoked AFTER soft_limited, as revocation might occur during soft limit handling
    if task_was_revoked: # Use local flag (also check if AsyncResult says so, though flag should capture it)
        final_status_message = "completed_partially_revoked"
        log_final_status = "partially completed (interrupted by revocation)"

    logger.info(f"[Task ID: {task_id}] AI skill ask task processing finished {log_final_status}.")

    if getattr(request_data, "user_task_id", None):
        user_task_blocked_reason_code = None
        if isinstance(main_processor_debug_metadata, dict):
            raw_blocked_reason = main_processor_debug_metadata.get("user_task_blocked_reason_code")
            if isinstance(raw_blocked_reason, str) and raw_blocked_reason:
                user_task_blocked_reason_code = raw_blocked_reason

        if user_task_blocked_reason_code:
            await _update_user_task_execution_state(
                request_data,
                directus_service_instance,
                ai_execution_state="blocked",
                status="blocked",
                blocked_reason_code=user_task_blocked_reason_code,
            )
        elif task_was_soft_limited or task_was_revoked:
            await _update_user_task_execution_state(
                request_data,
                directus_service_instance,
                ai_execution_state=final_status_message,
            )
        else:
            await _finalize_user_task_execution(request_data, directus_service_instance)

    return {
        "task_id": task_id,
        "status": final_status_message,
        "preprocessing_summary": preprocessing_result.model_dump() if preprocessing_result else {},
        "main_processing_output": aggregated_final_response,
        "postprocessing_summary": postprocessing_result.model_dump() if postprocessing_result else {},
        "interrupted_by_soft_time_limit": task_was_soft_limited, # Return determined flag
        "interrupted_by_revocation": task_was_revoked, # Return determined flag
        "_celery_task_state": "SUCCESS"
    }


@celery_config.app.task(
    bind=True, 
    name="apps.ai.tasks.skill_ask", 
    soft_time_limit=300, 
    time_limit=360,
    autoretry_for=(ChatNotFoundError,),
    retry_kwargs={'max_retries': 3},
    retry_backoff=False,
    retry_jitter=False,
    countdown=1
)
def process_ai_skill_ask_task(
    self, request_data_dict: dict, skill_config_dict: dict,
    legacy_batch_proof: Optional[dict] = None,
):
    task_id = self.request.id
    record_ai_queue_span(
        (getattr(self.request, "headers", None) or {}).get(AI_QUEUE_ENQUEUED_AT_HEADER)
    )
    # Conditionally log request and skill config data based on environment
    # Even in development, we sanitize sensitive data (message_history, chat_tags, chat_summary, etc.)
    # to show only counts and lengths, not actual content
    if os.getenv("SERVER_ENVIRONMENT", "development") != "production":
        # Sanitize request data to show only metadata (counts, lengths) instead of actual content
        sanitized_request = sanitize_request_data_for_logging(request_data_dict)
        logger.info(
            f"[Task ID: {task_id}] Received apps.ai.tasks.skill_ask task "
            f"(request={sanitized_request}, skill_config_keys={sorted(skill_config_dict.keys())})"
        )
    else:
        # In production, never log request data with sensitive content
        logger.info(f"[Task ID: {task_id}] Received apps.ai.tasks.skill_ask task.")

    # Custom flags on 'self' are no longer initialized here,
    # their status will be derived from the async helper's return value.

    completion_timing = AICompletionTiming.start()
    turn_scope = ai_phase_span("turn")
    turn_span = turn_scope.__enter__()

    try:
        with ai_phase_span("prepare"):
            request_data = AskSkillRequest(**request_data_dict)
            skill_config = AskSkillDefaultConfig(**skill_config_dict)
    except ValidationError as e:
        logger.error(f"[Task ID: {task_id}] Validation error for input data: {e}", exc_info=True)
        self.update_state(state='FAILURE', meta={'exc_type': 'ValidationError', 'exc_message': str(e.errors())})
        notification_identity = _validation_failure_identity(request_data_dict, task_id)
        if notification_identity:
            notify_chat_failure_sync(
                notification_identity,
                stage="preprocessing",
                category="unexpected_error",
            )
        record_ai_completion_timing(
            turn_span,
            worker_tail_ms=completion_timing.worker_tail_ms(),
            terminal_class="failed_before_main",
        )
        turn_scope.__exit__(None, None, None)
        raise Ignore()

    # Idempotency dedup is now handled globally by `DedupedTask.__call__`
    # (see backend/core/api/app/tasks/base_task.py). It runs BEFORE this
    # function body, so by the time we get here this is guaranteed to be
    # the first delivery of `task_id` (or DedupedTask already returned the
    # `deduplicated_skip` short-circuit and we never reach this code).

    # Focus mode continuation now creates its own assistant message (this task_id).
    # Client merges "focus activation" + "continuation" into one bubble for display.

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    task_result_dict: Optional[Dict[str, Any]] = None
    legacy_completion_requires_persistence = False
    terminal_class = "worker_interrupted"
    recovery_context_token = None
    legacy_context_token = None
    volatile_context_token = None
    legacy_batch_claimed = False
    legacy_ordinary_claimed = False
    try:
        from backend.shared.python_utils.chat_recovery_context import (
            LegacyOutputContext, active_legacy_output_context,
        )
        from backend.shared.python_utils.volatile_embed_authority import (
            MAIN_HEADER, active_volatile_ai_context, verify_main_header,
            require_live_incognito_session,
        )
        volatile_header = (getattr(self.request, "headers", None) or {}).get(MAIN_HEADER)
        requires_volatile = (
            not request_data.is_anonymous
            and (request_data.is_incognito or
                 (request_data.is_external and not request_data.recovery_task_id))
        )
        if requires_volatile:
            if volatile_header is None:
                raise RequiredRecoveryOutputError("Volatile AI task lacks signed request authority")
            volatile_context = verify_main_header(
                volatile_header, owner_id=request_data.user_id,
                owner_hash=request_data.user_id_hash,
                chat_id=request_data.chat_id, message_id=request_data.message_id,
                main_task_id=task_id,
                hashed_team_id=request_data.team_id_hash,
            )
            expected_mode = "external" if request_data.is_external else "incognito"
            if volatile_context.mode != expected_mode:
                raise RequiredRecoveryOutputError("Volatile AI task mode mismatch")
            if volatile_context.mode == "incognito":
                loop.run_until_complete(require_live_incognito_session(
                    volatile_context.session_nonce or "", volatile_context.owner_hash,
                ))
            from backend.shared.python_utils.embed_producer_dispatch import _transaction
            volatile_actor = loop.run_until_complete(_transaction(
                "verify_volatile_output_actor", {
                    "protocol_version": 1,
                    "actor_user_id": request_data.user_id,
                    "hashed_user_id": request_data.user_id_hash,
                    "target_chat_id": None,
                    "hashed_team_id": volatile_context.hashed_team_id,
                },
            ))
            if volatile_actor.get("authorized") is not True:
                raise RequiredRecoveryOutputError("Volatile AI actor no longer authorized")
            volatile_context_token = active_volatile_ai_context.set(volatile_context)
        elif volatile_header is not None:
            raise RequiredRecoveryOutputError("Saved AI task carries volatile authority")
        recovery_inference_id = request_data.resolved_recovery_inference_task_id()
        if recovery_inference_id:
            if not all((request_data.recovery_preflight_id, request_data.recovery_turn_id,
                        request_data.recovery_public_key, request_data.chat_key_version)):
                raise RequiredRecoveryOutputError("Admitted task lacks sealed output recovery identity")
            recovery_context_token = active_recovery_output_context.set(RecoveryOutputContext(
                owner_id=request_data.user_id,
                owner_hash=request_data.user_id_hash,
                root_chat_id=request_data.root_chat_id or request_data.chat_id,
                target_chat_id=request_data.chat_id,
                turn_id=request_data.recovery_turn_id,
                preflight_id=request_data.recovery_preflight_id,
                inference_task_id=recovery_inference_id,
                public_key=request_data.recovery_public_key,
                key_version=request_data.chat_key_version,
            ))
        elif not requires_volatile:
            legacy_identity = (
                request_data.root_legacy_cutover_task_id
                or request_data.legacy_cutover_task_id
            )
            if legacy_identity:
                root_chat_id = request_data.root_chat_id or request_data.chat_id
                root_message_id = request_data.root_user_message_id or request_data.message_id
                expected_identity = hashlib.sha256(
                    f"{request_data.user_id}:{root_chat_id}:{root_message_id}".encode()
                ).hexdigest()
                if legacy_identity != expected_identity:
                    raise RequiredRecoveryOutputError("Legacy AI root admission mismatch")
                if (legacy_batch_proof is None and not request_data.is_sub_chat
                        and not any((
                            request_data.is_sub_chat_continuation,
                            request_data.is_focus_mode_continuation,
                            request_data.is_app_settings_memories_continuation,
                            request_data.is_connected_account_permission_continuation,
                            request_data.is_async_skill_continuation,
                        ))):
                    if task_id != legacy_identity:
                        raise RequiredRecoveryOutputError("Legacy root task ID mismatch")
                    from backend.shared.python_utils.embed_producer_dispatch import bind_task_invocation
                    ordinary_binding = bind_task_invocation(
                        task_name="apps.ai.tasks.skill_ask",
                        task_uuid=task_id,
                        args=[],
                        kwargs={
                            "request_data_dict": request_data_dict,
                            "skill_config_dict": skill_config_dict,
                        },
                    )
                    admission_directus = DirectusService()
                    try:
                        start_proof = loop.run_until_complete(
                            ChatRecoveryService(admission_directus).execute(
                                "claim_legacy_inference_start", {
                                    "protocol_version": 1,
                                    "task_identity": legacy_identity,
                                    "actor_user_id": request_data.user_id,
                                    "hashed_user_id": request_data.user_id_hash,
                                    "chat_id": root_chat_id,
                                    "first_message_id": root_message_id,
                                    "hashed_team_id": request_data.team_id_hash,
                                    "broker_task_id": task_id,
                                    "dispatch_binding": ordinary_binding,
                                },
                            )
                        )
                    finally:
                        loop.run_until_complete(admission_directus.close())
                    if (start_proof.get("authorized") is not True
                            or start_proof.get("claimed") is not True
                            or start_proof.get("status") != "RUNNING"):
                        raise RequiredRecoveryOutputError(
                            "Legacy root inference admission is not current"
                        )
                    legacy_ordinary_claimed = True
                legacy_context_token = active_legacy_output_context.set(LegacyOutputContext(
                    owner_id=request_data.user_id,
                    owner_hash=request_data.user_id_hash,
                    legacy_task_identity=legacy_identity,
                    root_chat_id=root_chat_id,
                    root_turn_id=request_data.root_turn_id,
                    root_user_message_id=root_message_id,
                    target_chat_id=request_data.chat_id,
                ))
            elif not request_data.is_anonymous:
                raise RequiredRecoveryOutputError("Saved AI task lacks durable admission authority")
        if legacy_batch_proof is not None:
            if (requires_volatile or request_data.is_anonymous or request_data.is_sub_chat
                    or request_data.recovery_task_id
                    or not request_data.legacy_cutover_task_id):
                raise RequiredRecoveryOutputError("Queued legacy proof on wrong execution mode")
            proof = _verify_legacy_batch_proof(legacy_batch_proof, request_data, task_id)
            batch_directus = DirectusService()
            try:
                claim = loop.run_until_complete(ChatRecoveryService(batch_directus).execute(
                    "claim_legacy_batch", proof,
                ))
            finally:
                loop.run_until_complete(batch_directus.close())
            if claim.get("claimed") is not True:
                raise RequiredRecoveryOutputError("Queued legacy batch already claimed or revoked")
            legacy_batch_claimed = True
        # Update progress before calling async helper
        self.update_state(state='PROGRESS', meta={'step': 'preprocessing', 'status': 'started'})

        task_result_dict = loop.run_until_complete(
            _async_process_ai_skill_ask_task(
                task_id,
                request_data,
                skill_config,
                completion_timing=completion_timing,
                legacy_batch_proof=legacy_batch_proof,
            )
        )
        from backend.apps.ai.utils.preprocessing_history import STANDARDIZED_USER_ERROR_MESSAGE
        alert_stage = failure_stage(task_result_dict, STANDARDIZED_USER_ERROR_MESSAGE)
        terminal_class = classify_terminal_result(
            task_result_dict,
            STANDARDIZED_USER_ERROR_MESSAGE,
        )
        if alert_stage:
            loop.run_until_complete(notify_chat_failure(
                f"{request_data.chat_id}:{request_data.message_id}", stage=alert_stage,
            ))
        legacy_completion_requires_persistence = completion_requires_persistence(
            task_result_dict
        )
        
        # Update progress after preprocessing if successful and before main processing (if applicable)
        # The async helper now returns more detailed status, so we use that.
        if task_result_dict and task_result_dict.get("preprocessing_summary"):
             self.update_state(state='PROGRESS', meta={
                 'step': 'preprocessing', 'status': 'completed', 
                 'result': task_result_dict.get("preprocessing_summary")
            })
        
        if task_result_dict and task_result_dict.get("main_processing_output") is not None: # Check if main processing happened
            self.update_state(state='PROGRESS', meta={
                'step': 'main_processing', 'status': 'started_streaming' 
                # Note: 'completed_streaming' status update would happen based on task_result_dict.status
            })


        # Handle results that indicate logical failure within the async logic
        if isinstance(task_result_dict, dict) and task_result_dict.get("_celery_task_state") == "FAILURE":
            failure_meta = {k: v for k, v in task_result_dict.items() if k not in ["_celery_task_state", "task_id"]}
            failure_meta['exc_type'] = str(task_result_dict.get('reason', 'AsyncLogicError'))
            failure_meta['exc_message'] = str(task_result_dict.get('message', 'Async task indicated failure.'))
            # Add interruption flags from async result to the meta
            failure_meta['interrupted_by_soft_time_limit'] = task_result_dict.get('interrupted_by_soft_time_limit', False)
            failure_meta['interrupted_by_revocation'] = task_result_dict.get('interrupted_by_revocation', False)
            self.update_state(state='FAILURE', meta=failure_meta)
            loop.run_until_complete(_mark_sub_chat_terminal_failure(
                request_data,
                task_id,
                cancelled=bool(task_result_dict.get('interrupted_by_revocation')),
            ))
            return task_result_dict
        
        # If successful or partially successful (due to interruption)
        if isinstance(task_result_dict, dict):
            success_meta = {
                'status_message': task_result_dict.get('status'),
                'preprocessing_summary': task_result_dict.get('preprocessing_summary'),
                'main_processing_output_summary': (task_result_dict.get('main_processing_output')[:500] + "...") if task_result_dict.get('main_processing_output') and len(task_result_dict.get('main_processing_output')) > 500 else task_result_dict.get('main_processing_output'),
                'interrupted_by_soft_time_limit': task_result_dict.get('interrupted_by_soft_time_limit'),
                'interrupted_by_revocation': task_result_dict.get('interrupted_by_revocation')
            }
            # If task was interrupted, it's technically a failure for Celery unless handled as a custom success state.
            # For now, let's align with Celery's expectation: SUCCESS means fully completed.
            # Partial completions due to limits/revocation are often marked as FAILURE with details.
            current_celery_state = 'SUCCESS'
            if task_result_dict.get('interrupted_by_soft_time_limit') or task_result_dict.get('interrupted_by_revocation'):
                 # Or a custom state if your system handles it, e.g., 'PARTIAL_SUCCESS'
                 # For standard Celery, this might still be 'FAILURE' to prevent retries if not desired.
                 # Let's assume for now that "completed_partially_..." means the task did what it could.
                 # If these should be hard failures, change current_celery_state to 'FAILURE'.
                 pass # Keep as SUCCESS but with interruption flags in meta.

            self.update_state(state=current_celery_state, meta=success_meta)
            return task_result_dict
        else: # Should not happen if _async_process_ai_skill_ask_task always returns a dict
            logger.error(f"[Task ID: {task_id}] Async helper returned unexpected type: {type(task_result_dict)}")
            self.update_state(state='FAILURE', meta={'exc_type': 'InternalError', 'exc_message': 'Async helper returned non-dict result.'})
            raise Ignore()


    except SoftTimeLimitExceeded:
        logger.warning(f"[Task ID: {task_id}] Soft time limit exceeded in synchronous task wrapper.")
        # Check if the task was revoked (user-initiated cancellation) to use appropriate embed status
        was_revoked = self.request.id and celery_config.app.AsyncResult(self.request.id).state == TASK_STATE_REVOKED
        terminal_class = "revoked" if was_revoked else "soft_limited"
        # CRITICAL: Clean up active_ai_task marker and processing embeds before failing
        # This ensures the typing indicator stops and embeds don't get stuck in "processing" state
        try:
            loop.run_until_complete(_cleanup_on_task_failure(
                task_id=task_id,
                chat_id=request_data.chat_id,
                message_id=request_data.message_id,
                user_id=request_data.user_id,
                user_id_hash=request_data.user_id_hash,
                user_vault_key_id=f"user:{request_data.user_id}:encryption_key",
                error_message="Task exceeded soft time limit",
                use_cancelled_status=bool(was_revoked)
            ))
        except Exception as cleanup_err:
            logger.error(f"[Task ID: {task_id}] Error cleaning up after soft time limit: {cleanup_err}")
        if not was_revoked:
            loop.run_until_complete(notify_chat_failure(f"{request_data.chat_id}:{request_data.message_id}", stage="inference", category="timeout"))
        try:
            loop.run_until_complete(_mark_sub_chat_terminal_failure(
                request_data,
                task_id,
                cancelled=bool(was_revoked),
            ))
        except Exception as sub_chat_err:
            logger.error(f"[Task ID: {task_id}] Failed to settle sub-chat after soft time limit: {sub_chat_err}")
        try:
            loop.run_until_complete(_mark_recovery_inference_failed(
                request_data,
                task_id,
                "user_cancelled" if was_revoked else "soft_time_limit",
            ))
        except Exception as recovery_err:
            logger.error(f"[Task ID: {task_id}] Failed to mark recovery inference failed: {recovery_err}")
        try:
            loop.run_until_complete(_update_user_task_execution_state_with_new_directus(
                request_data,
                ai_execution_state="failed",
                status="blocked",
                blocked_reason_code="ai_soft_time_limit",
            ))
        except Exception as task_update_err:
            logger.error(f"[Task ID: {task_id}] Error updating user task after soft time limit: {task_update_err}")
        self.update_state(state='FAILURE', meta={
            'exc_type': 'SoftTimeLimitExceeded', 
            'exc_message': 'Task exceeded soft time limit in sync wrapper.',
            'status_message': 'completed_partially_soft_limit_wrapper', # Distinguish from async limit
            'interrupted_by_soft_time_limit': True, # This limit was in the sync part
            'interrupted_by_revocation': bool(was_revoked)
        })
        raise
    except RuntimeError as e: 
        logger.error(f"[Task ID: {task_id}] Runtime error from async task execution: {e}", exc_info=True)
        # Check if the task was revoked (user-initiated cancellation) to use appropriate embed status
        was_revoked = self.request.id and celery_config.app.AsyncResult(self.request.id).state == TASK_STATE_REVOKED
        terminal_class = "revoked" if was_revoked else (
            "billing_failed" if completion_timing.billing_failed
            else "failed_during_main" if completion_timing.first_token_ms is not None
            else "failed_before_main"
        )
        # CRITICAL: Clean up active_ai_task marker and processing embeds before failing
        # This ensures the typing indicator stops and embeds don't get stuck in "processing" state
        try:
            loop.run_until_complete(_cleanup_on_task_failure(
                task_id=task_id,
                chat_id=request_data.chat_id,
                message_id=request_data.message_id,
                user_id=request_data.user_id,
                user_id_hash=request_data.user_id_hash,
                user_vault_key_id=f"user:{request_data.user_id}:encryption_key",
                error_message=str(e),
                use_cancelled_status=bool(was_revoked)
            ))
        except Exception as cleanup_err:
            logger.error(f"[Task ID: {task_id}] Error cleaning up after RuntimeError: {cleanup_err}")
        recovery_pause_settled = False
        if not was_revoked:
            loop.run_until_complete(notify_chat_failure(
                f"{request_data.chat_id}:{request_data.message_id}",
                stage="finalization" if completion_timing.first_token_ms is not None else "preprocessing",
                category="unexpected_error",
            ))
        try:
            loop.run_until_complete(_mark_sub_chat_terminal_failure(
                request_data,
                task_id,
                cancelled=bool(was_revoked),
                pause_parent=isinstance(e, (RequiredRecoveryOutputError, RecoveryCheckpointPersistenceError)),
            ))
            recovery_pause_settled = True
        except Exception as sub_chat_err:
            logger.error(f"[Task ID: {task_id}] Failed to settle sub-chat after RuntimeError: {sub_chat_err}")
        if recovery_pause_settled and isinstance(e, (RequiredRecoveryOutputError, RecoveryCheckpointPersistenceError)):
            try:
                loop.run_until_complete(_publish_recovery_output_pause(request_data, task_id))
            except Exception as pause_err:
                logger.error(f"[Task ID: {task_id}] Failed to publish durable-output pause: {pause_err}")
        try:
            loop.run_until_complete(_mark_recovery_inference_failed(
                request_data,
                task_id,
                "user_cancelled" if was_revoked else "runtime_error",
            ))
        except Exception as recovery_err:
            logger.error(f"[Task ID: {task_id}] Failed to mark recovery inference failed: {recovery_err}")
        try:
            loop.run_until_complete(_update_user_task_execution_state_with_new_directus(
                request_data,
                ai_execution_state="failed",
                status="blocked",
                blocked_reason_code="ai_runtime_error",
            ))
        except Exception as task_update_err:
            logger.error(f"[Task ID: {task_id}] Error updating user task after RuntimeError: {task_update_err}")
        self.update_state(state='FAILURE', meta={
            'exc_type': 'RuntimeErrorFromAsync', 
            'exc_message': str(e),
            'interrupted_by_soft_time_limit': False, # Assuming not a soft limit unless explicitly caught as such
            'interrupted_by_revocation': bool(was_revoked)
        })
        raise Ignore()
    except Exception as e:
        logger.error(f"[Task ID: {task_id}] Unhandled exception in synchronous task wrapper: {e}", exc_info=True)
        # Check if the task was revoked (user-initiated cancellation) to use appropriate embed status
        was_revoked = self.request.id and celery_config.app.AsyncResult(self.request.id).state == TASK_STATE_REVOKED
        terminal_class = "revoked" if was_revoked else (
            "billing_failed" if completion_timing.billing_failed
            else "failed_during_main" if completion_timing.first_token_ms is not None
            else "failed_before_main"
        )
        # CRITICAL: Clean up active_ai_task marker and processing embeds before failing
        # This ensures the typing indicator stops and embeds don't get stuck in "processing" state
        try:
            loop.run_until_complete(_cleanup_on_task_failure(
                task_id=task_id,
                chat_id=request_data.chat_id,
                message_id=request_data.message_id,
                user_id=request_data.user_id,
                user_id_hash=request_data.user_id_hash,
                user_vault_key_id=f"user:{request_data.user_id}:encryption_key",
                error_message=str(e),
                use_cancelled_status=bool(was_revoked)
            ))
        except Exception as cleanup_err:
            logger.error(f"[Task ID: {task_id}] Error cleaning up after exception: {cleanup_err}")
        if not was_revoked:
            loop.run_until_complete(notify_chat_failure(
                f"{request_data.chat_id}:{request_data.message_id}", stage="finalization" if completion_timing.first_token_ms is not None else "preprocessing",
                category="unexpected_error",
            ))
        try:
            loop.run_until_complete(_mark_sub_chat_terminal_failure(
                request_data,
                task_id,
                cancelled=bool(was_revoked),
            ))
        except Exception as sub_chat_err:
            logger.error(f"[Task ID: {task_id}] Failed to settle sub-chat after exception: {sub_chat_err}")
        try:
            loop.run_until_complete(_mark_recovery_inference_failed(
                request_data,
                task_id,
                "user_cancelled" if was_revoked else "unhandled_error",
            ))
        except Exception as recovery_err:
            logger.error(f"[Task ID: {task_id}] Failed to mark recovery inference failed: {recovery_err}")
        try:
            loop.run_until_complete(_update_user_task_execution_state_with_new_directus(
                request_data,
                ai_execution_state="failed",
                status="blocked",
                blocked_reason_code="ai_unhandled_error",
            ))
        except Exception as task_update_err:
            logger.error(f"[Task ID: {task_id}] Error updating user task after exception: {task_update_err}")
        self.update_state(state='FAILURE', meta={
            'exc_type': str(type(e).__name__), 
            'exc_message': str(e),
            'interrupted_by_soft_time_limit': False,
            'interrupted_by_revocation': bool(was_revoked)
            })
        raise Ignore()
    finally:
        if recovery_context_token is not None:
            active_recovery_output_context.reset(recovery_context_token)
        if legacy_context_token is not None:
            active_legacy_output_context.reset(legacy_context_token)
        if volatile_context_token is not None:
            active_volatile_ai_context.reset(volatile_context_token)
        if (
            "request_data" in locals()
            and not request_data.is_incognito
            and not request_data.is_external
            and not request_data.recovery_task_id
            and request_data.legacy_cutover_task_id
            and (legacy_batch_claimed or legacy_ordinary_claimed)
        ):
            try:
                loop.run_until_complete(
                    _finalize_legacy_cutover_admission(
                        request_data,
                        legacy_completion_requires_persistence,
                    )
                )
            except Exception:
                logger.error(
                    "Failed to finalize durable legacy cutover admission",
                    exc_info=True,
                )
        # Clean up live mock context vars (no-op if not activated)
        if os.getenv("MOCK_EXTERNAL_APIS") == "true":
            try:
                from backend.shared.testing.mock_context import deactivate_mock_mode, write_live_mock_receipt
                try:
                    write_live_mock_receipt()
                finally:
                    deactivate_mock_mode()
            except ImportError:
                pass
        record_ai_completion_timing(
            turn_span,
            first_token_ms=completion_timing.first_token_ms,
            final_marker_ms=completion_timing.final_marker_ms,
            worker_tail_ms=completion_timing.worker_tail_ms(),
            terminal_class=terminal_class,
        )
        turn_scope.__exit__(None, None, None)
        loop.close()
        logger.info(f"[Task ID: {task_id}] Async event loop closed.")
