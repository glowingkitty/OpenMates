# backend/apps/ai/processing/main_processor.py
# Handles the main processing stage of AI skill requests.

import asyncio
import importlib
import inspect
import logging
from typing import Awaitable, Callable, Dict, Any, List, Optional, AsyncIterator, Tuple, TypeVar, Union
import json
import re
import httpx
import datetime
import zoneinfo
import os
import copy
import hashlib
import hmac
import time
import uuid
from functools import lru_cache
from pathlib import Path
from toon_format import encode
import yaml
from backend.shared.python_utils.recent_work_summary_client import authoritative_context_turn_id
from backend.shared.python_utils.calendar_action_journal import calendar_undo_payload

# Import Pydantic models for type hinting
from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.apps.ai.processing.preprocessor import (
    IMAGE_CHAT_SAFE_MODEL_ID,
    IMAGE_CHAT_SAFE_MODEL_NAME,
    PreprocessingResult,
)
from backend.apps.ai.processing.ai_model_catalogue_context import build_ai_model_catalogue_context
from backend.apps.ai.processing.search_skill_reliability import (
    expand_companion_skills,
    normalize_json_request_array,
    normalize_string_query_request_items,
    omit_unstated_generic_repository_criteria,
)
from backend.apps.ai.utils.mate_utils import MateConfig
from backend.apps.ai.utils.main_processing_failure import main_processing_failure
from backend.apps.ai.utils.app_skill_result_groups import is_request_group_failure, maps_result_parent_metadata
from backend.apps.ai.utils.answer_recovery import (
    ANSWER_RECOVERY_INSTRUCTION,
    AnswerRecoveryState,
    build_answer_recovery_history,
)
from backend.shared.python_utils.learning_mode import (
    AGE_GROUP_13_15,
    apply_learning_mode_policy_to_skill_result,
    build_learning_mode_global_prompt,
    is_learning_mode_blocked_skill,
    is_learning_mode_enabled,
)
from backend.shared.python_utils.tracing.ai_observability import ai_phase_span, observe_ai_stream
from backend.shared.python_utils.app_memory_policy import is_removed_app_memory_key
from backend.apps.ai.utils.llm_utils import (
    call_main_llm_stream,
    truncate_message_history_to_token_budget,
    AllServersFailedError,
    _transform_message_history_for_llm,
    native_cache_route,
    native_cache_quote_payload,
    prepare_native_cache_context,
)
from backend.apps.ai.llm_providers.native_cache_context import NativeCacheProviderOutput, NativeCacheSchemaChanged
from backend.apps.ai.processing.native_history_cache import (
    add_dispatch_event, append_provider_output, append_tool_results,
    collect_server_embed_provenance,
    native_replay_fits_budget, new_native_segment, resume_native_segment,
    validate_native_embed_fingerprints,
)
from backend.core.api.app.utils.text_sanitization import sanitize_text_simple
from backend.apps.ai.processing import agentic_context
from backend.apps.ai.processing.rule_context import applied_rule_receipt
from backend.shared.python_utils.rule_loader import applied_rule_set_key
from backend.apps.ai.processing.related_work import (
    RelatedWorkCandidate, fetch_related_chat_summaries, fetch_related_task_candidates, select_related_work,
    fetch_direction_task_context,
)
from backend.apps.ai.processing.chat_direction import (
    DirectionAuthority, CorrectionDeliveryReceipt,
    assemble_direction_context, assess_chat_direction, chat_direction_correction_coordinator,
)
from backend.apps.ai.processing.chat_direction_review import review_chat_direction as _review_chat_direction
from backend.apps.ai.utils.embeds_map_view import (
    EMBEDS_MAP_VIEW_INSTRUCTION,
    should_include_embeds_results_view_instruction,
    should_include_embeds_map_view_hint,
)
from backend.apps.ai.utils.tool_protocol_guard import ToolProtocolGuard
from backend.core.api.app.utils.override_parser import UserOverrides
from backend.apps.ai.llm_providers.mistral_client import ParsedMistralToolCall, MistralUsage
from backend.apps.ai.llm_providers.google_client import GoogleUsageMetadata, ParsedGoogleToolCall
from backend.apps.ai.llm_providers.anthropic_client import ParsedAnthropicToolCall, AnthropicUsageMetadata
from backend.apps.ai.llm_providers.bedrock_shared import ParsedBedrockToolCall, BedrockUsageMetadata
from backend.apps.ai.llm_providers.openai_shared import ParsedOpenAIToolCall, OpenAIUsageMetadata
from backend.apps.ai.llm_providers.types import UnifiedStreamChunk, StreamChunkType
from backend.shared.python_schemas.app_metadata_schemas import AppYAML, AppSkillDefinition
from backend.shared.providers.wikipedia.wikipedia_api import normalize_wikipedia_language
from backend.apps.ai.processing.wikipedia_context import (
    WIKIPEDIA_CONTEXT_UNAVAILABLE_MARKER,
    WIKIPEDIA_CONTEXT_UNAVAILABLE_MESSAGE,
    WIKIPEDIA_CONTEXT_UNAVAILABLE_REJECTION_REASON,
    WikipediaSafetyUnavailableError,
    format_wikipedia_reference_context,
    resolve_wikipedia_reference_context,
)
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.config_manager import config_manager
from backend.core.api.app.utils.text_sanitization import sanitize_text_payload_for_ascii_smuggling

# Import services for type hinting
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.translations import TranslationService
from backend.core.api.app.services.sub_chat_orchestration_service import SubChatOrchestrationService

# Import tool generator
from backend.apps.ai.processing.tool_generator import generate_tools_from_apps
from backend.apps.ai.processing.task_runtime_tools import build_task_runtime_tools, merge_task_runtime_tools
from backend.apps.ai.processing.project_file_tools import (
    PROJECT_FILE_TOOL_TO_OPERATION,
    build_project_file_tools,
    build_project_focus_prompt,
    build_project_source_routing_context,
    requests_project_file_work,
    uniquely_named_project_focus_id,
    without_unscoped_project_search,
)
from backend.apps.ai.processing.task_queue_continuation import (
    TASK_QUEUE_GUARD_MAX_RETRIES,
    build_task_queue_continuation_event,
    evaluate_task_queue_post_turn,
    filter_plan_skills_for_task_queue,
    task_context_blocks_plan_creation,
    task_queue_llm_history_role,
    task_queue_post_turn_prompt,
)
from backend.apps.ai.processing.task_tool_context import build_task_context_prompt, refresh_task_tool_context, resolve_task_tool_context

from backend.apps.ai.processing.task_tool_executor import (
    TASK_TOOL_CANONICAL_NAMES,
    TASK_TOOL_RESOLVER_APP_ID,
    assigned_app_ids_with_task_app_for_explicit_skill,
    execute_task_tool_call,
    explicit_task_app_skill_tool_name,
    is_legacy_task_runtime_tool_name,
    is_task_tool_name,
    publish_task_tool_result,
    should_suppress_task_runtime_tools_for_app_skill,
    task_app_skill_ids_from_message_text,
    task_app_skill_ids_from_user_override_skills,
    task_tool_skill_id,
    task_tool_name_variants,
)
from backend.apps.ai.processing.model_usage_tracker import ModelUsageTracker, calculate_model_usage_credits
from backend.apps.ai.processing.chat_compressor import model_history_token_budget, model_total_input_token_budget
from backend.apps.ai.processing.audio_recording_guard import (
    AUDIO_TRANSCRIBE_SKILL_ID,
    has_transcribed_web_audio_recording,
    should_block_local_audio_transcription,
)
from backend.apps.ai.processing.connected_account_receipts import (
    attach_connected_account_action_metadata,
)
from backend.apps.ai.processing.focus_mode_routing import (
    gate_tools_for_deep_research,
    resolve_deep_research_tool_choice,
    should_expose_subchat_tool,
    should_force_deep_research_delegation,
    workflow_clarification_skill_scope,
)
from backend.apps.workflows.skills.chat_authoring_context import (
    WORKFLOW_AUTHORING_TOOL_INSTRUCTION,
    is_natural_language_authoring_call,
    with_trusted_timezone,
)
from backend.apps.ai.sub_chat_orchestration import (
    MAX_AUTO_SUB_CHATS_PER_TURN,
    MAX_AUTO_SUB_CHAT_CREDITS,
    MAX_DIRECT_SUB_CHATS_PER_PARENT,
    count_direct_sub_chats,
    create_orchestration_root,
    create_sub_chat_records,
    dispatch_sub_chat_task,
    ensure_orchestration_envelope,
    expand_sub_chat_requests,
    get_sub_chat_context_policy,
    get_sub_chat_execution_mode,
    is_sub_chat_continuation,
    resolve_sub_chat_depth,
    store_pending_sub_chat_confirmation,
    validate_sub_chat_capacity,
)
# Import skill executor
from backend.apps.ai.processing.skill_executor import (
    execute_skill_with_multiple_requests,
    SkillCancelledException,
    generate_skill_task_id,
    DEFAULT_SKILL_TIMEOUT
)
from backend.shared.python_utils.chat_recovery_context import RequiredRecoveryOutputError
# Import billing utilities
from backend.shared.python_utils.billing_utils import (
    calculate_total_credits,
    select_customer_context_band,
    MINIMUM_CREDITS_CHARGED,
)
from backend.shared.python_utils.skill_provider_attribution import resolve_skill_usage_provider_id


def _trusted_focus_override(overrides: UserOverrides | None, focus_id: str) -> bool:
    return bool(overrides and any(f"{app_id}-{identifier}" == focus_id
                                 for app_id, identifier in overrides.focus_modes))


def _forward_agentic_context(request: AskSkillRequest) -> dict:
    return {field: getattr(request, field, []) for field in (
        "accepted_plan_context", "custom_rule_documents", "project_focus_catalog", "project_focus_documents",
        "project_context_documents", "related_task_candidates",
    )}


async def _load_main_agentic_context(
    *, request: Any, task_id: str, preprocessing: Any, directus: Any, cache: Any,
    secrets_manager: Any, eligible_app_ids: list[str], vault_key_id: str | None,
    decision_model: str, effective_instructions: str, active_phase: str,
    initial: bool, explicit_dependency_task_ids: frozenset[str] = frozenset(),
) -> tuple[str, list]:
    """Load bounded fresh references after authority; references grant no tools."""
    async def rules():
        selected = getattr(preprocessing, "relevant_rules", None)
        if initial and selected is not None:
            from backend.apps.ai.processing.context_preselection import reload_preselected_rules
            return await reload_preselected_rules(request, directus, cache, eligible_app_ids, selected)
        return await agentic_context.select_rule_guides(
            request=request, directus=directus, cache=cache, eligible_app_ids=eligible_app_ids,
            model_id=decision_model, secrets_manager=secrets_manager,
            effective_instructions=effective_instructions, active_phase=active_phase,
        )
    async def workflows():
        selected = getattr(preprocessing, "relevant_workflows", None)
        if initial and selected is not None:
            from backend.apps.ai.processing.context_preselection import reload_preselected_workflows
            return await reload_preselected_workflows(request, cache, selected)
        return await agentic_context.select_existing_workflows(
            request=request, model_id=decision_model, secrets_manager=secrets_manager,
            vault_key_id=vault_key_id, effective_instructions=effective_instructions,
        )
    async def related():
        if not agentic_context.first_party(request):
            return []
        chats = await fetch_related_chat_summaries(request, task_id, cache, directus)
        tasks = await fetch_related_task_candidates(
            request, directus, client_summaries=getattr(request, "related_task_candidates", []),
            explicit_dependency_task_ids=explicit_dependency_task_ids,
        )
        candidates = [RelatedWorkCandidate.from_chat_summary(item, authorized=True) for item in chats] + tasks
        project = request.current_project or {}
        selected = await select_related_work(
            candidates=candidates, owner_id=request.user_id, current_project_id=project.get("project_id"),
            current_chat_id=request.chat_id, request=request.current_user_content or "",
            model_id=decision_model, secrets_manager=secrets_manager,
        )
        return [item.as_context() for item in selected]
    initial_binding = await agentic_context.fresh_project(request, directus, cache)
    outcomes = await asyncio.gather(
        rules(), workflows(), related(), agentic_context.selected_project_documents(
            request=request, directus=directus, cache=cache, model_id=decision_model,
            secrets_manager=secrets_manager, effective_instructions=effective_instructions,
        ), return_exceptions=True,
    )
    guides, graphs, references, documents = [value if isinstance(value, list) else [] for value in outcomes]
    # Selected Project facts and reusable guidance share Memory transparency.
    # The resolver above checked current activation, ownership and source revision.
    from backend.shared.python_utils.memory_loader import MemoryDefinition
    import hashlib
    current_binding = await agentic_context.fresh_project(request, directus, cache)
    if (current_binding or {}).get("activation_id") != (initial_binding or {}).get("activation_id"):
        documents = []
        guides = [guide for guide in guides if guide.source == "app"]
    # Both legacy Markdown selection and generic Project reference selection can
    # discover the same source. Give it one identity and apply it only once.
    guides = [guide.model_copy(update={"id": f"project:{guide.project_id}:{guide.id}"})
              if guide.source == "project" and not guide.id.startswith(f"project:{guide.project_id}:")
              else guide for guide in guides]
    applied_ids = {guide.id for guide in guides}
    memory_documents = []
    for document in documents:
        if current_binding and document.get("kind") in {"memory", "fact"}:
            try:
                body = document["document"]
                if not isinstance(body, str) or not body.strip() or len(body) > 20_000:
                    continue
                memory = MemoryDefinition(
                    id=f"project:{current_binding['project_id']}:{document['item_id']}",
                    title=document["title"][:180],
                    description=(document.get("description") or document["title"])[:1_200],
                    when_to_use="Relevant context for the active Project.", body=body,
                    revision=hashlib.sha256(body.encode("utf-8")).hexdigest(),
                    source="project", project_id=current_binding["project_id"],
                )
            except (KeyError, ValueError, TypeError):
                # Optional malformed context must not interrupt inference or expose its content.
                continue
            if memory.id in applied_ids or len(guides) + len(memory_documents) >= 24:
                continue
            from backend.shared.python_utils.memory_loader import memories_prompt
            if len(memories_prompt([*guides, *memory_documents, memory])) <= 32_000:
                memory_documents.append(memory)
                applied_ids.add(memory.id)
    guides = [*guides, *memory_documents]
    documents = [row for row in documents if row.get("kind") not in {"memory", "fact"}]
    # Keep complete graphs/documents, never truncated executable definitions.
    bounded_graphs = []
    graph_chars = 0
    for graph in graphs[:3]:
        size = len(json.dumps(graph, ensure_ascii=False))
        if graph_chars + size <= 32_000:
            bounded_graphs.append(graph)
            graph_chars += size
    return agentic_context.context_prompt(rules=guides, workflows=bounded_graphs,
                                          documents=documents, related=references), guides


_DIRECTION_DELIVERY_CAS = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
if redis.call('GET', KEYS[2]) ~= ARGV[2] then return 0 end
return redis.call('SET', KEYS[3], ARGV[3], 'NX', 'EX', 1800) and 1 or 0
"""


async def _direction_authority_current(*, request, authority, task_id, cache, directus,
                                       expected_plan_summary=None):
    from backend.apps.ai.tasks.async_skill_continuation import async_skill_latest_user_turn_key
    if (authority.owner_id != request.user_id or authority.chat_id != request.chat_id
            or authority.turn_id != authoritative_context_turn_id(request)
            or authority.goal_revision != agentic_context.goal_revision(request.message_history)):
        return False
    if (await cache.get_active_ai_task(request.chat_id) != task_id
            or await cache.get(async_skill_latest_user_turn_key(request.user_id, request.chat_id)) != authority.turn_id):
        return False
    if expected_plan_summary is not None:
        from backend.apps.ai.processing.accepted_plan_context import validate_accepted_plan_context
        if await validate_accepted_plan_context(request, directus) != expected_plan_summary:
            return False
    return True


async def _deliver_direction_instruction(
    *, request: Any, task_id: str, authority: DirectionAuthority, cache: Any,
    instruction: str, fingerprint: str, append: Callable[[str], None],
    validate_context: Callable[[], Awaitable[bool]] | None = None,
) -> CorrectionDeliveryReceipt:
    """CAS the current task/user turn, then append synchronously without an await."""
    from backend.apps.ai.tasks.async_skill_continuation import async_skill_latest_user_turn_key
    if (authority.owner_id != request.user_id or authority.chat_id != request.chat_id
            or authority.turn_id != authoritative_context_turn_id(request)
            or authority.goal_revision != agentic_context.goal_revision(request.message_history)):
        return CorrectionDeliveryReceipt(False, authority)
    if validate_context is not None and not await validate_context():
        return CorrectionDeliveryReceipt(False, authority)
    client = await cache.client
    if client is None:
        return CorrectionDeliveryReceipt(False, authority)
    delivery_id = str(uuid.uuid4())
    accepted = await client.eval(_DIRECTION_DELIVERY_CAS, 3,
        cache._get_active_task_key(request.chat_id),
        async_skill_latest_user_turn_key(request.user_id, request.chat_id),
        f"chat-direction-delivery:{fingerprint}", task_id, authority.turn_id, delivery_id)
    if accepted != 1 or authority.goal_revision != agentic_context.goal_revision(request.message_history):
        return CorrectionDeliveryReceipt(False, authority)
    if validate_context is not None:
        if not await validate_context():
            return CorrectionDeliveryReceipt(False, authority)
        still_current = await client.eval(
            "if redis.call('GET',KEYS[1])~=ARGV[1] or redis.call('GET',KEYS[2])~=ARGV[2] then return 0 end return 1",
            2, cache._get_active_task_key(request.chat_id),
            async_skill_latest_user_turn_key(request.user_id, request.chat_id), task_id, authority.turn_id)
        if still_current != 1:
            return CorrectionDeliveryReceipt(False, authority)
    append(instruction)
    return CorrectionDeliveryReceipt(True, authority, delivery_id)

logger = logging.getLogger(__name__)
ORCHESTRATED_AI_MAX_OUTPUT_TOKENS = 8_192
ANONYMOUS_AI_MAX_OUTPUT_TOKENS = 4_096
ANONYMOUS_AI_INPUT_ENVELOPE_TOKENS = 4_096
DELEGATED_DEEP_RESEARCH_INSTRUCTION = (
    "\n\nDelegated child rule: You are already executing one research angle for a parent report. "
    "Do not call start_sub_chats or activate Deep research again. Research the assigned angle "
    "directly with the available web tools and return a sourced report to the parent."
)

_FALLBACK_DIFF_EDITABLE_EMBED_TYPES = frozenset({
    "code",
    "code-code",
    "document",
    "docs-doc",
    "email",
    "mail",
    "mail-email",
    "mermaid",
    "diagrams-mermaid",
    "mindmap",
    "mindmaps-mindmap",
    "pcb_schematic",
    "schematic",
    "electronics-pcb-schematic",
    "sheet",
})
_TYPE_MARKER_RE = re.compile(
    r'(?:(?:"type"|"embed_type")\s*:\s*"([^"\n]+)"|\b(?:type|embed_type)\s*:\s*([A-Za-z0-9_-]+))',
    re.IGNORECASE,
)


def _message_content(message: Any) -> Optional[str]:
    content = message.content if hasattr(message, "content") else (
        message.get("content") if isinstance(message, dict) else None
    )
    return content if isinstance(content, str) else None


def _iter_user_request_texts(request_data: AskSkillRequest) -> List[str]:
    texts: List[str] = []
    current_user_content = getattr(request_data, "current_user_content", None)
    if isinstance(current_user_content, str):
        texts.append(current_user_content)

    for message in reversed(request_data.message_history or []):
        role = message.role if hasattr(message, "role") else message.get("role") if isinstance(message, dict) else None
        if role != "user":
            continue
        content = _message_content(message)
        if content:
            texts.append(content)
    return texts


def _apply_repository_relevance_criteria_guard(
    arguments: Dict[str, Any],
    app_id: str,
    skill_id: str,
    message_history: Optional[List[Dict[str, Any]]],
    log_prefix: str,
) -> Dict[str, Any]:
    if (app_id, skill_id) != ("code", "search_repos"):
        return arguments

    latest_user_text: Optional[str] = None
    for message in reversed(message_history or []):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            latest_user_text = content.strip()
            break

    guarded, removed = omit_unstated_generic_repository_criteria(
        arguments,
        latest_user_text,
    )
    if removed:
        logger.warning(
            "%s Removed %d unstated generic relevance_criteria value(s) from "
            "neutral code.search_repos request",
            log_prefix,
            removed,
        )
    return guarded


def _llm_history_message(message: Any) -> Dict[str, Any]:
    if hasattr(message, "model_dump"):
        payload = message.model_dump(exclude_none=True)
    elif isinstance(message, dict):
        payload = dict(message)
    else:
        payload = {}
    # Vault ciphertext is carried only for local replay restoration. It must
    # never enter provider history, token quotes, or diagnostic projections.
    payload.pop("encrypted_native_cache_context", None)
    payload.pop("native_cache_context", None)
    payload.pop("native_cache_canonical_content_sha256", None)
    llm_role = task_queue_llm_history_role(payload.get("role"), payload.get("content"))
    if llm_role != payload.get("role"):
        payload["role"] = llm_role
        payload["sender_name"] = "user"
    return payload


def _metadata_value(item: Any, field_name: str) -> Any:
    if isinstance(item, dict):
        return item.get(field_name)
    return getattr(item, field_name, None)


def _add_embed_type_identifier(diffable_types: set[str], value: Any) -> None:
    if isinstance(value, str) and value.strip():
        diffable_types.add(value.strip().lower())


def _diffable_embed_types_from_apps_metadata(apps_metadata: Any) -> set[str]:
    diffable_types: set[str] = set()
    if not isinstance(apps_metadata, dict):
        return diffable_types

    for app_metadata in apps_metadata.values():
        for embed_type_def in _metadata_value(app_metadata, "embed_types") or []:
            content_catalog = _metadata_value(embed_type_def, "content_catalog") or {}
            if not isinstance(content_catalog, dict):
                continue
            if not content_catalog.get("enabled") or not content_catalog.get("diff_editable"):
                continue
            _add_embed_type_identifier(diffable_types, _metadata_value(embed_type_def, "id"))
            _add_embed_type_identifier(diffable_types, _metadata_value(embed_type_def, "backend_type"))
            _add_embed_type_identifier(diffable_types, _metadata_value(embed_type_def, "frontend_type"))
            _add_embed_type_identifier(diffable_types, content_catalog.get("content_type_id"))
    return diffable_types


@lru_cache(maxsize=1)
def _diffable_embed_types_from_shared_config() -> set[str]:
    diffable_types: set[str] = set()
    shared_config_path = Path(__file__).resolve().parents[4] / "shared/config/embed_types.yml"
    try:
        shared_config = yaml.safe_load(shared_config_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning(f"[DIFF_PROMPT] Could not read shared embed type metadata: {exc}", exc_info=True)
        return diffable_types

    for embed_type_def in shared_config.get("embed_types", []):
        content_catalog = embed_type_def.get("content_catalog") or {}
        if not content_catalog.get("enabled") or not content_catalog.get("diff_editable"):
            continue
        _add_embed_type_identifier(diffable_types, embed_type_def.get("id"))
        _add_embed_type_identifier(diffable_types, embed_type_def.get("backend_type"))
        _add_embed_type_identifier(diffable_types, embed_type_def.get("frontend_type"))
        _add_embed_type_identifier(diffable_types, content_catalog.get("content_type_id"))
    return diffable_types


async def _get_diffable_embed_types(
    cache_service: Optional[CacheService],
    log_prefix: str,
) -> set[str]:
    diffable_types = set(_FALLBACK_DIFF_EDITABLE_EMBED_TYPES)
    diffable_types.update(_diffable_embed_types_from_shared_config())
    get_discovered_apps_metadata = getattr(cache_service, "get_discovered_apps_metadata", None)
    if not callable(get_discovered_apps_metadata):
        return diffable_types

    try:
        apps_metadata = await get_discovered_apps_metadata()
    except Exception as exc:
        logger.warning(
            f"{log_prefix} [DIFF_PROMPT] Could not read app metadata for "
            f"diff-editable embed types: {exc}",
            exc_info=True,
        )
        return diffable_types

    diffable_types.update(_diffable_embed_types_from_apps_metadata(apps_metadata))
    return diffable_types


def _message_has_diffable_type_marker(content: str, diffable_embed_types: set[str]) -> bool:
    for match in _TYPE_MARKER_RE.finditer(content):
        marker_value = match.group(1) or match.group(2)
        if isinstance(marker_value, str) and marker_value.lower() in diffable_embed_types:
            return True
    return False


def _embed_data_has_diffable_type(embed_data: Any, diffable_embed_types: set[str]) -> bool:
    if not isinstance(embed_data, dict):
        return False

    for field_name in (
        "type",
        "embed_type",
        "backend_type",
        "frontend_type",
        "content_type_id",
    ):
        embed_type = embed_data.get(field_name)
        if isinstance(embed_type, str) and embed_type.lower() in diffable_embed_types:
            return True
    return False


async def _has_diffable_embeds_in_cache(
    request_data: AskSkillRequest,
    cache_service: Optional[CacheService],
    diffable_embed_types: set[str],
    log_prefix: str,
) -> bool:
    if not cache_service or not getattr(request_data, "chat_id", None):
        return False

    get_chat_embed_ids = getattr(cache_service, "get_chat_embed_ids", None)
    get_embed_from_cache = getattr(cache_service, "get_embed_from_cache", None)
    if not callable(get_chat_embed_ids) or not callable(get_embed_from_cache):
        return False

    try:
        embed_ids = await get_chat_embed_ids(request_data.chat_id)
    except Exception as exc:
        logger.warning(f"{log_prefix} [DIFF_PROMPT] Could not read chat embed index from cache: {exc}", exc_info=True)
        return False

    for embed_id in embed_ids or []:
        try:
            embed_data = await get_embed_from_cache(str(embed_id))
        except Exception as exc:
            logger.warning(f"{log_prefix} [DIFF_PROMPT] Could not read cached embed {embed_id}: {exc}", exc_info=True)
            continue
        if _embed_data_has_diffable_type(embed_data, diffable_embed_types):
            return True

    return False


async def _has_diffable_embeds_in_directus(
    request_data: AskSkillRequest,
    directus_service: Optional[DirectusService],
    diffable_embed_types: set[str],
    log_prefix: str,
) -> bool:
    if not directus_service or not getattr(request_data, "chat_id", None):
        return False

    embed_methods = getattr(directus_service, "embed", None)
    get_embeds_by_hashed_chat_id = getattr(embed_methods, "get_embeds_by_hashed_chat_id", None)
    if not callable(get_embeds_by_hashed_chat_id):
        return False

    hashed_chat_id = hashlib.sha256(request_data.chat_id.encode()).hexdigest()
    try:
        embeds = await get_embeds_by_hashed_chat_id(hashed_chat_id)
    except Exception as exc:
        logger.warning(f"{log_prefix} [DIFF_PROMPT] Could not read chat embeds from Directus: {exc}", exc_info=True)
        return False

    for embed_data in embeds or []:
        # Persisted embed types are encrypted, but editable file-backed artifacts
        # retain file_path metadata. Use this only as a DB fallback when prompt
        # history and Redis did not expose a direct type signal.
        if _embed_data_has_diffable_type(embed_data, diffable_embed_types) or embed_data.get("file_path"):
            return True

    return False


async def _has_diffable_embeds_for_prompt(
    request_data: AskSkillRequest,
    cache_service: Optional[CacheService] = None,
    directus_service: Optional[DirectusService] = None,
    log_prefix: str = "",
) -> bool:
    """Return True when the LLM can target an existing artifact with a diff fence."""
    diffable_embed_types = await _get_diffable_embed_types(cache_service, log_prefix)
    for message in request_data.message_history:
        content = _message_content(message)
        if content and _message_has_diffable_type_marker(content, diffable_embed_types):
            return True

    # Resolved history can expose only the server-side ref index to this stage.
    # The stream consumer already uses the same index to resolve diff:<embed_ref>.
    if getattr(request_data, "embed_file_path_index", None):
        return True

    if await _has_diffable_embeds_in_cache(request_data, cache_service, diffable_embed_types, log_prefix):
        return True

    return await _has_diffable_embeds_in_directus(request_data, directus_service, diffable_embed_types, log_prefix)

INTERACTIVE_QUESTIONS_INSTRUCTION = """
# INTERACTIVE QUESTIONS PROTOCOL

You have the capability to embed structured interactive questionnaires, Q&A forms, sliders, visual swipes, or star ratings using the "interactive_question" block. 

To collect structured answers, output a single ```interactive_question fenced block with a valid JSON payload. Do not output anything other than JSON in this block.

## Supported Schemas:

1. TYPE: "choice"
{
  "type": "choice",
  "id": "<unique_string_id>",
  "multiple": <boolean>,
  "question": "<string_question_text>",
  "custom_option_id": "<optional_option_id_that_requires_text_input>",
  "custom_placeholder": "<optional_placeholder_for_custom_answer>",
  "options": [ { "id": "<string_option_id>", "text": "<string_option_text>", "embed_ids": ["<optional_embed_id>"] } ]
}
Use custom_option_id when one of the options means "other", "my own answer", or a custom answer. The custom_option_id must match one option id. Do not offer an option such as "I give you my own answer" without custom_option_id, because clients will show a text input only for custom options.
Use embed_ids whenever an option is represented by existing or newly generated OpenMates embeds. If you create or show option-specific embeds immediately before the question, repeat those exact embed_id values inside the matching option's embed_ids array so the embeds render inside the option. Never put full code, document, sheet, or image content inside interactive_question JSON; create/store the embed through the normal embed pipeline first, then reference its embed_id.

2. TYPE: "input" (sequential forms)
{
  "type": "input",
  "id": "<unique_string_id>",
  "fields": [ { "id": "<field_id>", "label": "<label_text>", "placeholder": "<placeholder_text_optional>", "required": <boolean> } ]
}

3. TYPE: "slider" (rating/scale)
{
  "type": "slider",
  "id": "<unique_string_id>",
  "question": "<string_question_text>",
  "min": <int>, "max": <int>, "step": <int>, "default": <int>,
  "labels": { "1": "Label Low", "5": "Label High" }
}

4. TYPE: "swipe" (rapid binary choice)
{
  "type": "swipe",
  "id": "<unique_string_id>",
  "cards": [ { "id": "<card_id>", "text": "<card_text_or_description>", "image_url": "<string_url_optional>", "embed_ids": ["<optional_embed_id>"] } ]
}
Use embed_ids for code/document/sheet/image/content cards whenever an OpenMates embed exists. If you create or show card-specific embeds immediately before the question, repeat those exact embed_id values inside the matching card's embed_ids array so the embeds render inside the card. image_url is only for ordinary external preview images.

5. TYPE: "rating" (stars review)
{
  "type": "rating",
  "id": "<unique_string_id>",
  "question": "<string_question_text>",
  "max_stars": 5,
  "require_comment": <boolean>,
  "comment_placeholder": "<string_placeholder_optional>"
}

## How You Will Receive the User's Answer:
The user will submit their answer in a ```interactive_response fenced block containing a clean JSON payload mapping to your question's ID.
Example response:
```interactive_response
{
  "id": "quiz_1",
  "selection": ["option_a_id"],
  "custom_answer": "Optional typed answer when the selected option is custom"
}
```

Acknowledge their choice, explain if it's correct/incorrect, or use their submitted preferences to proceed with the active task. Keep your follow-up conversational and tailored directly to their structured selection.

## Rules:
- Only generate ONE interactive question per assistant turn.
- Ensure the "id" is completely unique to the active question context.
- When a choice option or swipe card is about a code/document/sheet/image/content embed, include its embed_id in that option/card's embed_ids. Do not rely on standalone embeds above the question as the only visual reference.
"""

FOLLOW_UP_SUGGESTIONS_DISABLED_INSTRUCTION = (
    "The user has turned off follow-up suggestions. Answer the request directly and avoid ending "
    "with optional next-step questions, suggested prompts, or phrases like 'Would you like me to...' "
    "unless clarification is necessary to answer safely and correctly."
)

# Furry Mode prompt styling is disabled until any furry art is made by human artists.


def _resolve_app_skill_model_override(
    user_preferences: Optional[Dict[str, Any]],
    app_id: str,
    skill_id: str,
    log_prefix: str,
) -> Optional[str]:
    defaults = (user_preferences or {}).get("default_app_skill_models")
    if not isinstance(defaults, dict):
        return None

    skill_key = f"{app_id}.{skill_id}"
    model_ref = defaults.get(skill_key)
    if not model_ref:
        return None
    if not isinstance(model_ref, str) or "/" not in model_ref:
        logger.warning(
            f"{log_prefix} Ignoring invalid default_app_skill_models[{skill_key!r}]: {model_ref!r}"
        )
        return None

    provider_id, model_id = model_ref.split("/", 1)
    model_config = config_manager.get_model_pricing(provider_id, model_id)
    if not model_config:
        logger.warning(
            f"{log_prefix} Ignoring unknown app skill model override for {skill_key}: {model_ref}"
        )
        return None
    if model_config.get("for_app_skill") != skill_key:
        logger.warning(
            f"{log_prefix} Ignoring app skill model override {model_ref} for {skill_key}; "
            f"model belongs to {model_config.get('for_app_skill')!r}."
        )
        return None

    return model_ref


def _build_pending_app_settings_memories_context(
    request_data: AskSkillRequest,
    request_id: str,
    missing_keys: List[str],
    task_id: str,
) -> Dict[str, Any]:
    """Build the request context needed to restart after memory permission."""
    return {
        "request_id": request_id,
        "chat_id": request_data.chat_id,
        "message_id": request_data.message_id,
        "user_id": request_data.user_id,
        "user_id_hash": request_data.user_id_hash,
        "mate_id": request_data.mate_id,
        "active_focus_id": request_data.active_focus_id,
        "chat_has_title": request_data.chat_has_title,
        "current_chat_title": request_data.current_chat_title,
        "is_incognito": request_data.is_incognito,
        "user_preferences": request_data.user_preferences or {},
        "embed_file_path_index": request_data.embed_file_path_index,
        "has_image_upload_embed": getattr(request_data, "has_image_upload_embed", False),
        "requested_keys": missing_keys,
        "task_id": task_id,
        # Resume the authorized turn without claiming a second inference identity.
        # See docs/architecture/core/chat-encryption-implementation.md.
        "recovery_inference_task_id": (
            getattr(request_data, "recovery_task_id", None)
            or getattr(request_data, "recovery_inference_task_id", None)
        ),
        "recovery_preflight_id": getattr(request_data, "recovery_preflight_id", None),
        "recovery_turn_id": getattr(request_data, "recovery_turn_id", None),
        "recovery_public_key": getattr(request_data, "recovery_public_key", None),
        "chat_key_version": getattr(request_data, "chat_key_version", None),
        "preprocessing_resume_ref": getattr(request_data, "preprocessing_resume_ref", None),
    }

# Four tool-enabled passes followed by one answer-only pass. Recovery first
# retries the same model with clean evidence, then permits one configured alternate.
# Neither recovery attempt can execute a skill.
MAX_TOOL_CALL_ITERATIONS = 5
MAX_ANSWER_ONLY_RECOVERY_ITERATIONS = 2

# === SKILL CALL BUDGET LIMITS ===
# These limits prevent runaway research loops where the AI keeps requesting more and more searches.
# Each "skill call" is counted per-request (e.g., a tool call with 3 requests counts as 3 skill calls).
#
# SOFT_LIMIT_SKILL_CALLS: When this limit is reached, inject a budget warning into the next LLM call,
# instructing the AI to finish with gathered information or ask the user for follow-up.
SOFT_LIMIT_SKILL_CALLS = 3
#
# HARD_LIMIT_SKILL_CALLS: When this limit is reached, stop executing further skills entirely.
# Force the LLM to answer with gathered information by setting tool_choice="none".
# Maximum of 5 request attempts per assistant message to prevent excessive research loops.
HARD_LIMIT_SKILL_CALLS = 5


def _limit_news_search_batch_to_budget(
    parsed_args: Dict[str, Any], remaining_requests: int
) -> Tuple[Dict[str, Any], List[Any]]:
    """Run the news searches that fit instead of discarding an oversized batch."""
    requests = parsed_args.get("requests") if isinstance(parsed_args, dict) else None
    if remaining_requests <= 0 or not isinstance(requests, list) or len(requests) <= remaining_requests:
        return parsed_args, []
    return {**parsed_args, "requests": requests[:remaining_requests]}, requests[remaining_requests:]


INVALID_TOOL_FALLBACK_MESSAGE = (
    "I found relevant information, but I could not complete every requested action automatically. "
    "Here is the best answer I can provide from the available results."
)

INVALID_TOOL_RESULT_REASON = (
    "This requested action is not available in the selected tool set. Continue using available "
    "completed results. Do not mention unavailable internal tools to the user."
)

APP_FOCUS_MODES_NAMESPACE = "app_focus_modes"

ASYNC_SKILL_INLINE_WAIT_SECONDS = 10.0
MAX_PARALLEL_APP_SKILL_EXECUTIONS = 3
# These apps own persistent, connected-account, payment, or workspace state.
# They remain serial even if metadata is incorrectly marked parallel_safe.
_PARALLEL_SAFE_EXCLUDED_APP_IDS = frozenset({
    "calendar",
    "finance",
    "mail",
    "projects",
    "reminder",
    "tasks",
    "workflows",
})
_ParallelResult = TypeVar("_ParallelResult")
ASYNC_SKILL_INLINE_WAIT_SKILLS = {
    ("social_media", "search"),
    ("social_media", "get-posts"),
}
ASYNC_SKILLS = ASYNC_SKILL_INLINE_WAIT_SKILLS | {
    ("audio", "generate"),
    ("audio", "speak"),
    ("code", "run"),
    ("code", "image_to_html"),
    ("images", "generate"),
    ("images", "generate_draft"),
    ("images", "vectorize"),
    ("models3d", "generate"),
    ("music", "generate"),
    ("videos", "generate"),
}
VARIABLE_RESULT_BILLING_SKILLS = {("code", "image_to_html"), ("audio", "generate"), ("audio", "speak")}


def _is_async_skill_blocked_in_orchestration(
    request_data: AskSkillRequest,
    app_id: str,
    skill_id: str,
) -> bool:
    return bool(request_data.orchestration_id and (app_id, skill_id) in ASYNC_SKILLS)


def _is_parallel_safe_app_skill_batch(
    tool_calls: List[Any],
    tool_resolver_map: Dict[str, tuple[str, str]],
    discovered_apps_metadata: Dict[str, AppYAML],
) -> bool:
    """Return whether every call in a model batch is an explicitly safe app skill.

    System, task, unknown, and excluded stateful app calls cannot enter the
    concurrent path. The full-batch requirement prevents a dependent call from
    observing another call's partially completed state.
    """
    if len(tool_calls) < 2:
        return False

    for tool_call in tool_calls:
        resolved_tool = tool_resolver_map.get(_canonicalize_tool_name(tool_call.function_name))
        if not resolved_tool:
            return False
        app_id, skill_id = resolved_tool
        # web.search is the only provider operation audited as read-only and
        # independent of connected-account, workspace, or payment state.
        if (app_id, skill_id) != ("web", "search"):
            return False
        if app_id in _PARALLEL_SAFE_EXCLUDED_APP_IDS:
            return False
        app_metadata = discovered_apps_metadata.get(app_id)
        if not app_metadata:
            return False
        skill_definition = next(
            (skill for skill in app_metadata.skills or [] if skill.id == skill_id),
            None,
        )
        if not skill_definition or skill_definition.parallel_safe is not True:
            return False
    return True


async def _execute_parallel_app_skill_operations(
    operations: List[Callable[[], Awaitable[_ParallelResult]]],
) -> List[_ParallelResult]:
    """Run already-isolated app-skill operations with bounded, input-ordered results.

    Each operation must own its per-call reservation, deduplication, error, and
    billing handling before it reaches this helper. ``gather`` preserves input
    order even when individual operations complete in a different order.
    """
    semaphore = asyncio.Semaphore(MAX_PARALLEL_APP_SKILL_EXECUTIONS)

    async def run_operation(operation: Callable[[], Awaitable[_ParallelResult]]) -> _ParallelResult:
        async with semaphore:
            return await operation()

    return list(await asyncio.gather(*(run_operation(operation) for operation in operations)))


async def _cancel_parallel_app_skill_tasks(
    parallel_executions: Dict[str, Dict[str, Any]],
) -> None:
    """Cancel and drain provider tasks when their parent inference is cancelled."""
    tasks = [
        execution["task"]
        for execution in parallel_executions.values()
        if isinstance(execution.get("task"), asyncio.Task)
    ]
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def _create_parallel_app_skill_tasks(
    operations: List[Callable[[], Awaitable[_ParallelResult]]],
) -> List[asyncio.Task[_ParallelResult]]:
    """Start bounded app-skill operations for ordered outcome collection."""
    semaphore = asyncio.Semaphore(MAX_PARALLEL_APP_SKILL_EXECUTIONS)

    async def run_operation(operation: Callable[[], Awaitable[_ParallelResult]]) -> _ParallelResult:
        async with semaphore:
            return await operation()

    return [asyncio.create_task(run_operation(operation)) for operation in operations]


def _get_skill_execution_args(
    parsed_args: Dict[str, Any],
    placeholder_embed_data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if isinstance(placeholder_embed_data, dict):
        placeholder_parsed_args = placeholder_embed_data.get("parsed_args")
        if isinstance(placeholder_parsed_args, dict):
            return placeholder_parsed_args

    return parsed_args


# Characters LLM providers use instead of the canonical hyphen in tool names.
# Gemini 3.5 Flash emits colons ('web:search'), some older models emit underscores
# ('web_search'), others emit pipes or dots. We normalize all of these to the
# hyphen form ('web-search') before the allow-list check in main processing.
# See OPE-399 follow-up for the incident where an entire chat response went
# empty because Gemini 3 called 'web:search' and the strict string-match
# allow-list rejected it even though 'web-search' was preselected.
_TOOL_NAME_SEPARATORS = (":", "|", "_", ".")


def _resolve_focus_mode_display_name(
    translation_service: TranslationService,
    translation_key: str,
    fallback: str,
    user_language: str,
) -> str:
    """Resolve app.yml focus-mode labels through the frontend app_focus_modes namespace."""
    candidate_keys = []
    if translation_key.startswith(f"{APP_FOCUS_MODES_NAMESPACE}."):
        candidate_keys.append(translation_key)
    else:
        candidate_keys.append(f"{APP_FOCUS_MODES_NAMESPACE}.{translation_key}")
        candidate_keys.append(translation_key)

    for lang in (user_language, "en"):
        if not lang:
            continue
        for candidate_key in candidate_keys:
            translated = translation_service.get_nested_translation(candidate_key, lang=lang)
            if translated and translated != candidate_key:
                return translated

    return fallback


def _canonicalize_tool_name(name: str) -> str:
    """Normalize an LLM-emitted tool name to its canonical hyphen form.

    Converts all known separator variants to the hyphen separator used by
    tool_generator.skill_definition_to_tool_definition. Preserves case and
    any other characters. Empty/None-safe: returns the input unchanged if
    it isn't a string.

    Examples:
        web:search       -> web-search
        web|search       -> web-search
        web_search       -> web-search
        web.search       -> web-search
        web-search       -> web-search (unchanged)
        mail|get_apps_settings -> mail-get-apps-settings (still rejected as
                                  hallucination because it isn't preselected)
    """
    if not isinstance(name, str):
        return name
    out = name
    for sep in _TOOL_NAME_SEPARATORS:
        out = out.replace(sep, "-")
    return out


def _is_task_tool_like(name: str) -> bool:
    canonical_name = _canonicalize_tool_name(name)
    return is_task_tool_name(name) or is_task_tool_name(canonical_name) or str(canonical_name).startswith("task-")


def _format_tool_call_for_history(tool_call: Any) -> Dict[str, Any]:
    """Return provider-compatible tool-call history without executing it."""
    function_name = tool_call.function_name
    arguments = "{}" if _is_task_tool_like(function_name) else tool_call.function_arguments_raw
    return {
        "id": tool_call.tool_call_id,
        "type": "function",
        "function": {
            "name": function_name,
            "arguments": arguments,
        },
        **(
            {"provider_transport_state": tool_call.provider_transport_state}
            if getattr(tool_call, "provider_transport_state", None)
            else {}
        ),
        **(
            {"thought_signature": tool_call.thought_signature}
            if hasattr(tool_call, "thought_signature") and tool_call.thought_signature
            else {}
        ),
    }


def _append_tool_call_turn_to_history(
    message_history: List[Dict[str, Any]],
    tool_calls: List[Any],
    rejected_tool_calls: List[Tuple[Any, Dict[str, Any]]],
    assistant_content: Optional[str],
) -> None:
    """Append matched tool_use/tool_result pairs required by LLM APIs.

    Invalid tool calls are protocol bookkeeping only: they are not executed and
    never get user-visible embeds, but providers still require the streamed
    tool_use to be paired with a tool_result before the next model call.
    """
    rejected_calls = [tool_call for tool_call, _ in rejected_tool_calls]
    assistant_message_tool_calls = [
        _format_tool_call_for_history(tool_call)
        for tool_call in [*tool_calls, *rejected_calls]
    ]
    assistant_message: Dict[str, Any] = {
        "role": "assistant",
        "content": assistant_content or None,
        "tool_calls": assistant_message_tool_calls,
    }
    message_history.append(assistant_message)

    for _, rejection_message in rejected_tool_calls:
        message_history.append(rejection_message)


def _is_empty_post_tool_turn(tool_inference_iterations: int, llm_turn_had_content: bool) -> bool:
    """Return whether a tool continuation ended without a user-visible answer."""
    return tool_inference_iterations > 0 and not llm_turn_had_content


def _has_visible_text(content: str) -> bool:
    return bool(content.strip())


def _build_async_skill_pending_tool_result(
    *,
    async_result: Dict[str, Any],
    async_task_ids: List[str],
    app_id: str,
    skill_id: str,
    inline_wait_seconds: float,
) -> Dict[str, Any]:
    """Build the LLM-visible result when an async skill is still running."""
    result: Dict[str, Any] = {
        "status": "processing",
        "app_id": app_id,
        "skill_id": skill_id,
        "message": (
            f"The requested skill is still processing after waiting {inline_wait_seconds:.0f} seconds. "
            "Tell the user it is still running and will update the chat when ready."
        ),
    }
    if async_result.get("embed_id"):
        result["embed_id"] = async_result.get("embed_id")
    if async_result.get("task_id"):
        result["task_id"] = async_result.get("task_id")
    if async_task_ids:
        result["task_ids"] = async_task_ids
    return result


def _hash_skill_arguments(app_id: str, skill_id: str, arguments: Dict[str, Any]) -> str:
    """
    Create a deterministic hash of skill arguments for deduplication.
    
    This prevents the same skill from being executed multiple times with identical
    arguments within a single AI response. This commonly happens when LLMs
    (especially Gemini) repeatedly call the same tool across iterations even after
    receiving a successful result.
    
    The hash is computed from (app_id, skill_id, sorted_json_arguments).
    Same skill with different arguments will have different hashes and execute normally.
    
    Args:
        app_id: The app identifier (e.g., 'reminder')
        skill_id: The skill identifier (e.g., 'set-reminder')
        arguments: The parsed arguments dict from the tool call
        
    Returns:
        MD5 hash string for deduplication lookup
    """
    # Sort keys for deterministic hashing regardless of JSON key order
    args_str = json.dumps(arguments, sort_keys=True, default=str)
    hash_input = f"{app_id}:{skill_id}:{args_str}"
    return hashlib.md5(hash_input.encode()).hexdigest()


def _has_explicit_skill_error(result: Any) -> bool:
    """Return whether a skill result wrapper explicitly reports failure."""
    if isinstance(result, list):
        return any(_has_explicit_skill_error(item) for item in result)
    if not isinstance(result, dict):
        return False
    if result.get("status") in ("error", "cancelled") or bool(result.get("error")):
        return True
    nested_results = result.get("results")
    return isinstance(nested_results, list) and _has_explicit_skill_error(nested_results)


def _should_cache_skill_call_for_dedup(results: Any) -> bool:
    """Cache non-empty successful wrappers, including valid zero-hit results."""
    return bool(results) and not _has_explicit_skill_error(results)


def _flatten_for_toon_tabular(obj: Any, prefix: str = "") -> Any:
    """
    Flatten nested objects into primitive fields for TOON tabular format encoding.
    
    This function matches the proven working approach from toon_encoding_test.ipynb.
    TOON tabular format requires uniform objects with only primitive fields (no nested objects or arrays).
    This function converts nested structures to flat primitive fields:
    - profile: { name: "..." } → profile_name: "..."
    - meta_url: { favicon: "..." } → meta_url_favicon: "..."
- thumbnail: { original: "..." } → thumbnail_original: "..."
    - extra_snippets: [...] → extra_snippets: "|".join([...]) (pipe-delimited string)
    
    This enables TOON to use efficient tabular format like:
    results[10]{type,title,url,description,page_age,profile_name,meta_url_favicon,thumbnail_original,extra_snippets,hash}:
      search_result,Title 1,url1,desc1,age1,name1,favicon1,thumb1,snippets1,hash1
      search_result,Title 2,url2,desc2,age2,name2,favicon2,thumb2,snippets2,hash2
    
    Instead of repeating field names for each result (which wastes tokens).
    This approach saves 25-32% in token usage compared to nested JSON format.
    
    Args:
        obj: Object to flatten (dict, list, or primitive)
        prefix: Prefix for flattened field names (used for recursion)
    
    Returns:
        Flattened object with only primitive fields
    """
    if isinstance(obj, dict):
        flattened = {}
        for key, value in obj.items():
            # Build the new key with prefix if provided
            new_key = f"{prefix}_{key}" if prefix else key
            
            if isinstance(value, dict):
                # Recursively flatten nested dictionaries
                # This handles cases like profile: {name: "..."} → profile_name: "..."
                flattened.update(_flatten_for_toon_tabular(value, new_key))
            elif isinstance(value, list):
                # Handle lists - different strategies based on content type
                if not value:
                    # Empty list - store as empty string
                    flattened[new_key] = ""
                elif all(isinstance(v, (str, int, float, bool, type(None))) for v in value):
                    # List of primitives - join with pipe delimiter
                    # None values are converted to empty strings in the pipe-delimited format
                    flattened[new_key] = "|".join(str(v) if v is not None else "" for v in value)
                elif all(isinstance(v, dict) for v in value):
                    # List of dictionaries - flatten each dictionary individually
                    # This is CRITICAL: flatten each dict so TOON can use tabular format
                    # Store as a list of flattened dicts (TOON will encode this as tabular array)
                    flattened_list = [_flatten_for_toon_tabular(item, "") for item in value]
                    flattened[new_key] = flattened_list
                else:
                    # Mixed list or list with non-dict complex objects - convert to JSON string (fallback)
                    # This should be rare, but handles edge cases where list contains objects
                    flattened[new_key] = json.dumps(value)
            else:
                # Primitive value (str, int, float, bool, None) - keep as-is
                # TOON format will handle None values appropriately (as null)
                flattened[new_key] = value
        return flattened
    elif isinstance(obj, list):
        # If we get a list at the top level, flatten each item
        return [_flatten_for_toon_tabular(item, prefix) for item in obj]
    else:
        # Primitive value - return as-is
        return obj


def _filter_skill_results_for_llm(
    results: List[Dict[str, Any]],
    exclude_fields: Optional[List[str]]
) -> List[Dict[str, Any]]:
    """
    Filter skill results to remove fields not relevant for LLM inference.
    
    Removes fields specified in exclude_fields_for_llm from app.yml.
    Supports dot notation for nested fields (e.g., "meta_url.favicon", "thumbnail.original").
    
    CRITICAL: This function preserves essential fields that MUST be included in LLM inference:
    - url: Required for LLM to reference sources
    - page_age: Required for LLM to understand result freshness
    - profile.name: Required for LLM to identify source credibility
    
    Full results with all fields are stored in chat history for persistence.
    This filtered version is only used for the current LLM call to reduce token usage.
    
    Args:
        results: List of skill result dictionaries
        exclude_fields: List of field paths to exclude (supports dot notation for nested fields)
    
    Returns:
        Filtered list of results with excluded fields removed (but essential fields preserved)
    """
    if not exclude_fields:
        # No fields to exclude, return results as-is
        return results
    
    # Essential fields that MUST be preserved for LLM inference
    # These fields are critical for the LLM to understand and reference search results
    ESSENTIAL_FIELDS = {"url", "page_age", "profile.name"}
    
    filtered = []
    
    def remove_field_path(obj: Dict[str, Any], field_path: str) -> None:
        """
        Remove a field from an object using dot notation path.
        Handles nested dictionaries (e.g., "meta_url.favicon").
        
        CRITICAL: Never removes essential fields (url, page_age, profile.name).
        """
        # Check if this is an essential field - if so, skip removal
        if field_path in ESSENTIAL_FIELDS:
            logger.debug(f"Skipping removal of essential field '{field_path}' - required for LLM inference")
            return
        
        # Check if this is a nested essential field (e.g., "profile.name")
        if field_path.startswith("profile.") and "profile.name" in ESSENTIAL_FIELDS:
            # Don't remove profile.name even if profile.* is being filtered
            if field_path == "profile.name":
                logger.debug(f"Skipping removal of essential field '{field_path}' - required for LLM inference")
                return
        
        parts = field_path.split('.', 1)
        if len(parts) == 1:
            # Simple field - remove directly (but not if it's essential)
            if parts[0] not in ESSENTIAL_FIELDS:
                obj.pop(parts[0], None)
        else:
            # Nested field - navigate to parent and remove child
            parent_key, child_path = parts
            if parent_key in obj and isinstance(obj[parent_key], dict):
                # Special handling for profile.name - preserve it even if filtering profile
                if parent_key == "profile" and child_path == "name":
                    logger.debug("Preserving essential field 'profile.name' - required for LLM inference")
                    return
                remove_field_path(obj[parent_key], child_path)
                # If parent dict is now empty, remove it
                if not obj[parent_key]:
                    obj.pop(parent_key, None)
    
    for result in results:
        # CRITICAL: Use deepcopy to avoid modifying original results when removing nested fields
        # Shallow copy() shares nested dict references, so remove_field_path would corrupt originals
        filtered_result = copy.deepcopy(result)
        
        # Handle both single result dict and result dict with "previews" array
        if "previews" in filtered_result:
            # Result has a "previews" array - filter each preview
            filtered_previews = []
            for preview in filtered_result.get("previews", []):
                # Use deepcopy for nested dicts to avoid corrupting original previews
                filtered_preview = copy.deepcopy(preview)
                
                # Remove each excluded field (but preserve essential fields)
                for field_path in exclude_fields:
                    remove_field_path(filtered_preview, field_path)
                
                filtered_previews.append(filtered_preview)
            
            filtered_result["previews"] = filtered_previews
        else:
            # Direct result object - filter it directly (but preserve essential fields)
            for field_path in exclude_fields:
                remove_field_path(filtered_result, field_path)
        
        filtered.append(filtered_result)
    
    return filtered


async def _record_connected_account_operation_journal_entries(
    *,
    app_id: str,
    skill_id: str,
    results: Any,
    token_artifacts: list[dict[str, Any]],
    user_id: str,
    user_vault_key_id: str | None,
    chat_id: str,
    message_id: str,
    directus_service: Optional[DirectusService],
    encryption_service: EncryptionService,
    cache_service: CacheService,
    log_prefix: str,
) -> list[dict[str, Any]]:
    if app_id != "calendar" or not user_vault_key_id or not token_artifacts:
        return []

    journal_entries: list[dict[str, Any]] = []
    try:
        from backend.core.api.app.services.connected_account_operation_journal import (
            ConnectedAccountOperationJournalService,
        )
        from backend.apps.ai.processing.connected_account_receipts import (
            publish_connected_account_action_receipt,
        )

        journal_service = ConnectedAccountOperationJournalService(encryption_service=encryption_service)
        normalized_results = _normalize_connected_account_results(results)
        for artifact in token_artifacts:
            connected_account_id = artifact.get("connected_account_id")
            action = str(artifact.get("action") or "")
            if not connected_account_id or not action:
                logger.error("%s Connected-account journal artifact missing account/action metadata", log_prefix)
                continue
            receipt = {
                "app_id": app_id,
                "skill_id": skill_id,
                "action": action,
                "decision": "completed",
                "result_count": len(normalized_results),
                "undo_available": _calendar_undo_available(skill_id),
            }
            journal_entry = await journal_service.record_entry(
                directus_service=directus_service,
                user_id=user_id,
                user_vault_key_id=user_vault_key_id,
                connected_account_id=str(connected_account_id),
                app_id=app_id,
                action=action,
                decision="completed",
                action_scope=artifact.get("action_scope") if isinstance(artifact.get("action_scope"), dict) else {},
                receipt=receipt,
                undo_payload=calendar_undo_payload(skill_id, normalized_results),
                chat_id=chat_id,
                message_id=message_id,
            )
            journal_entries.append(journal_entry)
            await publish_connected_account_action_receipt(
                cache_service=cache_service,
                user_id=user_id,
                payload={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "action_id": journal_entry.get("action_id"),
                    "receipt": receipt,
                },
            )
    except Exception as journal_error:
        logger.error("%s Failed to persist connected-account operation journal: %s", log_prefix, journal_error, exc_info=True)
    return journal_entries


def _normalize_connected_account_results(results: Any) -> list[dict[str, Any]]:
    if isinstance(results, list):
        return [item for item in results if isinstance(item, dict)]
    if isinstance(results, dict):
        maybe_results = results.get("results")
        if isinstance(maybe_results, list):
            return [item for item in maybe_results if isinstance(item, dict)]
        return [results]
    return []


def _calendar_undo_available(skill_id: str) -> bool:
    return skill_id in {"create-event", "update-event", "delete-event"}


DEFAULT_APP_INTERNAL_PORT = 8000
AVG_CHARS_PER_TOKEN = 4
INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
INTERNAL_API_SHARED_TOKEN = os.getenv("INTERNAL_API_SHARED_TOKEN")
INTERNAL_API_TIMEOUT = 10.0  # Timeout for internal API requests in seconds


async def _make_internal_api_request(
    method: str,
    endpoint: str,
    payload: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Helper function to make internal API requests to the main API service.
    Used for fetching provider pricing and other configuration data.
    """
    headers = {"Content-Type": "application/json"}
    if INTERNAL_API_SHARED_TOKEN:
        headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN
    else:
        logger.warning("INTERNAL_API_SHARED_TOKEN not set. Internal API calls will be unauthenticated.")
    
    url = f"{INTERNAL_API_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    
    async with httpx.AsyncClient(timeout=INTERNAL_API_TIMEOUT) as client:
        try:
            response = await client.request(method, url, json=payload, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Internal API HTTP error for {method} {endpoint}: {e.response.status_code} - {e.response.text}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Internal API request error for {method} {endpoint}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in internal API request for {method} {endpoint}: {e}", exc_info=True)
            raise


async def _publish_skill_status(
    cache_service: Optional[CacheService],
    task_id: str,
    request_data: AskSkillRequest,
    app_id: str,
    skill_id: str,
    status: str,
    preview_data: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None
) -> None:
    """
    Publish skill execution status update to Redis for WebSocket delivery.
    
    Args:
        cache_service: CacheService instance for publishing events
        task_id: Task ID for the skill execution
        request_data: AskSkillRequest containing user and chat info
        app_id: The app ID that owns the skill
        skill_id: The skill ID being executed
        status: Status of execution ('processing', 'finished', 'error')
        preview_data: Optional preview data for the skill results
        error: Optional error message if status is 'error'
    """
    if not cache_service:
        logger.debug(f"[Task ID: {task_id}] Cache service not available, skipping skill status publish")
        return

    # CRITICAL: Skip WebSocket events for external requests (REST API)
    # This prevents skill status updates from popping up in the web app when a user makes an API call.
    if request_data.is_external:
        logger.debug(f"[Task ID: {task_id}] External request detected. Skipping skill status publish for Web App.")
        return

    # Update the routing ledger independently from WebSocket delivery. The helper
    # retains identity/outcome/count only and never stores preview contents.
    try:
        from backend.apps.ai.processing.routing_ledger import record_skill_event

        await record_skill_event(
            cache_service,
            request_data,
            task_id=task_id,
            app_id=app_id,
            skill_id=skill_id,
            status=status,
            preview_data=preview_data,
        )
    except Exception as ledger_error:
        logger.warning(
            f"[Task ID: {task_id}] Failed to update content-free routing ledger: "
            f"{ledger_error.__class__.__name__}"
        )
    
    try:
        # Construct the skill status payload matching frontend expectations
        skill_status_payload = {
            "type": "skill_execution_status",
            "event_for_client": "skill_execution_status",
            "task_id": task_id,
            "chat_id": request_data.chat_id,
            "message_id": request_data.message_id,
            "user_id_uuid": request_data.user_id,
            "user_id_hash": request_data.user_id_hash,
            "app_id": app_id,
            "skill_id": skill_id,
            "status": status,
            "preview_data": preview_data or {}
        }
        
        # Add error if present
        if error:
            skill_status_payload["error"] = error
        
        # Publish to Redis channel for WebSocket delivery
        # Channel format: ai_typing_indicator_events::{user_id_hash}
        channel = f"ai_typing_indicator_events::{request_data.user_id_hash}"
        await cache_service.publish_event(channel, skill_status_payload)
        logger.info(
            f"[Task ID: {task_id}] Published skill status '{status}' for skill '{app_id}.{skill_id}' "
            f"to channel '{channel}' with preview_data keys: {list(preview_data.keys()) if preview_data else 'none'}"
        )

        # --- TEST RECORD: capture skill_execution status updates to the fixture ---
        # When a TEST_RECORD task is active, mirror every skill status update into
        # the FixtureRecorder so replay mode can emit the same sequence of events.
        # Without this, fixtures record `skill_executions: []` and replayed embeds
        # stay stuck at "Processing…" forever even though the text stream finishes.
        if os.getenv("SERVER_ENVIRONMENT", "production") != "production":
            try:
                from backend.apps.ai.testing.mock_replay import get_active_fixture_recorder
                _recorder = get_active_fixture_recorder()
                if _recorder is not None:
                    _recorder.record_skill_execution(
                        app_id=app_id,
                        skill_id=skill_id,
                        status=status,
                        preview_data=preview_data,
                        error=error,
                    )
            except Exception as rec_err:
                logger.warning(
                    f"[Task ID: {task_id}] Failed to record skill_execution to fixture: {rec_err}"
                )
    except Exception as e:
        logger.error(
            f"[Task ID: {task_id}] Failed to publish skill status for '{app_id}.{skill_id}': {e}",
            exc_info=True
        )


def _validate_skill_provider(
    provider: Optional[str],
    app_id: str,
    skill_id: str,
    discovered_apps_metadata: Dict[str, AppYAML],
    log_prefix: str,
) -> Optional[str]:
    """
    Validate a provider value against the skill's known providers list from app.yml.

    If the provider is not in the skill's providers list (or is None/empty), returns
    the first valid provider from the skill definition. This prevents LLM hallucination
    (e.g. returning 'Brave Search' for the events skill that only supports 'Meetup').

    Args:
        provider:                 Provider string from LLM output or metadata (may be wrong)
        app_id:                   App identifier (e.g. 'events', 'web', 'maps')
        skill_id:                 Skill identifier (e.g. 'search')
        discovered_apps_metadata: Full app metadata dict from which skill providers are read
        log_prefix:               Log prefix for debug/warning messages

    Returns:
        A valid provider string, or the original provider if the skill has no providers
        list defined (in which case we cannot validate).
    """
    app_metadata = discovered_apps_metadata.get(app_id)
    if not app_metadata:
        return provider

    skill_provider_refs = None
    for skill_def in (app_metadata.skills or []):
        if skill_def.id == skill_id:
            skill_provider_refs = skill_def.providers
            break

    if not skill_provider_refs:
        # No providers list in app.yml — cannot validate, return as-is
        return provider

    # Extract provider names from ProviderRef objects for comparison
    skill_providers = [ref.name for ref in skill_provider_refs]

    if provider in skill_providers:
        return provider

    # "auto" and "none" are valid meta-values meaning "use all providers" —
    # don't override them with a specific provider name.
    if provider and provider.lower() in ("auto", "none"):
        return provider

    # Provider is invalid (hallucinated or wrong) — override with the first valid one
    correct_provider = skill_providers[0]
    if provider:
        logger.warning(
            "%s Provider %r is not in the skill's providers list %r for %s.%s — "
            "overriding with %r",
            log_prefix,
            provider,
            skill_providers,
            app_id,
            skill_id,
            correct_provider,
        )
    else:
        logger.debug(
            "%s No provider set for %s.%s — defaulting to %r",
            log_prefix,
            app_id,
            skill_id,
            correct_provider,
        )
    return correct_provider


async def _resolve_skill_preview_metadata(
    *,
    app_id: str,
    skill_id: str,
    request_metadata: Dict[str, Any],
    discovered_apps_metadata: Optional[Dict[str, AppYAML]],
    log_prefix: str,
) -> Dict[str, Any]:
    """Resolve display metadata that is known before a skill executes."""
    if not discovered_apps_metadata or app_id not in discovered_apps_metadata:
        return {}

    skill_def = None
    for candidate in discovered_apps_metadata[app_id].skills or []:
        if candidate.id == skill_id:
            skill_def = candidate
            break
    if not skill_def or not skill_def.class_path:
        return {}

    try:
        module_path, class_name = skill_def.class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        skill_class = getattr(module, class_name)
        resolver = getattr(skill_class, "resolve_preview_metadata", None)
        if not callable(resolver):
            return {}

        resolved = resolver(dict(request_metadata))
        if inspect.isawaitable(resolved):
            resolved = await resolved
        if not isinstance(resolved, dict):
            return {}
        return {key: value for key, value in resolved.items() if value not in (None, "", [])}
    except Exception as exc:
        logger.warning(
            "%s Failed to resolve preview metadata for %s.%s: %s",
            log_prefix,
            app_id,
            skill_id,
            exc,
        )
        return {}


def _sanitize_tool_call_input_for_storage(arguments: Any) -> Any:
    """Keep persisted tool metadata useful without storing raw private inputs."""
    if not isinstance(arguments, dict):
        return {"raw_arguments_redacted": True}
    try:
        from backend.core.api.app.services.embed_service import EmbedService

        return EmbedService._sanitize_request_metadata(arguments)
    except Exception:
        logger.warning("Failed to sanitize tool call input for storage", exc_info=True)
        return {"raw_arguments_redacted": True}


def _apply_benchmark_usage_details(request_data: AskSkillRequest, usage_details: Dict[str, Any]) -> None:
    benchmark_metadata = getattr(request_data, "benchmark_metadata", None)
    if not isinstance(benchmark_metadata, dict) or benchmark_metadata.get("source") != "benchmark":
        return

    usage_details["source"] = "benchmark"
    for key in (
        "benchmark_run_id",
        "benchmark_suite",
        "benchmark_case",
        "benchmark_target_model",
        "benchmark_judge_model",
    ):
        value = benchmark_metadata.get(key)
        if isinstance(value, str) and value:
            usage_details[key] = value


def _skill_operation_id(app_id: str, skill_id: str, task_id: str, execution_id: str, index: int) -> str:
    return f"{app_id}.{skill_id}:{task_id}:{execution_id}:{index}"


class AnonymousUsageAccountingError(RuntimeError):
    """An anonymous accounting failure must not trigger model fallback."""


class AnonymousUsageLimitError(AnonymousUsageAccountingError):
    """The authoritative anonymous allowance cannot fund another operation."""


class AuthenticatedReservationError(RuntimeError):
    """A durable personal/team hold was unavailable before provider dispatch."""


class AuthenticatedReservationLimitError(AuthenticatedReservationError):
    """The account cannot fund even the fitted next inference call."""


ANONYMOUS_ACCOUNTING_MAX_ATTEMPTS = 2
ANONYMOUS_AI_CREDIT_ROUNDING_HEADROOM = 1


async def _anonymous_accounting_request(endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Retry a lost acknowledgement once with the same immutable operation payload."""
    for attempt in range(ANONYMOUS_ACCOUNTING_MAX_ATTEMPTS):
        try:
            return await _make_internal_api_request("POST", endpoint, payload)
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 429:
                raise AnonymousUsageLimitError("Anonymous operation allowance exhausted") from error
            raise AnonymousUsageAccountingError("Anonymous operation accounting rejected") from error
        except httpx.RequestError as error:
            if attempt == 0:
                continue
            raise AnonymousUsageAccountingError("Anonymous operation acknowledgement unavailable") from error
        except Exception as error:
            raise AnonymousUsageAccountingError("Anonymous operation response is invalid") from error
    raise AssertionError("Unreachable anonymous accounting retry state")


async def _reserve_anonymous_operation(
    *,
    request_data: AskSkillRequest,
    operation_id: str,
    charge_id: str,
    quoted_credits: int,
) -> None:
    parent_request_id = request_data.anonymous_reservation_id
    if not parent_request_id:
        raise AnonymousUsageAccountingError("Anonymous operation is missing its request reservation")
    await _anonymous_accounting_request(
        "internal/anonymous-usage/reserve-operation",
        {
            "parent_request_id": parent_request_id,
            "operation_id": operation_id,
            "charge_id": charge_id,
            "quoted_credits": quoted_credits,
        },
    )


async def _finalize_anonymous_charge(*, charge_id: str, actual_credits: int) -> None:
    await _make_internal_api_request(
        "POST",
        "internal/anonymous-usage/finalize-charge",
        {"charge_id": charge_id, "actual_credits": actual_credits},
    )


async def _release_anonymous_operation(*, operation_id: str, reason: str) -> None:
    await _make_internal_api_request(
        "POST",
        "internal/anonymous-usage/release-operation",
        {"operation_id": operation_id, "reason": reason},
    )


async def _checkpoint_anonymous_ai_operation(*, operation_id: str, checkpoint_credits: int) -> None:
    """Release unused quote capacity while keeping AI billing reversible."""
    await _anonymous_accounting_request(
        "internal/anonymous-usage/checkpoint-operation",
        {"operation_id": operation_id, "checkpoint_credits": checkpoint_credits},
    )


async def _resolve_skill_billing_config(
    *,
    app_id: str,
    skill_id: str,
    discovered_apps_metadata: Dict[str, AppYAML],
    log_prefix: str,
) -> tuple[Optional[AppSkillDefinition], Optional[Dict[str, Any]]]:
    app_metadata = discovered_apps_metadata.get(app_id)
    if not app_metadata:
        logger.warning("%s App '%s' not found in metadata; billing is unavailable", log_prefix, app_id)
        return None, None

    skill_def = next((skill for skill in app_metadata.skills or [] if skill.id == skill_id), None)
    if not skill_def:
        logger.warning("%s Skill '%s' not found in app '%s'; billing is unavailable", log_prefix, skill_id, app_id)
        return None, None

    if skill_def.pricing:
        return skill_def, skill_def.pricing.model_dump(exclude_none=True)

    pricing_config = None
    if skill_def.full_model_reference and "/" in skill_def.full_model_reference:
        provider_id, model_suffix = skill_def.full_model_reference.split("/", 1)
        try:
            pricing_config = await _make_internal_api_request(
                "GET", f"internal/config/provider_model_pricing/{provider_id}/{model_suffix}"
            )
        except Exception as exc:
            logger.warning("%s Failed to resolve model pricing for %s: %s", log_prefix, skill_def.full_model_reference, exc)

    if not pricing_config and skill_def.providers:
        provider_name = skill_def.providers[0].name
        provider_id = provider_name.lower().replace(" ", "_")
        if provider_name == "Google" and app_id == "maps":
            provider_id = "google_maps"
        elif provider_name in {"Brave", "Brave Search"}:
            provider_id = "brave"
        try:
            provider_pricing = await _make_internal_api_request(
                "GET", f"internal/config/provider_pricing/{provider_id}"
            )
            if isinstance(provider_pricing, dict) and "per_request_credits" in provider_pricing:
                pricing_config = {"per_unit": {"credits": provider_pricing["per_request_credits"]}}
            elif isinstance(provider_pricing, dict) and "per_unit" in provider_pricing:
                pricing_config = {"per_unit": provider_pricing["per_unit"]}
        except Exception as exc:
            logger.warning("%s Failed to resolve provider pricing for %s: %s", log_prefix, provider_id, exc)

    # Account-free inline skills backed only by free/public providers still
    # consume a minimum credit from the shared anonymous allowance.
    if (
        not pricing_config
        and skill_def.anonymous_access == "inline"
        and skill_def.providers
        and all(provider.no_api_key for provider in skill_def.providers)
    ):
        pricing_config = {"fixed": MINIMUM_CREDITS_CHARGED}

    return skill_def, pricing_config


def _get_variable_preflight_reserved_credits(
    app_id: str,
    skill_id: str,
    parsed_args: Dict[str, Any],
) -> Optional[List[int]]:
    if (app_id, skill_id) not in VARIABLE_RESULT_BILLING_SKILLS:
        return None
    requests = parsed_args.get("requests")
    items = requests if isinstance(requests, list) else [parsed_args]
    if app_id == "audio" and skill_id == "generate":
        from backend.apps.audio.pricing import DEFAULT_SOUND_EFFECT_DURATION_SECONDS, calculate_sound_effect_credits

        quotes: List[int] = []
        for item in items:
            item_data = item if isinstance(item, dict) else {}
            duration_seconds = item_data.get("duration_seconds")
            if not isinstance(duration_seconds, (int, float)) or isinstance(duration_seconds, bool) or duration_seconds <= 0:
                duration_seconds = DEFAULT_SOUND_EFFECT_DURATION_SECONDS
            quotes.append(calculate_sound_effect_credits(duration_seconds=float(duration_seconds)))
        return quotes
    if app_id == "audio" and skill_id == "speak":
        from backend.apps.audio.pricing import (
            DEFAULT_SPEECH_MODEL,
            SPEECH_MODEL_CREDITS_PER_SECOND,
            calculate_speech_credits,
            estimate_speech_duration_seconds,
        )

        quotes: List[int] = []
        for item in items:
            item_data = item if isinstance(item, dict) else {}
            raw_text = item_data.get("text") if isinstance(item_data.get("text"), str) else ""
            text = raw_text.strip()
            model = item_data.get("model") if isinstance(item_data.get("model"), str) else DEFAULT_SPEECH_MODEL
            if model not in SPEECH_MODEL_CREDITS_PER_SECOND:
                model = DEFAULT_SPEECH_MODEL
            quotes.append(calculate_speech_credits(model=model, duration_seconds=estimate_speech_duration_seconds(text)))
        return quotes
    if app_id == "code" and skill_id == "image_to_html":
        from backend.apps.code.skills.image_to_html_skill import reserved_credits_for_correction_passes

        return [
            reserved_credits_for_correction_passes(
                int((item if isinstance(item, dict) else {}).get("max_correction_passes") or 0)
            )
            for item in items
        ]
    return None


def _skill_preflight_quotes(
    app_id: str,
    skill_id: str,
    parsed_args: Dict[str, Any],
    pricing_config: Optional[Dict[str, Any]],
) -> list[int]:
    units = len(parsed_args.get("requests", [])) if isinstance(parsed_args.get("requests"), list) else 1
    variable_quotes = _get_variable_preflight_reserved_credits(app_id, skill_id, parsed_args)
    if variable_quotes is not None:
        return variable_quotes
    quoted_credits = (
        calculate_total_credits(pricing_config=pricing_config, units_processed=units)
        if pricing_config
        else MINIMUM_CREDITS_CHARGED
    )
    per_unit = quoted_credits // units
    remainder = quoted_credits - (per_unit * units)
    return [per_unit + (remainder if index == units - 1 else 0) for index in range(units)]


async def _reserve_skill_credits(
    *,
    task_id: str,
    execution_id: str,
    request_data: AskSkillRequest,
    app_id: str,
    skill_id: str,
    discovered_apps_metadata: Dict[str, AppYAML],
    parsed_args: Dict[str, Any],
    directus_service: Optional[DirectusService],
    log_prefix: str,
) -> list[str]:
    is_anonymous = bool(getattr(request_data, "is_anonymous", False))
    if not request_data.orchestration_id and not is_anonymous:
        return []
    skill_definition, pricing_config = await _resolve_skill_billing_config(
        app_id=app_id,
        skill_id=skill_id,
        discovered_apps_metadata=discovered_apps_metadata,
        log_prefix=log_prefix,
    )
    variable_quotes = _get_variable_preflight_reserved_credits(app_id, skill_id, parsed_args)
    if is_anonymous and (not skill_definition or (not pricing_config and variable_quotes is None)):
        raise RuntimeError(f"Anonymous skill pricing is unavailable for {app_id}.{skill_id}")
    quotes = _skill_preflight_quotes(app_id, skill_id, parsed_args, pricing_config)
    quoted_credits = sum(quotes)
    if quoted_credits <= 0:
        return []

    service = None if is_anonymous else SubChatOrchestrationService(directus_service)
    reserved: list[str] = []
    try:
        for index, quote in enumerate(quotes):
            if quote <= 0:
                continue
            operation_id = _skill_operation_id(app_id, skill_id, task_id, execution_id, index)
            if is_anonymous:
                await _reserve_anonymous_operation(
                    request_data=request_data,
                    operation_id=operation_id,
                    charge_id=operation_id,
                    quoted_credits=quote,
                )
            else:
                await service.execute("reserve_operation", {  # type: ignore[union-attr]
                    "protocol_version": 1,
                    "operation_id": operation_id,
                    "charge_id": operation_id,
                    "orchestration_id": request_data.orchestration_id,
                    "hashed_user_id": request_data.user_id_hash,
                    "root_chat_id": request_data.root_chat_id,
                    "actual_chat_id": request_data.chat_id,
                    "depth": request_data.sub_chat_depth,
                    "app_id": app_id,
                    "skill_id": skill_id,
                    "phase": "provider_request",
                    "quoted_credits": quote,
                })
            reserved.append(operation_id)
    except Exception:
        for operation_id in reserved:
            if is_anonymous:
                await _release_anonymous_operation(operation_id=operation_id, reason="reservation_batch_failed")
            else:
                await service.execute("fail_operation", {  # type: ignore[union-attr]
                    "protocol_version": 1,
                    "operation_id": operation_id,
                    "orchestration_id": request_data.orchestration_id,
                    "hashed_user_id": request_data.user_id_hash,
                })
        raise
    return reserved


async def _settle_anonymous_skill_quote(
    *,
    app_id: str,
    skill_id: str,
    parsed_args: Dict[str, Any],
    discovered_apps_metadata: Dict[str, AppYAML],
    reserved_operation_ids: list[str],
    log_prefix: str,
) -> int:
    skill_definition, pricing_config = await _resolve_skill_billing_config(
        app_id=app_id,
        skill_id=skill_id,
        discovered_apps_metadata=discovered_apps_metadata,
        log_prefix=log_prefix,
    )
    variable_quotes = _get_variable_preflight_reserved_credits(app_id, skill_id, parsed_args)
    if not skill_definition or (not pricing_config and variable_quotes is None):
        raise RuntimeError(f"Anonymous skill pricing is unavailable for {app_id}.{skill_id}")
    quotes = _skill_preflight_quotes(app_id, skill_id, parsed_args, pricing_config)
    if len(reserved_operation_ids) != len(quotes):
        raise RuntimeError("Anonymous skill reservation count does not match its provider quote count")
    for operation_id, quote in zip(reserved_operation_ids, quotes):
        await _finalize_anonymous_charge(charge_id=operation_id, actual_credits=quote)
    return sum(quotes)


def _normal_chat_cache_pricing_scope(request_data: AskSkillRequest) -> bool:
    """Admit cache customer pricing only for ordinary standalone chats."""
    preferences = getattr(request_data, "user_preferences", None) or {}
    return not (
        getattr(request_data, "is_anonymous", False)
        or getattr(request_data, "is_external", False)
        or getattr(request_data, "is_sub_chat", False)
        or getattr(request_data, "is_sub_chat_continuation", False)
        or getattr(request_data, "parent_id", None)
        or getattr(request_data, "orchestration_id", None)
        or (getattr(request_data, "sub_chat_depth", 0) or 0) > 0
        or preferences.get("workflow_ai") is True
        or preferences.get("workflow_budget") is not None
        or preferences.get("workflow_credit_allowance") is not None
    )


_NATIVE_FIXTURE_ADMISSION_REASONS = frozenset({
    "accepted", "route_unavailable", "fallback_model", "answer_recovery",
    "protocol_recovery", "prefix_empty", "history_truncated", "prompt_sanitized",
    "prepare_rejected", "budget_rejected", "schema_changed", "cold_reset",
})
_NATIVE_FIXTURE_PRIOR_REASONS = frozenset({
    "scope_off", "no_vault_key", "no_assistant", "no_ciphertext",
    "fingerprint_rejected", "decrypt_failed", "retained",
})


def _log_native_fixture_admission(
    admission: str, prior: str, *, history_count: int, visible_count: int,
) -> None:
    """Expose only fixed predicates for the signed isolated replay fixture."""
    if (admission not in _NATIVE_FIXTURE_ADMISSION_REASONS
            or prior not in _NATIVE_FIXTURE_PRIOR_REASONS
            or os.getenv("CI") != "true"
            or os.getenv("OPENMATES_CI_ISOLATED") != "1"):
        return
    from backend.shared.testing.mock_context import get_mock_group
    if get_mock_group() != "native_cache_tools_v1":
        return
    logger.info(
        "Native fixture admission: admission=%s prior=%s history_count=%d visible_count=%d",
        admission, prior, history_count, visible_count,
    )


def _has_remote_image_url(value: Any) -> bool:
    """Find provider image blocks whose token cost cannot be inferred from the URL."""
    if isinstance(value, dict):
        if value.get("type") in {"image_url", "input_image"}:
            image = value.get("image_url")
            url = image.get("url") if isinstance(image, dict) else image
            if isinstance(url, str) and url.lower().startswith(("https://", "http://")):
                return True
        return any(_has_remote_image_url(child) for child in value.values())
    if isinstance(value, list):
        return any(_has_remote_image_url(child) for child in value)
    return False


def _quote_ai_iteration_credits(
    *,
    model_id: str,
    system_prompt: str,
    message_history: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    output_token_limit: Optional[int] = None,
    input_envelope_tokens: int = 0,
    credit_rounding_headroom: int = 0,
    inference_host: Optional[str] = None,
    customer_cache_pricing_enabled: bool = True,
) -> int:
    if "/" not in model_id:
        raise RuntimeError("AI reservation requires a provider-qualified model id")
    provider_id, model_suffix = model_id.split("/", 1)
    model_config = config_manager.get_model_pricing(provider_id, model_suffix)
    if not model_config:
        raise RuntimeError(f"AI reservation pricing is unavailable for {model_id}")
    if not customer_cache_pricing_enabled and (model_config.get("cache_pricing") or {}).get("enabled"):
        model_config = copy.deepcopy(model_config)
        model_config["cache_pricing"]["enabled"] = False
    configured_max_output_tokens = (model_config.get("features") or {}).get("max_output_tokens")
    if output_token_limit is not None:
        max_output_tokens = (
            min(configured_max_output_tokens, output_token_limit)
            if isinstance(configured_max_output_tokens, int) and configured_max_output_tokens > 0
            else output_token_limit
        )
    else:
        max_output_tokens = configured_max_output_tokens
    if not isinstance(max_output_tokens, int) or max_output_tokens <= 0:
        raise RuntimeError(f"AI reservation output limit is unavailable for {model_id}")
    serialized_input = json.dumps(
        {"system": system_prompt, "messages": message_history, "tools": tools or []},
        default=str,
        separators=(",", ":"),
    )
    estimated_input_tokens = max(
        1,
        len(serialized_input.encode("utf-8")) + max(0, input_envelope_tokens),
    )
    if _has_remote_image_url(message_history):
        # A URL's byte length does not bound the provider's image token usage.
        # Reserve the model's entire advertised input/context capacity, plus
        # the separate output allowance below. Settlement releases unused hold.
        costs = model_config.get("costs") or {}
        context_limits = [
            value for category in ("input_per_million_token", "output_per_million_token")
            if isinstance(entry := costs.get(category), dict)
            if isinstance(value := entry.get("max_context"), int)
            and not isinstance(value, bool) and value > 0
        ]
        if not context_limits:
            raise RuntimeError(f"AI reservation context limit is unavailable for remote image on {model_id}")
        estimated_input_tokens = max(estimated_input_tokens, max(context_limits))
    quote_host = inference_host or model_config.get("default_server") or provider_id
    _context_band, selected_rates = select_customer_context_band(
        model_pricing_details=model_config,
        inference_host=quote_host,
        input_total=estimated_input_tokens,
    )
    base_rates = (model_config.get("pricing") or {}).get("tokens") or {}
    quote_config = model_config
    if selected_rates is not base_rates:
        quote_config = copy.deepcopy(model_config)
        quote_config["pricing"]["tokens"] = copy.deepcopy(selected_rates)
    cache_policy = model_config.get("cache_pricing") or {}
    if cache_policy.get("enabled") and cache_policy.get("write_billing") == "separate":
        token_rates = (quote_config.get("pricing") or {}).get("tokens") or {}
        input_units = [
            rate.get("per_credit_unit")
            for category in ("input", "cache_write", "cache_write_1h")
            if isinstance(rate := token_rates.get(category), dict)
        ]
        positive_units = [
            value for value in input_units
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
        ]
        if positive_units:
            # All estimated input could be a cold write. Bound that premium
            # without mutating the live tariff or assuming a future cache hit.
            if quote_config is model_config:
                quote_config = copy.deepcopy(model_config)
            quote_config["pricing"]["tokens"].setdefault("input", {})["per_credit_unit"] = min(positive_units)
    quote = calculate_total_credits(
        pricing_config=quote_config,
        input_tokens=estimated_input_tokens,
        output_tokens=max_output_tokens,
    )
    # A cumulative rounded charge can carry one fractional credit from an
    # earlier operation. Reserve that capacity up front; never clamp usage.
    return quote + credit_rounding_headroom if quote > 0 else 0


def _mistral_prompt_cache_key(request_data: AskSkillRequest) -> Optional[str]:
    """Bind Mistral's opaque key to one authorized user/team/chat scope."""
    if not INTERNAL_API_SHARED_TOKEN or not request_data.chat_id:
        return None
    scope = json.dumps(
        [getattr(request_data, "user_id_hash", "") or "",
         getattr(request_data, "team_id", None), request_data.chat_id],
        separators=(",", ":"), ensure_ascii=False,
    )
    return hmac.new(
        INTERNAL_API_SHARED_TOKEN.encode("utf-8"),
        b"openmates:mistral-chat-cache:v2\0" + scope.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _max_affordable_ai_output_tokens(
    *,
    model_id: str,
    system_prompt: str,
    message_history: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    requested_output_token_limit: int,
    available_credits: int,
    input_envelope_tokens: int = 0,
    credit_rounding_headroom: int = 0,
    inference_host: Optional[str] = None,
    customer_cache_pricing_enabled: bool = True,
) -> Optional[int]:
    if requested_output_token_limit <= 0 or available_credits <= 0:
        return None

    quote_kwargs = {
        "model_id": model_id,
        "system_prompt": system_prompt,
        "message_history": message_history,
        "tools": tools,
        "input_envelope_tokens": input_envelope_tokens,
        "credit_rounding_headroom": credit_rounding_headroom,
        "inference_host": inference_host,
        "customer_cache_pricing_enabled": customer_cache_pricing_enabled,
    }
    if _quote_ai_iteration_credits(
        **quote_kwargs,
        output_token_limit=requested_output_token_limit,
    ) <= available_credits:
        return requested_output_token_limit

    affordable_limit: Optional[int] = None
    low = 1
    high = requested_output_token_limit
    while low <= high:
        candidate = (low + high) // 2
        quote = _quote_ai_iteration_credits(**quote_kwargs, output_token_limit=candidate)
        if quote <= available_credits:
            affordable_limit = candidate
            low = candidate + 1
        else:
            high = candidate - 1
    return affordable_limit


async def _fit_anonymous_output_token_limit(
    *,
    model_id: str,
    system_prompt: str,
    message_history: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    requested_output_token_limit: Optional[int],
    request_data: AskSkillRequest,
) -> Optional[int]:
    """Fit the next anonymous call to current capacity, then reserve atomically."""
    if not getattr(request_data, "is_anonymous", False):
        return requested_output_token_limit
    if not request_data.anonymous_reservation_id or requested_output_token_limit is None:
        raise AnonymousUsageAccountingError("Anonymous inference is missing its reservation or output limit")
    budget = await _anonymous_accounting_request(
        "internal/anonymous-usage/request-budget",
        {"parent_request_id": request_data.anonymous_reservation_id},
    )
    available = budget.get("available_credits")
    if not isinstance(available, int) or isinstance(available, bool) or available < 0:
        raise AnonymousUsageAccountingError("Anonymous allowance response is invalid")
    fitted = _max_affordable_ai_output_tokens(
        model_id=model_id,
        system_prompt=system_prompt,
        message_history=message_history,
        tools=tools,
        requested_output_token_limit=requested_output_token_limit,
        available_credits=available,
        input_envelope_tokens=ANONYMOUS_AI_INPUT_ENVELOPE_TOKENS,
        credit_rounding_headroom=ANONYMOUS_AI_CREDIT_ROUNDING_HEADROOM,
        customer_cache_pricing_enabled=_normal_chat_cache_pricing_scope(request_data),
    )
    if fitted is None:
        raise AnonymousUsageLimitError("Anonymous allowance cannot cover inference input")
    return fitted


async def _reserve_authenticated_ai_turn(
    *,
    task_id: str,
    request_data: AskSkillRequest,
    model_id: str,
    system_prompt: str,
    message_history: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    requested_output_token_limit: Optional[int],
    model_usage_tracker: ModelUsageTracker,
    reservation_state: Dict[str, Any],
    inference_host: Optional[str] = None,
) -> int:
    """Top up one durable turn hold; fit output against authoritative capacity."""
    if getattr(request_data, "is_anonymous", False) or request_data.orchestration_id:
        raise ValueError("Authenticated turn reservation requires an ordinary request")
    if not request_data.user_id or not request_data.user_id_hash:
        raise AuthenticatedReservationError("Authenticated reservation identity is missing")
    if requested_output_token_limit is None:
        if "/" not in model_id:
            raise AuthenticatedReservationError("Authenticated reservation needs a bounded output limit")
        configured = config_manager.get_model_pricing(*model_id.split("/", 1)) or {}
        requested_output_token_limit = (configured.get("features") or {}).get("max_output_tokens")
        if requested_output_token_limit is None:
            requested_output_token_limit = ORCHESTRATED_AI_MAX_OUTPUT_TOKENS
    if isinstance(requested_output_token_limit, bool) or not isinstance(requested_output_token_limit, int) or requested_output_token_limit <= 0:
        raise AuthenticatedReservationError("Authenticated reservation needs a bounded output limit")
    charge_id = f"ai-ask:{task_id}:main"
    endpoint = "internal/billing/team/reserve" if request_data.team_id else "internal/billing/reserve"
    identity = (
        {"team_id": request_data.team_id, "actor_user_id": request_data.user_id}
        if request_data.team_id else
        {"user_id": request_data.user_id, "user_id_hash": request_data.user_id_hash}
    )
    observed_credits = (
        calculate_model_usage_credits(model_usage_tracker.usage_by_model, config_manager.get_model_pricing)
        if model_usage_tracker.usage_by_model else 0
    )
    fitted_limit = requested_output_token_limit
    for _ in range(2):
        next_quote = _quote_ai_iteration_credits(
            model_id=model_id, system_prompt=system_prompt,
            message_history=message_history, tools=tools,
            output_token_limit=fitted_limit, credit_rounding_headroom=1,
            inference_host=inference_host,
            customer_cache_pricing_enabled=_normal_chat_cache_pricing_scope(request_data),
        )
        cumulative_quote = max(int(reservation_state.get("quoted_credits") or 0), observed_credits + next_quote)
        try:
            result = await _make_internal_api_request("POST", endpoint, {
                **identity, "idempotency_key": charge_id,
                "quoted_credits": cumulative_quote, "app_id": "ai", "skill_id": "ask",
            })
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 402:
                raise AuthenticatedReservationError("Authenticated reservation rejected") from error
            try:
                refusal = error.response.json()
                if isinstance(refusal.get("detail"), dict):
                    refusal = refusal["detail"]
                max_quote = refusal.get("max_quotable_credits")
            except (ValueError, AttributeError):
                max_quote = None
            if isinstance(max_quote, bool) or not isinstance(max_quote, int):
                raise AuthenticatedReservationError("Reservation capacity response is invalid") from error
            affordable = _max_affordable_ai_output_tokens(
                model_id=model_id, system_prompt=system_prompt,
                message_history=message_history, tools=tools,
                requested_output_token_limit=fitted_limit,
                available_credits=max_quote - observed_credits,
                credit_rounding_headroom=1,
                inference_host=inference_host,
                customer_cache_pricing_enabled=_normal_chat_cache_pricing_scope(request_data),
            )
            if affordable is None or affordable >= fitted_limit:
                raise AuthenticatedReservationLimitError("Insufficient credits for inference input") from error
            fitted_limit = affordable
            continue
        except Exception as error:
            raise AuthenticatedReservationError("Authenticated reservation acknowledgement unavailable") from error
        if result.get("state") == "skipped" and result.get("charge_id") == charge_id:
            # The billing authority disables holds for payment-disabled/self-hosted deployments.
            reservation_state.clear()
            return fitted_limit
        if result.get("state") != "reserved" or result.get("charge_id") != charge_id:
            raise AuthenticatedReservationError("Authenticated reservation response is invalid")
        held = result.get("quoted_credits")
        if isinstance(held, bool) or not isinstance(held, int) or held < cumulative_quote:
            raise AuthenticatedReservationError("Authenticated reservation quote is invalid")
        reservation_state.update({"charge_id": charge_id, "quoted_credits": held, "active": True})
        return fitted_limit
    raise AuthenticatedReservationLimitError("Insufficient credits for fitted inference")


async def _release_authenticated_ai_reservation(
    *, request_data: AskSkillRequest, reservation_state: Dict[str, Any], reason: str,
) -> None:
    if not reservation_state.get("active"):
        return
    payload = {
        "subject_kind": "team" if request_data.team_id else "personal",
        "idempotency_key": reservation_state["charge_id"],
        "reason": reason,
        **({"team_id": request_data.team_id, "actor_user_id": request_data.user_id}
           if request_data.team_id else
           {"user_id": request_data.user_id, "user_id_hash": request_data.user_id_hash}),
    }
    try:
        await _make_internal_api_request("POST", "internal/billing/reservation/release", payload)
    except Exception as error:
        raise AuthenticatedReservationError("Authenticated reservation release acknowledgement unavailable") from error
    reservation_state["active"] = False
    reservation_state["released"] = True


def _fit_workflow_output_token_limit(
    *, model_id: str, system_prompt: str, message_history: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]], requested_output_token_limit: Optional[int],
    request_data: AskSkillRequest,
) -> Optional[int]:
    """Bound a signed Workflow Ask AI call before contacting its model provider."""
    preferences = request_data.user_preferences or {}
    budget = preferences.get("workflow_budget") if preferences.get("workflow_ai") is True else None
    if budget is not None:
        from backend.core.api.app.services.workflow_app_skill_adapter import verify_workflow_ai_budget
        allowance = verify_workflow_ai_budget(request_data.user_id, budget)
        if allowance is None or allowance != preferences.get("workflow_credit_allowance"):
            raise RuntimeError("Workflow Ask AI credit allowance is invalid")
    else:
        allowance = None
        if preferences.get("workflow_credit_allowance") is not None:
            raise RuntimeError("Workflow Ask AI credit allowance is unsigned")
    if allowance is None:
        return requested_output_token_limit
    if isinstance(allowance, bool) or not isinstance(allowance, int) or allowance <= 0:
        raise RuntimeError("Workflow Ask AI credit allowance is invalid")
    if requested_output_token_limit is None:
        if "/" not in model_id:
            raise RuntimeError("Workflow Ask AI model has no bounded output limit")
        provider_id, model_suffix = model_id.split("/", 1)
        model_config = config_manager.get_model_pricing(provider_id, model_suffix) or {}
        requested_output_token_limit = (model_config.get("features") or {}).get("max_output_tokens")
    if not isinstance(requested_output_token_limit, int) or requested_output_token_limit <= 0:
        raise RuntimeError("Workflow Ask AI model has no bounded output limit")
    fitted = _max_affordable_ai_output_tokens(
        model_id=model_id, system_prompt=system_prompt,
        message_history=message_history, tools=tools,
        requested_output_token_limit=requested_output_token_limit,
        available_credits=allowance, input_envelope_tokens=512,
        credit_rounding_headroom=1,
        customer_cache_pricing_enabled=_normal_chat_cache_pricing_scope(request_data),
    )
    if fitted is None:
        raise RuntimeError("Workflow Ask AI input exceeds its credit allowance")
    return fitted


async def _fit_parent_continuation_output_token_limit(
    *,
    model_id: str,
    system_prompt: str,
    message_history: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    requested_output_token_limit: Optional[int],
    request_data: AskSkillRequest,
    directus_service: Optional[DirectusService],
    log_prefix: str,
) -> Optional[int]:
    if (
        requested_output_token_limit is None
        or not is_sub_chat_continuation(request_data)
        or not request_data.orchestration_id
        or not directus_service
    ):
        return requested_output_token_limit

    root_state = await SubChatOrchestrationService(directus_service).execute("get_root_state", {
        "protocol_version": 1,
        "orchestration_id": request_data.orchestration_id,
        "hashed_user_id": request_data.user_id_hash,
    })
    available_credits = max(
        int(root_state["credit_limit"])
        - int(root_state["spent_credits"])
        - int(root_state["reserved_credits"]),
        0,
    )
    fitted_limit = _max_affordable_ai_output_tokens(
        model_id=model_id,
        system_prompt=system_prompt,
        message_history=message_history,
        tools=tools,
        requested_output_token_limit=requested_output_token_limit,
        available_credits=available_credits,
        customer_cache_pricing_enabled=_normal_chat_cache_pricing_scope(request_data),
    )
    if fitted_limit is None:
        raise RuntimeError("Remaining orchestration credits cannot cover parent synthesis input")
    if fitted_limit < requested_output_token_limit:
        logger.info(
            "%s [SUB_CHAT] Reduced parent synthesis output limit from %s to %s tokens to fit %s remaining credits",
            log_prefix,
            requested_output_token_limit,
            fitted_limit,
            available_credits,
        )
    return fitted_limit


def _orchestrated_ai_output_token_limit(
    model_id: str,
    orchestration_id: Optional[str],
    is_anonymous: bool = False,
) -> Optional[int]:
    if not orchestration_id and not is_anonymous:
        return None
    hard_limit = ANONYMOUS_AI_MAX_OUTPUT_TOKENS if is_anonymous else ORCHESTRATED_AI_MAX_OUTPUT_TOKENS
    if "/" not in model_id:
        return hard_limit
    provider_id, model_suffix = model_id.split("/", 1)
    model_config = config_manager.get_model_pricing(provider_id, model_suffix) or {}
    configured_limit = (model_config.get("features") or {}).get("max_output_tokens")
    if isinstance(configured_limit, int) and configured_limit > 0:
        return min(configured_limit, hard_limit)
    return hard_limit


def _personal_chat_output_token_limit(model_id: str) -> int:
    """Keep the provider output cap independently of customer credit holds."""
    if "/" not in model_id:
        raise ValueError("Personal chat model must be provider-qualified")
    provider_id, model_suffix = model_id.split("/", 1)
    configured = config_manager.get_model_pricing(provider_id, model_suffix) or {}
    limit = (configured.get("features") or {}).get("max_output_tokens")
    if limit is None:
        limit = ORCHESTRATED_AI_MAX_OUTPUT_TOKENS
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("Personal chat model has no valid output token limit")
    return limit


async def _fit_personal_chat_output_token_limit(
    *,
    request_data: AskSkillRequest,
    cache_service: Optional[CacheService],
    model_usage_tracker: ModelUsageTracker,
    model_id: str,
    system_prompt: str,
    message_history: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    requested_output_token_limit: Optional[int],
    inference_host: str,
) -> int:
    """Bound one unreserved dispatch to the remaining personal-wallet capacity."""
    if not request_data.user_id or cache_service is None:
        raise AuthenticatedReservationError("Personal inference balance is unavailable")
    if (isinstance(requested_output_token_limit, bool)
            or not isinstance(requested_output_token_limit, int)
            or requested_output_token_limit <= 0):
        raise AuthenticatedReservationError("Personal inference needs a bounded output limit")
    try:
        user = await cache_service.get_user_by_id(request_data.user_id)
    except Exception as exc:
        raise AuthenticatedReservationError("Personal inference balance is unavailable") from exc
    balance = user.get("credits") if isinstance(user, dict) else None
    if isinstance(balance, bool) or not isinstance(balance, int):
        raise AuthenticatedReservationError("Personal inference balance is unavailable")
    try:
        observed_credits = (
            calculate_model_usage_credits(model_usage_tracker.usage_by_model, config_manager.get_model_pricing)
            if model_usage_tracker.usage_by_model else 0
        )
        fitted = _max_affordable_ai_output_tokens(
            model_id=model_id,
            system_prompt=system_prompt,
            message_history=message_history,
            tools=tools,
            requested_output_token_limit=requested_output_token_limit,
            available_credits=balance + 500 - observed_credits,
            credit_rounding_headroom=1,
            inference_host=inference_host,
            customer_cache_pricing_enabled=_normal_chat_cache_pricing_scope(request_data),
        )
    except Exception as exc:
        raise AuthenticatedReservationError("Personal inference quote is unavailable") from exc
    if fitted is None:
        raise AuthenticatedReservationLimitError("Personal inference input exceeds remaining credits")
    return fitted


async def _reserve_ai_iteration(
    *,
    task_id: str,
    iteration: int,
    model_id: str,
    system_prompt: str,
    message_history: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    output_token_limit: Optional[int],
    request_data: AskSkillRequest,
    directus_service: Optional[DirectusService],
) -> Optional[str]:
    is_anonymous = bool(getattr(request_data, "is_anonymous", False))
    if not request_data.orchestration_id and not is_anonymous:
        return None
    if not directus_service and not is_anonymous:
        raise RuntimeError("Orchestrated AI reservation requires Directus")
    quote = _quote_ai_iteration_credits(
        model_id=model_id,
        system_prompt=system_prompt,
        message_history=message_history,
        tools=tools,
        output_token_limit=output_token_limit,
        input_envelope_tokens=ANONYMOUS_AI_INPUT_ENVELOPE_TOKENS if is_anonymous else 0,
        credit_rounding_headroom=ANONYMOUS_AI_CREDIT_ROUNDING_HEADROOM if is_anonymous else 0,
        customer_cache_pricing_enabled=_normal_chat_cache_pricing_scope(request_data),
    )
    if quote <= 0:
        return None
    charge_id = f"ai-ask:{task_id}:main"
    operation_id = f"{charge_id}:iteration:{iteration}:model:{model_id}"
    if is_anonymous:
        await _reserve_anonymous_operation(
            request_data=request_data,
            operation_id=operation_id,
            charge_id=charge_id,
            quoted_credits=quote,
        )
    else:
        await SubChatOrchestrationService(directus_service).execute("reserve_operation", {  # type: ignore[arg-type]
            "protocol_version": 1,
            "operation_id": operation_id,
            "charge_id": charge_id,
            "orchestration_id": request_data.orchestration_id,
            "hashed_user_id": request_data.user_id_hash,
            "root_chat_id": request_data.root_chat_id,
            "actual_chat_id": request_data.chat_id,
            "depth": request_data.sub_chat_depth,
            "app_id": "ai",
            "skill_id": "ask",
            "phase": f"inference_{iteration}",
            "quoted_credits": quote,
        })
    return operation_id


async def _fail_reserved_operation(
    *,
    operation_id: Optional[str],
    request_data: AskSkillRequest,
    directus_service: Optional[DirectusService],
    preserve_anonymous_reservation: bool = False,
) -> None:
    if not operation_id:
        return
    if getattr(request_data, "is_anonymous", False):
        if preserve_anonymous_reservation:
            logger.warning(
                "Retaining anonymous AI reservation %s after an ambiguous provider failure",
                operation_id,
            )
            return
        await _release_anonymous_operation(operation_id=operation_id, reason="provider_failed")
        return
    if not request_data.orchestration_id or not directus_service:
        return
    await SubChatOrchestrationService(directus_service).execute("fail_operation", {
        "protocol_version": 1,
        "operation_id": operation_id,
        "orchestration_id": request_data.orchestration_id,
        "hashed_user_id": request_data.user_id_hash,
    })


def _dict_value(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _coerce_nonnegative_credits(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        credits = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, credits)


def _get_result_declared_charge_items(
    app_id: str,
    skill_id: str,
    results: List[Dict[str, Any]],
) -> Optional[List[Tuple[int, int, Dict[str, Any]]]]:
    if (app_id, skill_id) not in VARIABLE_RESULT_BILLING_SKILLS:
        return None

    charge_items: List[Tuple[int, int, Dict[str, Any]]] = []
    found_result_declared_billing = False
    for result_index, result in enumerate(results):
        item = _dict_value(result)
        direct_credits = _coerce_nonnegative_credits(item.get("credits_charged"))
        if item.get("status") == "finished" and direct_credits is not None:
            found_result_declared_billing = True
            if direct_credits > 0:
                charge_items.append((result_index, direct_credits, item))
            continue

        usage = _dict_value(item.get("usage"))
        usage_credits = _coerce_nonnegative_credits(usage.get("credits_charged"))
        if usage_credits is not None:
            found_result_declared_billing = True
            if usage_credits > 0:
                charge_items.append((result_index, usage_credits, item))

    return charge_items if found_result_declared_billing else None


def _get_result_declared_usage_details(
    app_id: str,
    skill_id: str,
    result: Dict[str, Any],
) -> Dict[str, Any]:
    if (app_id, skill_id) not in VARIABLE_RESULT_BILLING_SKILLS:
        return {}

    details: Dict[str, Any] = {}
    if app_id == "audio":
        model = result.get("model")
        if isinstance(model, str) and model.strip():
            details["model_used"] = model if "/" in model else f"elevenlabs/{model}"
        duration_seconds = result.get("duration_seconds")
        if isinstance(duration_seconds, (int, float)) and not isinstance(duration_seconds, bool):
            details["duration_second"] = float(duration_seconds)
        return details

    usage = _dict_value(result.get("usage"))
    if not usage:
        return details
    details.update({f"image_to_html_{key}": value for key, value in usage.items()})
    if usage.get("model"):
        details["model_used"] = usage["model"]
    if usage.get("input_tokens") is not None:
        details["input_tokens"] = usage["input_tokens"]
    if usage.get("output_tokens") is not None:
        details["output_tokens"] = usage["output_tokens"]
    if usage.get("duration_second") is not None:
        details["duration_second"] = usage["duration_second"]
    elif usage.get("e2b_render_seconds") is not None:
        details["duration_second"] = usage["e2b_render_seconds"]
    return details


async def _charge_skill_credits(
    task_id: str,
    execution_id: str,
    request_data: AskSkillRequest,
    app_id: str,
    skill_id: str,
    discovered_apps_metadata: Dict[str, AppYAML],
    results: List[Dict[str, Any]],
    parsed_args: Dict[str, Any],
    log_prefix: str,
    grouped_results: Optional[List[Dict[str, Any]]] = None,
    provider_result_data: Any = None,
    directus_service: Optional[DirectusService] = None,
    reserved_operation_ids: Optional[List[str]] = None,
) -> None:
    """
    Calculate and charge credits for a skill execution.
    Creates usage entry automatically via BillingService.
    
    Args:
        grouped_results: Optional grouped results from multi-request skills.
            Each group has {"id": ..., "results": [...], "error": "..."}.
            Used to count only successful requests for billing (failed requests are not charged).
        provider_result_data: Original top-level execution response retained for
            provider attribution before results are flattened for model inference.
    """
    charged_operation_ids: set[str] = set()
    anonymous_settlement_failed = False
    try:
        skill_def, pricing_config = await _resolve_skill_billing_config(
            app_id=app_id,
            skill_id=skill_id,
            discovered_apps_metadata=discovered_apps_metadata,
            log_prefix=log_prefix,
        )
        if not skill_def:
            return
        
        # Skip charging if the skill returned no results (e.g. API key failure,
        # provider outage). Users should not be billed for failed requests.
        if not results:
            logger.info(f"{log_prefix} Skill '{app_id}.{skill_id}' returned 0 results, skipping billing.")
            return
        
        # Skip charging if ALL results indicate failure (error/cancelled status).
        # When a skill execution fails (HTTP error, rate limit, timeout, etc.),
        # the results list contains dicts with status="error" or status="cancelled".
        # Users should not be charged for failed executions.
        # Note: the REST API flow (apps_api.py) already handles this via
        # is_skill_execution_successful() — this mirrors that logic for the
        # AI chat flow.
        if all(
            isinstance(r, dict) and r.get("status") in ("error", "cancelled")
            for r in results
        ):
            logger.info(f"{log_prefix} Skill '{app_id}.{skill_id}' failed — all {len(results)} result(s) have error/cancelled status, skipping billing.")
            return

        if getattr(request_data, "is_anonymous", False) and (app_id, skill_id) in ASYNC_SKILLS:
            operation_ids = list(reserved_operation_ids or [])
            quoted_credits = await _settle_anonymous_skill_quote(
                app_id=app_id,
                skill_id=skill_id,
                parsed_args=parsed_args,
                discovered_apps_metadata=discovered_apps_metadata,
                reserved_operation_ids=operation_ids,
                log_prefix=log_prefix,
            )
            charged_operation_ids.update(operation_ids)
            logger.info(
                "%s Settled %s conservatively quoted anonymous credits for async skill '%s.%s'.",
                log_prefix,
                quoted_credits,
                app_id,
                skill_id,
            )
            return
        
        # Calculate credits based on skill execution
        # All skills use 'requests' array format - charge per request (units_processed)
        # IMPORTANT: Only charge for SUCCESSFUL requests. Failed requests (e.g., rate-limited
        # searches, HTTP errors) should not be billed to the user.
        units_processed = None
        if grouped_results and isinstance(grouped_results, list):
            # Use grouped_results to count only successful requests (no error field, non-empty results)
            total_requests = len(grouped_results)
            successful_requests = sum(
                1 for group in grouped_results
                if isinstance(group, dict)
                and not group.get("error")  # No error field
                and group.get("results")    # Has non-empty results
            )
            units_processed = successful_requests
            if successful_requests < total_requests:
                logger.info(
                    f"{log_prefix} Skill '{app_id}.{skill_id}': {successful_requests}/{total_requests} "
                    f"request(s) succeeded — only charging for successful ones"
                )
            else:
                logger.debug(f"{log_prefix} Skill '{app_id}.{skill_id}' executed with {units_processed} successful request(s)")
        elif "requests" in parsed_args and isinstance(parsed_args["requests"], list):
            # Fallback: count all requests in the requests array (when grouped_results not available)
            units_processed = len(parsed_args["requests"])
            logger.debug(f"{log_prefix} Skill '{app_id}.{skill_id}' executed with {units_processed} request(s) in requests array")
        else:
            # Fallback: if no requests array found, charge for single execution
            # This handles edge cases where a skill might not use the requests pattern yet
            units_processed = 1
            logger.debug(f"{log_prefix} Skill '{app_id}.{skill_id}' has no 'requests' array, charging for single execution")
        
        # If all requests failed, skip billing entirely
        if units_processed <= 0:
            logger.info(f"{log_prefix} Skill '{app_id}.{skill_id}': no successful requests, skipping billing entirely.")
            return
        
        result_declared_charge_items = _get_result_declared_charge_items(app_id, skill_id, results)
        if result_declared_charge_items is not None:
            if not result_declared_charge_items:
                logger.info(f"{log_prefix} Skill '{app_id}.{skill_id}': no result-declared successful charges, skipping billing.")
                return
            charge_items = result_declared_charge_items
            units_processed = len(charge_items)
            credits_charged = sum(item_credits for _, item_credits, _ in charge_items)
            logger.info(
                f"{log_prefix} Using result-declared credits for skill '{app_id}.{skill_id}': "
                f"{credits_charged} across {units_processed} successful result(s)."
            )
        elif pricing_config:
            credits_charged = calculate_total_credits(
                pricing_config=pricing_config,
                units_processed=units_processed
            )
            per_request_credits = credits_charged // units_processed if units_processed > 0 else credits_charged
            credits_remainder = credits_charged - (per_request_credits * units_processed)
            charge_items = [
                (
                    i,
                    per_request_credits + (credits_remainder if i == units_processed - 1 else 0),
                    {},
                )
                for i in range(units_processed)
            ]
        else:
            # Default to minimum charge if no pricing config
            credits_charged = MINIMUM_CREDITS_CHARGED
            charge_items = [(0, credits_charged, {})]
            logger.info(f"{log_prefix} No pricing config for skill '{app_id}.{skill_id}', using minimum charge: {credits_charged}")
        
        if credits_charged <= 0:
            logger.debug(f"{log_prefix} Calculated credits for skill '{app_id}.{skill_id}' is 0, skipping billing.")
            return
        
        # Resolve provider info (name + region) for usage tracking
        # This allows the usage detail view to show provider and region for ALL skills,
        # not just AI Ask. We derive the provider_id from full_model_reference or providers list.
        resolved_provider_name = None
        resolved_region = None
        resolved_model_used = skill_def.full_model_reference  # e.g., "bfl/flux-schnell" or None
        
        # Determine provider_id for info lookup
        info_provider_id = resolve_skill_usage_provider_id(
            app_id,
            skill_id,
            skill_def,
            provider_result_data if provider_result_data is not None else results,
        )
        if info_provider_id:
            # Preserve compatibility for legacy human-readable provider refs.
            pname = info_provider_id
            info_provider_id = info_provider_id.lower().replace(" ", "_")
            if pname == "Google" and app_id == "maps":
                info_provider_id = "google_maps"
            elif pname in ("Brave", "Brave Search"):
                info_provider_id = "brave"
        
        if info_provider_id:
            try:
                model_ref_param = f"?model_ref={skill_def.full_model_reference}" if skill_def.full_model_reference else ""
                info_endpoint = f"internal/config/provider_info/{info_provider_id}{model_ref_param}"
                provider_info = await _make_internal_api_request("GET", info_endpoint)
                if provider_info and isinstance(provider_info, dict):
                    resolved_provider_name = provider_info.get("name")
                    resolved_region = provider_info.get("region")
                    logger.debug(f"{log_prefix} Resolved provider info for '{info_provider_id}': name={resolved_provider_name}, region={resolved_region}")
            except Exception as e:
                logger.warning(f"{log_prefix} Failed to fetch provider info for '{info_provider_id}': {e}")
        
        # Prepare usage details
        # Include chat_id and message_id when skill is triggered in a chat context
        # These fields are important for linking usage entries to chat sessions
        # The billing service will validate and only include non-empty values
        usage_details = {
            "chat_id": request_data.chat_id,  # Always available in AskSkillRequest
            "root_chat_id": request_data.root_chat_id or request_data.chat_id,
            "actual_chat_id": request_data.chat_id,
            "root_turn_id": request_data.root_turn_id,
            "orchestration_id": request_data.orchestration_id,
            "depth": request_data.sub_chat_depth,
            "message_id": request_data.message_id,  # Always available in AskSkillRequest
            "is_incognito": getattr(request_data, 'is_incognito', False),  # Include incognito flag for billing
            "units_processed": units_processed,
            "model_used": resolved_model_used,  # Full model reference (e.g., "bfl/flux-schnell") or None
            "server_provider": resolved_provider_name,  # Provider display name (e.g., "Brave Search", "BFL")
            "server_region": resolved_region,  # Server region (e.g., "US", "EU")
        }
        _apply_benchmark_usage_details(request_data, usage_details)
        
        headers = {"Content-Type": "application/json"}
        if INTERNAL_API_SHARED_TOKEN:
            headers["X-Internal-Service-Token"] = INTERNAL_API_SHARED_TOKEN
        
        async with httpx.AsyncClient() as client:
            url = f"{INTERNAL_API_BASE_URL}/internal/billing/charge"
            charge_count = len(charge_items)
            for charge_position, (operation_index, request_credits, result_item) in enumerate(charge_items):
                if request_credits <= 0:
                    continue
                
                # Each individual request gets units_processed=1 to reflect one request
                request_usage_details = {
                    **usage_details,
                    **_get_result_declared_usage_details(app_id, skill_id, result_item),
                    "units_processed": 1,
                }
                operation_id = _skill_operation_id(app_id, skill_id, task_id, execution_id, operation_index)
                request_usage_details["operation_id"] = operation_id

                if getattr(request_data, "is_anonymous", False):
                    await _finalize_anonymous_charge(
                        charge_id=operation_id,
                        actual_credits=request_credits,
                    )
                    charged_operation_ids.add(operation_id)
                    logger.info(
                        "%s Settled %s anonymous credits for skill '%s.%s' (request %s/%s).",
                        log_prefix,
                        request_credits,
                        app_id,
                        skill_id,
                        charge_position + 1,
                        charge_count,
                    )
                    continue
                
                team_id = getattr(request_data, "team_id", None)
                if team_id:
                    request_usage_details = {
                        **request_usage_details,
                        "workspace_type": getattr(request_data, "team_workspace_type", None) or "chat",
                        "object_id_hash": getattr(request_data, "team_object_id_hash", None),
                    }
                    charge_payload = {
                        "team_id": team_id,
                        "actor_user_id": request_data.user_id,
                        "credits": request_credits,
                        "skill_id": skill_id,
                        "app_id": app_id,
                        "idempotency_key": operation_id,
                        "usage_details": request_usage_details,
                    }
                    url = f"{INTERNAL_API_BASE_URL}/internal/billing/team/charge"
                else:
                    charge_payload = {
                        "user_id": request_data.user_id,
                        "user_id_hash": request_data.user_id_hash,
                        "credits": request_credits,
                        "skill_id": skill_id,  # Required: ID of the skill that was executed
                        "app_id": app_id,  # Required: ID of the app that contains the skill
                        "idempotency_key": operation_id,
                        "usage_details": request_usage_details  # Contains chat_id, message_id, and other optional metadata
                    }
                    url = f"{INTERNAL_API_BASE_URL}/internal/billing/charge"
                logger.info(f"{log_prefix} Charging {request_credits} credits for skill '{app_id}.{skill_id}' (request {charge_position + 1}/{charge_count}).")
                response = await client.post(url, json=charge_payload, headers=headers, timeout=10.0)
                response.raise_for_status()
                charged_operation_ids.add(operation_id)
                logger.debug(f"{log_prefix} Charged request {charge_position + 1}/{charge_count} for '{app_id}.{skill_id}': {response.json()}")
            
            logger.info(f"{log_prefix} Successfully charged {credits_charged} total credits for skill '{app_id}.{skill_id}' across {units_processed} request(s).")
            
    except httpx.HTTPStatusError as e:
        anonymous_settlement_failed = bool(getattr(request_data, "is_anonymous", False))
        logger.error(f"{log_prefix} HTTP error charging credits for skill '{app_id}.{skill_id}': {e.response.status_code} - {e.response.text}", exc_info=True)
        # Don't raise - billing failure shouldn't break skill execution
    except Exception as e:
        anonymous_settlement_failed = bool(getattr(request_data, "is_anonymous", False))
        logger.error(f"{log_prefix} Error charging credits for skill '{app_id}.{skill_id}': {e}", exc_info=True)
        # Don't raise - billing failure shouldn't break skill execution
    finally:
        uncharged_operation_ids = set(reserved_operation_ids or []) - charged_operation_ids
        if getattr(request_data, "is_anonymous", False) and not anonymous_settlement_failed:
            for operation_id in uncharged_operation_ids:
                try:
                    await _release_anonymous_operation(operation_id=operation_id, reason="provider_not_charged")
                except Exception:
                    logger.error("%s Failed to release anonymous operation reservation %s", log_prefix, operation_id, exc_info=True)
        elif request_data.orchestration_id and directus_service:
            service = SubChatOrchestrationService(directus_service)
            for operation_id in uncharged_operation_ids:
                try:
                    await service.execute("fail_operation", {
                        "protocol_version": 1,
                        "operation_id": operation_id,
                        "orchestration_id": request_data.orchestration_id,
                        "hashed_user_id": request_data.user_id_hash,
                    })
                except Exception:
                    logger.error("%s Failed to release operation reservation %s", log_prefix, operation_id, exc_info=True)


def _convert_timestamps_to_human_readable(value: Any) -> Any:
    """
    Recursively converts Unix timestamps in app settings/memories data to human-readable date strings.
    
    CRITICAL: LLMs cannot reliably interpret raw Unix timestamps (e.g., 1768390180).
    They may hallucinate incorrect years, especially for dates outside their training data.
    Converting timestamps to human-readable format (e.g., "January 14, 2026") ensures
    the LLM correctly understands when settings/memories were created.
    
    Detects timestamps by:
    1. Looking for keys containing 'date', 'time', 'created', 'updated', 'added', '_at' (case-insensitive)
    2. Checking if the value is an integer in a reasonable Unix timestamp range (2010-2100)
    
    Args:
        value: The value to process (can be dict, list, or primitive)
    
    Returns:
        The processed value with timestamps converted to readable strings
    """
    # Define timestamp field name patterns (case-insensitive)
    TIMESTAMP_PATTERNS = ('date', 'time', 'created', 'updated', 'added', '_at')
    
    # Unix timestamp range: 2010-01-01 to 2100-01-01 (to avoid false positives)
    MIN_TIMESTAMP = 1262304000  # 2010-01-01 00:00:00 UTC
    MAX_TIMESTAMP = 4102444800  # 2100-01-01 00:00:00 UTC
    
    def is_likely_timestamp(key: str, val: Any) -> bool:
        """Check if a field is likely a Unix timestamp based on key name and value."""
        if not isinstance(val, (int, float)):
            return False
        key_lower = key.lower()
        # Check if key matches any timestamp pattern
        if any(pattern in key_lower for pattern in TIMESTAMP_PATTERNS):
            # Check if value is in valid Unix timestamp range
            return MIN_TIMESTAMP <= val <= MAX_TIMESTAMP
        return False
    
    def timestamp_to_readable(timestamp: int) -> str:
        """Convert Unix timestamp to human-readable date string."""
        try:
            dt = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
            # Format: "January 14, 2026" - clear and unambiguous
            return dt.strftime("%B %d, %Y")
        except Exception:
            # If conversion fails, return original value as string
            return str(timestamp)
    
    if isinstance(value, dict):
        processed = {}
        for k, v in value.items():
            if is_likely_timestamp(k, v):
                processed[k] = timestamp_to_readable(int(v))
            else:
                processed[k] = _convert_timestamps_to_human_readable(v)
        return processed
    elif isinstance(value, list):
        return [_convert_timestamps_to_human_readable(item) for item in value]
    else:
        return value


async def handle_main_processing(
    task_id: str,
    request_data: AskSkillRequest,
    preprocessing_results: PreprocessingResult,
    base_instructions: Dict[str, Any],
    directus_service: DirectusService,
    encryption_service: EncryptionService, # Added EncryptionService
    user_vault_key_id: Optional[str],
    all_mates_configs: List[MateConfig],
    discovered_apps_metadata: Dict[str, AppYAML],
    secrets_manager: Optional[SecretsManager] = None,
    cache_service: Optional[CacheService] = None,
    always_include_skills: Optional[List[str]] = None,  # Skills to ALWAYS include regardless of preprocessing
    user_overrides: Optional[UserOverrides] = None,  # User overrides from @mention syntax (for skip-permission logic)
    skill_config_dict: Optional[dict[str, Any]] = None,
) -> AsyncIterator[Union[str, MistralUsage, GoogleUsageMetadata, AnthropicUsageMetadata, OpenAIUsageMetadata]]:
    """
    Handles the main processing of an AI skill request after preprocessing.
    This function is an async generator, yielding chunks of the final assistant response.
    """
    log_prefix = f"[Celery Task ID: {task_id}, ChatID: {request_data.chat_id}] MainProcessor:"
    logger.info(f"{log_prefix} Starting main processing.")

    # Missing or forged child ancestry fails closed at maximum depth.
    chat_depth = resolve_sub_chat_depth(request_data)
    logger.info(
        "%s Resolved server sub-chat depth to %d (orchestration_id=%s)",
        log_prefix,
        chat_depth,
        request_data.orchestration_id,
    )
    
    # --- Auto-reject any pending app settings/memories request for this chat ---
    # If user sends a new message without responding to the permission dialog,
    # we auto-interpret this as a rejection of the previous request.
    # This ensures we only process the NEW message, not both.
    if cache_service:
        try:
            pending_context = await cache_service.get_pending_app_settings_memories_request(request_data.chat_id)
            if pending_context:
                old_request_id = pending_context.get("request_id", "unknown")
                old_message_id = pending_context.get("message_id", "unknown")
                logger.info(
                    f"{log_prefix} Found pending app settings/memories request {old_request_id} for message {old_message_id}. "
                    f"User sent new message - auto-rejecting previous request."
                )
                
                # Delete the pending context (auto-reject) and clean up per-user index
                await cache_service.delete_pending_app_settings_memories_request(request_data.chat_id, user_id=request_data.user_id)
                
                # Notify client to dismiss the permission dialog
                # Use Redis pub/sub to send to WebSocket
                try:
                    # Note: json is imported at module level, don't re-import locally as it shadows the global import
                    redis_client = await cache_service.client
                    if redis_client:
                        channel = f"user_cache_events:{request_data.user_id}"
                        pubsub_message = {
                            "event_type": "dismiss_app_settings_memories_dialog",
                            "payload": {
                                "chat_id": request_data.chat_id,
                                "request_id": old_request_id,
                                "reason": "new_message_sent",
                                "message_id": old_message_id  # The original message that triggered the request
                            }
                        }
                        await redis_client.publish(channel, json.dumps(pubsub_message))
                        logger.info(f"{log_prefix} Sent dismiss_app_settings_memories_dialog event to client")
                except Exception as e:
                    logger.warning(f"{log_prefix} Failed to notify client about auto-rejection: {e}")
        except Exception as e:
            logger.error(f"{log_prefix} Error checking/auto-rejecting pending request: {e}", exc_info=True)
    
    # --- Request app settings/memories from client (zero-knowledge architecture) ---
    # The server NEVER decrypts app settings/memories - client decrypts using crypto API
    # App settings/memories are stored in cache (similar to embeds) when client confirms
    # Cache key format: app_settings_memories:{user_id}:{app_id}:{item_key}
    # This is more efficient than extracting from YAML in chat history
    #
    # IMPORTANT: If app settings/memories are needed but not in cache:
    # - Server sends request to client via WebSocket
    # - Task COMPLETES immediately (no LLM processing)
    # - Client shows permission dialog to user
    # - Once user confirms/rejects, client sends data back
    # - On user's NEXT message, data is available in cache for LLM processing
    loaded_app_settings_and_memories_content: Dict[str, Any] = {}
    # Start with any cleartext the client sent for @memory/@memory-entry mentions (so we do not request those again)
    if getattr(request_data, "mentioned_settings_memories_cleartext", None):
        mentioned = request_data.mentioned_settings_memories_cleartext
        if isinstance(mentioned, dict) and mentioned:
            for key, value in mentioned.items():
                if (
                    isinstance(key, str)
                    and value is not None
                    and not is_removed_app_memory_key(key)
                ):
                    loaded_app_settings_and_memories_content[key] = value
            logger.info(f"{log_prefix} Pre-filled {len(mentioned)} app settings/memories from client-mentioned cleartext: {list(mentioned.keys())}")

    if preprocessing_results.load_app_settings_and_memories and cache_service:
        logger.debug(f"{log_prefix} Preprocessing requested app settings/memories: {preprocessing_results.load_app_settings_and_memories}")
        try:
            # Import helper function for creating requests
            from backend.core.api.app.utils.app_settings_memories_request import (
                create_app_settings_memories_request_message
            )
            
            requested_keys = [
                key
                for key in preprocessing_results.load_app_settings_and_memories
                if not is_removed_app_memory_key(key)
            ]
            # Include keys from client-mentioned cleartext so we have a full set; they are already in loaded_app_settings_and_memories_content
            if getattr(request_data, "mentioned_settings_memories_cleartext", None):
                mentioned = request_data.mentioned_settings_memories_cleartext
                if isinstance(mentioned, dict):
                    for key in mentioned:
                        if (
                            key not in requested_keys
                            and not is_removed_app_memory_key(key)
                        ):
                            requested_keys.append(key)
            
            # Check cache first (similar to how embeds are handled)
            # Cache stores vault-encrypted data that server can decrypt for AI processing
            # Chat-specific caching ensures app settings/memories are evicted with the chat
            cached_data = await cache_service.get_app_settings_memories_batch_from_cache(
                user_id=request_data.user_id,
                chat_id=request_data.chat_id,
                requested_keys=requested_keys
            )
            
            if cached_data:
                logger.info(f"{log_prefix} Found {len(cached_data)} app settings/memories entries in cache")
                
                # IMPORTANT: Decrypt the vault-encrypted content before passing to LLM
                # The cache stores: {"app_id": ..., "item_key": ..., "content": "<encrypted>", "cached_at": ...}
                # We need to decrypt "content" and pass only the decrypted content to the LLM
                for key, cache_entry in cached_data.items():
                    try:
                        encrypted_content = cache_entry.get("content")
                        if encrypted_content and user_vault_key_id and encryption_service:
                            # Decrypt the vault-encrypted content
                            decrypted_content = await encryption_service.decrypt_with_user_key(
                                ciphertext=encrypted_content,
                                key_id=user_vault_key_id
                            )
                            if decrypted_content:
                                # Try to parse as JSON (content might be serialized JSON)
                                try:
                                    parsed_content = json.loads(decrypted_content)
                                    loaded_app_settings_and_memories_content[key] = parsed_content
                                    content_type = type(parsed_content).__name__
                                    if isinstance(parsed_content, list):
                                        content_metadata = f"list_len={len(parsed_content)}"
                                    elif isinstance(parsed_content, dict):
                                        dict_keys = list(parsed_content.keys())
                                        content_metadata = f"dict_key_count={len(dict_keys)}"
                                    else:
                                        content_metadata = "scalar"
                                    logger.info(
                                        f"{log_prefix} Successfully decrypted app settings/memories for {key} "
                                        f"(type={content_type}, {content_metadata})"
                                    )
                                except json.JSONDecodeError:
                                    # If not JSON, use as plain string
                                    loaded_app_settings_and_memories_content[key] = decrypted_content
                                    logger.info(
                                        f"{log_prefix} Successfully decrypted app settings/memories for {key} "
                                        f"(type=str, length={len(decrypted_content)})"
                                    )
                            else:
                                logger.warning(f"{log_prefix} Failed to decrypt app settings/memories for {key}")
                        else:
                            # If no encryption service or vault key, log warning
                            logger.warning(f"{log_prefix} Cannot decrypt app settings/memories for {key} - missing encryption_service or user_vault_key_id")
                    except Exception as decrypt_error:
                        logger.error(f"{log_prefix} Error decrypting app settings/memories for {key}: {decrypt_error}", exc_info=True)
            
            # Check if we need to create a new request for missing keys.
            # Keys already in loaded_app_settings_and_memories_content (from client cleartext or cache) must not be requested again.
            missing_keys = [
                key for key in requested_keys
                if key not in loaded_app_settings_and_memories_content
            ]

            if missing_keys and getattr(request_data, "is_app_settings_memories_continuation", False):
                # This is a continuation task (user already confirmed/rejected the original request).
                # Do NOT issue another permission dialog — the user's decision was already recorded.
                # Proceed without the missing data instead.
                logger.info(
                    f"{log_prefix} Continuation task: skipping new permission request for "
                    f"{len(missing_keys)} missing keys {missing_keys} — user already responded to the original request. "
                    f"Proceeding without these keys."
                )
                missing_keys = []

            if missing_keys:
                logger.info(f"{log_prefix} Creating new app settings/memories request for {len(missing_keys)} missing keys")
                # Create new system message request in chat history
                # Client will encrypt with chat key and store it
                # When user confirms, client will send app settings/memories as separate data (like embeds)
                # and server will store them in cache for future use
                request_id = await create_app_settings_memories_request_message(
                    chat_id=request_data.chat_id,
                    requested_keys=missing_keys,
                    cache_service=cache_service,
                    connection_manager=None,  # Celery tasks run in separate processes, can't access WebSocket manager directly
                    user_id=request_data.user_id,
                    device_fingerprint_hash=None,  # Will use first available device connection
                    message_id=request_data.message_id  # User message that triggered this request (for UI display)
                )
                
                if request_id:
                    logger.info(f"{log_prefix} Created app settings/memories request {request_id} - storing pending context and returning")
                    # IMPORTANT: Store the pending request context so we can re-trigger processing
                    # when user confirms or rejects. The confirmation/rejection acts as a trigger
                    # for a NEW AI processing pass - not a continuation of this task.
                    #
                    # Flow:
                    # 1. This task completes (no LLM response)
                    # 2. Client shows permission dialog
                    # 3. User confirms/rejects (could be seconds or hours later)
                    # 4. Server receives confirmation → triggers NEW ask_skill task
                    # 5. New task finds data in cache (if confirmed) → normal LLM response
                    #
                    # NOTE: We only store minimal context here - NOT the message_history!
                    # The chat history is already cached on the server (recent chat).
                    # When continuing, we retrieve the chat from cache.
                    try:
                        # Store MINIMAL context needed to re-trigger processing
                        # Do NOT store message_history - it's already in the chat cache
                        pending_context = _build_pending_app_settings_memories_context(
                            request_data=request_data,
                            request_id=request_id,
                            missing_keys=missing_keys,
                            task_id=task_id,
                        )
                        await cache_service.store_pending_app_settings_memories_request(
                            chat_id=request_data.chat_id,
                            context=pending_context,
                            ttl=86400 * 7  # 7 days - user can confirm/reject within a week
                        )
                        logger.info(f"{log_prefix} Stored pending context for request {request_id}")
                    except Exception as e:
                        logger.error(f"{log_prefix} Failed to store pending context: {e}", exc_info=True)
                        # Continue without storing - user will need to send a new message
                    
                    # CRITICAL: Yield a special marker to signal that we're awaiting user permission.
                    # The stream_consumer.py will detect this marker and NOT send an error message.
                    # Without this marker, the empty stream would be treated as an error.
                    yield {"__awaiting_app_settings_memories_permission__": True, "request_id": request_id}
                    
                    # Return early - task complete, no LLM response
                    return
                else:
                    logger.warning(f"{log_prefix} Failed to create app settings/memories request message - continuing without app settings/memories")
            else:
                logger.info(f"{log_prefix} All requested app settings/memories keys found in cache")
            
        except Exception as e:
            logger.error(f"{log_prefix} Error handling app settings/memories requests: {e}", exc_info=True)
            # Continue without app settings/memories - don't fail the entire request

    # Validate and apply final model guard before prompt construction so the
    # creator/model instruction and actual inference model cannot diverge.
    if not preprocessing_results.selected_main_llm_model_id:
        error_msg = (
            f"{log_prefix} Cannot proceed with main processing: selected_main_llm_model_id is None. "
            f"This usually indicates preprocessing failed (rejection_reason: {preprocessing_results.rejection_reason}). "
            f"Main processing requires a valid model_id."
        )
        logger.error(error_msg)
        raise ValueError(error_msg)

    if (
        preprocessing_results.relevant_app_skills
        and "images-view" in preprocessing_results.relevant_app_skills
        and preprocessing_results.selected_main_llm_model_id.startswith("google/")
    ):
        logger.warning(
            f"{log_prefix} IMAGE_MODEL_GUARD: Final safety reroute from "
            f"'{preprocessing_results.selected_main_llm_model_id}' to '{IMAGE_CHAT_SAFE_MODEL_ID}' "
            f"because images-view is preselected."
        )
        preprocessing_results.selected_main_llm_model_id = IMAGE_CHAT_SAFE_MODEL_ID
        preprocessing_results.selected_main_llm_model_name = IMAGE_CHAT_SAFE_MODEL_NAME
        preprocessing_results.selected_main_llm_thinking_level = None
        preprocessing_results.selected_secondary_model_id = None

    wikipedia_reference_context = ""
    wikipedia_references = getattr(user_overrides, "wikipedia_references", None) or []
    if wikipedia_references:
        try:
            prepared_wikipedia_references = await resolve_wikipedia_reference_context(
                wikipedia_references,
                task_id=task_id,
                secrets_manager=secrets_manager,
                cache_service=cache_service,
            )
            wikipedia_reference_context = format_wikipedia_reference_context(prepared_wikipedia_references)
        except WikipediaSafetyUnavailableError as exc:
            logger.warning("%s Wikipedia reference rejected before inference: %s", log_prefix, exc)
            yield {
                WIKIPEDIA_CONTEXT_UNAVAILABLE_MARKER: True,
                "rejection_reason": WIKIPEDIA_CONTEXT_UNAVAILABLE_REJECTION_REASON,
                "message": WIKIPEDIA_CONTEXT_UNAVAILABLE_MESSAGE,
            }
            return
        except Exception as exc:
            logger.warning("%s Wikipedia reference unavailable before inference: %s", log_prefix, exc, exc_info=True)
            yield {
                WIKIPEDIA_CONTEXT_UNAVAILABLE_MARKER: True,
                "rejection_reason": WIKIPEDIA_CONTEXT_UNAVAILABLE_REJECTION_REASON,
                "message": WIKIPEDIA_CONTEXT_UNAVAILABLE_MESSAGE,
            }
            return

    # Keep shared, time-independent rules first so provider prompt caches can
    # reuse them across turns. The clock and private artifact context follow.
    stable_prefix_parts = [
        base_instructions.get("base_ethics_instruction", ""),
        base_instructions.get("follow_up_instruction", ""),
        base_instructions.get("base_link_encouragement_instruction", ""),
        base_instructions.get("base_wikipedia_linking_instruction", ""),
        base_instructions.get("base_url_sourcing_instruction", ""),
        base_instructions.get("base_code_block_instruction", ""),
        base_instructions.get("base_document_generation_instruction", ""),
    ]
    cacheable_system_prefix = "\n\n".join(filter(None, stable_prefix_parts))
    prompt_parts = [*filter(None, stable_prefix_parts)]
    # Explicit research/dispatch requirements apply to the tool phase. Keep all
    # safety, focus, output-format and user constraints in the synthesis prompt.
    research_only_prompt_parts: set[str] = set()
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    if request_data.historical_artifact_context:
        prompt_parts.append(request_data.historical_artifact_context)
        logger.info(
            "%s Injected bounded historical artifact context (%d chars)",
            log_prefix,
            len(request_data.historical_artifact_context),
        )

    # Resolve user's timezone — fall back to UTC if not set or unrecognised
    user_timezone = request_data.user_preferences.get("timezone") if request_data.user_preferences else None
    try:
        user_tz = zoneinfo.ZoneInfo(user_timezone) if user_timezone else datetime.timezone.utc
    except (zoneinfo.ZoneInfoNotFoundError, KeyError):
        logger.warning(f"Unrecognised timezone '{user_timezone}', falling back to UTC")
        user_tz = datetime.timezone.utc
        user_timezone = None  # Don't include an invalid tz name in the prompt

    # Convert current time to user's local timezone so the LLM works in local time directly
    now_local = now_utc.astimezone(user_tz)
    date_time_str = now_local.strftime("%Y-%m-%d %H:%M:%S %Z")

    if user_timezone:
        # Include both local time and timezone name so the LLM never needs to convert
        clock_instruction = (
            f"Current date and time (in user's timezone): {date_time_str}\n"
            f"User's timezone: {user_timezone}"
        )
    else:
        # No timezone info — fall back to UTC and note it
        date_time_str_utc = now_utc.strftime("%Y-%m-%d %H:%M:%S %Z")
        clock_instruction = f"Current date and time: {date_time_str_utc} (user timezone unknown)"
    prompt_parts.append(clock_instruction)
    # Add temporal awareness instruction right after the date to emphasize its importance
    # This ensures the LLM properly filters past vs future events based on the current date
    prompt_parts.append(base_instructions.get("base_temporal_awareness_instruction", ""))
    ai_model_topics = getattr(preprocessing_results, "ai_model_topics", None) or []
    if ai_model_topics:
        model_catalogue_context = build_ai_model_catalogue_context(
            config_manager.get_provider_configs(),
            ai_model_topics,
            today=now_utc.date(),
        )
        if model_catalogue_context:
            prompt_parts.append(model_catalogue_context)
    selected_mate_config = next((mate for mate in all_mates_configs if mate.id == preprocessing_results.selected_mate_id), None)
    learning_mode_context = getattr(request_data, "learning_mode", None) or {}
    learning_mode_active = is_learning_mode_enabled(learning_mode_context)
    if selected_mate_config:
        if learning_mode_active:
            prompt_parts.append(selected_mate_config.learning_mode_system_prompt)
        else:
            prompt_parts.append(selected_mate_config.default_system_prompt)
        # Furry Mode prompt styling is disabled until any furry art is made by human artists.
    # Insert creator_and_used_model_instruction right after the mate-specific prompt
    # This informs the user who created the assistant and which model (name and id) powers the response.
    try:
        creator_and_model_instruction_template = base_instructions.get("creator_and_used_model_instruction")
        if creator_and_model_instruction_template:
            # Prefer the model name from preprocessing; fall back to suffix of the model id or a generic label
            selected_model_id: str = preprocessing_results.selected_main_llm_model_id or ""
            # If model name is missing, use the id's suffix (after provider prefix) as a reasonable display name
            derived_model_name: str = (
                preprocessing_results.selected_main_llm_model_name
                or (selected_model_id.split("/", 1)[-1] if selected_model_id else "")
            )

            filled_instruction = creator_and_model_instruction_template.format(
                MODEL_NAME=derived_model_name,
                MODEL_ID=selected_model_id,
            )
            prompt_parts.append(filled_instruction)
            logger.debug(
                f"{log_prefix} Added creator_and_used_model_instruction with model_name='{derived_model_name}', model_id='{selected_model_id}'."
            )
        else:
            logger.debug(f"{log_prefix} Base instructions missing 'creator_and_used_model_instruction'; skipping injection.")
    except Exception as e:
        # Robust error handling to ensure prompt construction never fails because of formatting issues
        logger.error(
            f"{log_prefix} Failed to inject creator_and_used_model_instruction: {e}",
            exc_info=True,
        )
    # TODO: Update this key once app use is implemented - currently using base_capabilities_instruction
    # which explains what the chatbot can and cannot do yet
    # Inject available apps list into capabilities instruction
    base_capabilities_instruction_template = base_instructions.get("base_capabilities_instruction", "")
    if base_capabilities_instruction_template:
        # Extract available app IDs from discovered_apps_metadata
        available_app_ids = sorted(list(discovered_apps_metadata.keys())) if discovered_apps_metadata else []
        available_apps_str = ", ".join(available_app_ids) if available_app_ids else "none (no apps available)"
        
        # Replace placeholder with actual available apps list
        filled_capabilities_instruction = base_capabilities_instruction_template.replace(
            "{AVAILABLE_APPS}",
            available_apps_str
        )
        prompt_parts.append(filled_capabilities_instruction)
        logger.info(
            f"{log_prefix} Injected available apps list into system prompt: {available_apps_str} "
            f"({len(available_app_ids)} app(s) available)"
        )
    else:
        logger.warning(f"{log_prefix} base_capabilities_instruction not found in base_instructions.yml")
    
    wikipedia_language = normalize_wikipedia_language((request_data.user_preferences or {}).get("language"))
    prompt_parts.append(
        f"For all `wiki:` inline links, use article titles from {wikipedia_language}.wikipedia.org "
        f"only. Do not use English Wikipedia titles unless the user's UI language is English."
    )
    if wikipedia_reference_context:
        prompt_parts.append(wikipedia_reference_context)
     
    # Add app deep linking instruction so the AI uses correct relative hash links
    # Only include when apps are available (no point linking to apps that don't exist)
    selected_app_ids = getattr(preprocessing_results, "selected_app_ids", None)
    selected_app_ids = set(selected_app_ids) if selected_app_ids is not None else None
    if discovered_apps_metadata and (request_data.user_preferences or {}).get("apps_enabled") is not False:
        prompt_parts.append(base_instructions.get("base_app_deep_linking_instruction", ""))
    
    # Add settings/memories deep link instruction so the AI can suggest creating/updating
    # entries inline in its response. Only include when apps are available (the AI needs
    # to know the category IDs and field names). The instruction is always-on for simplicity;
    # the AI will only generate links when the conversation actually reveals preferences.
    if discovered_apps_metadata:
        settings_deep_link_instruction = base_instructions.get("base_settings_memories_deep_link_instruction", "")
        if settings_deep_link_instruction:
            prompt_parts.append(settings_deep_link_instruction)
    
    # === BUILD PRESELECTED SKILLS SET ===
    # Build this BEFORE the instruction injection block so we can filter app instructions
    # by whether their skills are preselected. Also used later for tool generation.
    preselected_skills = None
    if hasattr(preprocessing_results, 'relevant_app_skills'):
        if preprocessing_results.relevant_app_skills is not None:
            preselected_skills = set(preprocessing_results.relevant_app_skills)
            if preselected_skills:
                logger.debug(f"{log_prefix} Using preselected skills from preprocessing: {preselected_skills}")
            else:
                logger.debug(f"{log_prefix} No skills preselected by preprocessing (empty list)")
        else:
            logger.warning(f"{log_prefix} relevant_app_skills is None (should be list or empty list). Treating as empty list.")
            preselected_skills = set()

    # HARDENING: Merge always_include_skills into preselected_skills unless the user
    # explicitly requested a specific tool/search surface. In that case use only the
    # user's selection and add a mandatory instruction to call it.
    user_requested_skills_only = getattr(preprocessing_results, "user_requested_skills_only", False)
    override_skills = getattr(user_overrides, "skills", None)
    task_app_skill_mentions = task_app_skill_ids_from_user_override_skills(override_skills)
    task_app_skill_mentions |= task_app_skill_ids_from_message_text(request_data.current_user_content)
    if task_app_skill_mentions:
        if preselected_skills is None:
            preselected_skills = set()
        preselected_skills = preselected_skills | task_app_skill_mentions
        user_requested_skills_only = True
        logger.info(
            "%s [USER_SKILLS] Forced explicit Tasks app skill mention(s) into preselected skills: %s",
            log_prefix,
            sorted(task_app_skill_mentions),
        )
    if user_requested_skills_only and preselected_skills:
        logger.info(
            f"{log_prefix} [USER_SKILLS] User explicitly requested skill(s); not merging always_include_skills. "
            f"Preselected only: {preselected_skills}"
        )
    elif always_include_skills:
        if preselected_skills is None:
            preselected_skills = set()
        # An app chosen by stage one may keep its configured helper skills.
        # Uploaded images still need their viewer even when no app was chosen.
        scoped_always_include = {
            skill for skill in always_include_skills
            if selected_app_ids is None
            or any(skill.startswith(f"{app_id}-") for app_id in selected_app_ids)
            or (skill == "images-view" and getattr(request_data, "has_image_upload_embed", False))
        }
        skills_to_add = scoped_always_include - preselected_skills
        if skills_to_add:
            logger.info(
                f"{log_prefix} [SKILL_HARDENING] Adding always-include skills to preselected set: {skills_to_add}. "
                "These helper skills belong to apps selected for this turn."
            )
        preselected_skills = preselected_skills | scoped_always_include
        logger.debug(f"{log_prefix} Final preselected skills (after merging always-include): {preselected_skills}")

    # === COMPANION SKILLS ===
    # Some skills naturally pair together — when the system prompt instructs the
    # LLM to consider a companion skill, it must also be in the allowed tool set.
    # Without this the LLM follows the instruction, calls the companion, and the
    # hallucination guard rejects it → zero response. Explicit requests stay exact.
    if preselected_skills:
        expanded_preselected_skills = expand_companion_skills(
            preselected_skills,
            exact_request=user_requested_skills_only,
        )
        if selected_app_ids is not None:
            expanded_preselected_skills = preselected_skills | {
                skill for skill in expanded_preselected_skills
                if any(skill.startswith(f"{app_id}-") for app_id in selected_app_ids)
            }
        companions_to_add = expanded_preselected_skills - preselected_skills
        if companions_to_add:
            logger.info(
                f"{log_prefix} [COMPANION_SKILLS] Auto-including companion skills: "
                f"{sorted(companions_to_add)} (triggered by preselected skills)"
            )
            preselected_skills = expanded_preselected_skills

    clarification_skills = workflow_clarification_skill_scope(
        active_focus_id=request_data.active_focus_id,
        relevant_focus_modes=getattr(preprocessing_results, "relevant_focus_modes", []) or [],
        explicit_focus_mention=getattr(preprocessing_results, "user_requested_focus_only", False),
    )
    if clarification_skills is not None:
        preselected_skills = clarification_skills
        # The search verb describes the future workflow, not a request to use
        # an Events/News search tool in the clarification chat now.
        user_requested_skills_only = False
    if preselected_skills and "workflows-create-or-modify" in preselected_skills:
        prompt_parts.append(WORKFLOW_AUTHORING_TOOL_INSTRUCTION)

    task_tool_context = None
    task_context_prompt = ""
    task_tools_enabled = "task_update_jobs" in (getattr(request_data, "client_capabilities", None) or [])
    project_capabilities = getattr(request_data, "client_capabilities", None) or []
    project_file_tools_enabled = (
        "project_file_jobs" in project_capabilities
        and not request_data.is_incognito
        and cache_service is not None
    )
    from backend.apps.ai.processing.focus_phases import (
        FocusPhaseRuntime, restore_state, phase_prompt, parse_project_phase_focus,
        invalidate_phase_runtime, reselect_phase_tools,
    )
    focus_phase_runtimes = []
    project_phase_prompt_section = None
    phase_state_in = getattr(request_data, "focus_phase_state", None) or {}
    phase_redis = await cache_service.client if cache_service else None
    active_project_focus = None
    active_project_sources: list[dict[str, Any]] = []
    # Focus instructions remain active even when the current client cannot
    # execute files. Execution capability controls tools, never focus semantics.
    if not request_data.is_incognito and cache_service is not None:
        try:
            from backend.core.api.app.services.project_write_authorization_service import (
                ProjectWriteAuthorizationService,
            )

            active_project_focus = await ProjectWriteAuthorizationService(
                directus_service, cache_service
            ).get_active_focus(user_id=request_data.user_id, chat_id=request_data.chat_id)
        except Exception:
            logger.warning("%s Project focus authorization failed closed", log_prefix, exc_info=True)
            active_project_focus = None
    if active_project_focus:
        try:
            from backend.core.api.app.services.project_remote_access_service import (
                ProjectRemoteAccessError,
                ProjectRemoteAccessService,
            )

            source_rows = await directus_service.project.list_sources(
                active_project_focus["project_id"],
                request_data.user_id,
                team_id=active_project_focus.get("team_id"),
            )
            connected_source_ids: set[str] = set()
            remote_access = ProjectRemoteAccessService(cache_service)
            for source in source_rows:
                source_id = source.get("source_id")
                if source.get("status") == "revoked" or not isinstance(source_id, str) or not source_id:
                    continue
                try:
                    await remote_access.get_active_binding(
                        request_data.user_id,
                        active_project_focus["project_id"],
                        source_id,
                        team_id=active_project_focus.get("team_id"),
                        now=int(time.time()),
                    )
                    connected_source_ids.add(source_id)
                except ProjectRemoteAccessError:
                    pass
            active_project_sources = build_project_source_routing_context(
                source_rows,
                connected_source_ids=connected_source_ids,
            )
        except Exception:
            logger.warning("%s Project source discovery failed closed", log_prefix, exc_info=True)
            active_project_sources = []
    request_data.active_project_focus = active_project_focus
    request_data.current_project = (
        {
            **{
                key: active_project_focus.get(key)
                for key in ("project_id", "project_id_hash", "team_id", "team_id_hash")
            },
            "sources": active_project_sources,
        }
        if active_project_focus
        else None
    )
    reference_preview = getattr(request_data, "project_file_reference_preview", None)
    if reference_preview is not None:
        # A continuation may publish only the result of its freshly authorized
        # Project. Consume this transient hint once before the answer model runs.
        request_data.project_file_reference_preview = None
        if (not isinstance(reference_preview, dict) or not active_project_focus
                or reference_preview.get("project_id") != active_project_focus.get("project_id")):
            raise RequiredRecoveryOutputError("Project file reference focus changed before publication")
        from backend.apps.ai.processing.project_file_references import (
            publish_project_file_reference_preview,
        )

        reference = await publish_project_file_reference_preview(
            preview=reference_preview, request_data=request_data,
            cache_service=cache_service, directus_service=directus_service,
            encryption_service=encryption_service, user_vault_key_id=user_vault_key_id,
            task_id=task_id, log_prefix=log_prefix,
        )
        if not reference:
            raise RequiredRecoveryOutputError("Project file reference was not published")
        # Only originals are file artifacts for this completion. Interpret the
        # bytes as temporary context; the consumer must not turn a model's
        # quoted source into a new code/document embed.
        yield {"__project_file_reference_output__": True}
        preprocessing_results.relevant_embedded_previews = []
        prompt_parts.append(
            "A reference-only Project file card has already been published. "
            "Use the completed file results to answer the request and refer to this card to open the original. "
            "Do not reproduce the original file in code fences, YAML, document/image embeds, or any new chat file artifact. "
            f"Published reference card: {reference}"
        )
        yield f"```json\n{reference}\n```\n\n"
    project_reference_setup_last = time.monotonic() if reference_preview is not None else None

    def mark_project_reference_setup(stage: str) -> None:
        nonlocal project_reference_setup_last
        if project_reference_setup_last is None:
            return
        now = time.monotonic()
        logger.info(
            "%s [PROJECT_REF_SETUP] stage=%s elapsed_ms=%.1f",
            log_prefix, stage, (now - project_reference_setup_last) * 1000,
        )
        project_reference_setup_last = now

    if active_project_focus:
        project_instruction_focus = parse_project_phase_focus(
            active_project_focus.get("instruction") or "", active_project_focus["focus_id"])
        effective_project_focus = dict(active_project_focus)
        if project_instruction_focus:
            project_runtime = FocusPhaseRuntime(project_instruction_focus,
                restore_state(project_instruction_focus, focus_id=active_project_focus["focus_id"],
                    chat_id=request_data.chat_id, saved=phase_state_in.get(active_project_focus["focus_id"])),
                redis=phase_redis, owner_id=request_data.user_id)
            await project_runtime.load()
            focus_phase_runtimes.append(project_runtime)
            effective_project_focus["instruction"] = phase_prompt(project_instruction_focus, project_runtime.state)
        project_phase_prompt_section = build_project_focus_prompt(effective_project_focus, active_project_sources)
        prompt_parts.append(project_phase_prompt_section)
    mark_project_reference_setup("project_focus")
    suppress_task_runtime_tools = should_suppress_task_runtime_tools_for_app_skill(
        preselected_skills,
        user_requested_skills_only=user_requested_skills_only,
    )
    if suppress_task_runtime_tools:
        logger.info(
            "%s [USER_SKILLS] Suppressing legacy task runtime tools because a Tasks app skill was explicitly requested.",
            log_prefix,
        )
    if task_tools_enabled and not request_data.is_incognito and not suppress_task_runtime_tools:
        task_methods = getattr(directus_service, "user_task", None)
        if task_methods is not None:
            try:
                task_tool_context = await resolve_task_tool_context(
                    task_methods=task_methods,
                    user_id=request_data.user_id,
                    chat_id=request_data.chat_id,
                    message_text=request_data.current_user_content,
                    team_id=getattr(request_data, "team_id", None),
                )
                task_context_prompt = build_task_context_prompt(task_tool_context)
                logger.info(
                    "%s Resolved task tool context: %s attached, %s referenced, %s hidden/missing mentions",
                    log_prefix,
                    len(task_tool_context.attached_tasks),
                    len(task_tool_context.referenced_tasks),
                    len(task_tool_context.missing_reference_ids),
                )
            except Exception:
                logger.error("%s Failed to resolve task tool context", log_prefix, exc_info=True)

    mark_project_reference_setup("task_context")
    task_queue_blocks_plan_tools = task_context_blocks_plan_creation(task_tool_context)
    preselected_skills, removed_plan_skills = filter_plan_skills_for_task_queue(
        preselected_skills,
        task_tool_context,
    )
    if removed_plan_skills:
        logger.info(
            "%s [TASK_QUEUE_PLAN_GUARD] Removed plan skill(s) while chat tasks remain: %s",
            log_prefix,
            sorted(removed_plan_skills),
        )
    if task_queue_blocks_plan_tools:
        prompt_parts.append(
            "Open chat tasks remain. Continue or explicitly block/complete those tasks before creating or switching to a plan."
        )

    # When user explicitly requested skills, add a mandatory instruction so the model must use them
    if user_requested_skills_only and preselected_skills:
        mandatory_skills_list = ", ".join(sorted(preselected_skills))
        mandatory_instruction = (
            f"The user explicitly requested that you use the following tool(s) for this request; "
            f"you MUST call at least one of them: {mandatory_skills_list}. Do not use other tools unless the user's request clearly requires them."
        )
        prompt_parts.append(mandatory_instruction)
        research_only_prompt_parts.add(mandatory_instruction)
        logger.info(f"{log_prefix} [USER_SKILLS] Added mandatory skill instruction for: {mandatory_skills_list}")

    # === DYNAMIC APP-SPECIFIC INSTRUCTIONS ===
    # Load instructions from each available app's app.yml configuration.
    # Instructions are ONLY included when at least one skill from the app is preselected
    # (or the app has no skills, e.g. purely instructional apps).
    # This prevents the AI from seeing references to tools it can't call in this turn,
    # which would cause tool name hallucination (e.g., calling 'images' when images-generate
    # wasn't preselected as a tool).
    app_instructions_added = []
    app_instructions_skipped = []
    if discovered_apps_metadata:
        # Get the conversation category from preprocessing for category-filtered instructions
        conversation_category = preprocessing_results.category if preprocessing_results else None

        # Build normalized set of relevant embed preview types from preprocessing.
        # The preprocessor uses freeform strings (e.g., 'email', 'document') that may
        # differ from app embed type IDs (e.g., 'email', 'doc'). The normalization map
        # bridges cases where the preprocessor string differs from the app.yml ID.
        relevant_previews = set()
        if preprocessing_results and preprocessing_results.relevant_embedded_previews:
            relevant_previews = set(preprocessing_results.relevant_embedded_previews)
        PREVIEW_TO_EMBED_TYPE = {
            "document": "doc",
            "pcb_schematic": "schematic",
            "pcb-schematic": "schematic",
        }
        normalized_previews = set()
        for p in relevant_previews:
            normalized_previews.add(p)
            if p in PREVIEW_TO_EMBED_TYPE:
                normalized_previews.add(PREVIEW_TO_EMBED_TYPE[p])

        workflow_presentation_only = (request_data.user_preferences or {}).get("workflow_ai") is True
        workflow_known_sources = {
            source for source in (request_data.user_preferences or {}).get("workflow_presentation_sources", [])
            if isinstance(source, str) and "-" in source
        } if workflow_presentation_only else set()
        if workflow_presentation_only:
            normalized_previews.update(
                source.split("-", 1)[1] for source in workflow_known_sources
            )

        for app_id, app_metadata in discovered_apps_metadata.items():
            if not app_metadata.instructions:
                continue

            # Check if this app has any skills preselected for this turn.
            app_has_preselected_skill = False
            if app_metadata.skills and preselected_skills:
                app_has_preselected_skill = any(
                    f"{app_id}-{skill.id}" in preselected_skills
                    for skill in app_metadata.skills
                )

            for instruction_def in app_metadata.instructions:
                if workflow_presentation_only and (
                    not instruction_def.for_embed_types
                    or not any(source.startswith(f"{app_id}-") for source in workflow_known_sources)
                ):
                    # Search instructions may direct the model to invoke a skill.
                    # Workflow Ask may reuse presentation guidance only.
                    continue
                # Instructions with for_embed_types bypass skill preselection gating.
                # They are injected when the preprocessor identified any matching embed
                # preview type as relevant (e.g., email drafting format instructions
                # triggered by relevant_embedded_previews: ['email']).
                if instruction_def.for_embed_types:
                    if not (set(instruction_def.for_embed_types) & normalized_previews):
                        continue
                    # Embed-type match — skip skill preselection, fall through to category check
                else:
                    # Stage one chose the apps whose ordinary instructions can
                    # enter this turn. An empty skill set no longer means all apps.
                    if selected_app_ids is not None and app_id not in selected_app_ids:
                        continue
                    if (app_metadata.skills and not app_has_preselected_skill
                            and (selected_app_ids is not None or preselected_skills)):
                        continue

                # Check if instruction has category filtering
                if instruction_def.categories:
                    # Only include if conversation category matches
                    if conversation_category and conversation_category in instruction_def.categories:
                        prompt_parts.append(instruction_def.instruction)
                        app_instructions_added.append(f"{app_id} (category: {conversation_category})")
                    # Skip if categories specified but don't match
                else:
                    prompt_parts.append(instruction_def.instruction)
                    app_instructions_added.append(app_id)

            # Track skipped apps (only if ALL instructions were gated out)
            if app_metadata.skills and preselected_skills and not app_has_preselected_skill:
                if not any(inst.for_embed_types for inst in app_metadata.instructions):
                    app_instructions_skipped.append(app_id)
        
        if app_instructions_added:
            logger.info(f"{log_prefix} [APP_INSTRUCTIONS] Loaded instructions from apps: {', '.join(app_instructions_added)}")
        else:
            logger.debug(f"{log_prefix} [APP_INSTRUCTIONS] No app-specific instructions to load (apps: {list(discovered_apps_metadata.keys())})")
        if app_instructions_skipped:
            logger.debug(f"{log_prefix} [APP_INSTRUCTIONS] Skipped instructions for apps without preselected skills: {', '.join(app_instructions_skipped)}")
    else:
        logger.warning(f"{log_prefix} [APP_INSTRUCTIONS] No discovered apps - app-specific instructions unavailable")
    
    # === IMAGE CONTENT SAFETY INSTRUCTION ===
    # Conditionally inject prompt-injection defence for image uploads.
    # Only included when the images-view skill is preselected by the preprocessor,
    # so conversations without images pay zero extra tokens for this instruction.
    if preselected_skills and "images-view" in preselected_skills:
        image_safety_instruction = base_instructions.get("base_image_content_safety_instruction", "")
        if image_safety_instruction:
            prompt_parts.append(image_safety_instruction)
            logger.info(f"{log_prefix} [IMAGE_SAFETY] Injected image content safety instruction (images-view is preselected)")
    
    # === TOOL-CALLING THINKING DISCIPLINE ===
    # Prevents reasoning models (e.g., Gemini Flash) from hallucinating about tool
    # output in their thinking phase before the tool returns. Only injected when
    # skills are preselected, so conversations without tool use pay zero tokens.
    if preselected_skills:
        thinking_discipline = base_instructions.get("base_tool_thinking_discipline_instruction", "")
        if thinking_discipline:
            prompt_parts.append(thinking_discipline)
            logger.debug(f"{log_prefix} [THINKING_DISCIPLINE] Injected tool-calling thinking discipline instruction")
    
    # Add generic proactive skill usage instruction (only when apps are available)
    # This encourages using available skills proactively for time-sensitive queries
    if discovered_apps_metadata and (request_data.user_preferences or {}).get("apps_enabled") is not False:
        proactive_skill_instruction = base_instructions.get("base_proactive_skill_usage_instruction", "")
        prompt_parts.append(proactive_skill_instruction)
        research_only_prompt_parts.add(proactive_skill_instruction)
    else:
        # When no apps available, skip the proactive skill usage instruction
        # to avoid confusing the AI about capabilities it doesn't have
        logger.info(f"{log_prefix} Skipping base_proactive_skill_usage_instruction - no apps available")
    
    if ai_model_topics:
        prompt_parts.append(
            "AI model accuracy: The dated catalogue snapshot above is the anchor for recent "
            "OpenMates-supported models and their core capabilities. Do not center older models "
            "in a current comparison unless the user explicitly asks about them. "
            "For current subscription prices, included usage, quotas, or claimed changes, "
            "search the official provider help, pricing, or announcement pages and cite those "
            "primary sources. Search those provider domains directly; third-party summaries "
            "and user assertions are not confirmation. If official evidence is unavailable, "
            "say what is unverified and avoid exact usage figures or change claims."
        )

    # === EMBED INSTRUCTION GATING ===
    # Scan message history once to determine which embed types exist in the conversation.
    # This prevents the LLM from seeing (and misusing) embed syntax when no embed results
    # are present. Without this guard, the LLM can hallucinate embed reference syntax —
    # e.g. fabricating > [quote](embed:web-result-1) blocks — even when no web search was run.
    # See docs/architecture/embed-prompt-gating.md (issue c35ac944).
    #
    # Composite skills that produce embed_refs the LLM can reference inline or as cards.
    # Format must match preselected_skills entries: "app_id-skill_id".
    _EMBED_PRODUCING_PRESELECTED_IDS = {
        "web-search", "news-search", "videos-search",
        "maps-search", "events-search",
        "travel-search_connections", "travel-search_stays",
        "shopping-search_products",
        "social_media-search", "social_media-get-posts",
        "web-read",  # Non-composite single-result skills also produce embed_refs
    }
    # Subset whose results contain quotable text (web/news search results with
    # title/description/snippets that the source-quote verification can check against):
    _QUOTABLE_PRESELECTED_IDS = {"web-search", "news-search", "web-read"}
    _workflow_presentation_sources = set(
        source for source in (request_data.user_preferences or {}).get("workflow_presentation_sources", [])
        if isinstance(source, str) and source in _EMBED_PRODUCING_PRESELECTED_IDS
    )

    # Determine whether embeds already exist in chat history (from prior turns).
    # Uses the same lightweight substring checks as the preprocessor's skill-forcing logic.
    _has_any_embeds_in_history = False
    _has_quotable_embeds_in_history = False
    _embed_history_texts: List[str] = []
    for _msg in request_data.message_history:
        _msg_content = _msg.content if hasattr(_msg, "content") else (
            _msg.get("content") if isinstance(_msg, dict) else None
        )
        if not isinstance(_msg_content, str):
            continue
        _embed_history_texts.append(_msg_content)
        # Any TOON block with an embed_ref field indicates embed results from a previous turn
        if not _has_any_embeds_in_history and "embed_ref:" in _msg_content:
            _has_any_embeds_in_history = True
        # Quotable embeds: web/news search results and web.read results contain
        # text-heavy content (title/description/snippets/markdown) worth quoting.
        # We check for embed_ref alongside app_id/skill_id markers in TOON content.
        if not _has_quotable_embeds_in_history and "embed_ref:" in _msg_content and (
            ("app_id: web" in _msg_content and "skill_id: search" in _msg_content) or
            ("app_id: news" in _msg_content and "skill_id: search" in _msg_content) or
            ("app_id: web" in _msg_content and "skill_id: read" in _msg_content)
        ):
            _has_quotable_embeds_in_history = True
    # Determine whether the current turn is about to produce embeds.
    # If a composite skill is preselected, the LLM will receive embed_ref slugs in tool results.
    _current_turn_produces_embeds = bool(
        preselected_skills and preselected_skills & _EMBED_PRODUCING_PRESELECTED_IDS
    )
    # If a quotable skill is preselected, the LLM will receive source_quote_hint in tool results.
    _current_turn_produces_quotable_embeds = bool(
        preselected_skills and preselected_skills & _QUOTABLE_PRESELECTED_IDS
    )

    # Inject inline/preview embed instruction only when the LLM will actually have embed_refs
    # to reference — either from history or from skills running this turn.
    _include_embed_referencing = _has_any_embeds_in_history or _current_turn_produces_embeds or bool(_workflow_presentation_sources)
    if _include_embed_referencing:
        prompt_parts.append(base_instructions.get("base_embed_referencing_instruction", ""))
        logger.debug(
            f"{log_prefix} [EMBED_PROMPT] Injected embed referencing instruction "
            f"(history_embeds={_has_any_embeds_in_history}, current_turn_produces={_current_turn_produces_embeds})"
        )
    else:
        logger.debug(f"{log_prefix} [EMBED_PROMPT] Skipped embed referencing instruction — no embeds in history or preselected skills")

    _include_results_view_instruction = should_include_embeds_results_view_instruction(
        (preselected_skills or set()) | _workflow_presentation_sources,
        _iter_user_request_texts(request_data),
        _embed_history_texts,
    )
    if _include_results_view_instruction:
        prompt_parts.append(EMBEDS_MAP_VIEW_INSTRUCTION)
        logger.debug(
            f"{log_prefix} [EMBED_PROMPT] Injected embeds results-view instruction "
            "for visual-capable current or historical embeds"
        )
    else:
        logger.debug(
            f"{log_prefix} [EMBED_PROMPT] Skipped embeds results-view instruction — "
            "no visual-capable embeds in history or preselected skills"
        )

    # Inject source quote instruction only when quotable search results exist or are expected.
    # Quotable embed types: web search results, news search results (contain title/description/snippets).
    _include_source_quote = _has_quotable_embeds_in_history or _current_turn_produces_quotable_embeds
    if _include_source_quote:
        prompt_parts.append(base_instructions.get("base_embed_source_quote_instruction", ""))
        logger.debug(
            f"{log_prefix} [EMBED_PROMPT] Injected source quote instruction "
            f"(history_quotable={_has_quotable_embeds_in_history}, current_turn_quotable={_current_turn_produces_quotable_embeds})"
        )
    else:
        logger.debug(f"{log_prefix} [EMBED_PROMPT] Skipped source quote instruction — no quotable embeds in history or preselected skills")
    # Add code block formatting instruction to ensure proper language and filename syntax
    # This helps with consistent parsing and rendering of code embeds
    # Add document generation instruction for rich document embeds (document_html fences)
    # This enables the LLM to create structured HTML documents rendered as document previews
    # Add math plot instruction only when the math app is available.
    # Teaches the LLM to emit ```plot f(x) = ... ``` fences that stream_consumer.py
    # converts to interactive math-plot embeds rendered by function-plot on the frontend.
    if discovered_apps_metadata and "math" in discovered_apps_metadata:
        prompt_parts.append(base_instructions.get("base_plot_code_block_instruction", ""))
    # Add Mermaid diagram instruction only when the Diagrams app is available.
    # Teaches the LLM to emit ```mermaid``` fences that stream_consumer.py
    # converts to Diagrams-owned direct embeds.
    if discovered_apps_metadata and "diagrams" in discovered_apps_metadata:
        prompt_parts.append(base_instructions.get("base_mermaid_code_block_instruction", ""))
    # Inject diff editing instruction when diffable embeds (code/document/sheet) exist in history.
    # This teaches the LLM to output unified diffs instead of regenerating full content.
    _has_diffable_embeds = await _has_diffable_embeds_for_prompt(
        request_data,
        cache_service=cache_service,
        directus_service=directus_service,
        log_prefix=log_prefix,
    )
    mark_project_reference_setup("diffable_embeds")
    if _has_diffable_embeds:
        prompt_parts.append(base_instructions.get("base_diff_editing_instruction", ""))
        logger.debug(f"{log_prefix} [DIFF_PROMPT] Injected diff editing instruction (diffable embeds in history)")
    
    # DEBUG: Log the app_settings_memories content before adding to prompt
    # This helps diagnose issues where data is found in cache but not injected into prompt
    server_environment = os.getenv("SERVER_ENVIRONMENT", "production").lower()
    if loaded_app_settings_and_memories_content:
        if server_environment == "development":
            logger.info(f"{log_prefix} [APP_SETTINGS_MEMORIES] Adding {len(loaded_app_settings_and_memories_content)} item(s) to system prompt: {list(loaded_app_settings_and_memories_content.keys())}")
        else:
            logger.info(f"{log_prefix} [APP_SETTINGS_MEMORIES] Adding {len(loaded_app_settings_and_memories_content)} item(s) to system prompt (keys redacted - production environment)")
    else:
        logger.info(f"{log_prefix} [APP_SETTINGS_MEMORIES] No app settings/memories content to add to system prompt (dict is empty)")
    
    if loaded_app_settings_and_memories_content:
        # First, add the instruction telling the LLM how to use this data
        # CRITICAL: This instruction is essential because without it, the LLM may ignore the data
        # and respond with "I don't know anything about you" even when the data is present.
        app_settings_usage_instruction = base_instructions.get("base_app_settings_memories_usage_instruction", "")
        if app_settings_usage_instruction:
            prompt_parts.append(app_settings_usage_instruction)
        
        # Then add the actual data
        settings_and_memories_prompt_section = ["\n--- Relevant Information from Your App Memories ---"]
        for key, value in loaded_app_settings_and_memories_content.items():
            # CRITICAL: Convert Unix timestamps to human-readable date strings
            # LLMs hallucinate dates when given raw timestamps (e.g., may say "added in 2024" for 2026 timestamps)
            # This ensures dates like "added_date" are formatted as "January 14, 2026" instead of 1768390180
            processed_value = _convert_timestamps_to_human_readable(value)
            value_str = json.dumps(processed_value) if not isinstance(processed_value, str) else processed_value
            settings_and_memories_prompt_section.append(f"- {key}: {value_str}")
        prompt_parts.append("\n".join(settings_and_memories_prompt_section))

    active_focus_definition = None
    active_focus_prompt_text: Optional[str] = None
    active_focus_prompt_section: Optional[str] = None
    translation_service = TranslationService()
    if request_data.active_focus_id:
        try:
            # Parse focus mode ID (format: "app_id-focus_id" using hyphen for consistency with tool names)
            if request_data.active_focus_id.startswith("project-focus:"):
                private = await agentic_context.private_focus_document(
                    request_data, request_data.active_focus_id, directus_service, cache_service,
                )
                if not private:
                    raise PermissionError("Private specialist Focus is no longer authorized")
                active_focus_definition = parse_project_phase_focus(private["instruction"], request_data.active_focus_id)
                if active_focus_definition:
                    active_focus_prompt_text = active_focus_definition.system_prompt
                else:
                    from backend.shared.python_utils.focus_mode_skill_loader import _split_frontmatter_and_body, _parse_body_sections
                    _metadata, body = _split_frontmatter_and_body(private["instruction"], "Private Project Focus")
                    active_focus_prompt_text = _parse_body_sections(body).get("system_prompt", body).strip()
                app_id_of_focus, focus_id_in_app = "", ""
            else:
                app_id_of_focus, focus_id_in_app = request_data.active_focus_id.split('-', 1)
            app_metadata_for_focus = discovered_apps_metadata.get(app_id_of_focus)
            if app_metadata_for_focus and app_metadata_for_focus.focuses:
                for focus_def in app_metadata_for_focus.focuses:
                    if focus_def.id == focus_id_in_app:
                        active_focus_definition = focus_def
                        active_focus_prompt_text = focus_def.system_prompt
                        # Translation-backed focuses must be resolved on every request,
                        # not only when proposing activation. See apps/focus-modes-implementation.md.
                        if not active_focus_prompt_text and focus_def.systemprompt_translation_key:
                            language = getattr(preprocessing_results, "output_language", None) or "en"
                            translation_key = focus_def.systemprompt_translation_key
                            for candidate_language in dict.fromkeys((language, "en")):
                                translated = translation_service.get_nested_translation(
                                    translation_key, lang=candidate_language
                                )
                                if translated and translated != translation_key and not translated.startswith("[T:"):
                                    active_focus_prompt_text = translated
                                    break
                        break
        except Exception as e:
            if request_data.active_focus_id.startswith("project-focus:"):
                logger.error("%s Private Project Focus instruction unavailable (%s)", log_prefix, type(e).__name__)
                raise ValueError("PRIVATE_PROJECT_FOCUS_INSTRUCTION_INVALID") from None
            logger.error(f"{log_prefix} Error processing active_focus_id '{request_data.active_focus_id}': {e}", exc_info=True)
            raise
        if not active_focus_prompt_text:
            logger.error("%s Active focus has no resolvable instruction: %s", log_prefix, request_data.active_focus_id)
            raise ValueError("Active focus instructions are unavailable")
    if active_focus_definition and active_focus_definition.phases:
        catalog_runtime = FocusPhaseRuntime(active_focus_definition,
            restore_state(active_focus_definition, focus_id=request_data.active_focus_id,
                chat_id=request_data.chat_id, saved=phase_state_in.get(request_data.active_focus_id)),
            redis=phase_redis, owner_id=request_data.user_id)
        await catalog_runtime.load()
        focus_phase_runtimes.append(catalog_runtime)
        active_focus_prompt_text = phase_prompt(active_focus_definition, catalog_runtime.state)
    if active_focus_prompt_text:
        if request_data.active_focus_id == "web-research" and chat_depth > 0:
            active_focus_prompt_text += DELEGATED_DEEP_RESEARCH_INSTRUCTION
        active_focus_prompt_section = f"--- Active Focus: {request_data.active_focus_id} ---\n{active_focus_prompt_text}\n--- End Active Focus ---"
        prompt_parts.insert(0, active_focus_prompt_section)
    mark_project_reference_setup("catalog_focus")

    follow_up_suggestions_enabled = (request_data.user_preferences or {}).get("follow_up_suggestions_enabled", True) is not False
    if not follow_up_suggestions_enabled:
        prompt_parts.append(FOLLOW_UP_SUGGESTIONS_DISABLED_INSTRUCTION)

    if learning_mode_active:
        learning_age_group = learning_mode_context.get("age_group") or AGE_GROUP_13_15
        prompt_parts.append(build_learning_mode_global_prompt(learning_age_group))
        logger.info(
            f"{log_prefix} Added Learning Mode global prompt "
            f"(age_group={learning_age_group})"
        )

    # Enforce response language based on the preprocessor's detected output_language.
    # Appended last so it sits at the end of the system prompt where LLMs give it high
    # attention — this overrides any language the mate persona or instructions might imply.
    # ISO 639-1 code → human-readable name mapping (must stay in sync with SUPPORTED_LANGUAGES
    # in preprocessor.py). English is skipped — no instruction needed since it's the default.
    _LANGUAGE_NAMES: dict[str, str] = {
        "de": "German", "zh": "Chinese", "es": "Spanish", "fr": "French",
        "pt": "Portuguese", "ru": "Russian", "ja": "Japanese", "ko": "Korean",
        "it": "Italian", "tr": "Turkish", "vi": "Vietnamese", "id": "Indonesian",
        "pl": "Polish", "nl": "Dutch", "ar": "Arabic", "hi": "Hindi",
        "th": "Thai", "cs": "Czech", "sv": "Swedish",
    }
    output_language_code = preprocessing_results.output_language or "en"
    if output_language_code != "en":
        language_name = _LANGUAGE_NAMES.get(output_language_code, output_language_code)
        prompt_parts.append(
            f"IMPORTANT: The user is communicating in {language_name}. "
            f"You MUST respond entirely in {language_name}. "
            f"Do not switch to any other language under any circumstances."
        )
        logger.debug(f"{log_prefix} Added language enforcement instruction for '{output_language_code}' ({language_name}).")

    prompt_parts.append(INTERACTIVE_QUESTIONS_INSTRUCTION)

    if task_context_prompt:
        prompt_parts.append(task_context_prompt)

    # --- Add sub-chats usage instructions for LLM ---
    enable_subchats_results = preprocessing_results.enable_subchats if hasattr(preprocessing_results, 'enable_subchats') else False
    if (request_data.user_preferences or {}).get("apps_enabled") is False:
        enable_subchats_results = False
    if enable_subchats_results:
        sub_chats_instruction = (
            "### Sub-Chats (Sub-Agents) Orchestration Instruction:\n"
            "You have the unique ability to spawn one or multiple autonomous background sub-chats "
            "to parallelize complex tasks (such as parallel web research, batch processing, comparative analysis, or dividing a long-form task into sections) "
            "using the 'start_sub_chats' tool.\n"
            "When the user asks a complex question that would benefit from parallel or distributed processing (e.g., comparing multiple items, batch looping, or deep multi-topic research), "
            "you MUST call 'start_sub_chats' to delegate those tasks to sub-agents. Do not attempt to do everything in a single turn if it would benefit from sub-chats.\n"
            "When spawning sub-chats, provide precise and focused prompts for each sub-chat so they can work independently and efficiently. "
            "If a sub-chat can answer independently, its final assistant response is automatically treated as its completion summary for the parent. "
            "Sub-chats should not call an end function just to finish. If a sub-chat needs clarification from the user, it MUST call 'ask_user_input' with the exact question instead of embedding a marker in normal text. "
            "If the user is complaining about sub-chats or wants you to try starting them, proceed to call 'start_sub_chats' on their request immediately."
        )
        prompt_parts.append(sub_chats_instruction)
        research_only_prompt_parts.add(sub_chats_instruction)
        logger.info(f"{log_prefix} Appended sub-chats orchestration instructions to system prompt.")

    if getattr(request_data, "is_anonymous", False):
        prompt_parts.append(
            "In this anonymous chat, use only the tools made available for this turn. "
            "If the user asks for image, audio, music, video, or other file generation, "
            "or an account-connected action, explain that creating an account is required."
        )
    full_system_prompt = "\n\n".join(filter(None, prompt_parts))
    answer_recovery_system_prompt = "\n\n".join(
        part for part in prompt_parts if part and part not in research_only_prompt_parts
    )
    mark_project_reference_setup("prompt_assembly")
    
    # Generate tool definitions from discovered apps using the tool generator
    # Filter by preselected skills from preprocessing (architecture: only preselected skills are forwarded)
    # Note: preselected_skills was already built earlier (before app instruction injection)
    # so it's available here for tool generation.
    # `tools` is the CC-compatible field name for per-mate app/skill allowlist
    # (renamed from the legacy `assigned_apps`). Still treated as a list of
    # app IDs downstream until per-skill gating lands.
    assigned_app_ids = selected_mate_config.tools if selected_mate_config else None
    assigned_app_ids = assigned_app_ids_with_task_app_for_explicit_skill(
        assigned_app_ids,
        task_app_skill_mentions,
    )
    
    # Reuse the translation service used to resolve active focus instructions.
    
    available_tools_for_llm = generate_tools_from_apps(
        discovered_apps_metadata=discovered_apps_metadata,
        assigned_app_ids=assigned_app_ids,
        preselected_skills=preselected_skills,
        translation_service=translation_service
    ) if assigned_app_ids != [] else []
    available_tools_for_llm = without_unscoped_project_search(available_tools_for_llm)

    if task_queue_blocks_plan_tools:
        original_tool_count = len(available_tools_for_llm)
        available_tools_for_llm = [
            tool for tool in available_tools_for_llm
            if not str(tool.get("function", {}).get("name") or "").startswith("plans-")
        ]
        if len(available_tools_for_llm) != original_tool_count:
            logger.info(
                "%s [TASK_QUEUE_PLAN_GUARD] Removed %s generated plan tool(s) while chat tasks remain.",
                log_prefix,
                original_tool_count - len(available_tools_for_llm),
            )

    if task_tools_enabled and task_tool_context is not None and not suppress_task_runtime_tools:
        task_tools = build_task_runtime_tools(task_tool_context)
        available_tools_for_llm = merge_task_runtime_tools(available_tools_for_llm, task_tools)
        logger.info(
            "%s Added %s task runtime tool(s) to main processing",
            log_prefix,
            len(task_tools),
        )

    if project_file_tools_enabled and active_project_focus:
        project_tools = build_project_file_tools()
        available_tools_for_llm.extend(project_tools)
        logger.info("%s Added %s authorized Project file tool(s)", log_prefix, len(project_tools))

    audio_transcribe_blocked_by_recording = has_transcribed_web_audio_recording(request_data.message_history)
    if audio_transcribe_blocked_by_recording:
        original_tool_count = len(available_tools_for_llm)
        available_tools_for_llm = [
            tool for tool in available_tools_for_llm
            if _canonicalize_tool_name(tool.get("function", {}).get("name", "")) != AUDIO_TRANSCRIBE_SKILL_ID
        ]
        if len(available_tools_for_llm) != original_tool_count:
            logger.info(
                f"{log_prefix} [AUDIO_RECORDING_GUARD] Removed '{AUDIO_TRANSCRIBE_SKILL_ID}' from main LLM tools: "
                "web UI audio recording already includes transcript text."
            )
    
    # --- Add focus mode tools if relevant ---
    # Focus modes are treated as special system tools that change the AI's behavior
    # activate_focus_mode: only when relevant focus modes exist AND no focus mode is active
    # deactivate_focus_mode: only when a focus mode is currently active
    
    relevant_focus_modes = preprocessing_results.relevant_focus_modes if hasattr(preprocessing_results, 'relevant_focus_modes') else []
    has_active_focus_mode = bool(request_data.active_focus_id or active_project_focus)
    project_candidates = {
        f"project-{candidate['project_id']}": candidate
        for candidate in (getattr(request_data, "project_focus_candidates", None) or [])
        if isinstance(candidate, dict) and candidate.get("project_id") and candidate.get("name")
    }
    private_candidates = {item["id"]: item for item in await agentic_context.private_focus_candidates(
        request_data, directus_service, cache_service)} if agentic_context.first_party(request_data) else {}
    mark_project_reference_setup("private_focus_candidates")
    relevant_focus_modes = [focus for focus in relevant_focus_modes
        if not focus.startswith("project-focus:") or focus in private_candidates]
    relevant_focus_modes = [
        focus for focus in relevant_focus_modes
        if focus not in project_candidates or (
            not getattr(request_data, "project_access_declined", False)
            and focus in project_candidates
            and project_file_tools_enabled
            and (not active_project_focus or project_candidates[focus]["project_id"] != active_project_focus["project_id"])
        )
    ]
    # An accepted specialist already supplies its instructions. Reoffering it
    # would restart the countdown on every continuation of the same user turn.
    relevant_focus_modes = [focus for focus in relevant_focus_modes if focus != request_data.active_focus_id]
    if has_active_focus_mode:
        relevant_focus_modes = [focus for focus in relevant_focus_modes if focus in project_candidates or focus in private_candidates]
    # Whether the user explicitly specified this focus mode via @focus:app:id mention
    user_requested_focus_only = getattr(preprocessing_results, 'user_requested_focus_only', False)
    
    if relevant_focus_modes and not user_requested_skills_only:
        # Build enum and descriptions for activate_focus_mode tool
        focus_mode_descriptions = []
        for focus_id in relevant_focus_modes:
            if focus_id in private_candidates:
                candidate = private_candidates[focus_id]
                focus_mode_descriptions.append(f"- {focus_id}: {candidate['title']}: {candidate['summary']}")
                continue
            if focus_id in project_candidates:
                focus_mode_descriptions.append(
                    f"- {focus_id}: Request access to Project {project_candidates[focus_id]['name']!r}. "
                    "The client shows a cancellable Focus countdown. You cannot access its files or "
                    "instructions until the user grants access. Never substitute a generic code tool."
                )
                continue
            try:
                app_id, mode_id = focus_id.split('-', 1)
                app_metadata = discovered_apps_metadata.get(app_id)
                if app_metadata and app_metadata.focuses:
                    for focus in app_metadata.focuses:
                        if focus.id == mode_id:
                            # Get translated description
                            description = translation_service.get_nested_translation(focus.description_translation_key) or focus.description_translation_key
                            focus_mode_descriptions.append(f"- {focus_id}: {description}")
                            break
            except Exception as e:
                logger.warning(f"{log_prefix} Error building description for focus mode {focus_id}: {e}")
        
        # Tool name MUST conform to Google Gemini's function-name spec:
        # ^[a-zA-Z_][a-zA-Z0-9_]*$. Hyphens cause Gemini to return
        # FinishReason.MALFORMED_FUNCTION_CALL, so we use snake_case here
        # even though the rest of the codebase uses hyphens for app skills.
        # The downstream resolver map below translates back to ("system",
        # "activate_focus_mode") for the dispatcher.
        #
        # NOTE: We intentionally do NOT use an `enum` constraint on focus_id.
        # Gemini 3.x emits FinishReason.MALFORMED_FUNCTION_CALL when the enum
        # contains hyphenated values (e.g. "jobs-career-insights"). Listing
        # the valid IDs in the description works reliably across providers
        # and still gives the model a constrained vocabulary to choose from.
        _valid_ids_list = ", ".join(f'"{fid}"' for fid in relevant_focus_modes)
        _desc_lines = [
            "Activate a focus mode to specialize the assistant's behavior for a specific task. "
            "Focus modes provide specialized instructions that help with particular types of requests.",
            "",
            f"Valid focus_id values (use EXACTLY one of these): {_valid_ids_list}",
        ]
        if focus_mode_descriptions:
            _desc_lines.extend(["", "Available focus modes:", *focus_mode_descriptions])
        activate_tool = {
            "type": "function",
            "function": {
                "name": "activate_focus_mode",
                "description": "\n".join(_desc_lines),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "focus_id": {
                            "type": "string",
                            "description": (
                                f"The focus mode to activate. Must be one of: {_valid_ids_list}. "
                                "Format: app_id-focus_id."
                            ),
                        }
                    },
                    "required": ["focus_id"]
                }
            }
        }
        available_tools_for_llm.append(activate_tool)
        logger.info(f"{log_prefix} Added activate_focus_mode tool with {len(relevant_focus_modes)} available focus mode(s): {relevant_focus_modes}")
    
    if request_data.active_focus_id and not user_requested_skills_only:
        # Add deactivate tool when a focus mode is active
        deactivate_tool = {
            "type": "function",
            "function": {
                # Snake_case for Gemini compatibility — see activate_focus_mode comment above.
                "name": "deactivate_focus_mode",
                "description": f"Deactivate the current focus mode ({request_data.active_focus_id}) and return to normal assistant behavior. Use this when the user no longer needs the specialized focus mode or asks to exit it.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
        available_tools_for_llm.append(deactivate_tool)
        logger.info(f"{log_prefix} Added deactivate_focus_mode tool (current focus: {request_data.active_focus_id})")

    # --- Add sub-chat orchestration tools ---
    start_sub_chats_tool = {
        "type": "function",
        "function": {
            "name": "start_sub_chats",
            "description": (
                "Spawn one or multiple autonomous background sub-chats to parallelize or sequence complex tasks. "
                "You can specify a list of sub-chats, each with its own prompt. "
                "Supports loops/templates where you specify a list of items and a prompt_template "
                "containing '{x}' which will be replaced with each item from the list. "
                "Use execution_mode='sequential' when child tasks could collide, must build on each other, or should run one after another. "
                f"Start at most {MAX_AUTO_SUB_CHATS_PER_TURN} sub-chats without explicit user approval; "
                f"larger batches require confirmation. Parallel batches can have at most {MAX_DIRECT_SUB_CHATS_PER_PARENT} direct sub-chats; sequential queues have no direct-child count limit."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "execution_mode": {
                        "type": "string",
                        "enum": ["parallel", "sequential"],
                        "description": "parallel starts all approved sub-chats immediately. sequential creates the queue but runs only one sub-chat at a time. Default parallel.",
                        "default": "parallel"
                    },
                    "context_policy": {
                        "type": "string",
                        "enum": ["none", "previous_summary", "cumulative_summaries"],
                        "description": "For sequential execution, choose whether later sub-chats receive no prior context, only the immediately previous summary, or all prior summaries. Default previous_summary.",
                        "default": "previous_summary"
                    },
                    "sub_chats": {
                        "type": "array",
                        "description": "List of sub-chats to spawn.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "prompt": {
                                    "type": "string",
                                    "description": "Specific custom prompt for this sub-chat. Use either 'prompt' OR 'prompt_template' and 'list'."
                                },
                                "prompt_template": {
                                    "type": "string",
                                    "description": "Template prompt containing '{x}' to spawn multiple similar sub-chats."
                                },
                                "title": {
                                    "type": "string",
                                    "description": "Concise 3-7 word UI title for this sub-chat. For templates, '{x}' is replaced with the current item."
                                },
                                "category": {
                                    "type": "string",
                                    "description": "The most relevant OpenMates mate category ID for this sub-chat, such as legal_law, business_development, or science."
                                },
                                "icon": {
                                    "type": "string",
                                    "description": "A relevant Lucide icon name for this sub-chat, such as scale, landmark, chart-line, or search."
                                },
                                "list": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Array of strings/elements to substitute into '{x}' of prompt_template."
                                },
                                "wait_for_completion": {
                                    "type": "boolean",
                                    "description": "If True, the parent chat will wait for this sub-chat's results before continuing. Default True.",
                                    "default": True
                                },
                                "budget_limit": {
                                    "type": "number",
                                    "description": "Optional credit budget limit for this sub-chat subtree."
                                },
                                "report_trigger": {
                                    "type": "string",
                                    "enum": ["each", "all"],
                                    "description": "Whether to report back after 'each' sub-chat completes or only after 'all' have completed. Default 'all'.",
                                    "default": "all"
                                }
                            },
                            "required": ["title", "category", "icon"]
                        }
                    }
                },
                "required": ["sub_chats"]
            }
        }
    }

    end_subchat_tool = {
        "type": "function",
        "function": {
            "name": "end_subchat",
            "description": "Successfully end the current sub-chat session and submit your final summary/report back to the parent chat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "The detailed markdown or structured JSON summary of your work and findings to report back to the parent chat."
                    }
                },
                "required": ["summary"]
            }
        }
    }

    ask_user_input_tool = {
        "type": "function",
        "function": {
            "name": "ask_user_input",
            "description": "Pause sub-chat execution and request clarifying input, context, or direction from the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The precise question or request for information you need from the user."
                    }
                },
                "required": ["question"]
            }
        }
    }

    if not request_data.is_incognito and should_expose_subchat_tool(
        enable_subchats=enable_subchats_results,
        chat_depth=chat_depth,
        is_sub_chat_continuation=request_data.is_sub_chat_continuation,
        active_focus_id=request_data.active_focus_id,
    ):
        available_tools_for_llm.append(start_sub_chats_tool)
        logger.info(f"{log_prefix} Added start_sub_chats tool to main LLM tools.")

    force_deep_research_delegation = should_force_deep_research_delegation(
        active_focus_id=request_data.active_focus_id,
        chat_depth=chat_depth,
        is_sub_chat_continuation=request_data.is_sub_chat_continuation,
    )
    if enable_subchats_results and force_deep_research_delegation:
        available_tools_for_llm = gate_tools_for_deep_research(
            available_tools_for_llm,
            active_focus_id=request_data.active_focus_id,
            start_sub_chats_tool=start_sub_chats_tool,
        )
        logger.info(
            f"{log_prefix} [SUB_CHAT] Deep research first-step gate: exposing only start_sub_chats to force delegated research."
        )

    if getattr(request_data, "is_anonymous", False):
        from backend.shared.python_utils.anonymous_skill_policy import filter_anonymous_tools

        available_tools_for_llm = filter_anonymous_tools(
            available_tools_for_llm,
            discovered_apps_metadata,
            _canonicalize_tool_name,
        )

    if (request_data.user_preferences or {}).get("apps_enabled") is False:
        # This is the authoritative tool boundary for Workflow Ask AI and API
        # requests that disable apps. The later allow-list also rejects invented
        # provider tool calls before any dispatcher can see them.
        available_tools_for_llm = []

    if not request_data.orchestration_id and any(
        tool.get("function", {}).get("name") == "start_sub_chats"
        for tool in available_tools_for_llm
    ):
        await create_orchestration_root(directus_service, request_data)
    
    if chat_depth > 0 and not getattr(request_data, "is_anonymous", False) and (request_data.user_preferences or {}).get("apps_enabled") is not False:
        available_tools_for_llm.append(ask_user_input_tool)
        logger.info(f"{log_prefix} Added ask_user_input tool to main LLM tools (depth={chat_depth}).")
    
    # Log available tools for debugging
    tool_names = [tool["function"]["name"] for tool in available_tools_for_llm]
    # Strict allow-list: the main LLM may ONLY call tools that the preprocessor
    # explicitly forwarded into available_tools_for_llm (including rule-based
    # auto-adds like images-view on upload and always_include_skills). Any
    # other tool name is a hallucination (e.g. invented "mail|get_apps_settings")
    # and must be rejected before it reaches skill execution. See OPE-399.
    #
    # Separator normalization: different LLM providers emit tool names with
    # different separators (Gemini 3.5 Flash uses ':' — 'web:search', older
    # models sometimes use '_' — 'web_search', some emit '|' — 'web|search',
    # and the canonical form is '-' — 'web-search'). To avoid rejecting a
    # legitimately preselected tool just because the provider used the
    # "wrong" separator, we normalize every tool name to its hyphen form
    # before the allow-list check. The allow-list itself stays strict — a
    # non-preselected skill is still a hallucination regardless of separator.
    allowed_tool_names: set[str] = set()
    for name in tool_names:
        allowed_tool_names.add(_canonicalize_tool_name(name))
        allowed_tool_names.update(task_tool_name_variants(name))
    logger.info(f"{log_prefix} Available tools for main processing LLM: {len(available_tools_for_llm)} total")
    logger.debug(f"{log_prefix} Tool names: {', '.join(tool_names) if tool_names else 'None'}")
    if preselected_skills:
        logger.info(f"{log_prefix} Using preselected skills filter: {preselected_skills}")
    if assigned_app_ids:
        logger.info(f"{log_prefix} Using assigned apps filter: {assigned_app_ids}")

    # Build a robust tool resolver map to handle LLM hallucinations (e.g., underscores instead of hyphens)
    # Maps tool_name (and variants) -> (app_id, skill_id)
    tool_resolver_map: Dict[str, tuple[str, str]] = {}
    
    # Iterate through all discovered apps and skills to build the map
    # We use discovered_apps_metadata instead of available_tools_for_llm to ensure we catch all valid skills
    # even if they weren't generated as tools for this specific turn (though usually they should match)
    for app_id, app_metadata in discovered_apps_metadata.items():
        if not app_metadata or not app_metadata.skills:
            continue

        for skill in app_metadata.skills:
            # Standard hyphenated name: app-skill (e.g., "web-search")
            hyphen_name = f"{app_id}-{skill.id}"
            tool_resolver_map[hyphen_name] = (app_id, skill.id)

            # Underscore variant: app_skill (e.g., "web_search") - common LLM hallucination
            underscore_name = f"{app_id}_{skill.id}"
            tool_resolver_map[underscore_name] = (app_id, skill.id)

            # Canonical (all-hyphen) form: what _canonicalize_tool_name produces.
            # For skills with underscored IDs (e.g., "search_appointments"),
            # hyphen_name is "health-search_appointments" but the canonicalizer
            # converts all separators to hyphens → "health-search-appointments".
            # Without this entry the allow-list passes but resolver lookup fails.
            canonical_name = _canonicalize_tool_name(hyphen_name)
            if canonical_name != hyphen_name:
                tool_resolver_map[canonical_name] = (app_id, skill.id)

            # Also map the skill ID directly if it's unique? No, that might be risky.
            # But we can map just the skill ID if the app ID is implicit? No, explicit is better.

    # System tools (focus mode activation/deactivation) live outside the
    # discovered_apps_metadata loop because they don't belong to any app.
    # The dispatcher at line ~2752 expects to look them up by the tuple
    # (app_id="system", skill_id="activate_focus_mode" | "deactivate_focus_mode").
    #
    # Tool names in the LLM-facing definition are bare snake_case
    # ("activate_focus_mode") for Google Gemini compatibility — Gemini emits
    # FinishReason.MALFORMED_FUNCTION_CALL when given hyphenated names. The
    # canonicalizer (_canonicalize_tool_name) then turns the LLM-emitted
    # underscored form into "activate-focus-mode" before resolver lookup, so
    # we register BOTH the canonicalized form (post-canonicalize) and the raw
    # snake_case form (pre-canonicalize, defensive) for both tools.
    for system_skill in (
        "activate_focus_mode",
        "deactivate_focus_mode",
        "start_sub_chats",
        "ask_user_input",
        *PROJECT_FILE_TOOL_TO_OPERATION.keys(),
    ):
        # Pre-canonicalize form (raw snake_case as the LLM emits it)
        tool_resolver_map[system_skill] = ("system", system_skill)
        # Post-canonicalize form (underscores → hyphens, what the dispatcher sees)
        tool_resolver_map[system_skill.replace("_", "-")] = ("system", system_skill)

    for task_tool_name in TASK_TOOL_CANONICAL_NAMES:
        tool_resolver_map[task_tool_name] = (TASK_TOOL_RESOLVER_APP_ID, task_tool_skill_id(task_tool_name))
        tool_resolver_map[task_tool_name.replace("-", "_")] = (TASK_TOOL_RESOLVER_APP_ID, task_tool_skill_id(task_tool_name))

    current_message_history: List[Dict[str, Any]] = [_llm_history_message(msg) for msg in request_data.message_history]
    
    # Size the initial history for the selected answer model. Jev's independent
    # bounded projection never participates in this calculation.
    selected_history_budget = model_history_token_budget(
        preprocessing_results.selected_main_llm_model_id,
        config_manager,
        system_prompt=full_system_prompt,
        tools=available_tools_for_llm,
    )
    current_message_history = truncate_message_history_to_token_budget(
        current_message_history,
        max_tokens=selected_history_budget,
    )
    # Native replay is an optional optimization for ordinary direct-provider
    # chats. The task queue carries only Vault ciphertext; decrypt here and keep
    # the provider transcript in process memory until the final private marker.
    native_prior_state: Optional[Dict[str, Any]] = None
    native_scope = _normal_chat_cache_pricing_scope(request_data) and not request_data.is_incognito
    native_prior_reason = (
        "scope_off" if not native_scope else
        "no_vault_key" if not user_vault_key_id else "no_assistant"
    )
    if native_scope and request_data.message_history and user_vault_key_id:
        prior_assistant = next(
            (message for message in reversed(request_data.message_history[:-1])
             if message.role == "assistant"), None,
        )
        ciphertext = getattr(prior_assistant, "encrypted_native_cache_context", None) if prior_assistant else None
        native_prior_reason = "no_ciphertext" if prior_assistant else "no_assistant"
        if isinstance(ciphertext, str) and ciphertext.startswith("vault:v"):
            try:
                plaintext = await encryption_service.decrypt_with_user_key(ciphertext, user_vault_key_id)
                decoded = json.loads(plaintext)
                if (isinstance(decoded, dict) and await validate_native_embed_fingerprints(
                        decoded, cache_service, request_data.user_id_hash)):
                    native_prior_state = decoded
                    native_prior_reason = "retained"
                else:
                    native_prior_reason = "fingerprint_rejected"
            except Exception as exc:
                native_prior_reason = "decrypt_failed"
                logger.info("%s Native history cold reset after decrypt failure (%s)", log_prefix, type(exc).__name__)
    native_state: Optional[Dict[str, Any]] = None
    native_main_cursor: Optional[int] = None
    native_main_snapshot: Optional[List[Dict[str, Any]]] = None
    native_raw_final_output: Optional[List[Dict[str, Any]]] = None
    native_raw_final_text = ""
    native_terminal_ready = False
    logger.info(
        "%s Model-aware history budget for %s: %s tokens",
        log_prefix,
        preprocessing_results.selected_main_llm_model_id,
        selected_history_budget,
    )
    
    # Track all tool calls for code block generation
    # This will be used to prepend a code block with skill input/output/metadata to the assistant response
    tool_calls_info: List[Dict[str, Any]] = []

    # Track embed IDs that failed (error/cancelled) during skill execution.
    # These will be yielded at the end of the stream so the stream_consumer can
    # strip their embed references from the final message content.
    # Without this, the message markdown would contain embed references for embeds
    # that no longer exist, causing the client to re-request them on every page load.
    failed_embed_ids: set[str] = set()
    published_task_queue_continuation_event_ids: set[str] = set()
    
    # --- Yield debug metadata for the inspection script ---
    # This provides the full system prompt, tool definitions, and truncated message history
    # to the stream consumer, which passes it back to ask_skill_task for debug caching.
    # Only the first + last 3 messages are included to keep the debug entry manageable.
    DEBUG_MSG_HISTORY_HEAD = 1  # First message (usually system context or first user message)
    DEBUG_MSG_HISTORY_TAIL = 3  # Last 3 messages (most recent context)
    if len(current_message_history) <= DEBUG_MSG_HISTORY_HEAD + DEBUG_MSG_HISTORY_TAIL:
        # Snapshot before the tool loop appends provider-only transport state.
        debug_message_history = list(current_message_history)
    else:
        debug_message_history = (
            current_message_history[:DEBUG_MSG_HISTORY_HEAD]
            + [{"__truncated__": True, "omitted_messages": len(current_message_history) - DEBUG_MSG_HISTORY_HEAD - DEBUG_MSG_HISTORY_TAIL}]
            + current_message_history[-DEBUG_MSG_HISTORY_TAIL:]
        )
    
    async def request_project_focus(focus_id: str) -> str:
        """Route both named and model-selected Projects through one cancellable request."""
        from backend.apps.ai.tasks.async_skill_continuation import cache_async_skill_continuation_context
        from backend.core.api.app.services.embed_service import EmbedService
        from backend.core.api.app.services.project_focus_request_service import (
            PROJECT_FOCUS_REQUEST_TTL, ProjectFocusRequestService,
        )

        if (focus_id not in project_candidates or focus_id not in relevant_focus_modes
                or not project_file_tools_enabled
                or project_candidates[focus_id].get("auto_selection", True) is not True):
            raise PermissionError("Project activation was not offered for this turn")
        candidate = project_candidates[focus_id]
        embed = await EmbedService(
            cache_service=cache_service, directus_service=directus_service,
            encryption_service=encryption_service,
        ).create_focus_mode_activation_embed(
            focus_id=focus_id, app_id="projects",
            focus_mode_name=f"Work on {candidate['name']}",
            chat_id=request_data.chat_id, message_id=request_data.message_id,
            user_id=request_data.user_id, user_id_hash=request_data.user_id_hash,
            user_vault_key_id=user_vault_key_id, task_id=task_id, log_prefix=log_prefix,
        )
        if not embed:
            raise RuntimeError("Project access confirmation could not be created")
        request_id = embed["embed_id"]
        await cache_async_skill_continuation_context(
            cache_service=cache_service, async_task_id=request_id,
            request_data=request_data, skill_config_dict=skill_config_dict,
            app_id="system", skill_id="activate_focus_mode", tool_name="activate_focus_mode",
            tool_arguments={"focus_id": focus_id}, preprocessing_result=preprocessing_results,
            requires_current_turn=True,
            defer_until_initial_response_complete=True, ttl_seconds=PROJECT_FOCUS_REQUEST_TTL,
        )
        pending = await ProjectFocusRequestService(cache_service, directus_service).create_pending(
            user_id=request_data.user_id, chat_id=request_data.chat_id,
            request_id=request_id, project_id=candidate["project_id"],
            message_id=request_data.message_id, team_id=request_data.team_id,
        )
        redis_client = await cache_service.client
        await redis_client.publish(f"user_cache_events:{request_data.user_id}", json.dumps({
            "event_type": "focus_mode_pending", "payload": ProjectFocusRequestService.pending_event(pending),
        }))
        return embed["embed_reference"]

    # Build concise tool summaries (name + first 120 chars of description)
    TOOL_DESCRIPTION_PREVIEW_LENGTH = 120
    debug_tool_summaries = []
    for tool in available_tools_for_llm:
        func = tool.get("function", {})
        desc = func.get("description", "")
        debug_tool_summaries.append({
            "name": func.get("name", "unknown"),
            "description_preview": desc[:TOOL_DESCRIPTION_PREVIEW_LENGTH] + ("..." if len(desc) > TOOL_DESCRIPTION_PREVIEW_LENGTH else ""),
        })
    
    yield {
        "__debug_metadata__": True,
        "system_prompt": ("[Transient private context omitted]" if agentic_context.first_party(request_data) else full_system_prompt),
        "system_prompt_char_count": len(full_system_prompt),
        "available_tools": debug_tool_summaries,
        "available_tools_count": len(available_tools_for_llm),
        "message_history_sent_to_llm": debug_message_history,
        "message_history_total_count": len(current_message_history),
    }
    
    # --- End of existing logic ---

    # A unique name in the current user turn is enough to request access, but
    # never to grant it. Reuse the same cancellable countdown as the model tool.
    named_project_focus_id = None
    if (project_file_tools_enabled and not getattr(request_data, "project_access_declined", False)
            and not user_requested_skills_only and not user_requested_focus_only
            and requests_project_file_work(request_data.current_user_content or "")
            and (request_data.user_preferences or {}).get("apps_enabled") is not False
            and any(tool.get("function", {}).get("name") == "activate_focus_mode"
                    for tool in available_tools_for_llm)):
        named_project_focus_id = uniquely_named_project_focus_id(
            request_data.current_user_content or "",
            list(project_candidates.values()),
            relevant_focus_modes,
        )
    if named_project_focus_id:
        logger.info("%s Requesting named Project Focus through standard countdown", log_prefix)
        embed_reference = await request_project_focus(named_project_focus_id)
        yield f"```json\n{embed_reference}\n```\n\n"
        yield {"__awaiting_focus_mode_confirmation__": True,
               "focus_id": named_project_focus_id, "chat_id": request_data.chat_id}
        return

    # --- User-requested focus mode: bypass LLM + countdown ---
    # When the user explicitly mentioned a focus mode via @focus:app_id:focus_id in their message,
    # we skip the normal flow (LLM deciding to call activate_focus_mode, 5s countdown) and
    # directly activate the focus mode with countdown=0 (immediate).
    # This mirrors the exact same activation pipeline used in the deferred path, but without delay.
    if (user_requested_focus_only and relevant_focus_modes and not has_active_focus_mode
            and relevant_focus_modes[0] not in project_candidates
            and _trusted_focus_override(user_overrides, relevant_focus_modes[0])):
        focus_id = relevant_focus_modes[0]  # Only one can be selected per the UI constraint
        logger.info(
            f"{log_prefix} [FOCUS_MODE_OVERRIDE] User explicitly requested focus mode '{focus_id}' via @mention. "
            f"Bypassing LLM tool call and countdown — activating immediately."
        )

        # Create the focus mode activation embed (same as the LLM-initiated path)
        fm_embed_id = None
        if cache_service and user_vault_key_id and directus_service:
            try:
                from backend.core.api.app.services.embed_service import EmbedService
                embed_service = EmbedService(
                    cache_service=cache_service,
                    directus_service=directus_service,
                    encryption_service=encryption_service
                )

                # Resolve the translated focus mode display name
                focus_mode_display_name = focus_id  # fallback
                try:
                    fm_app_id, fm_mode_id = focus_id.split('-', 1)
                    user_language = preprocessing_results.output_language or "en"
                    fm_app_metadata = discovered_apps_metadata.get(fm_app_id)
                    if fm_app_metadata and fm_app_metadata.focuses:
                        for fm_def in fm_app_metadata.focuses:
                            if fm_def.id == fm_mode_id:
                                focus_mode_display_name = _resolve_focus_mode_display_name(
                                    translation_service,
                                    fm_def.name_translation_key,
                                    fallback=fm_def.name_translation_key,
                                    user_language=user_language,
                                )
                                break
                except Exception:
                    pass

                fm_embed_data = await embed_service.create_focus_mode_activation_embed(
                    focus_id=focus_id,
                    app_id=focus_id.split('-', 1)[0] if '-' in focus_id else focus_id,
                    focus_mode_name=focus_mode_display_name,
                    chat_id=request_data.chat_id,
                    message_id=request_data.message_id,
                    user_id=request_data.user_id,
                    user_id_hash=request_data.user_id_hash,
                    user_vault_key_id=user_vault_key_id,
                    task_id=task_id,
                    log_prefix=log_prefix
                )

                if fm_embed_data:
                    fm_embed_id = fm_embed_data.get("embed_id")
                    fm_embed_ref = fm_embed_data.get("embed_reference")
                    if fm_embed_ref:
                        yield f"```json\n{fm_embed_ref}\n```\n\n"
                        logger.info(
                            f"{log_prefix} [FOCUS_MODE_OVERRIDE] Yielded focus mode activation embed "
                            f"(embed_id={fm_embed_id})"
                        )
            except Exception as embed_error:
                logger.error(
                    f"{log_prefix} [FOCUS_MODE_OVERRIDE] Error creating focus mode embed: {embed_error}",
                    exc_info=True
                )

        # Load focus mode system prompt (same as the LLM-initiated path)
        focus_prompt_text = ""
        try:
            focus_app_id, focus_mode_id = focus_id.split('-', 1)
            translation_key = f"focus_modes.{focus_app_id}_{focus_mode_id}.systemprompt"
            user_language = preprocessing_results.output_language or "en"
            focus_prompt_text = translation_service.get_nested_translation(translation_key, lang=user_language) or ""
            if not focus_prompt_text and user_language != "en":
                focus_prompt_text = translation_service.get_nested_translation(translation_key, lang="en") or ""
                logger.info(
                    f"{log_prefix} [FOCUS_MODE_OVERRIDE] Loaded focus prompt in fallback language (en) "
                    f"({len(focus_prompt_text)} chars)"
                )
            else:
                logger.info(
                    f"{log_prefix} [FOCUS_MODE_OVERRIDE] Loaded focus prompt in user language ({user_language}) "
                    f"({len(focus_prompt_text)} chars)"
                )
        except Exception as e:
            logger.error(f"{log_prefix} [FOCUS_MODE_OVERRIDE] Error loading focus prompt: {e}", exc_info=True)

        # Store pending activation context in Redis (same structure as the LLM-initiated path)
        if cache_service:
            try:
                pending_context = {
                    "focus_id": focus_id,
                    "focus_prompt": focus_prompt_text,
                    "user_override": True,
                    **_forward_agentic_context(request_data),
                    "embed_id": fm_embed_id,
                    "chat_id": request_data.chat_id,
                    "message_id": request_data.message_id,
                    "user_id": request_data.user_id,
                    "user_id_hash": request_data.user_id_hash,
                    "mate_id": preprocessing_results.selected_mate_id or request_data.mate_id,
                    "chat_has_title": request_data.chat_has_title,
                    "is_incognito": getattr(request_data, 'is_incognito', False),
                    "task_id": task_id,
                    "recovery_inference_task_id": request_data.resolved_recovery_inference_task_id(),
                    "recovery_preflight_id": request_data.recovery_preflight_id,
                    "recovery_turn_id": request_data.recovery_turn_id,
                    "recovery_public_key": request_data.recovery_public_key,
                    "chat_key_version": request_data.chat_key_version,
                    "preprocessing_resume_ref": getattr(request_data, "preprocessing_resume_ref", None),
                    "parent_id": request_data.parent_id,
                    "is_sub_chat": request_data.is_sub_chat,
                    "orchestration_id": request_data.orchestration_id,
                    "root_chat_id": request_data.root_chat_id,
                    "root_turn_id": request_data.root_turn_id,
                    "sub_chat_depth": request_data.sub_chat_depth,
                    "orchestration_dispatch_token": request_data.orchestration_dispatch_token,
                    "orchestration_descendant_limit": request_data.orchestration_descendant_limit,
                    "orchestration_credit_limit": request_data.orchestration_credit_limit,
                    "orchestration_approved": request_data.orchestration_approved,
                    "budget_limit": request_data.budget_limit,
                    "budget_spent": request_data.budget_spent,
                    "team_id": request_data.team_id,
                    "team_id_hash": request_data.team_id_hash,
                    "team_workspace_type": request_data.team_workspace_type,
                    "team_object_id_hash": request_data.team_object_id_hash,
                }
                await cache_service.store_pending_focus_activation(
                    chat_id=request_data.chat_id,
                    context=pending_context,
                )
                logger.info(f"{log_prefix} [FOCUS_MODE_OVERRIDE] Stored pending focus activation context")
            except Exception as e:
                logger.error(
                    f"{log_prefix} [FOCUS_MODE_OVERRIDE] Failed to store pending context: {e}",
                    exc_info=True
                )

        # Schedule auto-confirm task with countdown=0 (immediate, no user-facing countdown delay)
        # The standard 5-second countdown is skipped because the user explicitly chose this focus mode.
        try:
            from backend.core.api.app.tasks.celery_config import app as celery_app_instance
            celery_app_instance.send_task(
                'apps.ai.tasks.focus_mode_auto_confirm',
                kwargs={
                    "chat_id": request_data.chat_id,
                    "request_id": fm_embed_id,
                },
                queue='app_ai',
                countdown=0,  # Immediate — user explicitly requested this focus mode, no countdown needed
            )
            logger.info(
                f"{log_prefix} [FOCUS_MODE_OVERRIDE] Scheduled auto-confirm task with countdown=0 "
                f"(user-requested focus mode '{focus_id}' bypasses the 5s countdown)"
            )
        except Exception as e:
            logger.error(
                f"{log_prefix} [FOCUS_MODE_OVERRIDE] Failed to schedule auto-confirm task: {e}",
                exc_info=True
            )

        # Yield the same special marker and return — stream_consumer handles this identically
        # to the LLM-initiated path (no error, awaiting continuation from auto-confirm task)
        logger.info(
            f"{log_prefix} [FOCUS_MODE_OVERRIDE] Yielding pending marker and returning — "
            f"auto-confirm fires immediately for user-requested focus mode '{focus_id}'"
        )
        yield {"__awaiting_focus_mode_confirmation__": True, "focus_id": focus_id, "chat_id": request_data.chat_id}
        return

    # === BUILD MODEL FALLBACK LIST ===
    # Create ordered list of models to try: primary -> secondary -> fallback
    # This enables automatic retry with different models if the primary fails
    models_to_try: List[str] = []
    if preprocessing_results.selected_main_llm_model_id:
        models_to_try.append(preprocessing_results.selected_main_llm_model_id)
    if preprocessing_results.selected_secondary_model_id:
        if preprocessing_results.selected_secondary_model_id not in models_to_try:
            models_to_try.append(preprocessing_results.selected_secondary_model_id)
    if preprocessing_results.selected_fallback_model_id:
        if preprocessing_results.selected_fallback_model_id not in models_to_try:
            models_to_try.append(preprocessing_results.selected_fallback_model_id)
    if (request_data.user_preferences or {}).get("workflow_budget") is not None:
        # A failed provider attempt may still consume tokens; one model keeps the
        # quoted allowance bound to one provider call.
        models_to_try = models_to_try[:1]

    # Track which model we're currently using (may change if we need to fallback)
    current_model_index = 0
    current_model_id = models_to_try[0] if models_to_try else preprocessing_results.selected_main_llm_model_id

    logger.info(
        f"{log_prefix} MODEL_FALLBACK: Prepared {len(models_to_try)} model(s) to try: {models_to_try}. "
        f"Starting with: {current_model_id}"
    )

    usage: Optional[Union[MistralUsage, GoogleUsageMetadata, AnthropicUsageMetadata, OpenAIUsageMetadata]] = None

    # === CUMULATIVE TOKEN TRACKING ACROSS ALL LLM ITERATIONS ===
    # When tool calls are involved, the LLM is called multiple times per user turn:
    # once to decide which tools to use, and again after receiving tool results.
    # Each intermediate call sends the full (growing) chat history plus all tool results
    # accumulated so far, so each call incurs real API token costs.
    #
    # We accumulate the token counts from every LLM call in this turn so the user is
    # billed for the true total rather than only the final iteration's tokens.
    # The final `usage` object from the last iteration is still used for provider/model
    # metadata — only its token counts are replaced by these cumulative totals.
    #
    # `tool_inference_iterations` counts how many EXTRA LLM calls were triggered by
    # tool use (i.e., total iterations minus 1).  A value of 0 means no tool calls
    # were made (single LLM call, baseline behaviour).  This is stored in the usage
    # entry so users can see it in Settings → Usage detail view.
    tool_inference_iterations: int = 0  # Number of extra LLM calls caused by tool use
    model_usage_tracker = ModelUsageTracker()
    # Only conclusively completed attempts may release conservative holds.
    # Reported usage from interrupted streams remains in terminal billing's
    # tracker above, but its uncertain reservation stays intact until then.
    anonymous_completed_usage = ModelUsageTracker()
    anonymous_checkpointed_credits = 0
    ordinary_reservation_state: Dict[str, Any] = {}
    last_reported_usage: Optional[Union[MistralUsage, GoogleUsageMetadata, AnthropicUsageMetadata, BedrockUsageMetadata, OpenAIUsageMetadata]] = None
    usage_events_emitted = False

    def billing_usage_events() -> List[Any]:
        """Emit incurred usage once, including an interrupted final attempt."""
        nonlocal usage_events_emitted
        if usage_events_emitted or not (model_usage_tracker.usage_by_model or ordinary_reservation_state.get("active")):
            return []
        usage_events_emitted = True
        sentinel = model_usage_tracker.sentinel(tool_inference_iterations=tool_inference_iterations)
        if ordinary_reservation_state.get("active"):
            sentinel["billing_reservation_required"] = True
            sentinel["billing_reservation_charge_id"] = ordinary_reservation_state["charge_id"]
        final_usage = last_reported_usage or usage
        return [sentinel, *([final_usage] if final_usage is not None else [])]

    async def terminal_billing_usage_events() -> List[Any]:
        # Confirmed terminal failures are customer-free; supplier usage remains
        # available as private numeric evidence in the sentinel.
        await _release_authenticated_ai_reservation(
            request_data=request_data,
            reservation_state=ordinary_reservation_state,
            reason="provider_failed",
        )
        return billing_usage_events()

    # === SKILL CALL BUDGET TRACKING ===
    # Track total skill calls across all iterations to prevent runaway research loops.
    # Each request within a tool call counts as one skill call.
    total_skill_calls = 0
    streaming_skill_count = 0  # Mirrors total_skill_calls during streaming to suppress over-budget placeholders
    budget_warning_injected = False
    images_search_executed = False  # Track whether images-search ran, to inject embed preview instruction
    force_no_tools = False  # When True, force tool_choice="none" to make LLM answer with gathered info
    task_queue_guard_retries = 0
    answer_recovery = AnswerRecoveryState()
    protocol_guard_recovery_started = False
    published_answer_text: List[str] = []
    omitted_news_search_requests = 0
    
    # === SKILL CALL DEDUPLICATION ===
    # Track successfully completed skill calls to prevent duplicate executions.
    # Some LLMs (especially Gemini) repeatedly call the same tool across iterations
    # even after receiving a successful result. This wastes credits and creates
    # duplicate side effects (e.g., multiple reminders for "set me a reminder").
    # Key: hash of (app_id, skill_id, arguments), Value: dict with results and embed_id
    completed_skill_calls: Dict[str, Dict[str, Any]] = {}
    pending_project_operation_id: Optional[str] = None

    def schedule_answer_recovery(reason: str) -> bool:
        """Spend one bounded synthesis attempt, keeping the first on this model."""
        nonlocal current_model_index, force_no_tools
        recovery_model = answer_recovery.next_model(current_model_id, models_to_try)
        if recovery_model is None:
            return False
        current_model_index = models_to_try.index(recovery_model)
        force_no_tools = True
        logger.warning(
            "%s [ANSWER_ONLY_RECOVERY] reason=%s attempt=%s model=%s; "
            "rebuilding final-answer context from completed evidence with tools disabled.",
            log_prefix, reason, answer_recovery.attempts, recovery_model,
        )
        return True
    
    max_iterations_with_recovery = MAX_TOOL_CALL_ITERATIONS + MAX_ANSWER_ONLY_RECOVERY_ITERATIONS
    async def evaluate_active_phases(boundary, boundary_id, evidence):
        nonlocal full_system_prompt, answer_recovery_system_prompt
        nonlocal active_focus_prompt_section, project_phase_prompt_section
        nonlocal available_tools_for_llm, allowed_tool_names
        changed = False
        for runtime in focus_phase_runtimes:
            changed = await runtime.evaluate(boundary=boundary, boundary_id=boundary_id,
                turn_id=request_data.message_id, latest_user=request_data.current_user_content,
                messages=evidence, secrets_manager=secrets_manager) or changed
        if changed:
            for runtime in focus_phase_runtimes:
                instruction = phase_prompt(runtime.focus, runtime.state)
                if runtime.state.focus_id == request_data.active_focus_id:
                    section = f"--- Active Focus: {request_data.active_focus_id} ---\n{instruction}\n--- End Active Focus ---"
                    if active_focus_prompt_section:
                        full_system_prompt = full_system_prompt.replace(active_focus_prompt_section, section, 1)
                        answer_recovery_system_prompt = answer_recovery_system_prompt.replace(active_focus_prompt_section, section, 1)
                    active_focus_prompt_section = section
                elif active_project_focus and runtime.state.focus_id == active_project_focus["focus_id"]:
                    section = build_project_focus_prompt({**active_project_focus, "instruction": instruction}, active_project_sources)
                    if project_phase_prompt_section:
                        full_system_prompt = full_system_prompt.replace(project_phase_prompt_section, section, 1)
                        answer_recovery_system_prompt = answer_recovery_system_prompt.replace(project_phase_prompt_section, section, 1)
                    project_phase_prompt_section = section
        if changed and not user_requested_skills_only:
            # Reuse the existing discovered (availability-filtered) app catalog.
            # Adding a candidate never bypasses dispatch permissions or Project policy.
            # None means inherited access; [] means no Mate app tools. Focus
            # metadata can guide relevance but cannot widen the Mate allowlist.
            candidate_apps = set(discovered_apps_metadata if assigned_app_ids is None else assigned_app_ids)
            candidate_skill_ids = {f"{app_id}-{skill.id}" for app_id in candidate_apps
                if app_id in discovered_apps_metadata
                for skill in discovered_apps_metadata[app_id].skills or []}
            # The legacy generator interprets an empty list as all apps, so
            # avoid it when the explicit allowlist contains no candidates.
            candidate_tools = generate_tools_from_apps(discovered_apps_metadata=discovered_apps_metadata,
                assigned_app_ids=list(candidate_apps), preselected_skills=list(candidate_skill_ids),
                translation_service=translation_service) if candidate_apps else []
            candidate_tools = without_unscoped_project_search(candidate_tools)
            if task_queue_blocks_plan_tools:
                candidate_tools = [tool for tool in candidate_tools
                    if not str(tool.get("function", {}).get("name") or "").startswith("plans-")]
            selected = await reselect_phase_tools(
                phase_instructions="\n\n".join(phase_prompt(r.focus, r.state) for r in focus_phase_runtimes),
                latest_user=request_data.current_user_content, candidates=candidate_tools,
                secrets_manager=secrets_manager)
            if selected is not None:
                # Preserve internal lifecycle/task/context tools installed by this
                # request. Refresh the generated app skills and existing workflow tools.
                generated_names = {t.get("function", {}).get("name") for t in candidate_tools}
                available_tools_for_llm = [t for t in available_tools_for_llm
                    if t.get("function", {}).get("name") not in generated_names] + selected
                allowed_tool_names = set()
                for tool in available_tools_for_llm:
                    name = str(tool.get("function", {}).get("name") or "")
                    allowed_tool_names.add(_canonicalize_tool_name(name))
                    allowed_tool_names.update(task_tool_name_variants(name))
        request_data.focus_phase_state = {r.state.focus_id: r.state.model_dump() for r in focus_phase_runtimes}
        return changed

    def phase_state_marker():
        # Redis/control state stays opaque. Enrich only this owner-scoped UI
        # projection from the currently authorized in-memory definition.
        from copy import deepcopy
        from backend.apps.ai.processing.focus_phases import private_project_phase
        states = deepcopy(request_data.focus_phase_state or {})
        runtimes = {runtime.state.focus_id: runtime for runtime in focus_phase_runtimes}
        for focus_id, state in states.items():
            if not isinstance(state, dict):
                continue
            runtime = runtimes.get(focus_id)
            if private_project_phase(focus_id):
                titles = {phase.id: phase.title for phase in (runtime.focus.phases or [])} if runtime else {}
                state["transitions"] = [
                    {**event, "phase_title": titles[event["phase_id"]]}
                    for event in state.get("transitions", [])
                    if isinstance(event, dict) and event.get("phase_id") in titles
                ]
            if active_project_focus and focus_id == active_project_focus["focus_id"]:
                for event in state.get("transitions", []):
                    event["project_id"] = active_project_focus["project_id"]
        return {"__focus_phases_updated__": True, "states": states}

    if focus_phase_runtimes:
        if not getattr(request_data, "is_focus_mode_continuation", False):
            await evaluate_active_phases("user", f"{request_data.message_id}:user", current_message_history)
        else:
            request_data.focus_phase_state = {r.state.focus_id: r.state.model_dump() for r in focus_phase_runtimes}
        yield phase_state_marker()
        # Report the effective phase after the user gate, matching actual inference.
        yield {"__debug_metadata__": True, "system_prompt": ("[Transient private context omitted]" if agentic_context.first_party(request_data) else full_system_prompt),
            "system_prompt_char_count": len(full_system_prompt),
            "available_tools": [{"name": t.get("function", {}).get("name", "unknown"),
                "description_preview": str(t.get("function", {}).get("description", ""))[:TOOL_DESCRIPTION_PREVIEW_LENGTH]}
                for t in available_tools_for_llm],
            "available_tools_count": len(available_tools_for_llm),
            "message_history_sent_to_llm": debug_message_history,
            "message_history_total_count": len(current_message_history)}

    agentic_section = ""
    applied_guides = []
    last_applied_rule_key = agentic_context.last_rule_set_key(request_data.message_history)
    last_context_identity = None
    pending_direction = None
    applied_context_revision = 0
    decision_model = ((skill_config_dict or {}).get("default_llms") or {}).get("decision_model") or "typesafe/jev-1.13"
    review_model = ((skill_config_dict or {}).get("default_llms") or {}).get("preprocessing_model")

    async def refresh_agentic_context(*, initial=False):
        nonlocal agentic_section, applied_guides, last_context_identity
        nonlocal full_system_prompt, answer_recovery_system_prompt
        nonlocal active_project_focus, project_phase_prompt_section, active_focus_prompt_section
        if agentic_context.first_party(request_data):
            fresh = await agentic_context.fresh_project(request_data, directus_service, cache_service)
            old_identity = (active_project_focus or {}).get("activation_id")
            fresh_identity = (fresh or {}).get("activation_id")
            if old_identity != fresh_identity or (fresh or {}).get("instruction") != (active_project_focus or {}).get("instruction"):
                if project_phase_prompt_section:
                    full_system_prompt = full_system_prompt.replace(project_phase_prompt_section, "", 1)
                    answer_recovery_system_prompt = answer_recovery_system_prompt.replace(project_phase_prompt_section, "", 1)
                active_project_focus = fresh
                request_data.active_project_focus = fresh
                request_data.current_project = ({key: fresh.get(key) for key in
                    ("project_id", "project_id_hash", "team_id", "team_id_hash")} if fresh else None)
                project_phase_prompt_section = build_project_focus_prompt(fresh, active_project_sources) if fresh else None
                if project_phase_prompt_section:
                    full_system_prompt += "\n\n" + project_phase_prompt_section
                    answer_recovery_system_prompt += "\n\n" + project_phase_prompt_section
                focus_phase_runtimes[:] = [r for r in focus_phase_runtimes
                    if r.state.focus_id == request_data.active_focus_id]
            if str(request_data.active_focus_id or "").startswith("project-focus:"):
                private = await agentic_context.private_focus_document(
                    request_data, request_data.active_focus_id, directus_service, cache_service)
                if not private:
                    if active_focus_prompt_section:
                        full_system_prompt = full_system_prompt.replace(active_focus_prompt_section, "", 1)
                        answer_recovery_system_prompt = answer_recovery_system_prompt.replace(active_focus_prompt_section, "", 1)
                    active_focus_prompt_section = None
                    request_data.active_focus_id = None
                    focus_phase_runtimes[:] = [r for r in focus_phase_runtimes if not r.state.focus_id.startswith("project-focus:")]
        identity = (request_data.active_focus_id, (request_data.current_project or {}).get("project_id"),
                    (active_project_focus or {}).get("activation_id"),
                    tuple((r.state.focus_id, r.state.phase_id) for r in focus_phase_runtimes))
        if identity == last_context_identity:
            return
        eligible = sorted(set(discovered_apps_metadata) if assigned_app_ids is None
                          else set(discovered_apps_metadata).intersection(assigned_app_ids))
        section, guides = await _load_main_agentic_context(
            request=request_data, task_id=task_id, preprocessing=preprocessing_results,
            directus=directus_service, cache=cache_service, secrets_manager=secrets_manager,
            eligible_app_ids=eligible, vault_key_id=user_vault_key_id, decision_model=decision_model,
            effective_instructions="\n\n".join(filter(None, (active_focus_prompt_section, project_phase_prompt_section))),
            active_phase=";".join(str(r.state.phase_id) for r in focus_phase_runtimes), initial=initial,
            explicit_dependency_task_ids=frozenset(str(row.get("task_id") or row.get("id"))
                for row in (task_tool_context.referenced_tasks if task_tool_context else [])),
        )
        for prior in (agentic_section,):
            if prior:
                full_system_prompt = full_system_prompt.replace("\n\n" + prior, "", 1)
                answer_recovery_system_prompt = answer_recovery_system_prompt.replace("\n\n" + prior, "", 1)
        agentic_section, applied_guides, last_context_identity = section, guides, identity
        if section:
            full_system_prompt += "\n\n" + section
            answer_recovery_system_prompt += "\n\n" + section

    await refresh_agentic_context(initial=True)
    mark_project_reference_setup("agentic_context")

    for iteration in range(max_iterations_with_recovery):
        if iteration == 0:
            mark_project_reference_setup("first_iteration")
        logger.info(f"{log_prefix} LLM call iteration {iteration + 1}/{max_iterations_with_recovery}, total_skill_calls={total_skill_calls}")
        # Capture newly completed results before context fitting can drop older
        # tool turns. Recovery projects from this preserved evidence, never from
        # another model's already-truncated recovery request.
        if not answer_recovery.active:
            answer_recovery.observe(current_message_history)
        
        # The fifth and optional recovery calls are answer-only, regardless of
        # remaining skill budget or Deep research routing.
        if iteration >= MAX_TOOL_CALL_ITERATIONS - 1 and not force_no_tools:
            force_no_tools = True
            if not budget_warning_injected:
                budget_warning_injected = True
            logger.info(
                f"{log_prefix} [MAX_ITERATIONS] Last iteration ({iteration + 1}/{MAX_TOOL_CALL_ITERATIONS}) - "
                f"forcing tool_choice='none' to ensure final answer is generated."
            )
        
        # Determine tool_choice based on budget state
        # If we've hit the hard limit or this is the last iteration, force the LLM to answer without tools
        if force_no_tools:
            current_tool_choice = "none"
            logger.info(
                f"{log_prefix} [SKILL_BUDGET] Forcing tool_choice='none' - LLM must answer with gathered information "
                f"(total_skill_calls={total_skill_calls}, hard_limit={HARD_LIMIT_SKILL_CALLS})"
            )
        else:
            current_tool_choice = "auto"

        if not force_no_tools:
            current_tool_choice = resolve_deep_research_tool_choice(
                current_tool_choice,
                active_focus_id=request_data.active_focus_id,
                chat_depth=chat_depth,
                is_sub_chat_continuation=request_data.is_sub_chat_continuation,
            )
        if current_tool_choice == "required":
            logger.info(
                f"{log_prefix} [SUB_CHAT] Requiring start_sub_chats for active Deep research."
            )
        
        iteration_tools = available_tools_for_llm if not force_no_tools else None
        await refresh_agentic_context()
        # Build system prompt for this iteration
        # Inject budget warning if we've exceeded the soft limit
        iteration_system_prompt = answer_recovery_system_prompt if answer_recovery.active else full_system_prompt
        if budget_warning_injected:
            if follow_up_suggestions_enabled:
                budget_guidance = (
                    "If you need more information to fully answer the user's question, suggest specific follow-up questions "
                    "the user could ask, rather than making additional research calls.\n"
                )
            else:
                budget_guidance = (
                    "If you need more information to fully answer the user's question, state the limitation briefly "
                    "without adding optional follow-up questions or suggested next prompts.\n"
                )
            budget_warning = (
                "\n\n--- IMPORTANT: Research Budget Limit ---\n"
                "You have used most of your available research calls for this response. "
                "Please provide the best possible answer using the information you have already gathered. "
                f"{budget_guidance}"
                "--- End Research Budget Warning ---\n"
            )
            iteration_system_prompt += budget_warning
            logger.info(f"{log_prefix} [SKILL_BUDGET] Injected budget warning into system prompt")

        if answer_recovery.active:
            iteration_system_prompt += "\n\n" + ANSWER_RECOVERY_INSTRUCTION

        if omitted_news_search_requests:
            iteration_system_prompt += (
                "\n\nThe news search budget omitted some requested searches. "
                "Identify those topics as unsearched, and cite only results actually returned by the news tool. "
                "Never invent a headline, date, source, or embed reference for an omitted search."
            )

        # Inject embed preview instruction when images-search was executed
        if images_search_executed:
            image_embed_instruction = (
                "\n\n--- IMPORTANT: Image Search Results Available ---\n"
                "You have image search results available. You MUST include them visually in your response "
                "using large embed preview cards. For each relevant image result, use the syntax:\n"
                "[!](embed:embed_ref)\n"
                "Place each image card on its own line. When showing multiple images, place them consecutively "
                "to create a carousel. Use the embed_ref values from the image search tool results.\n"
                "--- End Image Search Instructions ---\n"
            )
            iteration_system_prompt = iteration_system_prompt + image_embed_instruction
            logger.info(f"{log_prefix} [IMAGE_SEARCH] Injected embed preview instruction into system prompt")

        # === MODEL FALLBACK RETRY LOGIC ===
        # Try models in sequence until one succeeds or all fail
        # This handles transient API errors, rate limits, and model availability issues
        llm_stream = None
        preparation_failure_reason: Optional[str] = None
        model_fallback_attempts = 0
        last_model_error = None
        current_ai_operation_id: Optional[str] = None

        while current_model_index < len(models_to_try):
            try:
                current_model_id = models_to_try[current_model_index]
                model_fallback_attempts += 1
                # Tool results and prompt additions grow between iterations, and a
                # fallback model can have a different context window. Re-fit before
                # every provider call while preserving the newest tool/user tail.
                current_history_budget = model_history_token_budget(
                    current_model_id,
                    config_manager,
                    system_prompt=iteration_system_prompt,
                    tools=iteration_tools,
                )
                if answer_recovery.active:
                    # Normalize tool results through the existing content-safety
                    # and ignore-fields path before converting them to evidence.
                    current_message_history = build_answer_recovery_history(
                        _transform_message_history_for_llm(answer_recovery.recovery_history()),
                        request_data.current_user_content,
                        max_tokens=current_history_budget,
                        published_prefix="".join(published_answer_text),
                    )
                else:
                    current_message_history = truncate_message_history_to_token_budget(
                        current_message_history,
                        max_tokens=current_history_budget,
                    )
                current_output_token_limit = _orchestrated_ai_output_token_limit(
                    current_model_id,
                    request_data.orchestration_id,
                    bool(getattr(request_data, "is_anonymous", False)),
                )
                current_output_token_limit = await _fit_parent_continuation_output_token_limit(
                    model_id=current_model_id,
                    system_prompt=iteration_system_prompt,
                    message_history=current_message_history,
                    tools=iteration_tools,
                    requested_output_token_limit=current_output_token_limit,
                    request_data=request_data,
                    directus_service=directus_service,
                    log_prefix=log_prefix,
                )
                current_output_token_limit = _fit_workflow_output_token_limit(
                    model_id=current_model_id,
                    system_prompt=iteration_system_prompt,
                    message_history=current_message_history,
                    tools=iteration_tools,
                    requested_output_token_limit=current_output_token_limit,
                    request_data=request_data,
                )
                current_output_token_limit = await _fit_anonymous_output_token_limit(
                    model_id=current_model_id,
                    system_prompt=iteration_system_prompt,
                    message_history=current_message_history,
                    tools=iteration_tools,
                    requested_output_token_limit=current_output_token_limit,
                    request_data=request_data,
                )
                personal_normal_chat = (
                    _normal_chat_cache_pricing_scope(request_data)
                    and not getattr(request_data, "team_id", None)
                )
                if personal_normal_chat and current_output_token_limit is None:
                    current_output_token_limit = _personal_chat_output_token_limit(current_model_id)

                if model_fallback_attempts > 1:
                    logger.warning(
                        f"{log_prefix} MODEL_FALLBACK: Attempting fallback model #{current_model_index + 1}: {current_model_id} "
                        f"(previous error: {last_model_error})"
                    )

                current_ai_operation_id = await _reserve_ai_iteration(
                    task_id=task_id,
                    iteration=iteration,
                    model_id=current_model_id,
                    system_prompt=iteration_system_prompt,
                    message_history=current_message_history,
                    tools=iteration_tools,
                    output_token_limit=current_output_token_limit,
                    request_data=request_data,
                    directus_service=directus_service,
                )
                if pending_direction and review_model:
                    context, assessment = pending_direction
                    pending_direction = None
                    async def still_current(authority):
                        return await _direction_authority_current(
                            request=request_data, authority=authority, task_id=task_id,
                            cache=cache_service, directus=directus_service,
                            expected_plan_summary=context.accepted_plan_summary)
                    def append_correction(instruction):
                        nonlocal full_system_prompt, answer_recovery_system_prompt, iteration_system_prompt
                        section = "\n\n--- Internal direction instruction ---\n" + instruction
                        full_system_prompt += section
                        answer_recovery_system_prompt += section
                        iteration_system_prompt += section
                    event = await chat_direction_correction_coordinator.review_and_deliver(
                        context=context, assessment=assessment,
                        review=lambda c, a: _review_chat_direction(c, a, task_id=task_id,
                            model_id=review_model, secrets_manager=secrets_manager),
                        still_current=still_current,
                        deliver=lambda authority, instruction: _deliver_direction_instruction(
                            request=request_data, task_id=task_id, authority=authority, cache=cache_service,
                            instruction=instruction, fingerprint=assessment.fingerprint, append=append_correction,
                            validate_context=lambda: still_current(authority)),
                    )
                    if event:
                        yield {"__chat_context_applied__": True,
                               "receipt": agentic_context.receipt_event(request_data, event)}
                if not agentic_section or agentic_section in iteration_system_prompt:
                    receipt = applied_rule_receipt(applied_guides, previous_set_key=last_applied_rule_key)
                    new_rule_key = applied_rule_set_key(applied_guides)
                    if new_rule_key != last_applied_rule_key:
                        applied_context_revision += 1
                    last_applied_rule_key = new_rule_key
                    if receipt:
                        receipt["context_revision"] = str(applied_context_revision) + ":" + ";".join(
                            f"{r.state.focus_id}:{r.state.run_id}:{r.state.version}" for r in focus_phase_runtimes)
                    if receipt:
                        yield {"__chat_context_applied__": True,
                               "receipt": agentic_context.receipt_event(request_data, receipt)}
                native_prepared_context = None
                reservation_system_prompt = iteration_system_prompt
                reservation_history = current_message_history
                reservation_tools = iteration_tools
                native_route = native_cache_route(current_model_id) if native_scope else None
                native_admission_reason = "route_unavailable"
                if (
                    native_route and current_model_index == 0 and not answer_recovery.active
                    # Answer-only recovery replaces the provider transcript
                    # and is excluded by the answer_recovery.active guard.
                    and cacheable_system_prefix
                    and len(current_message_history) >= len(request_data.message_history)
                    and sanitize_text_simple(iteration_system_prompt) == iteration_system_prompt
                ):
                    native_host, native_server_model = native_route
                    try:
                        if native_state is None:
                            new_user_message = _transform_message_history_for_llm(
                                [_llm_history_message(request_data.message_history[-1])]
                            )[0]
                            native_state = (
                                resume_native_segment(
                                    native_prior_state, model_id=current_model_id,
                                    server_model_id=native_server_model,
                                    provider_prefix=native_host,
                                    cacheable_system_prefix=cacheable_system_prefix,
                                    visible_history=request_data.message_history,
                                    new_user_message=new_user_message,
                                ) if native_prior_state else None
                            )
                            if native_state is None:
                                native_state = new_native_segment(
                                    model_id=current_model_id, server_model_id=native_server_model,
                                    provider_prefix=native_host,
                                    cacheable_system_prefix=cacheable_system_prefix,
                                    selected_tools=iteration_tools or [],
                                    messages=[{"role": "system", "content": cacheable_system_prefix},
                                              *_transform_message_history_for_llm(current_message_history)],
                                    visible_history=request_data.message_history,
                                )
                            native_main_cursor = len(current_message_history)
                            native_main_snapshot = copy.deepcopy(current_message_history)
                        elif native_main_cursor is not None:
                            delta = current_message_history[native_main_cursor:]
                            unexpected_delta = bool(delta) and (
                                delta[0].get("role") != "assistant"
                                or any(item.get("role") != "tool" for item in delta[1:])
                            )
                            if (len(current_message_history) < native_main_cursor
                                    or current_message_history[:native_main_cursor] != native_main_snapshot
                                    or unexpected_delta):
                                raise ValueError("Native history diverged from the current tool turn")
                            if delta:
                                append_tool_results(
                                    native_state,
                                    _transform_message_history_for_llm(delta[1:]),
                                )
                            native_main_cursor = len(current_message_history)
                            native_main_snapshot = copy.deepcopy(current_message_history)
                        add_dispatch_event(
                            native_state, system_prompt=iteration_system_prompt,
                            selected_tools=iteration_tools or [], openai=native_host == "openai",
                            clock_instruction=clock_instruction,
                        )
                        candidate = prepare_native_cache_context(
                            native_state, logical_model_id=current_model_id,
                            server_model_id=native_server_model,
                            provider_prefix=native_host,
                            customer_cache_pricing_enabled=native_scope,
                        )
                        if candidate is not None:
                            quote_system, quote_history, quote_tools = native_cache_quote_payload(candidate, native_host)
                            if native_replay_fits_budget(
                                candidate, quote_system=quote_system,
                                quote_history=quote_history, quote_tools=quote_tools,
                                input_token_budget=model_total_input_token_budget(
                                    current_model_id, config_manager,
                                ),
                            ):
                                # Persist the provider-sanitized schemas that
                                # were actually sent, preserving old prefixes.
                                native_state = candidate
                                native_prepared_context = candidate
                                reservation_system_prompt = quote_system
                                reservation_history = quote_history
                                reservation_tools = quote_tools
                                native_admission_reason = "accepted"
                            else:
                                native_admission_reason = "budget_rejected"
                        else:
                            native_admission_reason = "prepare_rejected"
                    except NativeCacheSchemaChanged:
                        # OpenAI cannot mutate a previously introduced schema
                        # in-place. Run this turn cold; the next one can start
                        # a fresh segment with the current definitions.
                        native_state = None
                        native_prior_state = None
                        native_admission_reason = "schema_changed"
                    except (KeyError, TypeError, ValueError, IndexError) as exc:
                        native_state = None
                        native_admission_reason = "cold_reset"
                        logger.info("%s Native history cold reset (%s)", log_prefix, type(exc).__name__)
                    if native_prepared_context is None:
                        native_state = None
                elif native_route:
                    native_admission_reason = (
                        "fallback_model" if current_model_index != 0 else
                        "answer_recovery" if answer_recovery.active else
                        "prefix_empty" if not cacheable_system_prefix else
                        "history_truncated" if len(current_message_history) < len(request_data.message_history) else
                        "prompt_sanitized"
                    )
                if iteration == 0 and current_model_index == 0:
                    _log_native_fixture_admission(
                        native_admission_reason, native_prior_reason,
                        history_count=len(current_message_history),
                        visible_count=len(request_data.message_history),
                    )
                # Personal standalone chats were admitted by the preprocessor's
                # positive-balance check. Bound each dispatch to the remaining
                # wallet capacity without creating a monetary hold. Teams and
                # other authenticated scopes retain their reservation path.
                needs_authenticated_hold = (
                    not getattr(request_data, "is_anonymous", False)
                    and not request_data.orchestration_id
                    and not personal_normal_chat
                )
                if needs_authenticated_hold:
                    current_output_token_limit = await _reserve_authenticated_ai_turn(
                        task_id=task_id, request_data=request_data,
                        model_id=current_model_id,
                        system_prompt=reservation_system_prompt,
                        message_history=reservation_history,
                        tools=reservation_tools,
                        requested_output_token_limit=current_output_token_limit,
                        model_usage_tracker=model_usage_tracker,
                        reservation_state=ordinary_reservation_state,
                    )
                    async def admit_actual_provider(_server_model_id: str, dispatch_limit: Optional[int]) -> int:
                        return await _reserve_authenticated_ai_turn(
                            task_id=task_id, request_data=request_data,
                            model_id=current_model_id,
                            system_prompt=reservation_system_prompt,
                            message_history=reservation_history,
                            tools=reservation_tools,
                            requested_output_token_limit=dispatch_limit,
                            model_usage_tracker=model_usage_tracker,
                            reservation_state=ordinary_reservation_state,
                            inference_host=_server_model_id.split("/", 1)[0],
                        )
                elif personal_normal_chat:
                    async def admit_actual_provider(_server_model_id: str, dispatch_limit: Optional[int]) -> int:
                        return await _fit_personal_chat_output_token_limit(
                            request_data=request_data,
                            cache_service=cache_service,
                            model_usage_tracker=model_usage_tracker,
                            model_id=current_model_id,
                            system_prompt=reservation_system_prompt,
                            message_history=reservation_history,
                            tools=reservation_tools,
                            requested_output_token_limit=dispatch_limit,
                            inference_host=_server_model_id.split("/", 1)[0],
                        )
                else:
                    admit_actual_provider = None
                if iteration == 0 and model_fallback_attempts == 1:
                    mark_project_reference_setup("provider_dispatch")
                llm_stream = call_main_llm_stream(
                    task_id=task_id,
                    system_prompt=iteration_system_prompt,
                    message_history=current_message_history,
                    model_id=current_model_id,  # Use current_model_id from fallback list
                    temperature=preprocessing_results.llm_response_temp,
                    thinking_level=(
                        getattr(preprocessing_results, "selected_main_llm_thinking_level", None)
                        if current_model_id == preprocessing_results.selected_main_llm_model_id
                        else None
                    ),
                    secrets_manager=secrets_manager,
                    tools=iteration_tools,
                    tool_choice=current_tool_choice,
                    max_tokens=current_output_token_limit,
                    # A failed post-tool or forced answer may have already
                    # published text. Let the outer loop rebuild clean evidence
                    # and continue that prefix instead of appending an error.
                    recoverable_attempt=(
                        answer_recovery.active or force_no_tools or tool_inference_iterations > 0
                    ),
                    stop_after_provider_failure=bool(getattr(request_data, "is_anonymous", False)),
                    cacheable_system_prefix=cacheable_system_prefix or None,
                    prompt_cache_key=_mistral_prompt_cache_key(request_data),
                    pre_dispatch_admission=admit_actual_provider,
                    customer_cache_pricing_enabled=_normal_chat_cache_pricing_scope(request_data),
                    native_cache_context=native_prepared_context,
                )
                # Stream created successfully - break out of retry loop
                break

            except AnonymousUsageLimitError:
                logger.warning("%s Anonymous inference allowance exhausted before provider dispatch", log_prefix)
                preparation_failure_reason = "anonymous_usage_limit"
                break
            except AuthenticatedReservationLimitError:
                logger.warning("%s Authenticated inference capacity exhausted before provider dispatch", log_prefix)
                preparation_failure_reason = "stream_error"
                break
            except AuthenticatedReservationError:
                logger.error("%s Authenticated inference reservation failed before provider dispatch", log_prefix, exc_info=True)
                preparation_failure_reason = "stream_error"
                break
            except AnonymousUsageAccountingError:
                logger.error("%s Anonymous inference accounting failed before provider dispatch", log_prefix, exc_info=True)
                preparation_failure_reason = "stream_error"
                break
            except Exception as model_error:
                await _fail_reserved_operation(
                    operation_id=current_ai_operation_id,
                    request_data=request_data,
                    directus_service=directus_service,
                )
                current_ai_operation_id = None
                last_model_error = str(model_error)
                logger.error(
                    f"{log_prefix} MODEL_FALLBACK: Model {current_model_id} failed: {model_error}. "
                    f"Trying next model..."
                )
                if answer_recovery.active:
                    if schedule_answer_recovery("recovery_preparation_failed"):
                        continue
                    break
                current_model_index += 1

                # If we've exhausted all models, raise the last error
                if current_model_index >= len(models_to_try):
                    logger.error(
                        f"{log_prefix} MODEL_FALLBACK: All {len(models_to_try)} models failed. "
                        f"Last error: {last_model_error}"
                    )
                    raise RuntimeError(
                        f"All models failed. Tried: {models_to_try}. Last error: {last_model_error}"
                    ) from model_error

        if llm_stream is None:
            for billing_event in await terminal_billing_usage_events():
                yield billing_event
            yield main_processing_failure(
                preparation_failure_reason
                or ("protocol_guard" if protocol_guard_recovery_started else "empty_post_tool_response")
            )
            break

        protocol_guard = ToolProtocolGuard()
        current_turn_text_buffer = []
        tool_calls_for_this_turn: List[Union[ParsedMistralToolCall, ParsedGoogleToolCall, ParsedAnthropicToolCall, ParsedBedrockToolCall, ParsedOpenAIToolCall]] = []
        # Hallucinated tool calls that must round-trip through the history as
        # matched (tool_use, tool_result) pairs. If we appended only the tool
        # result without the corresponding tool_use block, the next LLM call
        # would crash with "toolResult blocks exceeds toolUse blocks" on
        # Bedrock / "Function call is missing a thought_signature" on Gemini.
        # Stored as (tool_call_obj, rejection_message_dict) so the assistant
        # message (line ~2599) can include them in its tool_calls list and the
        # rejection tool messages are appended right after.
        hallucinated_tool_calls_this_turn: List[Tuple[Any, Dict[str, Any]]] = []
        hallucinated_rejections_this_turn = 0
        llm_turn_had_content = False
        forbidden_tool_call_seen = False
        
        # Dictionary to store placeholder embeds created for tool calls during stream processing
        # Key: tool_call_id, Value: placeholder_embed_data dict
        # This allows us to create placeholders IMMEDIATELY when tool calls are detected,
        # showing the "processing" state to users before skill execution starts
        inline_placeholder_embeds: Dict[str, Dict[str, Any]] = {}
        focus_activation_seen_this_turn = False

        # Sync streaming budget counter with execution-phase counter at each iteration start
        # so it carries over correctly from previous iterations
        streaming_skill_count = total_skill_calls
        
        # Flag set when AllServersFailedError is caught during stream consumption.
        # When set, the outer loop will attempt the next model in the fallback list.
        _stream_all_servers_failed = False
        _stream_all_servers_error: Optional[AllServersFailedError] = None
        iteration_usage: Optional[Union[MistralUsage, GoogleUsageMetadata, AnthropicUsageMetadata, BedrockUsageMetadata, OpenAIUsageMetadata]] = None
        iteration_input_tokens = 0
        iteration_output_tokens = 0
        iteration_normalized_usage_by_attempt: Dict[str, Any] = {}
        iteration_native_output: Optional[NativeCacheProviderOutput] = None
        native_terminal_ready = False
        try:
          with ai_phase_span("main.iteration"):
           # Observe raw provider delivery before paragraph aggregation so
           # ai.ttft_ms/ai.first_text_ms are not inflated by presentation
           # buffering. The downstream paragraph contract remains unchanged.
           observed_llm_stream = observe_ai_stream(
               llm_stream,
               "provider",
               provider_purpose="main",
           )
           async for chunk in protocol_guard.filter(observed_llm_stream):
            if isinstance(chunk, NativeCacheProviderOutput):
                # Provider reasoning/output is private replay state. It is
                # neither a product stream event nor a debug/usage payload.
                iteration_native_output = chunk
                continue
            if isinstance(chunk, (MistralUsage, GoogleUsageMetadata, AnthropicUsageMetadata, BedrockUsageMetadata, OpenAIUsageMetadata)):
                iteration_usage = chunk
                last_reported_usage = chunk
                # Keep the final usage object local until the stream completes so
                # a failed attempt cannot become the recorded successful model.
                # Provider-reported tokens are still accumulated immediately:
                # once reported, that incurred usage remains billable even if a
                # later stream event triggers fallback.
                normalized_usage = getattr(chunk, "_normalized_llm_usage", None)
                previous_input = model_usage_tracker.total_input_tokens
                previous_output = model_usage_tracker.total_output_tokens
                _iter_input = 0
                _iter_output = 0
                if normalized_usage is not None:
                    usage_model_id = normalized_usage.model_id
                    model_usage_tracker.record_reported_usage(
                        model_id=usage_model_id,
                        normalized_usage=normalized_usage,
                        attempt_id=normalized_usage.attempt_id,
                    )
                    if normalized_usage.attempt_id:
                        iteration_normalized_usage_by_attempt[normalized_usage.attempt_id] = normalized_usage
                    _iter_input = model_usage_tracker.total_input_tokens - previous_input
                    _iter_output = model_usage_tracker.total_output_tokens - previous_output
                elif isinstance(chunk, MistralUsage):
                    _iter_input = chunk.prompt_tokens or 0
                    _iter_output = chunk.completion_tokens or 0
                elif isinstance(chunk, GoogleUsageMetadata):
                    _iter_input = chunk.prompt_token_count or 0
                    _iter_output = chunk.candidates_token_count or 0
                elif isinstance(chunk, (AnthropicUsageMetadata, BedrockUsageMetadata)):
                    _iter_input = chunk.input_tokens or 0
                    _iter_output = chunk.output_tokens or 0
                elif isinstance(chunk, OpenAIUsageMetadata):
                    _iter_input = chunk.input_tokens or 0
                    _iter_output = chunk.output_tokens or 0
                iteration_input_tokens += _iter_input
                iteration_output_tokens += _iter_output
                usage_model_id = current_model_id or preprocessing_results.selected_main_llm_model_id
                if usage_model_id and normalized_usage is None:
                    model_usage_tracker.record_reported_usage(
                        model_id=usage_model_id,
                        input_tokens=_iter_input,
                        output_tokens=_iter_output,
                        user_input_tokens=chunk.user_input_tokens,
                        system_prompt_tokens=chunk.system_prompt_tokens,
                    )
                logger.debug(
                    f"{log_prefix} [ITERATION_TOKENS] Iteration {iteration + 1}: "
                    f"+{_iter_input} input, +{_iter_output} output tokens. "
                    f"Billed totals: {model_usage_tracker.total_input_tokens} in / "
                    f"{model_usage_tracker.total_output_tokens} out"
                )
                continue
            if isinstance(chunk, (ParsedMistralToolCall, ParsedGoogleToolCall, ParsedAnthropicToolCall, ParsedBedrockToolCall, ParsedOpenAIToolCall)):
                if force_no_tools:
                    # The provider may return a function call even after a
                    # no-tools request. Never create a placeholder or execute
                    # that call: the remaining budget belongs to the answer.
                    forbidden_tool_call_seen = True
                    logger.warning(
                        "%s [MAX_ITERATIONS] Ignoring provider tool call while tools are disabled: %s",
                        log_prefix,
                        chunk.function_name,
                    )
                    continue
                # === STRICT ALLOW-LIST (OPE-399) ===
                # Reject any tool call whose name is not in the preprocessor-provided
                # tool list BEFORE it is appended for execution. This prevents
                # hallucinated skills (e.g. "mail|get_apps_settings") from reaching
                # skill execution via the broken fallback splitter.
                #
                # Separator normalization (OPE-399 follow-up): different providers
                # emit different separators for the same canonical skill. Gemini 3
                # Flash emits 'web:search', older models sometimes emit 'web_search',
                # the canonical form is 'web-search'. We normalize the emitted name
                # to the hyphen form before the allow-list check so a legitimately
                # preselected tool isn't rejected just because the provider picked
                # the "wrong" separator. The allow-list itself stays strict —
                # non-preselected skills are still hallucinations regardless of
                # separator format. See _canonicalize_tool_name() for details.
                raw_function_name = chunk.function_name
                canonical_name = explicit_task_app_skill_tool_name(raw_function_name, task_app_skill_mentions)
                normalized_from_explicit_task_app = canonical_name != _canonicalize_tool_name(raw_function_name)
                is_sub_chat_violation = (canonical_name == "start-sub-chats" and chat_depth >= 2)
                if (
                    canonical_name not in allowed_tool_names or canonical_name == "projects-search"
                    or is_sub_chat_violation
                ):
                    rejection_reason = "Nesting depth limit exceeded: Tier 2 (grandchild) chats cannot spawn sub-chats." if is_sub_chat_violation else INVALID_TOOL_RESULT_REASON
                    raw_arguments_log = "" if _is_task_tool_like(canonical_name) or _is_task_tool_like(raw_function_name) else f"Raw arguments: {chunk.function_arguments_raw[:500]}"
                    logger.warning(
                        f"{log_prefix} [HALLUCINATION/BLOCK] Rejecting tool call "
                        f"'{raw_function_name}' (canonical='{canonical_name}') "
                        f"from main LLM. tool_call_id={chunk.tool_call_id}. "
                        f"Nesting violation: {is_sub_chat_violation}. "
                        f"Allowed tools ({len(allowed_tool_names)}): {sorted(allowed_tool_names)}. "
                        f"{raw_arguments_log}"
                    )
                    # Defer both the assistant tool_use block AND its rejection
                    # tool_result message. The assistant message is built after
                    # the stream ends (line ~2609); without the matching tool_use
                    # block, the next LLM call crashes on conversation integrity
                    # checks (Bedrock: "toolResult exceeds toolUse", Gemini:
                    # "Function call is missing a thought_signature"). We therefore
                    # stash the rejected chunk + its rejection message and inject
                    # both together right after the assistant message is appended,
                    # so the pair is correctly matched in history.
                    rejection_tool_message = {
                        "tool_call_id": chunk.tool_call_id,
                        "role": "tool",
                        "name": raw_function_name,
                        "content": json.dumps({
                            "status": "rejected",
                            "reason": rejection_reason,
                        }),
                    }
                    hallucinated_tool_calls_this_turn.append((chunk, rejection_tool_message))
                    hallucinated_rejections_this_turn += 1
                    continue

                # Rewrite the chunk's function_name to the canonical form so all
                # downstream code paths (placeholder creation, tool_resolver_map
                # lookup, skill execution, dedup hashing) see a consistent hyphen
                # form regardless of which separator the provider emitted.
                if canonical_name != raw_function_name and (normalized_from_explicit_task_app or not _is_task_tool_like(raw_function_name)):
                    logger.info(
                        f"{log_prefix} Normalized tool call name: "
                        f"'{raw_function_name}' -> '{canonical_name}'"
                    )
                    chunk.function_name = canonical_name

                tool_calls_for_this_turn.append(chunk)

                # === IMMEDIATE PLACEHOLDER CREATION ===
                # Create and yield the embed placeholder as soon as a tool call is detected
                # This shows the "processing" state to users BEFORE skill execution starts
                try:
                    tool_name = chunk.function_name
                    tool_arguments_str = chunk.function_arguments_raw
                    tool_call_id = chunk.tool_call_id

                    # Parse arguments to extract metadata for placeholder
                    try:
                        parsed_args = json.loads(tool_arguments_str)
                    except json.JSONDecodeError:
                        parsed_args = {}
                        logger.warning(f"{log_prefix} Failed to parse tool arguments for inline placeholder, using empty dict")

                    # Resolve tool name to app_id and skill_id. After the allow-list
                    # check above, the resolver is guaranteed to succeed for any
                    # tool_name derived from available_tools_for_llm.
                    resolved_tool = tool_resolver_map.get(tool_name)
                    if resolved_tool:
                        app_id, skill_id = resolved_tool
                    else:
                        # Defensive: allow-list passed but resolver missed — log and skip
                        # this placeholder rather than fabricate ("unknown", "unknown").
                        logger.error(
                            f"{log_prefix} [INVARIANT] Allowed tool '{tool_name}' missing from "
                            f"tool_resolver_map. Skipping placeholder creation."
                        )
                        continue

                    if learning_mode_active and is_learning_mode_blocked_skill(app_id, skill_id):
                        logger.info(
                            f"{log_prefix} [LEARNING_MODE] Suppressing placeholder for "
                            f"blocked skill '{app_id}.{skill_id}'."
                        )
                        if tool_calls_for_this_turn and tool_calls_for_this_turn[-1] is chunk:
                            tool_calls_for_this_turn.pop()
                        rejection_tool_message = {
                            "tool_call_id": tool_call_id,
                            "role": "tool",
                            "name": tool_name,
                            "content": json.dumps({
                                "status": "rejected",
                                "reason": (
                                    "This tool is unavailable while Learning Mode is active. "
                                    "Teach the method without calculating the final answer."
                                ),
                            }),
                        }
                        hallucinated_tool_calls_this_turn.append((chunk, rejection_tool_message))
                        hallucinated_rejections_this_turn += 1
                        continue

                    if (
                        app_id == "audio"
                        and skill_id == "transcribe"
                        and (audio_transcribe_blocked_by_recording or should_block_local_audio_transcription(
                            parsed_args, request_data.message_history,
                        ))
                    ):
                        logger.warning(
                            f"{log_prefix} [AUDIO_RECORDING_GUARD] Rejecting '{tool_name}' before placeholder creation: "
                            "web UI audio recording already has transcript text."
                        )
                        if tool_calls_for_this_turn and tool_calls_for_this_turn[-1] is chunk:
                            tool_calls_for_this_turn.pop()
                        rejection_tool_message = {
                            "tool_call_id": chunk.tool_call_id,
                            "role": "tool",
                            "name": tool_name,
                            "content": json.dumps({
                                "status": "rejected",
                                "reason": (
                                    "This voice recording uses local transcription or already has a transcript. "
                                    "Use any available transcript; do not retry it with an external provider."
                                ),
                            }),
                        }
                        hallucinated_tool_calls_this_turn.append((chunk, rejection_tool_message))
                        hallucinated_rejections_this_turn += 1
                        continue

                    parsed_args = _normalize_skill_arguments(
                        arguments=parsed_args,
                        app_id=app_id,
                        skill_id=skill_id,
                        discovered_apps_metadata=discovered_apps_metadata,
                        task_id=task_id,
                        message_history=current_message_history,
                    )
                    parsed_args = _apply_repository_relevance_criteria_guard(
                        parsed_args,
                        app_id,
                        skill_id,
                        current_message_history,
                        log_prefix,
                    )

                    if app_id == "news" and skill_id == "search" and not getattr(request_data, "is_anonymous", False):
                        parsed_args, omitted_inline_news_requests = _limit_news_search_batch_to_budget(
                            parsed_args, HARD_LIMIT_SKILL_CALLS - streaming_skill_count
                        )
                        if omitted_inline_news_requests:
                            logger.info(
                                "%s INLINE: [SKILL_BUDGET] Limiting news-search placeholder batch to %s requests; "
                                "%s omitted.",
                                log_prefix,
                                len(parsed_args["requests"]),
                                len(omitted_inline_news_requests),
                            )

                    if app_id == "system" and skill_id == "activate_focus_mode":
                        focus_activation_seen_this_turn = True
                    elif is_legacy_task_runtime_tool_name(tool_name):
                        logger.debug(f"{log_prefix} INLINE: Task tool '{tool_name}' does not use app-skill placeholders.")
                        continue
                    elif focus_activation_seen_this_turn and app_id != "system":
                        logger.info(
                            f"{log_prefix} [FOCUS_EXCLUSIVITY] Suppressing inline placeholder for "
                            f"'{tool_name}' because activate_focus_mode was already emitted in this turn."
                        )
                        continue
                     
                    # === DEDUPLICATION CHECK (INLINE PLACEHOLDER PHASE) ===
                    # Check if this exact skill call was already executed in a previous iteration.
                    # If so, skip creating placeholder - the execution phase will also skip it.
                    # This prevents duplicate embeds from appearing in the stream.
                    call_hash = _hash_skill_arguments(app_id, skill_id, parsed_args)
                    if call_hash in completed_skill_calls:
                        logger.info(
                            f"{log_prefix} INLINE: [DEDUP] Skipping placeholder for duplicate '{app_id}.{skill_id}' "
                            f"(hash={call_hash[:8]}...). Already executed successfully in a previous iteration."
                        )
                        # Don't create placeholder embed - skip to next chunk
                        # The execution phase will also detect this duplicate and skip execution
                        continue
                    
                    # === STREAMING-PHASE BUDGET CHECK ===
                    # Count requests in this tool call to check against budget.
                    # Skip placeholder creation entirely when the budget would be exceeded,
                    # preventing phantom "Searching..." cards that flash then transition to error.
                    _streaming_requests_count = 1
                    _streaming_requests_list = parsed_args.get("requests", []) if isinstance(parsed_args, dict) else []
                    if isinstance(_streaming_requests_list, list) and len(_streaming_requests_list) > 0:
                        _streaming_requests_count = len(_streaming_requests_list)

                    if app_id != "system" and (
                        streaming_skill_count >= HARD_LIMIT_SKILL_CALLS
                        or streaming_skill_count + _streaming_requests_count > HARD_LIMIT_SKILL_CALLS
                    ):
                        logger.info(
                            f"{log_prefix} INLINE: [BUDGET_SKIP] Suppressing placeholder for '{tool_name}' "
                            f"({_streaming_requests_count} requests) - would exceed budget "
                            f"(streaming_skill_count={streaming_skill_count}, limit={HARD_LIMIT_SKILL_CALLS})"
                        )
                        continue  # Skip placeholder creation entirely

                    # Create placeholder embed IMMEDIATELY (before skill execution)
                    # Skip for system tools (e.g., activate_focus_mode, deactivate_focus_mode)
                    # because they create their own specific embed types (focus_mode_activation)
                    # rather than the generic app_skill_use placeholder
                    if cache_service and user_vault_key_id and directus_service and app_id != "unknown" and app_id != "system":
                        from backend.core.api.app.services.embed_service import EmbedService
                        
                        # Use passed-in encryption_service
                        embed_service = EmbedService(
                            cache_service=cache_service,
                            directus_service=directus_service,
                            encryption_service=encryption_service
                        )
                        
                        # Extract metadata for placeholder display
                        # Handle both direct args (query) and nested args (requests[0].query)
                        # CRITICAL: This metadata is included in the embed placeholder so the frontend
                        # can display the query immediately while the skill executes
                        
                        # Check if we have multiple requests
                        requests_list = parsed_args.get("requests", []) if isinstance(parsed_args, dict) else []
                        is_multiple_requests = isinstance(requests_list, list) and len(requests_list) > 1
                        
                        if is_multiple_requests:
                            # MULTIPLE REQUESTS: Create one placeholder per request
                            logger.info(
                                f"{log_prefix} INLINE: Detected {len(requests_list)} requests, creating placeholders for each"
                            )
                            
                            # Store multiple placeholders - key by request index/id for later matching
                            placeholder_embeds_list = []
                            
                            for request_idx, request in enumerate(requests_list):
                                if not isinstance(request, dict):
                                    continue
                                
                                # Extract ALL input parameters for this specific request
                                # This ensures placeholders include all relevant metadata (query, url, languages, etc.)
                                # not just query and provider
                                request_metadata = {}
                                
                                # Copy all input parameters from the request to metadata
                                # This preserves all skill-specific parameters (url for videos, query for search, etc.)
                                for key, value in request.items():
                                    # Skip internal metadata fields (id is handled separately)
                                    if key != "id":
                                        request_metadata[key] = value
                                
                                # Provider from request or fallback (for search skills).
                                # Validate against the skill's known providers list to prevent
                                # LLM hallucination (e.g. 'Brave Search' for the events skill).
                                raw_provider = request_metadata.get("provider")
                                if raw_provider is not None or skill_id == "search":
                                    validated_provider = _validate_skill_provider(
                                        provider=raw_provider,
                                        app_id=app_id,
                                        skill_id=skill_id,
                                        discovered_apps_metadata=discovered_apps_metadata,
                                        log_prefix=log_prefix,
                                    )
                                    if validated_provider is not None:
                                        request_metadata["provider"] = validated_provider

                                preview_metadata = await _resolve_skill_preview_metadata(
                                    app_id=app_id,
                                    skill_id=skill_id,
                                    request_metadata=request_metadata,
                                    discovered_apps_metadata=discovered_apps_metadata,
                                    log_prefix=log_prefix,
                                )
                                request_metadata.update(preview_metadata)
                                
                                # Add request ID for later matching
                                # ALWAYS auto-generate 1-indexed IDs - ignore any LLM-provided IDs
                                # This ensures consistency between placeholder creation here and
                                # skill execution in base_skill.py which respects provided IDs
                                # LLMs may provide 0-indexed or arbitrary IDs despite schema instructions,
                                # so we enforce our own ID scheme for reliable matching
                                request_id = request_idx + 1
                                # SET the ID in the request dict so skill receives our auto-generated ID
                                # This overwrites any LLM-provided ID in the request
                                request["id"] = request_id
                                # Normalize to string for consistent matching (handles int/str mismatches)
                                request_id_normalized = str(request_id)
                                request_metadata["request_id"] = request_id
                                
                                # Log all extracted metadata for debugging
                                metadata_summary = (
                                    ", ".join(sorted(k for k in request_metadata if k != "request_id"))
                                    if app_id == "hosting"
                                    else ", ".join(f"{k}={v}" for k, v in request_metadata.items() if k != "request_id")
                                )
                                logger.debug(
                                    f"{log_prefix} INLINE: Creating placeholder {request_idx + 1}/{len(requests_list)}: "
                                    f"request_id={request_id} (normalized={request_id_normalized}), metadata=[{metadata_summary}]"
                                )
                                
                                # Create placeholder for this request
                                placeholder_embed_data = await embed_service.create_processing_embed_placeholder(
                                    app_id=app_id,
                                    skill_id=skill_id,
                                    chat_id=request_data.chat_id,
                                    message_id=request_data.message_id,
                                    user_id=request_data.user_id,
                                    user_id_hash=request_data.user_id_hash,
                                    user_vault_key_id=user_vault_key_id,
                                    task_id=task_id,
                                    metadata=request_metadata,
                                    log_prefix=f"{log_prefix}[request_{request_idx}]"
                                )
                                
                                if placeholder_embed_data:
                                    # Store with normalized request ID for later matching
                                    placeholder_embed_data["request_id"] = request_id_normalized
                                    placeholder_embeds_list.append(placeholder_embed_data)
                                    
                                    # Yield embed reference immediately
                                    embed_reference_json = placeholder_embed_data.get("embed_reference")
                                    if embed_reference_json:
                                        embed_code_block = f"```json\n{embed_reference_json}\n```\n\n"
                                        yield embed_code_block
                                        logger.info(
                                            f"{log_prefix} INLINE: Created and yielded placeholder {request_idx + 1}/{len(requests_list)}: "
                                            f"embed_id={placeholder_embed_data.get('embed_id')}, "
                                            f"request_id={request_id}, "
                                            f"query_present={'query' in request_metadata}, "
                                            f"query_length={len(request_metadata.get('query')) if isinstance(request_metadata.get('query'), str) else 0}"
                                        )
                            
                            # Store list of placeholders for later matching
                            # CRITICAL: Also store the modified parsed_args with our auto-generated IDs
                            # This ensures the execution phase uses the same IDs we assigned here
                            # (parsed_args is parsed separately in both phases from the same tool_arguments_str)
                            if placeholder_embeds_list:
                                inline_placeholder_embeds[tool_call_id] = {
                                    "multiple": True,
                                    "placeholders": placeholder_embeds_list,
                                    "parsed_args": parsed_args  # Store with our modified request IDs
                                }
                                
                                # Publish "processing" status for all requests
                                await _publish_skill_status(
                                    cache_service=cache_service,
                                    task_id=task_id,
                                    request_data=request_data,
                                    app_id=app_id,
                                    skill_id=skill_id,
                                    status="processing",
                                    preview_data={"request_count": len(placeholder_embeds_list)}
                                )

                                # Track streaming budget for multi-request placeholder
                                if app_id != "system":
                                    streaming_skill_count += _streaming_requests_count
                        else:
                            # SINGLE REQUEST: Extract ALL input parameters
                            # This ensures placeholders include all relevant metadata (query, url, languages, etc.)
                            # not just query and provider
                            metadata = {}
                            
                            # If we have a requests array with one item, extract all parameters from that
                            if requests_list and len(requests_list) > 0:
                                first_request = requests_list[0]
                                if isinstance(first_request, dict):
                                    # Copy all input parameters from the first request
                                    for key, value in first_request.items():
                                        if key != "id":  # Skip id field
                                            metadata[key] = value
                                    logger.debug(f"{log_prefix} INLINE: Extracted metadata from requests[0]: {list(metadata.keys())}")
                            else:
                                # Direct parameters (simple skill format without requests array)
                                # Copy all input parameters from parsed_args
                                for key, value in parsed_args.items():
                                    if key not in ['requests']:  # Skip requests array if present
                                        metadata[key] = value
                                logger.debug(f"{log_prefix} INLINE: Extracted metadata from direct args: {list(metadata.keys())}")
                            
                            # Provider validation for search skills.
                            # Validates the provider (from LLM args or absent) against the skill's
                            # known providers list in app.yml to prevent LLM hallucination.
                            if skill_id == "search" or "provider" in metadata:
                                validated_provider = _validate_skill_provider(
                                    provider=metadata.get("provider"),
                                    app_id=app_id,
                                    skill_id=skill_id,
                                    discovered_apps_metadata=discovered_apps_metadata,
                                    log_prefix=log_prefix,
                                )
                                if validated_provider is not None:
                                    metadata["provider"] = validated_provider

                            preview_metadata = await _resolve_skill_preview_metadata(
                                app_id=app_id,
                                skill_id=skill_id,
                                request_metadata=metadata,
                                discovered_apps_metadata=discovered_apps_metadata,
                                log_prefix=log_prefix,
                            )
                            metadata.update(preview_metadata)
                            
                            # Log final metadata for debugging
                            metadata_summary = ", ".join([f"{k}={v}" for k, v in metadata.items()])
                            logger.info(
                                f"{log_prefix} INLINE: Final metadata for placeholder: [{metadata_summary}]"
                            )
                            
                            # Create single placeholder
                            placeholder_embed_data = await embed_service.create_processing_embed_placeholder(
                                app_id=app_id,
                                skill_id=skill_id,
                                chat_id=request_data.chat_id,
                                message_id=request_data.message_id,
                                user_id=request_data.user_id,
                                user_id_hash=request_data.user_id_hash,
                                user_vault_key_id=user_vault_key_id,
                                task_id=task_id,
                                metadata=metadata,
                                log_prefix=log_prefix
                            )
                            
                            if placeholder_embed_data:
                                # Store for later use during skill execution
                                inline_placeholder_embeds[tool_call_id] = placeholder_embed_data
                                
                                # CRITICAL: Yield the embed reference IMMEDIATELY as a code block chunk
                                # This ensures the frontend shows "processing" state BEFORE skill execution starts
                                # The code block format allows the frontend to parse and render the embed placeholder
                                embed_reference_json = placeholder_embed_data.get("embed_reference")
                                if embed_reference_json:
                                    embed_code_block = f"```json\n{embed_reference_json}\n```\n\n"
                                    # Yield immediately - this will be picked up by stream consumer and published right away
                                    yield embed_code_block
                                    
                                    logger.info(
                                        f"{log_prefix} INLINE: Created and yielded processing placeholder code block for '{tool_name}': "
                                        f"embed_id={placeholder_embed_data.get('embed_id')}, "
                                        f"code_block_length={len(embed_code_block)}"
                                    )
                                else:
                                    logger.warning(f"{log_prefix} INLINE: Placeholder embed_data missing embed_reference JSON")
                                
                                # Publish "processing" status immediately via Redis event
                                # This provides additional signal to frontend that skill is processing
                                await _publish_skill_status(
                                    cache_service=cache_service,
                                    task_id=task_id,
                                    request_data=request_data,
                                    app_id=app_id,
                                    skill_id=skill_id,
                                    status="processing",
                                    preview_data=metadata  # Include query/provider in preview
                                )

                                # Track streaming budget for single-request placeholder
                                if app_id != "system":
                                    streaming_skill_count += _streaming_requests_count
                            else:
                                logger.warning(f"{log_prefix} INLINE: Failed to create placeholder embed for '{tool_name}'")
                except Exception as e:
                    # Don't fail the stream processing if inline placeholder creation fails
                    logger.error(f"{log_prefix} INLINE: Error creating placeholder during stream: {e}", exc_info=True)
                
            elif isinstance(chunk, UnifiedStreamChunk):
                # Handle thinking/reasoning content from models like Gemini 3 Pro
                # These chunks contain the model's internal reasoning process
                # Pass them through to stream_consumer which will publish to thinking Redis channel
                if chunk.type == StreamChunkType.THINKING:
                    # Thinking content - yield through for stream_consumer to handle
                    logger.debug(f"{log_prefix} Yielding thinking chunk ({len(chunk.content or '')} chars)")
                    yield chunk
                elif chunk.type == StreamChunkType.THINKING_SIGNATURE:
                    # Thinking signature - yield through for storage
                    logger.debug(f"{log_prefix} Yielding thinking signature")
                    yield chunk
                elif chunk.type == StreamChunkType.TEXT:
                    # Text content wrapped in UnifiedStreamChunk - extract and yield as string
                    if chunk.content:
                        llm_turn_had_content = llm_turn_had_content or _has_visible_text(chunk.content)
                        yield chunk.content
                        current_turn_text_buffer.append(chunk.content)
                        published_answer_text.append(chunk.content)
                else:
                    logger.warning(f"{log_prefix} Unknown UnifiedStreamChunk type: {chunk.type}")
            elif isinstance(chunk, str):
                # CRITICAL: Always yield text chunks immediately, even when tool calls are pending
                # This ensures paragraph-by-paragraph streaming works correctly
                # Tool calls will be executed after the LLM finishes its turn, but text should stream immediately
                if chunk:
                    llm_turn_had_content = llm_turn_had_content or _has_visible_text(chunk)
                    yield chunk
                    # Retain every safe, published chunk. Besides tool history, this
                    # lets a guarded partial answer continue without replaying it.
                    current_turn_text_buffer.append(chunk)
                    published_answer_text.append(chunk)
            else:
                logger.warning(f"{log_prefix} Received unexpected chunk type from stream: {type(chunk)}")
        except (AuthenticatedReservationLimitError, AuthenticatedReservationError) as admission_error:
            logger.warning("%s Authenticated provider dispatch stopped by reservation: %s", log_prefix, type(admission_error).__name__)
            for billing_event in await terminal_billing_usage_events():
                yield billing_event
            yield main_processing_failure("stream_error")
            break
        except AllServersFailedError as asf_err:
            # All servers for the current model failed before yielding any content.
            # Try the next model in the fallback list instead of showing an error.
            _stream_all_servers_failed = True
            _stream_all_servers_error = asf_err
            logger.warning(
                f"{log_prefix} MODEL_FALLBACK: AllServersFailedError during stream consumption "
                f"for model '{models_to_try[current_model_index]}': {asf_err}. "
                f"Will attempt next model if available."
            )

        # === MODEL FALLBACK AFTER STREAM FAILURE ===
        # If all servers failed for the current model during stream consumption,
        # try the next model in the fallback list before giving up.
        if _stream_all_servers_failed:
            await _fail_reserved_operation(
                operation_id=current_ai_operation_id,
                request_data=request_data,
                directus_service=directus_service,
                preserve_anonymous_reservation=True,
            )
            current_ai_operation_id = None
            if answer_recovery.active or force_no_tools or tool_inference_iterations > 0:
                if schedule_answer_recovery("provider_exhausted"):
                    continue
                for billing_event in await terminal_billing_usage_events():
                    yield billing_event
                yield main_processing_failure("provider_exhausted")
                break
            current_model_index += 1
            if current_model_index < len(models_to_try):
                next_model = models_to_try[current_model_index]
                logger.warning(
                    f"{log_prefix} MODEL_FALLBACK: Switching to fallback model #{current_model_index + 1}: "
                    f"{next_model} (previous model failed: {_stream_all_servers_error})"
                )
                # Reset iteration state and continue the outer for loop
                # to retry with the next model on the same iteration
                continue
            else:
                # All models exhausted — yield standardized error to user
                logger.error(
                    f"{log_prefix} MODEL_FALLBACK: All {len(models_to_try)} models exhausted. "
                    f"Last error: {_stream_all_servers_error}"
                )
                for billing_event in await terminal_billing_usage_events():
                    yield billing_event
                yield main_processing_failure("provider_exhausted")
                break

        if iteration_usage is not None:
            usage = iteration_usage
            successful_model_id = current_model_id or preprocessing_results.selected_main_llm_model_id
            if getattr(request_data, "is_anonymous", False) and current_ai_operation_id:
                if iteration_normalized_usage_by_attempt:
                    for reported in iteration_normalized_usage_by_attempt.values():
                        anonymous_completed_usage.record_reported_usage(
                            model_id=reported.model_id,
                            normalized_usage=reported,
                            attempt_id=reported.attempt_id,
                        )
                else:
                    anonymous_completed_usage.record_reported_usage(
                        model_id=current_model_id,
                        input_tokens=iteration_input_tokens,
                        output_tokens=iteration_output_tokens,
                    )
                try:
                    cumulative_credits = calculate_model_usage_credits(
                        anonymous_completed_usage.usage_by_model,
                        config_manager.get_model_pricing,
                    )
                    checkpoint_credits = cumulative_credits - anonymous_checkpointed_credits
                    if checkpoint_credits < 0:
                        raise AnonymousUsageAccountingError("Cumulative anonymous usage decreased")
                    await _checkpoint_anonymous_ai_operation(
                        operation_id=current_ai_operation_id,
                        checkpoint_credits=checkpoint_credits,
                    )
                    anonymous_checkpointed_credits = cumulative_credits
                except Exception:
                    # The request may have reached the ledger despite a lost
                    # acknowledgement. Do not dispatch more work or switch models
                    # until accounting is known; the live hold remains reversible.
                    logger.error("%s Anonymous usage checkpoint failed", log_prefix, exc_info=True)
                    for billing_event in await terminal_billing_usage_events():
                        yield billing_event
                    yield main_processing_failure("stream_error")
                    break
            if successful_model_id and (llm_turn_had_content or tool_calls_for_this_turn):
                model_usage_tracker.mark_successful_model(successful_model_id)
            logger.debug(
                f"{log_prefix} [CUMULATIVE_TOKENS] Successful model for iteration: "
                f"'{successful_model_id}' ({iteration_input_tokens} input / "
                f"{iteration_output_tokens} output tokens)."
            )

        final_buffered_text_for_turn = "".join(current_turn_text_buffer)
        if native_prepared_context is not None:
            if (
                iteration_native_output is not None and native_state is not None
                and iteration_native_output.provider_prefix == native_prepared_context.get("provider_prefix")
                and iteration_native_output.model_id == native_prepared_context.get("server_model_id")
                and not protocol_guard.detected
            ):
                try:
                    append_provider_output(
                        native_state, iteration_native_output.output,
                        final_buffered_text_for_turn,
                    )
                    native_raw_final_output = copy.deepcopy(iteration_native_output.output)
                    native_raw_final_text = final_buffered_text_for_turn
                    native_terminal_ready = bool(
                        iteration_usage is not None and llm_turn_had_content
                        and not tool_calls_for_this_turn and not hallucinated_tool_calls_this_turn
                    )
                except (TypeError, ValueError):
                    native_state = None
            else:
                native_state = None
        else:
            native_state = None

        if protocol_guard.detected:
            logger.warning(
                "%s [TOOL_PROTOCOL_GUARD] Suppressed model-generated tool protocol; "
                "native_calls=%s safe_text_chars=%s recovery_attempts=%s",
                log_prefix,
                len(tool_calls_for_this_turn),
                len(final_buffered_text_for_turn),
                answer_recovery.attempts,
            )
            if not tool_calls_for_this_turn:
                # Disabling tools alone retains the prompt that elicited the
                # fabricated protocol. Rebuild clean answer-only context instead.
                protocol_guard_recovery_started = True
                if schedule_answer_recovery("protocol_guard"):
                    continue
                logger.error(
                    "%s [TOOL_PROTOCOL_GUARD] Answer-only recovery was exhausted; "
                    "preserving published safe text and marking the response failed.",
                    log_prefix,
                )
                for billing_event in await terminal_billing_usage_events():
                    yield billing_event
                yield main_processing_failure("protocol_guard")
                break

        if not tool_calls_for_this_turn:
            task_queue_result = await evaluate_task_queue_post_turn(
                task_tool_context=task_tool_context,
                directus_service=directus_service,
                user_id=request_data.user_id,
                chat_id=request_data.chat_id,
                now=int(time.time()),
            )
            if (
                task_queue_result
                and task_queue_result.get("requires_model_retry")
                and not force_no_tools
                and task_queue_guard_retries < TASK_QUEUE_GUARD_MAX_RETRIES
                and iteration < MAX_TOOL_CALL_ITERATIONS - 1
            ):
                task_queue_guard_retries += 1
                continuation_event = build_task_queue_continuation_event(
                    task_queue_result,
                    message_id=request_data.message_id,
                    now=int(time.time()),
                )
                if continuation_event and cache_service:
                    continuation_event_id = str(continuation_event.get("event_id") or "")
                    if continuation_event_id and continuation_event_id not in published_task_queue_continuation_event_ids:
                        published_task_queue_continuation_event_ids.add(continuation_event_id)
                        try:
                            await cache_service.publish_event(
                                f"chat_stream::{request_data.chat_id}",
                                {
                                    **continuation_event,
                                    "type": "task_event",
                                    "user_id_uuid": request_data.user_id,
                                    "user_id_hash": request_data.user_id_hash,
                                },
                            )
                        except Exception:
                            logger.error(
                                "%s [TASK_QUEUE_CONTINUATION] Failed to publish continuation task event",
                                log_prefix,
                                exc_info=True,
                            )
                retry_task_context_prompt = ""
                task_methods = getattr(directus_service, "user_task", None) if directus_service else None
                if task_methods is not None:
                    try:
                        task_tool_context = await refresh_task_tool_context(
                            existing_context=task_tool_context,
                            task_methods=task_methods,
                            user_id=request_data.user_id,
                            chat_id=request_data.chat_id,
                            message_text=request_data.current_user_content,
                            team_id=getattr(request_data, "team_id", None),
                        )
                        retry_task_context_prompt = build_task_context_prompt(task_tool_context)
                        if task_tools_enabled and not suppress_task_runtime_tools:
                            refreshed_task_tools = build_task_runtime_tools(task_tool_context)
                            available_tools_for_llm = merge_task_runtime_tools(available_tools_for_llm, refreshed_task_tools)
                            for refreshed_tool in refreshed_task_tools:
                                refreshed_name = str(refreshed_tool.get("function", {}).get("name") or "")
                                if refreshed_name:
                                    allowed_tool_names.add(_canonicalize_tool_name(refreshed_name))
                                    allowed_tool_names.update(task_tool_name_variants(refreshed_name))
                    except Exception:
                        logger.error(
                            "%s [TASK_QUEUE_CONTINUATION] Failed to refresh task context before retry",
                            log_prefix,
                            exc_info=True,
                        )
                retry_prompt = task_queue_post_turn_prompt(task_queue_result)
                if retry_task_context_prompt:
                    retry_prompt = f"{retry_prompt}\n\n{retry_task_context_prompt}"
                current_message_history.append({"role": "assistant", "content": final_buffered_text_for_turn or None})
                current_message_history.append({"role": "user", "content": retry_prompt})
                logger.info(
                    "%s [TASK_QUEUE_CONTINUATION] Retrying main processing for state=%s task_id=%s retry=%s/%s",
                    log_prefix,
                    task_queue_result.get("state"),
                    task_queue_result.get("task_id"),
                    task_queue_guard_retries,
                    TASK_QUEUE_GUARD_MAX_RETRIES,
                )
                continue
            if (
                (forbidden_tool_call_seen and not llm_turn_had_content)
                or _is_empty_post_tool_turn(tool_inference_iterations, llm_turn_had_content)
                or (force_no_tools and not llm_turn_had_content)
            ):
                if schedule_answer_recovery("empty_post_tool_response"):
                    continue

                logger.error(
                    f"{log_prefix} [POST_TOOL_RECOVERY] Forced tool continuation retry produced no answer. "
                    "Emitting the standardized user-facing error."
                )
                for billing_event in await terminal_billing_usage_events():
                    yield billing_event
                yield main_processing_failure("empty_post_tool_response")
                break
            # Safety net: if the LLM emitted ONLY hallucinated tool calls (all
            # rejected) and produced no visible text, the user would see zero
            # response.  Force one more LLM iteration with tool_choice="none"
            # so the model is compelled to produce a text answer.
            if hallucinated_rejections_this_turn > 0 and not final_buffered_text_for_turn.strip():
                _append_tool_call_turn_to_history(
                    current_message_history,
                    tool_calls=[],
                    rejected_tool_calls=hallucinated_tool_calls_this_turn,
                    assistant_content=None,
                )

                has_retry_iteration = iteration < MAX_TOOL_CALL_ITERATIONS - 1
                if has_retry_iteration:
                    if force_deep_research_delegation:
                        logger.warning(
                            f"{log_prefix} [HALLUCINATION_RECOVERY] Deep research delegation call was rejected; "
                            "retrying with required start_sub_chats."
                        )
                        force_no_tools = False
                    else:
                        logger.warning(
                            f"{log_prefix} [HALLUCINATION_RECOVERY] All {hallucinated_rejections_this_turn} "
                            f"tool call(s) this turn were rejected and no text was produced. "
                            f"Forcing one more iteration with tool_choice='none' to generate a response."
                        )
                        force_no_tools = True
                    continue

                logger.error(
                    f"{log_prefix} [HALLUCINATION_RECOVERY] Final iteration produced only rejected "
                    f"tool call(s). Emitting deterministic fallback text so the response is not embed-only."
                )
                yield INVALID_TOOL_FALLBACK_MESSAGE
                force_no_tools = True
                break
            if focus_phase_runtimes and await evaluate_active_phases(
                "assistant", f"{request_data.message_id}:{iteration}:assistant",
                [*current_message_history, {"role": "assistant", "content": final_buffered_text_for_turn}],
            ):
                yield phase_state_marker()
            break

        # Tool calls normally trigger another model pass. Count that extra pass
        # here, then undo the count if a client job pauses this loop instead.
        tool_inference_iterations += 1
        logger.info(
            f"{log_prefix} [CUMULATIVE_TOKENS] Tool calls detected — incrementing tool_inference_iterations "
            f"to {tool_inference_iterations}."
        )

        logger.info(f"{log_prefix} Processing {len(tool_calls_for_this_turn)} tool call(s).")
        
        # Append valid tool calls plus rejected hallucinated calls as matched
        # tool_use/tool_result pairs. Rejected calls are hidden protocol
        # bookkeeping; valid calls still execute normally below.
        _append_tool_call_turn_to_history(
            current_message_history,
            tool_calls=list(tool_calls_for_this_turn),
            rejected_tool_calls=hallucinated_tool_calls_this_turn,
            assistant_content=final_buffered_text_for_turn,
        )

        async def cancel_suppressed_placeholder(tool_call: Any, guard_name: str) -> None:
            placeholder = inline_placeholder_embeds.get(tool_call.tool_call_id)
            if not (placeholder and cache_service and user_vault_key_id and directus_service):
                return
            try:
                from backend.core.api.app.services.embed_service import EmbedService

                embed_service = EmbedService(
                    cache_service=cache_service,
                    directus_service=directus_service,
                    encryption_service=encryption_service,
                )
                app_id, skill_id = tool_resolver_map.get(
                    tool_call.function_name, ("unknown", "unknown"),
                )
                placeholders = (
                    placeholder.get("placeholders", [])
                    if isinstance(placeholder, dict) and placeholder.get("multiple")
                    else [placeholder]
                )
                embed_ids = [
                    item["embed_id"] for item in placeholders
                    if isinstance(item, dict) and item.get("embed_id")
                ]
                for embed_id in embed_ids:
                    await embed_service.update_embed_status_to_cancelled(
                        embed_id=embed_id, app_id=app_id, skill_id=skill_id,
                        chat_id=request_data.chat_id, message_id=request_data.message_id,
                        user_id=request_data.user_id, user_id_hash=request_data.user_id_hash,
                        user_vault_key_id=user_vault_key_id, task_id=task_id,
                        log_prefix=log_prefix,
                    )
                if embed_ids:
                    logger.info(
                        "%s [%s] Cancelled %s placeholder(s) for suppressed tool '%s'",
                        log_prefix, guard_name, len(embed_ids), tool_call.function_name,
                    )
            except Exception:
                logger.warning(
                    "%s [%s] Failed to cancel placeholder for '%s'",
                    log_prefix, guard_name, tool_call.function_name, exc_info=True,
                )

        # === FOCUS MODE EXCLUSIVITY GUARD ===
        # When activate_focus_mode is in the tool-call batch, it MUST run
        # exclusively — no other tool should execute in the same turn.
        # The LLM sometimes emits focus mode activation alongside regular
        # tools (e.g. web-search or a Project file read) in one call batch.
        # Without this guard, the focus mode's `return` would abandon the
        # other tools mid-execution, leaving orphaned placeholder embeds.
        # See: docs/architecture/focus-modes.md, issue e85778c8
        primary_focus_call = next(
            (tc for tc in tool_calls_for_this_turn
             if tool_resolver_map.get(tc.function_name, (None, None))[1] == "activate_focus_mode"),
            None,
        )
        if primary_focus_call and len(tool_calls_for_this_turn) > 1:
            _non_focus_tools = [
                tc for tc in tool_calls_for_this_turn
                if tc is not primary_focus_call
            ]
            if _non_focus_tools:
                logger.info(
                    f"{log_prefix} [FOCUS_EXCLUSIVITY] activate_focus_mode in batch with "
                    f"{len(_non_focus_tools)} other tool(s): "
                    f"{[tc.function_name for tc in _non_focus_tools]}. "
                    f"Suppressing other tools — focus mode takes priority."
                )
                for _suppressed_tc in _non_focus_tools:
                    _sup_tool_call_id = _suppressed_tc.tool_call_id
                    _sup_tool_name = _suppressed_tc.function_name

                    await cancel_suppressed_placeholder(_suppressed_tc, "FOCUS_EXCLUSIVITY")

                    # Add a synthetic tool response so the LLM's tool_call is properly closed
                    current_message_history.append({
                        "tool_call_id": _sup_tool_call_id,
                        "role": "tool",
                        "name": _sup_tool_name,
                        "content": json.dumps({
                            "status": "skipped",
                            "reason": "Focus mode activation takes priority. This skill will be available after focus mode is active."
                        })
                    })

                tool_calls_for_this_turn = [primary_focus_call]
                logger.info(
                    f"{log_prefix} [FOCUS_EXCLUSIVITY] Proceeding with {len(tool_calls_for_this_turn)} "
                    f"focus tool(s) only: {[tc.function_name for tc in tool_calls_for_this_turn]}"
                )

        # A client-executed Project file operation pauses this inference turn.
        # Other tools from the same model batch would spend credits and append
        # results only to transient history, which the async continuation cannot
        # recover. Execute one file operation; the continuation replans the
        # original user request after its actual client result arrives.
        primary_project_call = next(
            (tc for tc in tool_calls_for_this_turn
             if tool_resolver_map.get(tc.function_name, (None, None))[0] == "system"
             and tool_resolver_map.get(tc.function_name, (None, None))[1]
             in PROJECT_FILE_TOOL_TO_OPERATION),
            None,
        )
        if primary_project_call and len(tool_calls_for_this_turn) > 1:
            suppressed_project_batch = [
                tc for tc in tool_calls_for_this_turn if tc is not primary_project_call
            ]
            for suppressed_call in suppressed_project_batch:
                await cancel_suppressed_placeholder(suppressed_call, "PROJECT_FILE_EXCLUSIVITY")
                current_message_history.append({
                    "tool_call_id": suppressed_call.tool_call_id,
                    "role": "tool",
                    "name": suppressed_call.function_name,
                    "content": json.dumps({
                        "status": "deferred",
                        "reason": (
                            "A Project file operation is pending. Reconsider this tool after "
                            "the client returns the file result."
                        ),
                    }),
                })
            tool_calls_for_this_turn = [primary_project_call]
            logger.info(
                "%s [PROJECT_FILE_EXCLUSIVITY] Deferred %s other tool(s) until file completion",
                log_prefix, len(suppressed_project_batch),
            )

        # One chat request must produce one atomic Workflow authoring instruction.
        # All tool calls are known here, before any skill in this turn dispatches.
        workflow_authoring_calls = [
            tc for tc in tool_calls_for_this_turn
            if tool_resolver_map.get(tc.function_name) == ("workflows", "create-or-modify")
        ]
        block_split_workflow_authoring = len(workflow_authoring_calls) > 1

        # Preflight the only audited read-only skill batch before dispatching it.
        # Reservations remain sequential; provider work starts only after every
        # descriptor is fixed from this turn's immutable tool-call snapshot.
        parallel_executions: Dict[str, Dict[str, Any]] = {}
        if not getattr(request_data, "is_anonymous", False) and _is_parallel_safe_app_skill_batch(
            tool_calls_for_this_turn,
            tool_resolver_map,
            discovered_apps_metadata,
        ):
            parallel_candidates: List[Dict[str, Any]] = []
            parallel_hashes: set[str] = set()
            parallel_request_count = 0
            parallel_preflight_failed = False

            for parallel_tool_call in tool_calls_for_this_turn:
                parallel_tool_name = explicit_task_app_skill_tool_name(
                    parallel_tool_call.function_name,
                    task_app_skill_mentions,
                )
                parallel_resolved_tool = tool_resolver_map.get(parallel_tool_name)
                if parallel_tool_name not in allowed_tool_names:
                    parallel_preflight_failed = True
                    break
                try:
                    parallel_parsed_args = json.loads(parallel_tool_call.function_arguments_raw)
                except (TypeError, json.JSONDecodeError):
                    parallel_preflight_failed = True
                    break
                if not isinstance(parallel_parsed_args, dict) or not parallel_resolved_tool:
                    parallel_preflight_failed = True
                    break

                parallel_app_id, parallel_skill_id = parallel_resolved_tool
                if learning_mode_active and is_learning_mode_blocked_skill(
                    parallel_app_id,
                    parallel_skill_id,
                ):
                    parallel_preflight_failed = True
                    break
                parallel_placeholder = inline_placeholder_embeds.get(
                    parallel_tool_call.tool_call_id
                )
                if not isinstance(parallel_placeholder, dict):
                    parallel_preflight_failed = True
                    break
                parallel_requests = parallel_parsed_args.get("requests", [])
                parallel_requests_in_call = (
                    len(parallel_requests)
                    if isinstance(parallel_requests, list) and parallel_requests
                    else 1
                )
                parallel_call_hash = _hash_skill_arguments(
                    parallel_app_id,
                    parallel_skill_id,
                    parallel_parsed_args,
                )
                if (
                    (parallel_app_id, parallel_skill_id) in ASYNC_SKILLS
                    or is_legacy_task_runtime_tool_name(parallel_tool_name)
                    or parallel_call_hash in completed_skill_calls
                    or parallel_call_hash in parallel_hashes
                ):
                    parallel_preflight_failed = True
                    break
                parallel_hashes.add(parallel_call_hash)
                parallel_request_count += parallel_requests_in_call
                parallel_candidates.append({
                    "tool_call": parallel_tool_call,
                    "tool_name": parallel_tool_name,
                    "app_id": parallel_app_id,
                    "skill_id": parallel_skill_id,
                    "parsed_args": parallel_parsed_args,
                    "placeholder": parallel_placeholder,
                    "call_hash": parallel_call_hash,
                    "requests_in_call": parallel_requests_in_call,
                })

            if (
                total_skill_calls + parallel_request_count > HARD_LIMIT_SKILL_CALLS
                or request_data.orchestration_id
            ):
                parallel_preflight_failed = True

            if not parallel_preflight_failed:
                for candidate in parallel_candidates:
                    parallel_placeholder = candidate["placeholder"]
                    parallel_skill_task_id = None
                    parallel_skill_task_id = parallel_placeholder.get("skill_task_id")
                    parallel_placeholders = parallel_placeholder.get("placeholders")
                    if (
                        not parallel_skill_task_id
                        and isinstance(parallel_placeholders, list)
                        and parallel_placeholders
                        and isinstance(parallel_placeholders[0], dict)
                    ):
                        parallel_skill_task_id = parallel_placeholders[0].get("skill_task_id")
                    if not parallel_skill_task_id:
                        parallel_skill_task_id = generate_skill_task_id()

                    try:
                        parallel_arguments = _normalize_skill_arguments(
                            arguments=_get_skill_execution_args(
                                candidate["parsed_args"], parallel_placeholder
                            ),
                            app_id=candidate["app_id"],
                            skill_id=candidate["skill_id"],
                            discovered_apps_metadata=discovered_apps_metadata,
                            task_id=task_id,
                            message_history=current_message_history,
                        )
                        parallel_arguments = _apply_repository_relevance_criteria_guard(
                            parallel_arguments,
                            candidate["app_id"],
                            candidate["skill_id"],
                            current_message_history,
                            log_prefix,
                        )
                        parallel_placeholder_ids = []
                        if parallel_placeholder.get("multiple"):
                            parallel_placeholder_ids = [
                                placeholder.get("embed_id")
                                for placeholder in parallel_placeholder.get("placeholders", [])
                                if isinstance(placeholder, dict) and placeholder.get("embed_id")
                            ]
                        elif parallel_placeholder.get("embed_id"):
                            parallel_placeholder_ids = [parallel_placeholder["embed_id"]]
                        if parallel_placeholder_ids:
                            parallel_arguments = parallel_arguments.copy()
                            parallel_arguments["_placeholder_embed_ids"] = parallel_placeholder_ids
                        if user_vault_key_id:
                            parallel_arguments = parallel_arguments.copy()
                            parallel_arguments["_user_vault_key_id"] = user_vault_key_id
                        embed_file_path_index = getattr(
                            request_data,
                            "embed_file_path_index",
                            None,
                        )
                        if embed_file_path_index:
                            parallel_arguments = parallel_arguments.copy()
                            parallel_arguments["_file_path_index"] = embed_file_path_index
                        parallel_model_override = _resolve_app_skill_model_override(
                            getattr(request_data, "user_preferences", None),
                            candidate["app_id"],
                            candidate["skill_id"],
                            log_prefix,
                        )
                        if parallel_model_override:
                            parallel_arguments = parallel_arguments.copy()
                            parallel_arguments["_full_model_reference_override"] = parallel_model_override

                        parallel_reservation_ids: list[str] = []
                        if directus_service or getattr(request_data, "is_anonymous", False):
                            parallel_reservation_ids = await _reserve_skill_credits(
                                task_id=task_id,
                                execution_id=candidate["tool_call"].tool_call_id,
                                request_data=request_data,
                                app_id=candidate["app_id"],
                                skill_id=candidate["skill_id"],
                                discovered_apps_metadata=discovered_apps_metadata,
                                parsed_args=parallel_arguments,
                                directus_service=directus_service,
                                log_prefix=log_prefix,
                            )
                        candidate.update({
                            "arguments": parallel_arguments,
                            "skill_task_id": parallel_skill_task_id,
                            "reservation_ids": parallel_reservation_ids,
                        })
                    except Exception as preparation_error:
                        # Preserve the serial loop's per-call failure handling and
                        # result ordering even when preflight preparation fails.
                        candidate.update({
                            "preparation_error": preparation_error,
                            "skill_task_id": parallel_skill_task_id,
                            "reservation_ids": [],
                        })

                def parallel_operation(candidate: Dict[str, Any]) -> Callable[[], Awaitable[List[Dict[str, Any]]]]:
                    async def execute() -> List[Dict[str, Any]]:
                        if preparation_error := candidate.get("preparation_error"):
                            raise preparation_error
                        with ai_phase_span("tool"):
                            return await execute_skill_with_multiple_requests(
                                app_id=candidate["app_id"],
                                skill_id=candidate["skill_id"],
                                arguments=candidate["arguments"],
                                timeout=DEFAULT_SKILL_TIMEOUT,
                                chat_id=request_data.chat_id,
                                message_id=request_data.message_id,
                                user_id=request_data.user_id,
                                team_id=request_data.team_id,
                                skill_task_id=candidate["skill_task_id"],
                                cache_service=cache_service,
                                encryption_service=encryption_service,
                                secrets_manager=secrets_manager,
                                max_retries=0 if getattr(request_data, "is_anonymous", False) else 1,
                                is_anonymous=bool(getattr(request_data, "is_anonymous", False)),
                            )

                    return execute

                parallel_tasks = _create_parallel_app_skill_tasks(
                    [parallel_operation(candidate) for candidate in parallel_candidates]
                )
                try:
                    parallel_outcomes = await asyncio.gather(
                        *parallel_tasks,
                        return_exceptions=True,
                    )
                except asyncio.CancelledError:
                    task_executions = {
                        str(index): {"task": task}
                        for index, task in enumerate(parallel_tasks)
                    }
                    await _cancel_parallel_app_skill_tasks(task_executions)
                    raise
                for candidate, parallel_outcome in zip(parallel_candidates, parallel_outcomes):
                    parallel_executions[candidate["tool_call"].tool_call_id] = {
                        **candidate,
                        "outcome": parallel_outcome,
                    }
                logger.info(
                    "%s Dispatching %d preflight-reserved web.search calls concurrently (cap=%d)",
                    log_prefix,
                    len(parallel_executions),
                    MAX_PARALLEL_APP_SKILL_EXECUTIONS,
                )

        # Execute all tool calls (skills) in this turn
        for tool_call in tool_calls_for_this_turn:
            tool_name = explicit_task_app_skill_tool_name(tool_call.function_name, task_app_skill_mentions)
            tool_arguments_str = tool_call.function_arguments_raw
            tool_call_id = tool_call.tool_call_id
            tool_result_content_str: str
            omitted_news_requests_for_call: List[Any] = []

            if block_split_workflow_authoring and tool_resolver_map.get(tool_name) == ("workflows", "create-or-modify"):
                placeholder = inline_placeholder_embeds.get(tool_call_id)
                if isinstance(placeholder, dict) and cache_service and user_vault_key_id and directus_service:
                    try:
                        from backend.core.api.app.services.embed_service import EmbedService

                        embed_service = EmbedService(
                            cache_service=cache_service,
                            directus_service=directus_service,
                            encryption_service=encryption_service,
                        )
                        placeholders = placeholder.get("placeholders") if placeholder.get("multiple") else [placeholder]
                        for item in placeholders or []:
                            embed_id = item.get("embed_id") if isinstance(item, dict) else None
                            if embed_id:
                                await embed_service.update_embed_status_to_cancelled(
                                    embed_id=embed_id, app_id="workflows", skill_id="create-or-modify",
                                    chat_id=request_data.chat_id, message_id=request_data.message_id,
                                    user_id=request_data.user_id, user_id_hash=request_data.user_id_hash,
                                    user_vault_key_id=user_vault_key_id, task_id=task_id, log_prefix=log_prefix,
                                )
                    except Exception:
                        logger.warning("%s Could not cancel split Workflow authoring placeholder", log_prefix, exc_info=True)
                current_message_history.append({
                    "tool_call_id": tool_call_id,
                    "role": "tool",
                    "name": tool_name,
                    "content": json.dumps({
                        "status": "needs_clarification",
                        "reason": "Submit every requested workflow in one complete instruction so all changes save together. No workflow was saved.",
                    }),
                })
                continue

            try:
                # Parse function arguments
                parsed_args = json.loads(tool_arguments_str)

                # === STRICT ALLOW-LIST (OPE-399) ===
                # Defensive safety net: the streaming phase already filters hallucinated
                # tool calls out of tool_calls_for_this_turn, but enforce the allow-list
                # here again so no future code path can ever execute a skill that the
                # preprocessor did not explicitly forward.
                is_sub_chat_violation = (tool_name == "start-sub-chats" and chat_depth >= 2)
                if tool_name not in allowed_tool_names or is_sub_chat_violation:
                    rejection_reason = "Nesting depth limit exceeded: Tier 2 (grandchild) chats cannot spawn sub-chats." if is_sub_chat_violation else "Tool not available. Only preselected tools may be used. Do not retry this call."
                    raw_arguments_log = "" if is_task_tool_name(tool_name) else f". Raw arguments: {tool_arguments_str[:500]}"
                    logger.warning(
                        f"{log_prefix} [HALLUCINATION/BLOCK] Refusing to execute tool '{tool_name}'. "
                        f"tool_call_id={tool_call_id}. Allowed tools ({len(allowed_tool_names)}): "
                        f"{sorted(allowed_tool_names)}. Nesting violation: {is_sub_chat_violation}{raw_arguments_log}"
                    )
                    current_message_history.append({
                        "tool_call_id": tool_call_id,
                        "role": "tool",
                        "name": tool_name,
                        "content": json.dumps({
                            "status": "rejected",
                            "reason": rejection_reason,
                        }),
                    })
                    continue

                # Extract app_id and skill_id from tool name via the resolver map.
                # After the allow-list gate above, the resolver is guaranteed to succeed.
                resolved_tool = tool_resolver_map.get(tool_name)

                if resolved_tool:
                    app_id, skill_id = resolved_tool
                    logger.debug(f"{log_prefix} Resolved tool '{tool_name}' to app_id='{app_id}', skill_id='{skill_id}'")
                else:
                    # Invariant violation: tool_name passed the allow-list but the
                    # resolver map doesn't know it. Treat as a bug, not a hallucination.
                    logger.error(
                        f"{log_prefix} [INVARIANT] Allowed tool '{tool_name}' missing from "
                        f"tool_resolver_map. Rejecting tool call."
                    )
                    current_message_history.append({
                        "tool_call_id": tool_call_id,
                        "role": "tool",
                        "name": tool_name,
                        "content": json.dumps({
                            "status": "rejected",
                            "reason": "Internal error resolving tool. Do not retry.",
                        }),
                    })
                    continue

                if app_id == "projects" and skill_id == "search":
                    current_message_history.append({
                        "tool_call_id": tool_call_id,
                        "role": "tool",
                        "name": tool_name,
                        "content": json.dumps({
                            "status": "rejected",
                            "reason": "Unscoped Project search is unavailable. Request Project Focus first.",
                        }),
                    })
                    continue
                
                # Validate that app_id and skill_id are non-empty after split
                # This ensures we have valid identifiers before proceeding with skill execution and billing
                if not app_id or not app_id.strip():
                    logger.error(f"{log_prefix} Empty app_id extracted from tool name '{tool_name}'. Cannot proceed with skill execution.")
                    raise ValueError(f"Empty app_id in tool name '{tool_name}'")
                
                if not skill_id or not skill_id.strip():
                    logger.error(f"{log_prefix} Empty skill_id extracted from tool name '{tool_name}'. Cannot proceed with skill execution.")
                    raise ValueError(f"Empty skill_id in tool name '{tool_name}'")

                if getattr(request_data, "is_anonymous", False):
                    from backend.shared.python_utils.anonymous_skill_policy import (
                        has_single_anonymous_provider_request,
                        is_anonymous_inline_skill,
                    )

                    app_metadata = discovered_apps_metadata.get(app_id)
                    skill_definition = next(
                        (skill for skill in (app_metadata.skills or []) if skill.id == skill_id),
                        None,
                    ) if app_metadata else None
                    if not skill_definition or not is_anonymous_inline_skill(app_id, skill_definition):
                        current_message_history.append({
                            "tool_call_id": tool_call_id,
                            "role": "tool",
                            "name": tool_name,
                            "content": json.dumps({
                                "status": "signup_required",
                                "reason": "Create an account to use this skill.",
                            }),
                        })
                        continue
                
                # Normalize by stripping whitespace
                app_id = app_id.strip()
                skill_id = skill_id.strip()

                if is_legacy_task_runtime_tool_name(tool_name):
                    if task_tool_context is None:
                        tool_result_content_str = json.dumps({
                            "status": "rejected",
                            "reason": "Task tools are unavailable for this chat turn.",
                        })
                    elif not cache_service or not directus_service or not encryption_service:
                        tool_result_content_str = json.dumps({
                            "status": "rejected",
                            "reason": "Task persistence services are unavailable.",
                        })
                    else:
                        try:
                            task_result = await execute_task_tool_call(
                                tool_name=tool_name,
                                args=parsed_args if isinstance(parsed_args, dict) else {},
                                context=task_tool_context,
                                cache_service=cache_service,
                                directus_service=directus_service,
                                encryption_service=encryption_service,
                                user_vault_key_id=user_vault_key_id,
                                message_id=request_data.message_id,
                            )
                            await publish_task_tool_result(
                                cache_service=cache_service,
                                user_id=request_data.user_id,
                                user_id_hash=request_data.user_id_hash,
                                result=task_result,
                            )
                        except Exception as task_tool_error:
                            logger.warning(
                                "%s Task tool execution failed for %s: %s: %s",
                                log_prefix,
                                tool_name,
                                task_tool_error.__class__.__name__,
                                str(task_tool_error),
                            )
                            task_result = {
                                "status": "rejected",
                                "reason": "Task tool execution failed before encrypted persistence.",
                            }
                        tool_result_content_str = json.dumps(task_result, default=str)

                    current_message_history.append({
                        "tool_call_id": tool_call_id,
                        "role": "tool",
                        "name": tool_name,
                        "content": tool_result_content_str,
                    })
                    continue

                if learning_mode_active and is_learning_mode_blocked_skill(app_id, skill_id):
                    logger.info(
                        f"{log_prefix} [LEARNING_MODE] Refusing to execute blocked skill "
                        f"'{app_id}.{skill_id}'."
                    )
                    current_message_history.append({
                        "tool_call_id": tool_call_id,
                        "role": "tool",
                        "name": tool_name,
                        "content": json.dumps({
                            "status": "rejected",
                            "reason": (
                                "This tool is unavailable while Learning Mode is active. "
                                "Teach the method without calculating the final answer."
                            ),
                        }),
                    })
                    continue

                if (
                    app_id == "audio"
                    and skill_id == "transcribe"
                    and (audio_transcribe_blocked_by_recording or should_block_local_audio_transcription(
                        parsed_args, request_data.message_history,
                    ))
                ):
                    logger.warning(
                        f"{log_prefix} [AUDIO_RECORDING_GUARD] Refusing to execute '{tool_name}': "
                        "web UI audio recording already has transcript text."
                    )
                    current_message_history.append({
                        "tool_call_id": tool_call_id,
                        "role": "tool",
                        "name": tool_name,
                        "content": json.dumps({
                            "status": "rejected",
                            "reason": (
                                "This voice recording uses local transcription or already has a transcript. "
                                "Use any available transcript; do not retry it with an external provider."
                            ),
                        }),
                    })
                    continue

                # === SKILL CALL BUDGET CHECK ===
                # Count requests in this tool call and check against hard limit.
                # If we've already reached the limit, skip this tool call entirely.
                # User won't see any indication that the tool call was skipped.
                if app_id == "news" and skill_id == "search" and not getattr(request_data, "is_anonymous", False):
                    parsed_args, omitted_news_requests_for_call = _limit_news_search_batch_to_budget(
                        parsed_args, HARD_LIMIT_SKILL_CALLS - total_skill_calls
                    )
                    if omitted_news_requests_for_call:
                        omitted_news_search_requests += len(omitted_news_requests_for_call)
                        logger.info(
                            "%s [SKILL_BUDGET] Limiting news-search execution to %s requests; %s omitted.",
                            log_prefix,
                            len(parsed_args["requests"]),
                            len(omitted_news_requests_for_call),
                        )

                requests_in_this_call = 1  # Default: single request
                requests_list_for_budget = parsed_args.get("requests", []) if isinstance(parsed_args, dict) else []
                if isinstance(requests_list_for_budget, list) and len(requests_list_for_budget) > 0:
                    requests_in_this_call = len(requests_list_for_budget)

                if getattr(request_data, "is_anonymous", False) and (
                    requests_in_this_call != 1
                    or not has_single_anonymous_provider_request(app_id, skill_id, parsed_args)
                ):
                    current_message_history.append({
                        "tool_call_id": tool_call_id,
                        "role": "tool",
                        "name": tool_name,
                        "content": json.dumps({
                            "status": "rejected",
                            "reason": "Use one request per anonymous skill call.",
                        }),
                    })
                    continue

                # Skip this tool call if we've already reached or would exceed the hard limit
                # We don't count system tools (focus mode) against the budget
                # CRITICAL: Also check if this call WOULD exceed the limit (not just if limit is already reached)
                # This prevents a single tool call with multiple requests from exceeding the budget
                if app_id != "system" and (total_skill_calls >= HARD_LIMIT_SKILL_CALLS or total_skill_calls + requests_in_this_call > HARD_LIMIT_SKILL_CALLS):
                    logger.info(
                        f"{log_prefix} [SKILL_BUDGET] Skipping tool call '{tool_name}' with {requests_in_this_call} request(s) - "
                        f"would exceed hard limit (total_skill_calls={total_skill_calls}+{requests_in_this_call}={total_skill_calls + requests_in_this_call}, limit={HARD_LIMIT_SKILL_CALLS})"
                    )
                    # Add a tool response to history so the LLM knows this tool was skipped
                    # but the user won't see any placeholder or error
                    tool_response_message = {
                        "tool_call_id": tool_call_id,
                        "role": "tool",
                        "name": tool_name,
                        "content": json.dumps({
                            "status": "skipped",
                            "reason": "Research limit reached for this response. Use gathered information to answer."
                        })
                    }
                    current_message_history.append(tool_response_message)
                    # Set force_no_tools to prevent further tool calls
                    force_no_tools = True

                    # === SAFETY NET: Cancel any orphaned placeholder embeds ===
                    # With the streaming-phase budget check, orphaned placeholders should be rare.
                    # This handles edge cases where a placeholder slipped through (e.g., counter
                    # desync between streaming and execution phases). Use "cancelled" instead of
                    # "error" for a cleaner UX — the frontend silently removes cancelled embeds.
                    orphaned_placeholder = inline_placeholder_embeds.get(tool_call_id)
                    if orphaned_placeholder and cache_service and user_vault_key_id and directus_service:
                        try:
                            from backend.core.api.app.services.embed_service import EmbedService
                            _budget_embed_service = EmbedService(
                                cache_service=cache_service,
                                directus_service=directus_service,
                                encryption_service=encryption_service
                            )

                            # Collect embed IDs from both single and multi-request placeholders
                            _orphaned_ids = []
                            if isinstance(orphaned_placeholder, dict) and orphaned_placeholder.get("multiple"):
                                for _p in orphaned_placeholder.get("placeholders", []):
                                    _eid = _p.get("embed_id") if isinstance(_p, dict) else None
                                    if _eid:
                                        _orphaned_ids.append(_eid)
                            elif isinstance(orphaned_placeholder, dict) and "embed_id" in orphaned_placeholder:
                                _orphaned_ids.append(orphaned_placeholder["embed_id"])

                            for _eid in _orphaned_ids:
                                await _budget_embed_service.update_embed_status_to_cancelled(
                                    embed_id=_eid,
                                    app_id=app_id,
                                    skill_id=skill_id,
                                    chat_id=request_data.chat_id,
                                    message_id=request_data.message_id,
                                    user_id=request_data.user_id,
                                    user_id_hash=request_data.user_id_hash,
                                    user_vault_key_id=user_vault_key_id,
                                    task_id=task_id,
                                    log_prefix=log_prefix
                                )
                            if _orphaned_ids:
                                logger.warning(
                                    f"{log_prefix} [SKILL_BUDGET] Cancelled {len(_orphaned_ids)} orphaned placeholder(s) "
                                    f"for '{tool_name}' — streaming budget check should have prevented these"
                                )
                        except Exception as _budget_err:
                            logger.warning(
                                f"{log_prefix} [SKILL_BUDGET] Failed to cancel orphaned placeholder: {_budget_err}"
                            )

                    continue  # Skip to next tool call
                
                # === DEDUPLICATION CHECK (EXECUTION PHASE) ===
                # Check if this exact skill call was already executed in a previous iteration.
                # If so, skip execution and return the previous result to the LLM.
                # This prevents duplicate side effects (e.g., multiple reminders) and wasted credits.
                call_hash = _hash_skill_arguments(app_id, skill_id, parsed_args)
                if call_hash in completed_skill_calls:
                    previous_result = completed_skill_calls[call_hash]
                    logger.info(
                        f"{log_prefix} [DEDUP] Skipping duplicate '{app_id}.{skill_id}' (hash={call_hash[:8]}...). "
                        f"Returning cached result from previous iteration."
                    )
                    # Return a synthetic tool result telling the LLM this was already done
                    # This is NOT visible to users - it's only in the LLM message history
                    tool_response_message = {
                        "tool_call_id": tool_call_id,
                        "role": "tool",
                        "name": tool_name,
                        "content": json.dumps({
                            "status": "already_completed",
                            "message": f"This {skill_id} action was already performed successfully earlier in this response. "
                                       f"No need to call it again with the same parameters.",
                            "previous_embed_id": previous_result.get("embed_id")
                        })
                    }
                    current_message_history.append(tool_response_message)
                    continue  # Skip to next tool call
                
                # Update budget counters (only for non-system tools)
                if app_id != "system":
                    total_skill_calls += requests_in_this_call
                    logger.info(
                        f"{log_prefix} [SKILL_BUDGET] Executing '{tool_name}' with {requests_in_this_call} request(s), "
                        f"total now: {total_skill_calls}/{HARD_LIMIT_SKILL_CALLS}"
                    )
                    
                    # Check if we've reached the soft limit - inject warning for next iteration
                    if total_skill_calls >= SOFT_LIMIT_SKILL_CALLS and not budget_warning_injected:
                        budget_warning_injected = True
                        logger.info(
                            f"{log_prefix} [SKILL_BUDGET] Soft limit reached ({total_skill_calls} >= {SOFT_LIMIT_SKILL_CALLS}). "
                            f"Budget warning will be injected in next iteration."
                        )
                    
                    # Check if we've hit the hard limit - force no tools for next iteration
                    if total_skill_calls >= HARD_LIMIT_SKILL_CALLS:
                        force_no_tools = True
                        logger.info(
                            f"{log_prefix} [SKILL_BUDGET] Hard limit reached ({total_skill_calls} >= {HARD_LIMIT_SKILL_CALLS}). "
                            f"Next iteration will force tool_choice='none' to generate final answer."
                        )
                
                # --- Handle system tools (focus mode activation/deactivation) ---
                # System tools are special tools that modify the chat state rather than executing skills
                # They use app_id="system" to distinguish from regular app skills
                if app_id == "system":
                    if skill_id in PROJECT_FILE_TOOL_TO_OPERATION:
                        operation = PROJECT_FILE_TOOL_TO_OPERATION[skill_id]
                        if pending_project_operation_id:
                            project_result = {
                                "status": "rejected",
                                "reason": (
                                    "A Project file operation is already waiting for its authorized client result. "
                                    "Do not dispatch another operation or poll."
                                ),
                                "operation_id": pending_project_operation_id,
                            }
                        elif not cache_service:
                            project_result = {
                                "status": "rejected",
                                "reason": "Project file execution is unavailable.",
                            }
                        else:
                            operation_id = str(uuid.uuid4())
                            try:
                                from backend.apps.ai.tasks.async_skill_continuation import (
                                    cache_async_skill_continuation_context,
                                    async_skill_continuation_key,
                                )
                                from backend.core.api.app.services.project_file_operation_service import (
                                    PROJECT_FILE_OPERATION_PAYLOAD_TTL_SECONDS,
                                    ProjectFileOperationService,
                                )
                                from backend.core.api.app.services.project_write_authorization_service import (
                                    ProjectWriteAuthorizationService,
                                )
                                from backend.core.api.app.tasks.project_file_operation_tasks import (
                                    schedule_project_file_operation_deadlines,
                                )

                                current_focus = await ProjectWriteAuthorizationService(
                                    directus_service, cache_service
                                ).get_active_focus(
                                    user_id=request_data.user_id,
                                    chat_id=request_data.chat_id,
                                )
                                if (
                                    not current_focus
                                    or not active_project_focus
                                    or current_focus.get("project_id") != active_project_focus.get("project_id")
                                    or current_focus.get("focus_id_hash") != active_project_focus.get("focus_id_hash")
                                ):
                                    raise PermissionError("Project focus changed before file operation dispatch")

                                operation_arguments = dict(parsed_args) if isinstance(parsed_args, dict) else {}
                                requested_source_id = operation_arguments.pop("source_id", None)
                                if operation == "search":
                                    # The model sees two separate search tools. Pin the executor
                                    # target here so an extra model-supplied field cannot change it.
                                    operation_arguments["target"] = (
                                        "files" if skill_id == "project_search_files" else "content"
                                    )
                                dispatch_focus = dict(current_focus)
                                if requested_source_id is not None:
                                    source = await directus_service.project.get_source(
                                        str(current_focus["project_id"]),
                                        request_data.user_id,
                                        str(requested_source_id),
                                        team_id=current_focus.get("team_id"),
                                    )
                                    required_source_capability = (
                                        "write_request"
                                        if operation in {"create_file", "update_file"}
                                        else "search" if operation == "search" else "read"
                                    )
                                    if (
                                        not source
                                        or source.get("status") == "revoked"
                                        or required_source_capability not in set(source.get("capabilities") or [])
                                    ):
                                        raise PermissionError("Project source is unavailable or not authorized")
                                    dispatch_focus["source_id"] = str(requested_source_id)

                                await cache_async_skill_continuation_context(
                                    cache_service=cache_service,
                                    async_task_id=operation_id,
                                    request_data=request_data,
                                    skill_config_dict=skill_config_dict,
                                    app_id="system",
                                    skill_id=skill_id,
                                    tool_name=skill_id,
                                    tool_arguments=operation_arguments,
                                    preprocessing_result=preprocessing_results,
                                    ttl_seconds=PROJECT_FILE_OPERATION_PAYLOAD_TTL_SECONDS,
                                    requires_current_turn=True,
                                    defer_until_initial_response_complete=True,
                                )
                                operation_service = ProjectFileOperationService(cache_service)
                                try:
                                    project_result = await operation_service.create_operation(
                                        user_id=request_data.user_id,
                                        chat_id=request_data.chat_id,
                                        project_focus=dispatch_focus,
                                        operation=operation,
                                        arguments=operation_arguments,
                                        continuation_task_id=operation_id,
                                        message_id=request_data.message_id,
                                        operation_id=operation_id,
                                        publish=False,
                                    )
                                except Exception:
                                    await cache_service.delete(async_skill_continuation_key(operation_id))
                                    raise
                                operation_record = await operation_service.get_job(
                                    user_id=request_data.user_id,
                                    operation_id=operation_id,
                                )
                                schedule_project_file_operation_deadlines(
                                    user_id=request_data.user_id,
                                    operation_id=operation_id,
                                    episode_id=str(operation_record["episode_id"]),
                                )
                                await operation_service.publish_available(operation_record)
                                project_result = {
                                    **project_result,
                                    "status": "processing",
                                    "message": "Waiting for an authorized Project client executor.",
                                }
                                pending_project_operation_id = operation_id
                                request_data.awaiting_async_skill_continuation = True
                            except Exception as project_error:
                                logger.warning(
                                    "%s Project file operation dispatch failed: %s",
                                    log_prefix,
                                    project_error,
                                    exc_info=True,
                                )
                                if getattr(project_error, "code", None) == "conflict_recovery_budget_exhausted":
                                    project_result = {
                                        "status": "paused_conflict_budget_exhausted",
                                        "reason": (
                                            "This file reached the automatic conflict recovery limit for the original "
                                            "user turn. Explain the blocked edit and any partial work honestly; a new "
                                            "user request is required before another mutation of this file."
                                        ),
                                    }
                                else:
                                    project_result = {
                                        "status": "rejected",
                                        "reason": "Project file operation authorization or dispatch failed.",
                                    }
                        current_message_history.append(
                            {
                                "tool_call_id": tool_call_id,
                                "role": "tool",
                                "name": tool_name,
                                "content": json.dumps(project_result),
                            }
                        )
                        completed_skill_calls[call_hash] = project_result
                        continue

                    if skill_id == "activate_focus_mode":
                        focus_id = parsed_args.get("focus_id")
                        if focus_id in project_candidates:
                            embed_reference = await request_project_focus(focus_id)
                            yield f"```json\n{embed_reference}\n```\n\n"
                            yield {"__awaiting_focus_mode_confirmation__": True, "focus_id": focus_id, "chat_id": request_data.chat_id}
                            return
                        if focus_id not in relevant_focus_modes:
                            raise PermissionError("Focus activation was not offered for this turn")
                        private_definition = None
                        if focus_id in private_candidates:
                            private_definition = await agentic_context.private_focus_document(
                                request_data, focus_id, directus_service, cache_service, require_accepted=False,
                            )
                            if not private_definition:
                                raise PermissionError("Private Focus proposal is no longer authorized")
                        logger.info(f"{log_prefix} [FOCUS_MODE] LLM requested focus mode activation: {focus_id}")
                        
                        # --- DEFERRED ACTIVATION ARCHITECTURE ---
                        # Instead of immediately activating focus mode and re-invoking the LLM,
                        # we store the pending context in Redis and schedule an auto-confirm
                        # Celery task with countdown=6s. This gives the user 4 seconds to reject
                        # (click or ESC on the countdown embed) before focus mode activates.
                        #
                        # Flow:
                        # 1. Create and yield the focus mode embed (user sees countdown)
                        # 2. Store pending activation context in Redis (30s TTL)
                        # 3. Schedule auto-confirm task (fires in 6s)
                        # 4. Yield special marker and return (task exits cleanly)
                        # 5a. If no rejection within 6s → auto-confirm task activates focus mode
                        #     and fires a new Celery task WITH focus prompt
                        # 5b. If user rejects → WebSocket handler consumes pending context (GETDEL)
                        #     and fires a new Celery task WITHOUT focus prompt
                        #
                        # DO NOT: set active_focus_id, update cache/Directus, inject focus prompt,
                        # or re-invoke the LLM here. All of that happens in the continuation task.
                        
                        # --- Create focus mode activation embed ---
                        # This embed is rendered by the frontend as a countdown indicator
                        # (4-3-2-1) that the user can click to reject the focus mode.
                        fm_embed_id = None
                        if cache_service and user_vault_key_id and directus_service:
                            try:
                                from backend.core.api.app.services.embed_service import EmbedService
                                embed_service = EmbedService(
                                    cache_service=cache_service,
                                    directus_service=directus_service,
                                    encryption_service=encryption_service
                                )
                                
                                # Resolve the translated focus mode name for UI display
                                # Load in the user's language (from preprocessing) with English fallback
                                focus_mode_display_name = focus_id  # fallback
                                try:
                                    fm_app_id, fm_mode_id = focus_id.split('-', 1)
                                    user_language = preprocessing_results.output_language or "en"
                                    fm_app_metadata = discovered_apps_metadata.get(fm_app_id)
                                    if fm_app_metadata and fm_app_metadata.focuses:
                                        for fm_def in fm_app_metadata.focuses:
                                            if fm_def.id == fm_mode_id:
                                                focus_mode_display_name = _resolve_focus_mode_display_name(
                                                    translation_service,
                                                    fm_def.name_translation_key,
                                                    fallback=fm_def.name_translation_key,
                                                    user_language=user_language,
                                                )
                                                break
                                except Exception:
                                    pass
                                
                                fm_embed_data = await embed_service.create_focus_mode_activation_embed(
                                    focus_id=focus_id,
                                    app_id=focus_id.split('-', 1)[0] if '-' in focus_id else focus_id,
                                    focus_mode_name=focus_mode_display_name,
                                    chat_id=request_data.chat_id,
                                    message_id=request_data.message_id,
                                    user_id=request_data.user_id,
                                    user_id_hash=request_data.user_id_hash,
                                    user_vault_key_id=user_vault_key_id,
                                    task_id=task_id,
                                    log_prefix=log_prefix
                                )
                                
                                if fm_embed_data:
                                    fm_embed_id = fm_embed_data.get("embed_id")
                                    # Yield the embed reference as a JSON code block so the frontend
                                    # can parse and render it inline in the message
                                    fm_embed_ref = fm_embed_data.get("embed_reference")
                                    if fm_embed_ref:
                                        yield f"```json\n{fm_embed_ref}\n```\n\n"
                                        logger.info(
                                            f"{log_prefix} [FOCUS_MODE] Yielded focus mode activation embed "
                                            f"(embed_id={fm_embed_id})"
                                        )
                            except Exception as embed_error:
                                logger.error(
                                    f"{log_prefix} [FOCUS_MODE] Error creating focus mode embed: {embed_error}",
                                    exc_info=True
                                )
                        
                        # --- Load focus mode prompt from translation service ---
                        # Translation key format: focus_modes.{app_id}_{focus_id}.systemprompt
                        # Load in the user's language (from preprocessing) with English fallback
                        focus_prompt_text = ""
                        try:
                            focus_app_id, focus_mode_id = focus_id.split('-', 1)
                            translation_key = f"focus_modes.{focus_app_id}_{focus_mode_id}.systemprompt"
                            user_language = preprocessing_results.output_language or "en"
                            
                            # Try to load in user's language first
                            focus_prompt_text = translation_service.get_nested_translation(translation_key, lang=user_language) or ""
                            
                            # Fallback to English if not found in user's language
                            if not focus_prompt_text and user_language != "en":
                                focus_prompt_text = translation_service.get_nested_translation(translation_key, lang="en") or ""
                                logger.info(f"{log_prefix} [FOCUS_MODE] Loaded focus prompt in fallback language (en) ({len(focus_prompt_text)} chars)")
                            else:
                                logger.info(f"{log_prefix} [FOCUS_MODE] Loaded focus prompt in user language ({user_language}) ({len(focus_prompt_text)} chars)")
                        except Exception as e:
                            logger.error(f"{log_prefix} [FOCUS_MODE] Error loading focus prompt: {e}", exc_info=True)
                        
                        if private_definition:
                            focus_prompt_text = private_definition["instruction"]
                        # --- Store pending activation context in Redis ---
                        # This context is consumed by either the auto-confirm task (happy path)
                        # or the rejection WebSocket handler (user rejects)
                        pending_context_stored = False
                        if cache_service:
                            try:
                                pending_context = {
                                    "focus_id": focus_id,
                                    "focus_prompt": focus_prompt_text,
                                    **_forward_agentic_context(request_data),
                                    "embed_id": fm_embed_id,
                                    "chat_id": request_data.chat_id,
                                    "message_id": request_data.message_id,
                                    "user_id": request_data.user_id,
                                    "user_id_hash": request_data.user_id_hash,
                                    "mate_id": preprocessing_results.selected_mate_id or request_data.mate_id,  # Use preprocessor-selected mate, not the (typically None) request mate_id
                                    "chat_has_title": request_data.chat_has_title,
                                    "is_incognito": getattr(request_data, 'is_incognito', False),
                                    "task_id": task_id,
                                    "recovery_inference_task_id": request_data.resolved_recovery_inference_task_id(),
                                    "recovery_preflight_id": request_data.recovery_preflight_id,
                                    "recovery_turn_id": request_data.recovery_turn_id,
                                    "recovery_public_key": request_data.recovery_public_key,
                                    "chat_key_version": request_data.chat_key_version,
                                    "preprocessing_resume_ref": getattr(request_data, "preprocessing_resume_ref", None),
                                    "parent_id": request_data.parent_id,
                                    "is_sub_chat": request_data.is_sub_chat,
                                    "orchestration_id": request_data.orchestration_id,
                                    "root_chat_id": request_data.root_chat_id,
                                    "root_turn_id": request_data.root_turn_id,
                                    "sub_chat_depth": request_data.sub_chat_depth,
                                    "orchestration_dispatch_token": request_data.orchestration_dispatch_token,
                                    "orchestration_descendant_limit": request_data.orchestration_descendant_limit,
                                    "orchestration_credit_limit": request_data.orchestration_credit_limit,
                                    "orchestration_approved": request_data.orchestration_approved,
                                    "budget_limit": request_data.budget_limit,
                                    "budget_spent": request_data.budget_spent,
                                    "team_id": request_data.team_id,
                                    "team_id_hash": request_data.team_id_hash,
                                    "team_workspace_type": request_data.team_workspace_type,
                                    "team_object_id_hash": request_data.team_object_id_hash,
                                }
                                pending_context_stored = await cache_service.store_pending_focus_activation(
                                    chat_id=request_data.chat_id,
                                    context=pending_context,
                                )
                                logger.info(f"{log_prefix} [FOCUS_MODE] Stored pending focus activation context")
                            except Exception as e:
                                logger.error(f"{log_prefix} [FOCUS_MODE] Failed to store pending context: {e}", exc_info=True)
                                # If we can't store, fall through — auto-confirm will no-op
                        
                        # --- Schedule auto-confirm Celery task ---
                        # This task fires in 5 seconds (1s buffer over 4s client countdown).
                        # If the user hasn't rejected by then, it activates focus mode and
                        # fires a continuation task with focus prompt.
                        try:
                            from backend.core.api.app.tasks.celery_config import app as celery_app_instance
                            from backend.apps.ai.tasks.focus_mode_auto_confirm_task import FOCUS_MODE_AUTO_CONFIRM_COUNTDOWN
                            celery_app_instance.send_task(
                                'apps.ai.tasks.focus_mode_auto_confirm',
                                kwargs={
                                    "chat_id": request_data.chat_id,
                                    "request_id": fm_embed_id,
                                },
                                queue='app_ai',
                                countdown=FOCUS_MODE_AUTO_CONFIRM_COUNTDOWN,
                            )
                            # Positive live eligibility is a transient event, never embed metadata.
                            # Expiry is display-only; auto-confirm remains the state authority.
                            if cache_service and pending_context_stored:
                                redis_client = await cache_service.client
                                if redis_client:
                                    await redis_client.publish(
                                        f"user_cache_events:{request_data.user_id}",
                                        json.dumps({"event_type": "focus_mode_pending", "payload": {
                                            "chat_id": request_data.chat_id,
                                            "focus_id": focus_id,
                                            "embed_id": fm_embed_id,
                                            "expires_at": time.time() + FOCUS_MODE_AUTO_CONFIRM_COUNTDOWN - 1,
                                        }}),
                                    )
                            logger.info(
                                f"{log_prefix} [FOCUS_MODE] Scheduled auto-confirm task with "
                                f"countdown={FOCUS_MODE_AUTO_CONFIRM_COUNTDOWN}s"
                            )
                        except Exception as e:
                            logger.error(f"{log_prefix} [FOCUS_MODE] Failed to schedule auto-confirm task: {e}", exc_info=True)
                        
                        # --- Yield special marker and return ---
                        # The stream_consumer detects this marker and treats the empty stream
                        # as expected (not an error). The actual LLM response will come from
                        # the continuation task fired by auto-confirm or rejection handler.
                        logger.info(f"{log_prefix} [FOCUS_MODE] Yielding pending marker and returning — awaiting user decision")
                        yield {"__awaiting_focus_mode_confirmation__": True, "focus_id": focus_id, "chat_id": request_data.chat_id}
                        return
                        
                    elif skill_id == "deactivate_focus_mode":
                        previous_focus_id = request_data.active_focus_id
                        logger.info(f"{log_prefix} [FOCUS_MODE] Deactivating focus mode: {previous_focus_id}")
                        
                        # Clear active_focus_id
                        await invalidate_phase_runtime(phase_redis, owner_id=request_data.user_id,
                            chat_id=request_data.chat_id, focus_id=request_data.active_focus_id or "")
                        focus_phase_runtimes[:] = [r for r in focus_phase_runtimes if r.state.focus_id != request_data.active_focus_id]
                        request_data.active_focus_id = None
                        
                        # Clear focus_id in cache and Directus
                        if cache_service:
                            try:
                                await cache_service.update_chat_active_focus_id(
                                    user_id=request_data.user_id,
                                    chat_id=request_data.chat_id,
                                    encrypted_focus_id=None  # Clear the field
                                )
                                logger.info(f"{log_prefix} [FOCUS_MODE] Cleared focus_id from cache")
                                
                                # Dispatch Celery task to clear in Directus
                                from backend.core.api.app.tasks.celery_config import app as celery_app_instance
                                celery_app_instance.send_task(
                                    'app.tasks.persistence_tasks.persist_chat_active_focus_id',
                                    kwargs={
                                        "chat_id": request_data.chat_id,
                                        "encrypted_active_focus_id": None  # Clear the field
                                    },
                                    queue='persistence'
                                )
                                logger.info(f"{log_prefix} [FOCUS_MODE] Dispatched Celery task to clear focus_id in Directus")
                            except Exception as cache_error:
                                logger.error(f"{log_prefix} [FOCUS_MODE] Error clearing cache: {cache_error}", exc_info=True)
                        
                        tool_result_content_str = json.dumps({
                            "status": "deactivated",
                            "previous_focus_id": previous_focus_id,
                            "message": f"Focus mode '{previous_focus_id}' has been deactivated. Returning to normal assistant behavior."
                        })
                        
                        # Add tool response to history
                        tool_response_message = {
                            "tool_call_id": tool_call_id,
                            "role": "tool",
                            "name": tool_name,
                            "content": tool_result_content_str
                        }
                        current_message_history.append(tool_response_message)
                        
                        current_message_history.append({
                            "role": "system",
                            "content": json.dumps({
                                "type": "focus_mode_deactivated",
                                "focus_id": previous_focus_id,
                            }),
                        })

                        # Remove the exact instruction section before the next inference
                        # iteration, while retaining the transition in message history.
                        if active_focus_prompt_section in prompt_parts:
                            prompt_parts.remove(active_focus_prompt_section)
                        full_system_prompt = "\n\n".join(filter(None, prompt_parts))
                        if agentic_section:
                            full_system_prompt += "\n\n" + agentic_section
                        if active_focus_prompt_section:
                            answer_recovery_system_prompt = answer_recovery_system_prompt.replace(active_focus_prompt_section, "", 1)
                        active_focus_prompt_section = None
                        focus_phase_runtimes[:] = [r for r in focus_phase_runtimes if r.state.focus_id != previous_focus_id]
                        logger.info(f"{log_prefix} [FOCUS_MODE] Deactivated - continuing without focus mode instructions")
                        continue

                    elif skill_id == "start_sub_chats":
                        if request_data.is_incognito:
                            current_message_history.append({
                                "tool_call_id": tool_call_id,
                                "role": "tool",
                                "name": tool_name,
                                "content": json.dumps({
                                    "status": "rejected",
                                    "reason": "incognito_sub_chats_unavailable",
                                    "message": "Continue this work in the incognito chat without sub-chats.",
                                }),
                            })
                            continue
                        if chat_depth >= 2 or is_sub_chat_continuation(request_data):
                            tool_result_content_str = json.dumps({
                                "status": "rejected",
                                "reason": "sub_chat_depth_or_continuation_forbidden",
                                "message": "Grandchildren and continuation tasks cannot start sub-chats.",
                            })
                            current_message_history.append({
                                "tool_call_id": tool_call_id,
                                "role": "tool",
                                "name": tool_name,
                                "content": tool_result_content_str,
                            })
                            logger.warning("%s [SUB_CHAT] Rejected depth/continuation spawn request", log_prefix)
                            continue
                        sub_chats_args = parsed_args.get("sub_chats", [])
                        execution_mode = get_sub_chat_execution_mode(parsed_args)
                        context_policy = get_sub_chat_context_policy(parsed_args)
                        logger.info(f"{log_prefix} [SUB_CHAT] LLM requested start_sub_chats with {len(sub_chats_args)} chats mode={execution_mode}")

                        spawned_sub_chats = expand_sub_chat_requests(
                            sub_chats_args,
                            max_template_items=MAX_DIRECT_SUB_CHATS_PER_PARENT if execution_mode != "sequential" else None,
                        )
                        if (
                            request_data.active_focus_id == "web-research"
                            and execution_mode != "sequential"
                            and len(spawned_sub_chats) > MAX_AUTO_SUB_CHATS_PER_TURN
                        ):
                            logger.info(
                                f"{log_prefix} [SUB_CHAT] Deep research requested {len(spawned_sub_chats)} sub-chats; "
                                f"capping to {MAX_AUTO_SUB_CHATS_PER_TURN} to stay within automatic approval limits."
                            )
                            spawned_sub_chats = spawned_sub_chats[:MAX_AUTO_SUB_CHATS_PER_TURN]
                        existing_sub_chat_count = await count_direct_sub_chats(directus_service, request_data.chat_id)
                        capacity_result = validate_sub_chat_capacity(
                            existing_sub_chat_count,
                            len(spawned_sub_chats),
                        )

                        if not capacity_result["allowed"]:
                            tool_result_content_str = json.dumps({
                                "status": "rejected",
                                "reason": "sub_chat_limit_exceeded",
                                "max_direct_sub_chats": MAX_DIRECT_SUB_CHATS_PER_PARENT,
                                "existing_sub_chats": existing_sub_chat_count,
                                "requested_sub_chats": len(spawned_sub_chats),
                                "remaining_sub_chats": capacity_result["remaining"],
                                "message": capacity_result["message"],
                            })
                            current_message_history.append({
                                "tool_call_id": tool_call_id,
                                "role": "tool",
                                "name": tool_name,
                                "content": tool_result_content_str,
                            })
                            logger.warning(
                                f"{log_prefix} [SUB_CHAT] Rejected spawn request: existing={existing_sub_chat_count}, "
                                f"requested={len(spawned_sub_chats)}, max_concurrent={MAX_DIRECT_SUB_CHATS_PER_PARENT}"
                            )
                            continue

                        if len(spawned_sub_chats) > MAX_AUTO_SUB_CHATS_PER_TURN:
                            ensure_orchestration_envelope(request_data)
                            await create_orchestration_root(directus_service, request_data)
                            if current_ai_operation_id is None:
                                current_ai_operation_id = await _reserve_ai_iteration(
                                    task_id=task_id,
                                    iteration=iteration,
                                    model_id=current_model_id,
                                    system_prompt=iteration_system_prompt,
                                    message_history=current_message_history,
                                    tools=iteration_tools,
                                    output_token_limit=_orchestrated_ai_output_token_limit(
                                        current_model_id,
                                        request_data.orchestration_id,
                                        bool(getattr(request_data, "is_anonymous", False)),
                                    ),
                                    request_data=request_data,
                                    directus_service=directus_service,
                                )
                            proposed_credit_limit = max(
                                MAX_AUTO_SUB_CHAT_CREDITS,
                                sum(
                                    int(sc.get("budget_limit") or 0)
                                    for sc in spawned_sub_chats
                                    if isinstance(sc.get("budget_limit"), int)
                                ),
                            )
                            request_data.orchestration_descendant_limit = len(spawned_sub_chats)
                            request_data.orchestration_credit_limit = proposed_credit_limit
                            pending_context = {
                                "parent_request_data": request_data.model_dump(mode="json"),
                                "skill_config_dict": skill_config_dict or {},
                                "sub_chats": spawned_sub_chats,
                                "report_trigger": spawned_sub_chats[0].get("report_trigger", "all") if spawned_sub_chats else "all",
                                "execution_mode": execution_mode,
                                "context_policy": context_policy,
                                "created_at": int(time.time()),
                                "proposed_credit_limit": proposed_credit_limit,
                            }
                            await store_pending_sub_chat_confirmation(
                                cache_service=cache_service,
                                chat_id=request_data.chat_id,
                                task_id=task_id,
                                context=pending_context,
                            )
                            logger.info(
                                f"{log_prefix} [SUB_CHAT] Stored confirmation request for {len(spawned_sub_chats)} sub-chats"
                            )
                            if usage is not None:
                                yield usage
                            yield {
                                "__sub_chat_confirmation_required__": True,
                                "chat_id": request_data.chat_id,
                                "task_id": task_id,
                                "message_id": task_id,
                                "sub_chats": spawned_sub_chats,
                                "max_auto_sub_chats": MAX_AUTO_SUB_CHATS_PER_TURN,
                                "max_direct_sub_chats": MAX_DIRECT_SUB_CHATS_PER_PARENT,
                                "existing_sub_chats": existing_sub_chat_count,
                                "remaining_sub_chats": capacity_result["remaining"],
                                "execution_mode": execution_mode,
                                "context_policy": context_policy,
                                "proposed_credit_limit": proposed_credit_limit,
                            }
                            return

                        if execution_mode == "sequential":
                            logger.info(f"{log_prefix} [SUB_CHAT] Creating sequential queue with {len(spawned_sub_chats)} sub-chat(s)")
                            dispatch_tokens = await create_sub_chat_records(
                                directus_service=directus_service,
                                request_data=request_data,
                                spawned_sub_chats=spawned_sub_chats,
                                log_prefix=log_prefix,
                            )
                            if current_ai_operation_id is None:
                                current_ai_operation_id = await _reserve_ai_iteration(
                                    task_id=task_id,
                                    iteration=iteration,
                                    model_id=current_model_id,
                                    system_prompt=iteration_system_prompt,
                                    message_history=current_message_history,
                                    tools=iteration_tools,
                                    output_token_limit=_orchestrated_ai_output_token_limit(
                                        current_model_id,
                                        request_data.orchestration_id,
                                        bool(getattr(request_data, "is_anonymous", False)),
                                    ),
                                    request_data=request_data,
                                    directus_service=directus_service,
                                )

                            active_task_id = None
                            if spawned_sub_chats:
                                active_task_id = await dispatch_sub_chat_task(
                                    request_data=request_data,
                                    skill_config_dict=skill_config_dict or {},
                                    sub_chat=spawned_sub_chats[0],
                                    log_prefix=log_prefix,
                                    dispatch_token=dispatch_tokens[str(spawned_sub_chats[0]["id"])],
                                )
                                if cache_service and active_task_id:
                                    await cache_service.set_active_ai_task(spawned_sub_chats[0]["id"], active_task_id)

                            if cache_service:
                                await cache_service.set(
                                    f"sub_chat_pending:{request_data.chat_id}",
                                    {
                                        "parent_task_id": task_id,
                                        "parent_request_data": request_data.model_dump(mode="json"),
                                        "skill_config_dict": skill_config_dict or {},
                                        "expected_sub_chat_ids": [str(sc.get("id")) for sc in spawned_sub_chats if sc.get("id")],
                                        "sub_chats": spawned_sub_chats,
                                        "completed": {},
                                        "report_trigger": spawned_sub_chats[0].get("report_trigger", "all") if spawned_sub_chats else "all",
                                        "execution_mode": "sequential",
                                        "context_policy": context_policy,
                                        "next_index": 1 if spawned_sub_chats else 0,
                                        "active_sub_chat_id": spawned_sub_chats[0].get("id") if spawned_sub_chats else None,
                                        "active_task_id": active_task_id,
                                        "dispatch_tokens": dispatch_tokens,
                                        "created_at": int(time.time()),
                                    },
                                    ttl=60 * 60 * 24,
                                )

                            current_message_history.append({
                                "tool_call_id": tool_call_id,
                                "role": "tool",
                                "name": tool_name,
                                "content": json.dumps({
                                    "status": "spawned",
                                    "execution_mode": "sequential",
                                    "sub_chats": spawned_sub_chats,
                                    "message": f"Successfully queued {len(spawned_sub_chats)} sequential sub-chats. The parent will continue after the queue finishes.",
                                }),
                            })

                            yield {
                                "__spawn_sub_chats__": True,
                                "parent_id": request_data.chat_id,
                                "sub_chats": spawned_sub_chats,
                                "report_trigger": spawned_sub_chats[0].get("report_trigger", "all") if spawned_sub_chats else "all",
                                "execution_mode": "sequential",
                            }
                            yield {
                                "__sub_chat_progress__": True,
                                "chat_id": request_data.chat_id,
                                "message_id": task_id,
                                "task_id": task_id,
                                "execution_mode": "sequential",
                                "status": "running",
                                "total": len(spawned_sub_chats),
                                "completed": 0,
                                "active_sub_chat_id": spawned_sub_chats[0].get("id") if spawned_sub_chats else None,
                            }
                            if usage is not None:
                                yield usage
                            yield {"__awaiting_sub_chats_completion__": True, "chat_id": request_data.chat_id}
                            return

                        logger.info(f"{log_prefix} [SUB_CHAT] Creating {len(spawned_sub_chats)} sub-chat(s)")
                        dispatch_tokens = await create_sub_chat_records(
                            directus_service=directus_service,
                            request_data=request_data,
                            spawned_sub_chats=spawned_sub_chats,
                            log_prefix=log_prefix,
                        )
                        if current_ai_operation_id is None:
                            current_ai_operation_id = await _reserve_ai_iteration(
                                task_id=task_id,
                                iteration=iteration,
                                model_id=current_model_id,
                                system_prompt=iteration_system_prompt,
                                message_history=current_message_history,
                                tools=iteration_tools,
                                output_token_limit=_orchestrated_ai_output_token_limit(
                                    current_model_id,
                                    request_data.orchestration_id,
                                    bool(getattr(request_data, "is_anonymous", False)),
                                ),
                                request_data=request_data,
                                directus_service=directus_service,
                            )
                        for sub_chat in spawned_sub_chats:
                            child_task_id = await dispatch_sub_chat_task(
                                request_data=request_data,
                                skill_config_dict=skill_config_dict or {},
                                sub_chat=sub_chat,
                                log_prefix=log_prefix,
                                dispatch_token=dispatch_tokens[str(sub_chat["id"])],
                            )
                            if not child_task_id:
                                raise RuntimeError(f"Sub-chat child {sub_chat['id']} dispatch failed")

                        # Set up the tool response
                        tool_result_content_str = json.dumps({
                            "status": "spawned",
                            "sub_chats": spawned_sub_chats,
                            "message": f"Successfully spawned {len(spawned_sub_chats)} sub-chats in the background. Awaiting their completion."
                        })
                        
                        tool_response_message = {
                            "tool_call_id": tool_call_id,
                            "role": "tool",
                            "name": tool_name,
                            "content": tool_result_content_str
                        }
                        current_message_history.append(tool_response_message)
                        
                        # Yield the spawn sub-chats marker
                        yield {
                            "__spawn_sub_chats__": True,
                            "parent_id": request_data.chat_id,
                            "sub_chats": spawned_sub_chats,
                            "report_trigger": spawned_sub_chats[0].get("report_trigger", "all") if spawned_sub_chats else "all"
                        }
                        
                        # Stop parent execution now because we need to wait for completion of sub-chats
                        # unless they are marked as independent (wait_for_completion=False).
                        # Let's check if there are any that require waiting
                        any_wait = any(sc.get("wait_for_completion", True) for sc in spawned_sub_chats)
                        if any_wait:
                            logger.info(f"{log_prefix} [SUB_CHAT] Yielding wait marker and pausing parent execution")
                            if usage is not None:
                                yield usage
                            yield {"__awaiting_sub_chats_completion__": True, "chat_id": request_data.chat_id}
                            return
                        continue

                    elif skill_id == "end_subchat":
                        summary = parsed_args.get("summary", "")
                        logger.info(f"{log_prefix} [SUB_CHAT] LLM requested end_subchat")
                        
                        # Save sub-chat completion status in Directus/Cache
                        if directus_service:
                            try:
                                # Mark current chat as completed
                                await directus_service.chat.update_chat_fields_in_directus(
                                    request_data.chat_id,
                                    {"updated_at": int(time.time()), "is_sub_chat": True}
                                )
                                logger.info(f"{log_prefix} [SUB_CHAT] Marked sub-chat as completed in Directus.")
                                
                                # Report the summary through Redis/continuation handling. Do not write
                                # plaintext system messages to Directus; parent synthesis is zero-knowledge
                                # and handled by the normal AI continuation pipeline.
                                if request_data.parent_id:
                                    if cache_service:
                                        # Set completion marker in redis
                                        await cache_service.set(f"subchat:{request_data.chat_id}:completed", True, ttl=86400)
                                    
                                    # Yield a completed event back to client
                                    yield {
                                        "__sub_chat_completed__": True,
                                        "sub_chat_id": request_data.chat_id,
                                        "parent_id": request_data.parent_id,
                                        "summary": summary
                                    }
                            except Exception as db_err:
                                logger.error(f"{log_prefix} [SUB_CHAT] Error saving completion to Directus: {db_err}", exc_info=True)
                        
                        tool_result_content_str = json.dumps({
                            "status": "completed",
                            "message": "Sub-chat ended successfully. Report submitted to parent."
                        })
                        tool_response_message = {
                            "tool_call_id": tool_call_id,
                            "role": "tool",
                            "name": tool_name,
                            "content": tool_result_content_str
                        }
                        current_message_history.append(tool_response_message)
                        continue

                    elif skill_id == "ask_user_input":
                        question = parsed_args.get("question", "")
                        logger.info(f"{log_prefix} [SUB_CHAT] LLM requested ask_user_input: {question}")
                        
                        # Set sub-chat state in Directus/Cache to waiting_for_user
                        if directus_service:
                            try:
                                await directus_service.chat.update_chat_fields_in_directus(
                                    request_data.chat_id,
                                    {"updated_at": int(time.time())}
                                )
                            except Exception as db_err:
                                logger.error(f"{log_prefix} [SUB_CHAT] Error updating status in Directus: {db_err}")
                        
                        # Yield the user input requested event
                        yield {
                            "__awaiting_user_input__": True,
                            "question": question,
                            "chat_id": request_data.chat_id,
                            "parent_id": request_data.parent_id
                        }
                        return  # Halt sub-chat execution until user responds

                    else:
                        logger.warning(f"{log_prefix} Unknown system tool: {skill_id}")
                        tool_result_content_str = json.dumps({"error": f"Unknown system tool: {skill_id}"})
                        tool_response_message = {
                            "tool_call_id": tool_call_id,
                            "role": "tool",
                            "name": tool_name,
                            "content": tool_result_content_str
                        }
                        current_message_history.append(tool_response_message)
                        continue
                
                # Validate arguments against original schema (with min/max constraints)
                # The schema sent to LLM providers has min/max removed, but we validate against the original
                is_valid, validation_error = _validate_tool_arguments_against_schema(
                    arguments=parsed_args,
                    app_id=app_id,
                    skill_id=skill_id,
                    discovered_apps_metadata=discovered_apps_metadata,
                    task_id=task_id
                )
                
                if not is_valid:
                    logger.warning(
                        f"{log_prefix} Tool call arguments failed validation: {validation_error}. "
                        f"Proceeding anyway, but skill may reject invalid values."
                    )
                    # Optionally: clamp values to valid range or reject the tool call
                    # For now, we'll proceed and let the skill handle validation
                
                logger.debug(f"{log_prefix} Executing skill '{tool_name}' with app_id='{app_id}', skill_id='{skill_id}'")

                # STEP 1: Get placeholder embed (already created during stream processing)
                # The placeholder was created and streamed inline when the tool call was detected
                # This shows the "processing" state to users IMMEDIATELY (not after LLM stream completes)
                placeholder_embed_data = inline_placeholder_embeds.get(tool_call_id)
                
                if placeholder_embed_data:
                    logger.debug(
                        f"{log_prefix} Using inline-created placeholder embed: "
                        f"embed_id={placeholder_embed_data.get('embed_id')}"
                    )
                else:
                    # Fallback: create placeholder if inline creation failed
                    # This can happen if stream processing encountered an error
                    logger.warning(f"{log_prefix} No inline placeholder found for tool_call_id={tool_call_id}, creating now")
                    if cache_service and user_vault_key_id and directus_service:
                        try:
                            from backend.core.api.app.services.embed_service import EmbedService

                            # Use passed-in encryption_service
                            embed_service = EmbedService(
                                cache_service=cache_service,
                                directus_service=directus_service,
                                encryption_service=encryption_service
                            )

                            # Extract metadata from skill arguments for placeholder
                            # Handle both direct args (query) and nested args (requests[0].query)
                            metadata = {}
                            
                            # Direct query (simple skill format)
                            if "query" in parsed_args:
                                metadata["query"] = parsed_args["query"]
                            # Nested query (web search uses requests array)
                            elif "requests" in parsed_args and isinstance(parsed_args["requests"], list) and len(parsed_args["requests"]) > 0:
                                first_request = parsed_args["requests"][0]
                                if isinstance(first_request, dict) and "query" in first_request:
                                    metadata["query"] = first_request["query"]
                            
                            # Extract provider from LLM args (direct or nested), then validate
                            # against the skill's known providers list to prevent hallucination.
                            raw_provider: Optional[str] = None
                            if "provider" in parsed_args:
                                raw_provider = parsed_args["provider"]
                            elif "requests" in parsed_args and isinstance(parsed_args["requests"], list) and len(parsed_args["requests"]) > 0:
                                first_request = parsed_args["requests"][0]
                                if isinstance(first_request, dict) and "provider" in first_request:
                                    raw_provider = first_request["provider"]

                            # Validate provider (covers fallback + hallucination correction)
                            if skill_id == "search" or raw_provider is not None:
                                validated_provider = _validate_skill_provider(
                                    provider=raw_provider,
                                    app_id=app_id,
                                    skill_id=skill_id,
                                    discovered_apps_metadata=discovered_apps_metadata,
                                    log_prefix=log_prefix,
                                )
                                if validated_provider is not None:
                                    metadata["provider"] = validated_provider

                            preview_metadata = await _resolve_skill_preview_metadata(
                                app_id=app_id,
                                skill_id=skill_id,
                                request_metadata=metadata,
                                discovered_apps_metadata=discovered_apps_metadata,
                                log_prefix=log_prefix,
                            )
                            metadata.update(preview_metadata)

                            # Create placeholder embed (fallback path)
                            placeholder_embed_data = await embed_service.create_processing_embed_placeholder(
                                app_id=app_id,
                                skill_id=skill_id,
                                chat_id=request_data.chat_id,
                                message_id=request_data.message_id,
                                user_id=request_data.user_id,
                                user_id_hash=request_data.user_id_hash,
                                user_vault_key_id=user_vault_key_id,
                                task_id=task_id,
                                metadata=metadata,
                                log_prefix=log_prefix
                            )

                            if placeholder_embed_data:
                                # Stream embed reference (fallback path)
                                embed_reference_json = placeholder_embed_data.get("embed_reference")
                                embed_code_block = f"```json\n{embed_reference_json}\n```\n\n"
                                yield embed_code_block
                                
                                # Publish "processing" status (fallback path)
                                await _publish_skill_status(
                                    cache_service=cache_service,
                                    task_id=task_id,
                                    request_data=request_data,
                                    app_id=app_id,
                                    skill_id=skill_id,
                                    status="processing",
                                    preview_data=metadata
                                )
                                logger.info(
                                    f"{log_prefix} FALLBACK: Created and streamed processing placeholder: "
                                    f"embed_id={placeholder_embed_data.get('embed_id')}"
                                )
                        except Exception as e:
                            logger.error(f"{log_prefix} FALLBACK: Error creating placeholder embed: {e}", exc_info=True)

                # STEP 2: Execute skill with support for multiple parallel requests
                # Pass chat_id and message_id so skills can use them when recording usage
                # Pass skill_task_id for individual skill cancellation (allows user to cancel just this skill)
                
                parallel_execution = parallel_executions.get(tool_call_id)

                # Get skill_task_id from placeholder (generated during create_processing_embed_placeholder)
                # This ID is stored in embed content and allows frontend to cancel this specific skill
                # without cancelling the entire AI response
                skill_task_id = parallel_execution.get("skill_task_id") if parallel_execution else None
                if placeholder_embed_data:
                    skill_task_id = placeholder_embed_data.get("skill_task_id")
                    if not skill_task_id:
                        # Handle multiple placeholders case
                        if isinstance(placeholder_embed_data.get("placeholders"), list):
                            # For multiple requests, use first placeholder's skill_task_id
                            # (all requests in a tool call share the same cancellation scope)
                            first_placeholder = placeholder_embed_data.get("placeholders", [{}])[0]
                            skill_task_id = first_placeholder.get("skill_task_id")
                
                # Generate skill_task_id if not found (fallback for legacy placeholders)
                if not skill_task_id:
                    skill_task_id = generate_skill_task_id()
                    logger.debug(f"{log_prefix} Generated fallback skill_task_id: {skill_task_id}")
                
                # Track if skill was cancelled
                skill_was_cancelled = False
                reserved_skill_operation_ids: list[str] = []
                provider_dispatch_attempted = bool(parallel_execution)
                
                try:
                    # ARGUMENT NORMALIZATION:
                    # LLMs sometimes send flat arguments (e.g., {"prompt": "..."}) instead of the
                    # required {"requests": [...]} array format for skills that expect it.
                    # Detect this mismatch using the skill's tool_schema and normalize the arguments.
                    # See: https://github.com/anomalyco/OpenMates/issues/XXX (image generation 422 bug)
                    skill_arguments = parallel_execution["arguments"] if parallel_execution else _normalize_skill_arguments(
                        arguments=_get_skill_execution_args(parsed_args, placeholder_embed_data),
                        app_id=app_id,
                        skill_id=skill_id,
                        discovered_apps_metadata=discovered_apps_metadata,
                        task_id=task_id,
                        message_history=current_message_history,
                    )
                    skill_arguments = _apply_repository_relevance_criteria_guard(
                        skill_arguments,
                        app_id,
                        skill_id,
                        current_message_history,
                        log_prefix,
                    )
                    natural_workflow_authoring = is_natural_language_authoring_call(
                        app_id, skill_id, skill_arguments,
                    )
                    if natural_workflow_authoring:
                        skill_arguments = with_trusted_timezone(skill_arguments, user_timezone)

                    # For async skills (e.g., images.generate), thread placeholder embed_ids
                    # so the Celery task can update the existing placeholder instead of creating new embeds.
                    # This enables the in-place "processing" -> "finished" transition.
                    if placeholder_embed_data and not parallel_execution:
                        # Extract placeholder embed_ids to pass to the skill
                        _placeholder_ids = []
                        if isinstance(placeholder_embed_data, dict) and placeholder_embed_data.get("multiple"):
                            # Multiple placeholders
                            for p in placeholder_embed_data.get("placeholders", []):
                                _placeholder_ids.append(p.get("embed_id"))
                        elif isinstance(placeholder_embed_data, dict) and "embed_id" in placeholder_embed_data:
                            # Single placeholder
                            _placeholder_ids.append(placeholder_embed_data["embed_id"])
                        
                        if _placeholder_ids:
                            # Inject as metadata field (underscore prefix = stripped before Pydantic validation)
                            # Copy from skill_arguments (not parsed_args) to preserve normalization
                            skill_arguments = skill_arguments.copy()
                            skill_arguments["_placeholder_embed_ids"] = _placeholder_ids
                    
                    # Inject user_vault_key_id as server-side context for skills that need
                    # Vault Transit access (e.g. images-view needs it to look up embed
                    # crypto details from the Redis cache). Underscore prefix ensures it is
                    # stripped before Pydantic validation in base_app.py.
                    if user_vault_key_id and not parallel_execution:
                        skill_arguments = skill_arguments.copy()
                        skill_arguments["_user_vault_key_id"] = user_vault_key_id

                    # Inject the embed_ref → embed_id mapping so skills like images-view
                    # can resolve a human-readable file_path argument (e.g. "my_photo.jpg")
                    # back to the internal UUID embed_id for Redis/Vault/S3 lookup.
                    # Underscore prefix causes base_app.py to strip it before Pydantic validation.
                    embed_file_path_index = getattr(request_data, "embed_file_path_index", None)
                    if embed_file_path_index and not parallel_execution:
                        skill_arguments = skill_arguments.copy()
                        skill_arguments["_file_path_index"] = embed_file_path_index

                    model_override = _resolve_app_skill_model_override(
                        getattr(request_data, "user_preferences", None),
                        app_id,
                        skill_id,
                        log_prefix,
                    )
                    if model_override and not parallel_execution:
                        skill_arguments = skill_arguments.copy()
                        skill_arguments["_full_model_reference_override"] = model_override
                        logger.info(
                            f"{log_prefix} Applying app skill model override for "
                            f"{app_id}.{skill_id}: {model_override}"
                        )

                    connected_account_token_artifacts: list[dict[str, str]] = []
                    connected_account_journal_entries: list[dict[str, Any]] = []
                    from backend.apps.ai.processing.connected_account_execution import is_connected_account_skill

                    if is_connected_account_skill(app_id, skill_id) and (
                        app_id != "finance" or skill_arguments.get("connected_account_requests")
                    ):
                        from backend.apps.ai.processing.connected_account_execution import (
                            cleanup_connected_account_token_artifacts,
                            connected_account_action_for_skill,
                            prepare_connected_account_skill_execution,
                        )

                        try:
                            connected_context = await prepare_connected_account_skill_execution(
                                app_id=app_id,
                                skill_id=skill_id,
                                skill_arguments=skill_arguments,
                                connected_account_token_refs=getattr(request_data, "connected_account_token_refs", None),
                                user_id=request_data.user_id,
                                user_vault_key_id=user_vault_key_id,
                                chat_id=request_data.chat_id,
                                message_id=request_data.message_id,
                                cache_service=cache_service,
                                encryption_service=encryption_service,
                            )
                            skill_arguments = connected_context.skill_arguments
                            connected_account_token_artifacts = connected_context.token_artifacts
                        except PermissionError as permission_error:
                            logger.info(
                                f"{log_prefix} Connected-account permission required for "
                                f"{app_id}.{skill_id}: {permission_error}"
                            )
                            if getattr(request_data, "is_connected_account_permission_continuation", False):
                                current_message_history.append({
                                    "tool_call_id": tool_call_id,
                                    "role": "tool",
                                    "name": tool_name,
                                    "content": json.dumps({
                                        "status": "permission_denied",
                                        "reason": str(permission_error),
                                        "app_id": app_id,
                                        "skill_id": skill_id,
                                    }),
                                })
                                continue

                            from backend.apps.ai.processing.connected_account_permission_request import (
                                create_connected_account_permission_request,
                            )

                            request_id = await create_connected_account_permission_request(
                                cache_service=cache_service,
                                user_id=request_data.user_id,
                                chat_id=request_data.chat_id,
                                message_id=request_data.message_id,
                                user_id_hash=request_data.user_id_hash,
                                app_id=app_id,
                                skill_id=skill_id,
                                action=connected_account_action_for_skill(app_id, skill_id),
                                skill_arguments=skill_arguments,
                                connected_account_directory=getattr(request_data, "connected_account_directory", None),
                                reason=str(permission_error),
                                task_id=task_id,
                                preprocessing_resume_ref=getattr(request_data, "preprocessing_resume_ref", None),
                            )
                            if request_id:
                                yield {"__awaiting_connected_account_permission__": True, "request_id": request_id}
                                return
                            current_message_history.append({
                                "tool_call_id": tool_call_id,
                                "role": "tool",
                                "name": tool_name,
                                "content": json.dumps({
                                    "status": "permission_unavailable",
                                    "reason": (
                                        "No connected calendar account is available for this action. "
                                        "Ask the user to connect or select a Calendar account."
                                    ),
                                    "app_id": app_id,
                                    "skill_id": skill_id,
                                }),
                            })
                            continue

                    if _is_async_skill_blocked_in_orchestration(request_data, app_id, skill_id):
                        current_message_history.append({
                            "tool_call_id": tool_call_id,
                            "role": "tool",
                            "name": tool_name,
                            "content": json.dumps({
                                "status": "blocked_in_orchestration",
                                "reason": "Long-running background skills are unavailable inside bounded sub-chat trees.",
                                "app_id": app_id,
                                "skill_id": skill_id,
                            }),
                        })
                        logger.warning(
                            "%s Rejected async skill %s.%s inside orchestration %s before dispatch",
                            log_prefix,
                            app_id,
                            skill_id,
                            request_data.orchestration_id,
                        )
                        continue

                    if parallel_execution:
                        reserved_skill_operation_ids = parallel_execution["reservation_ids"]
                    elif (app_id, skill_id) not in ASYNC_SKILLS or getattr(request_data, "is_anonymous", False):
                        if not directus_service and request_data.orchestration_id:
                            raise RuntimeError("Orchestrated skill reservation requires Directus")
                        if directus_service or getattr(request_data, "is_anonymous", False):
                            reserved_skill_operation_ids = await _reserve_skill_credits(
                                task_id=task_id,
                                execution_id=tool_call_id,
                                request_data=request_data,
                                app_id=app_id,
                                skill_id=skill_id,
                                discovered_apps_metadata=discovered_apps_metadata,
                                parsed_args=skill_arguments,
                                directus_service=directus_service,  # type: ignore[arg-type]
                                log_prefix=log_prefix,
                            )

                    # Execute skill with retry logic (20s timeout, 1 retry by default)
                    # On timeout, the request is cancelled and retried with a fresh connection,
                    # which helps when external APIs are slow or proxy IPs need rotation
                    try:
                        if parallel_execution:
                            parallel_outcome = parallel_execution["outcome"]
                            if isinstance(parallel_outcome, BaseException):
                                raise parallel_outcome
                            results = parallel_outcome
                        else:
                            with ai_phase_span("tool"):
                                provider_dispatch_attempted = True
                                results = await execute_skill_with_multiple_requests(
                                    app_id=app_id,
                                    skill_id=skill_id,
                                    arguments=skill_arguments,
                                    timeout=90.0 if natural_workflow_authoring else DEFAULT_SKILL_TIMEOUT,
                                    chat_id=request_data.chat_id,
                                    message_id=request_data.message_id,
                                    user_id=request_data.user_id,
                                    team_id=request_data.team_id,
                                    skill_task_id=skill_task_id,
                                    cache_service=cache_service,
                                    encryption_service=encryption_service,
                                    secrets_manager=secrets_manager,
                                    max_retries=0 if natural_workflow_authoring or getattr(request_data, "is_anonymous", False) else 1,
                                    is_anonymous=bool(getattr(request_data, "is_anonymous", False)),
                                )
                        results, ascii_sanitization_stats = sanitize_text_payload_for_ascii_smuggling(
                            results,
                            log_prefix=f"{log_prefix}[{app_id}.{skill_id}] ",
                        )
                        if ascii_sanitization_stats.get("removed_count", 0) > 0:
                            logger.warning(
                                f"{log_prefix} Removed {ascii_sanitization_stats['removed_count']} "
                                f"ASCII-smuggling characters from {app_id}.{skill_id} skill results "
                                f"across {ascii_sanitization_stats.get('fields_sanitized', 0)} field(s)"
                            )
                        if connected_account_token_artifacts:
                            connected_account_journal_entries = await _record_connected_account_operation_journal_entries(
                                app_id=app_id,
                                skill_id=skill_id,
                                results=results,
                                token_artifacts=connected_account_token_artifacts,
                                user_id=request_data.user_id,
                                user_vault_key_id=user_vault_key_id,
                                chat_id=request_data.chat_id,
                                message_id=request_data.message_id,
                                directus_service=directus_service,
                                encryption_service=encryption_service,
                                cache_service=cache_service,
                                log_prefix=log_prefix,
                            )
                    finally:
                        if connected_account_token_artifacts:
                            from backend.apps.ai.processing.connected_account_execution import cleanup_connected_account_token_artifacts

                            await cleanup_connected_account_token_artifacts(
                                token_artifacts=connected_account_token_artifacts,
                                cache_service=cache_service,
                                encryption_service=encryption_service,
                            )
                    
                    # === RECORD SUCCESSFUL SKILL EXECUTION FOR DEDUPLICATION ===
                    # Store this successful call so subsequent iterations won't re-execute it.
                    # This prevents duplicate side effects (e.g., multiple reminders) when LLMs
                    # repeatedly call the same tool across iterations.
                    # Only record if we got valid results (not cancelled, not error).
                    if _should_cache_skill_call_for_dedup(results):
                        embed_id_for_dedup = placeholder_embed_data.get("embed_id") if placeholder_embed_data else None
                        completed_skill_calls[call_hash] = {
                            "embed_id": embed_id_for_dedup,
                            "skill_task_id": skill_task_id,
                        }
                        logger.info(
                            f"{log_prefix} [DEDUP] Recorded successful '{app_id}.{skill_id}' call "
                            f"(hash={call_hash[:8]}..., embed_id={embed_id_for_dedup})"
                        )
                        
                except SkillCancelledException:
                    # User cancelled this specific skill - continue with cancelled result
                    # The main AI response will continue, just without this skill's data
                    logger.info(
                        f"{log_prefix} Skill '{app_id}.{skill_id}' was cancelled by user "
                        f"(skill_task_id={skill_task_id}). Main processing will continue."
                    )
                    skill_was_cancelled = True
                    if getattr(request_data, "is_anonymous", False) and provider_dispatch_attempted:
                        try:
                            await _settle_anonymous_skill_quote(
                                app_id=app_id,
                                skill_id=skill_id,
                                parsed_args=skill_arguments,
                                discovered_apps_metadata=discovered_apps_metadata,
                                reserved_operation_ids=reserved_skill_operation_ids,
                                log_prefix=log_prefix,
                            )
                        finally:
                            reserved_skill_operation_ids = []
                    # Create cancelled result that tells the LLM the skill was cancelled
                    results = [{
                        "status": "cancelled",
                        "message": f"The {skill_id} skill was cancelled by the user. Please continue without this information.",
                        "app_id": app_id,
                        "skill_id": skill_id
                    }]
                    
                    # Update embed status to "cancelled" so frontend shows appropriate state
                    if cache_service and placeholder_embed_data:
                        try:
                            embed_id = placeholder_embed_data.get("embed_id")
                            if embed_id:
                                await _publish_skill_status(
                                    cache_service=cache_service,
                                    task_id=task_id,
                                    request_data=request_data,
                                    app_id=app_id,
                                    skill_id=skill_id,
                                    status="cancelled",
                                    preview_data={"embed_id": embed_id, "cancelled_by_user": True}
                                )
                        except Exception as status_error:
                            logger.error(f"{log_prefix} Error publishing cancelled status: {status_error}")
                except RequiredRecoveryOutputError:
                    raise
                except Exception as skill_error:
                    # CRITICAL: Handle skill execution failures gracefully
                    # When a skill fails (HTTP error, timeout, rate limit, etc.), we:
                    # 1. Create an error result that tells the LLM the skill failed
                    # 2. Update the embed status to "error" so frontend shows failure
                    # 3. Continue processing - don't crash the entire AI response
                    # This allows the LLM to interpret results from successful skills
                    # and provide a meaningful response even when some skills fail.
                    error_message = str(skill_error)
                    if getattr(request_data, "is_anonymous", False) and provider_dispatch_attempted:
                        try:
                            await _settle_anonymous_skill_quote(
                                app_id=app_id,
                                skill_id=skill_id,
                                parsed_args=skill_arguments,
                                discovered_apps_metadata=discovered_apps_metadata,
                                reserved_operation_ids=reserved_skill_operation_ids,
                                log_prefix=log_prefix,
                            )
                        finally:
                            reserved_skill_operation_ids = []
                    logger.warning(
                        f"{log_prefix} Skill '{app_id}.{skill_id}' failed with error: {error_message}. "
                        f"Main processing will continue with error result for LLM."
                    )
                    
                    # Create error result that tells the LLM the skill failed
                    # This allows the LLM to acknowledge the failure and continue with other results
                    results = [{
                        "status": "error",
                        "error": error_message,
                        "message": f"The {skill_id} skill failed: {error_message}. Please continue with any other available information.",
                        "app_id": app_id,
                        "skill_id": skill_id
                    }]
                    
                    # Update embed status to "error" so frontend shows failure state
                    if cache_service and placeholder_embed_data:
                        try:
                            embed_id = placeholder_embed_data.get("embed_id")
                            if embed_id:
                                # Use embed_service to properly update the embed status
                                from backend.core.api.app.services.embed_service import EmbedService
                                embed_service = EmbedService(
                                    cache_service=cache_service,
                                    directus_service=directus_service,
                                    encryption_service=encryption_service
                                )
                                await embed_service.update_embed_status_to_error(
                                    embed_id=embed_id,
                                    app_id=app_id,
                                    skill_id=skill_id,
                                    error_message=error_message,
                                    chat_id=request_data.chat_id,
                                    message_id=request_data.message_id,
                                    user_id=request_data.user_id,
                                    user_id_hash=request_data.user_id_hash,
                                    user_vault_key_id=user_vault_key_id,
                                    task_id=task_id,
                                    log_prefix=log_prefix
                                )
                                logger.info(f"{log_prefix} Updated embed {embed_id} status to 'error'")
                                failed_embed_ids.add(embed_id)
                        except Exception as status_error:
                            logger.error(f"{log_prefix} Error updating embed status to error: {status_error}")

                # =====================================================================
                # ASYNC SKILL DETECTION
                # =====================================================================
                # Long-running skills (e.g., images.generate) return immediately with
                # {"status": "processing", "task_id": "...", "embed_id": "..."}
                # and dispatch a Celery task that will update the embed asynchronously.
                #
                # For these skills, we SKIP the normal embed update flow because:
                # 1. The placeholder embed is already in "processing" state
                # 2. The Celery task will update it to "finished" when done
                # 3. The TOON encoding / update_embed_with_results flow doesn't apply
                #
                # We still need to:
                # - Create a minimal tool_result for the LLM (so it knows the task was dispatched)
                # - Publish a "processing" skill status (placeholder already shows this)
                # - Skip TOON encoding, embed updates, and credit charging
                # =====================================================================
                is_async_skill = False
                if results and len(results) == 1 and isinstance(results[0], dict):
                    first_result = results[0]
                    if first_result.get("status") == "processing" and ("task_id" in first_result or "task_ids" in first_result):
                        is_async_skill = True
                        logger.info(
                            f"{log_prefix} Detected async skill '{app_id}.{skill_id}' with status='processing'. "
                            f"Skipping embed update flow - Celery task will handle it. "
                            f"task_id={first_result.get('task_id')}, embed_id={first_result.get('embed_id')}"
                        )
                
                if is_async_skill:
                    # For async skills, either pass completed results after a short inline
                    # wait or preserve task identifiers so API/chat consumers can track it.
                    async_result = results[0]
                    async_task_ids = []
                    if async_result.get("task_id"):
                        async_task_ids.append(async_result.get("task_id"))
                    async_task_ids.extend(async_result.get("task_ids") or [])
                    # Inline waits are useful for a single async tool, but in a parallel
                    # tool batch they block later tools and can leave their placeholders
                    # stuck. Let the async continuation path handle multi-tool batches.
                    should_wait_inline = (
                        (app_id, skill_id) in ASYNC_SKILL_INLINE_WAIT_SKILLS
                        and len(tool_calls_for_this_turn) == 1
                    )
                    inline_wait_deadline = time.time() + ASYNC_SKILL_INLINE_WAIT_SECONDS if should_wait_inline else None
                    waits_for_remote_command = (
                        (app_id, skill_id) == ("code", "run")
                        and isinstance(parsed_args, dict)
                        and parsed_args.get("target") == "remote_source"
                        and parsed_args.get("wait_for_completion", True) is True
                    )
                    is_remote_command = (
                        (app_id, skill_id) == ("code", "run")
                        and isinstance(parsed_args, dict)
                        and parsed_args.get("target") == "remote_source"
                    )
                    try:
                        from backend.apps.ai.tasks.async_skill_continuation import (
                            cache_async_skill_continuation_context,
                            wait_for_async_skill_completion,
                        )

                        for async_task_id in async_task_ids:
                            await cache_async_skill_continuation_context(
                                cache_service=cache_service,
                                async_task_id=async_task_id,
                                request_data=request_data,
                                skill_config_dict=skill_config_dict,
                                app_id=app_id,
                                skill_id=skill_id,
                                tool_name=tool_name,
                                tool_arguments=parsed_args if isinstance(parsed_args, dict) else {},
                                preprocessing_result=preprocessing_results,
                                inline_wait_deadline=inline_wait_deadline,
                                requires_current_turn=is_remote_command,
                                defer_until_initial_response_complete=(
                                    is_remote_command and not waits_for_remote_command
                                ),
                            )
                        if (
                            is_remote_command
                        ):
                            from backend.core.api.app.services.remote_command_service import (
                                RemoteCommandService,
                            )

                            for async_task_id in async_task_ids:
                                await RemoteCommandService(cache_service).register_continuation(
                                    user_id=request_data.user_id,
                                    execution_id=str(async_task_id),
                                )
                        if async_task_ids:
                            logger.info(
                                f"{log_prefix} Cached async skill continuation context for "
                                f"{len(async_task_ids)} task(s) from '{app_id}.{skill_id}'"
                            )
                        inline_completion = None
                        if should_wait_inline and async_task_ids:
                            logger.info(
                                f"{log_prefix} Waiting up to {ASYNC_SKILL_INLINE_WAIT_SECONDS:.0f}s for "
                                f"async skill '{app_id}.{skill_id}' to finish inline"
                            )
                            inline_completion = await wait_for_async_skill_completion(
                                cache_service=cache_service,
                                async_task_ids=async_task_ids,
                                timeout_seconds=ASYNC_SKILL_INLINE_WAIT_SECONDS,
                            )
                        if inline_completion:
                            tool_result_content_str = encode(inline_completion)
                            logger.info(
                                f"{log_prefix} Async skill '{app_id}.{skill_id}' finished during inline wait; "
                                "passing completed results to LLM"
                            )
                        else:
                            if waits_for_remote_command and async_task_ids:
                                request_data.awaiting_async_skill_continuation = True
                            tool_result_content_str = json.dumps(
                                _build_async_skill_pending_tool_result(
                                    async_result=async_result,
                                    async_task_ids=async_task_ids,
                                    app_id=app_id,
                                    skill_id=skill_id,
                                    inline_wait_seconds=ASYNC_SKILL_INLINE_WAIT_SECONDS if should_wait_inline else 0,
                                )
                            )
                    except Exception as continuation_cache_error:
                        logger.error(
                            f"{log_prefix} Failed to cache async skill continuation context: {continuation_cache_error}",
                            exc_info=True,
                        )
                        tool_result_content_str = json.dumps(
                            _build_async_skill_pending_tool_result(
                                async_result=async_result,
                                async_task_ids=async_task_ids,
                                app_id=app_id,
                                skill_id=skill_id,
                                inline_wait_seconds=ASYNC_SKILL_INLINE_WAIT_SECONDS if should_wait_inline else 0,
                            )
                        )
                    
                    # Publish "finished" skill status (the embed itself stays "processing")
                    # This tells the frontend that the skill call completed (dispatched successfully)
                    await _publish_skill_status(
                        cache_service=cache_service,
                        task_id=task_id,
                        request_data=request_data,
                        app_id=app_id,
                        skill_id=skill_id,
                        status="finished",
                        preview_data={
                            "status": "processing",
                            "embed_id": async_result.get("embed_id"),
                            "task_id": async_result.get("task_id"),
                            "prompt": parsed_args.get("requests", [{}])[0].get("prompt", "") if isinstance(parsed_args, dict) else "",
                            "model": parsed_args.get("requests", [{}])[0].get("model", "") if isinstance(parsed_args, dict) else "",
                        }
                    )
                    
                    # Skip everything below (TOON encoding, embed updates, credit charging)
                    # and yield the tool result for the LLM
                    # The tool_result_content_str is used by the LLM iteration loop

                # SKIP normalization, TOON encoding, embed updates, and credit charging for async skills.
                # These skills (e.g., images.generate) dispatch Celery tasks and return immediately.
                # The tool_result_content_str was already set above; we jump directly to tool_call_info tracking.
                
                # Normalize skill responses that wrap actual results in a "results" field (e.g., web search)
                # execute_skill_with_multiple_requests returns one entry per request, but search skills return
                # a response object with its own "results" array.
                # 
                # CRITICAL: Preserve grouped structure for embed creation (multiple requests = multiple embeds)
                # Flatten only for LLM inference (token efficiency)
                response_ignore_fields: Optional[List[str]] = None
                first_response: Optional[Dict[str, Any]] = None  # Initialize to avoid UnboundLocalError
                grouped_results: Optional[List[Dict[str, Any]]] = None  # Preserve grouping for embed creation
                provider_result_data = results  # Preserve trusted response wrappers before LLM flattening.
                
                # Detect multimodal content block results from view skills (e.g., images.view).
                # These return [[{"type": "text", ...}, {"type": "image_url", ...}]] — a list
                # containing a single list of OpenAI-style content blocks.
                # We must NOT TOON-encode them; instead we pass the inner list directly as
                # tool_result_content_str so the provider adapters can convert the image_url
                # block to the LLM-specific format (Anthropic image source, Gemini inlineData, etc.).
                is_multimodal_result = (
                    not is_async_skill
                    and isinstance(results, list)
                    and len(results) == 1
                    and isinstance(results[0], list)
                    and len(results[0]) > 0
                    and all(
                        isinstance(b, dict) and b.get("type") in ("text", "image_url")
                        for b in results[0]
                    )
                    and any(b.get("type") == "image_url" for b in results[0])
                )
                if is_multimodal_result:
                    # Bypass all TOON encoding — set tool_result_content_str to the raw content
                    # block list so it arrives at the LLM as a proper multimodal tool result.
                    # preview_data["results_toon"] is set later when is_multimodal_result is False;
                    # for multimodal results we skip both TOON encoding blocks below.
                    tool_result_content_str = results[0]
                    logger.info(
                        f"{log_prefix} Detected multimodal content block result from '{tool_name}' "
                        f"({len(results[0])} blocks). Bypassing TOON encoding — passing raw list to LLM."
                    )

                if not is_async_skill and results and all(isinstance(r, dict) and "results" in r for r in results):
                    first_response = results[0]
                    # Skills no longer provide preview_data - we'll create it in main_processor
                    response_ignore_fields = first_response.get("ignore_fields_for_inference")

                    # PRESERVE GROUPING: Extract the grouped structure from the response
                    # execute_skill_with_multiple_requests returns [response_dict] where response_dict is:
                    # {"results": [{"id": 1, "results": [...]}, {"id": 2, "results": [...]}, ...], "provider": "...", ...}
                    # We need to extract the "results" array from the response dict to get the grouped structure
                    response_results_array = first_response.get("results", [])
                    
                    # Check if response_results_array contains the grouped structure (each item has "id" and "results")
                    if (isinstance(response_results_array, list) and 
                        len(response_results_array) > 0 and 
                        all(isinstance(r, dict) and "id" in r and "results" in r for r in response_results_array)):
                        # This is the grouped structure: [{"id": 1, "results": [...]}, {"id": 2, "results": [...]}, ...]
                        grouped_results = response_results_array
                        logger.debug(f"{log_prefix} Detected grouped results structure with {len(grouped_results)} request groups")
                    else:
                        # Fallback: Not grouped, treat as single request
                        grouped_results = None
                        logger.debug(f"{log_prefix} Results are not in grouped structure format")
                    
                    # Flatten only for LLM inference (token efficiency)
                    flattened_results: List[Dict[str, Any]] = []
                    for response in results:
                        response_results = response.get("results")
                        if isinstance(response_results, list):
                            # Check if response_results is grouped structure or flat list
                            if response_results and isinstance(response_results[0], dict) and "id" in response_results[0] and "results" in response_results[0]:
                                # Grouped structure: extract results from each group
                                for group in response_results:
                                    group_results = group.get("results", [])
                                    if isinstance(group_results, list):
                                        flattened_results.extend(group_results)
                            else:
                                # Flat list: use directly
                                flattened_results.extend(response_results)
                    results = flattened_results  # Use flattened for LLM inference
                
                # Extract ignore_fields_for_inference from skill results (if present)
                # This is a skill-defined list of fields to exclude from LLM inference
                # Skills can define this in their response to control what gets sent to LLM
                ignore_fields_for_inference: Optional[List[str]] = None

                # Prefer ignore_fields_for_inference defined on the skill response wrapper (if provided)
                if response_ignore_fields:
                    ignore_fields_for_inference = response_ignore_fields
                
                # Check if results contain ignore_fields_for_inference (from skill response)
                # This takes precedence over exclude_fields_for_llm from app.yml
                if results and len(results) > 0:
                    # Check first result for ignore_fields_for_inference
                    first_result = results[0]
                    if isinstance(first_result, dict) and "ignore_fields_for_inference" in first_result:
                        ignore_fields_for_inference = first_result.get("ignore_fields_for_inference")
                        logger.debug(
                            f"{log_prefix} Skill '{tool_name}' returned ignore_fields_for_inference: {ignore_fields_for_inference}"
                        )
                
                # Fallback to exclude_fields_for_llm from app.yml if skill didn't provide ignore_fields_for_inference
                if ignore_fields_for_inference is None:
                    if app_id in discovered_apps_metadata:
                        app_metadata = discovered_apps_metadata[app_id]
                        for skill_def in app_metadata.skills:
                            if skill_def.id == skill_id:
                                ignore_fields_for_inference = skill_def.exclude_fields_for_llm
                                logger.debug(
                                    f"{log_prefix} Using exclude_fields_for_llm from app.yml: {ignore_fields_for_inference}"
                                )
                                break
                
                # Create minimal preview_data - only contains results_toon and essential metadata
                # Skills no longer provide preview_data (removed as redundant)
                # We create a minimal preview_data here with:
                # - results_toon: Full TOON-encoded results (added below)
                # - query: Extracted from input arguments if available (for frontend previews)
                # - provider: Extracted from response if available (for frontend previews)
                # NOTE: For async skills, preview_data stays empty - the Celery task handles all data.
                # tool_result_content_str was already set in the async detection block above.
                preview_data: Dict[str, Any] = {}
                
                # Extract query from input arguments if available (for search skills)
                # This is used by frontend for preview display
                if not is_async_skill and parsed_args and isinstance(parsed_args, dict):
                    if "title" in parsed_args and isinstance(parsed_args["title"], str):
                        title = parsed_args["title"].strip()
                        if title:
                            preview_data["title"] = title
                    # Try to extract query from various possible input structures
                    if "query" in parsed_args:
                        preview_data["query"] = parsed_args["query"]
                    elif "requests" in parsed_args and isinstance(parsed_args["requests"], list) and len(parsed_args["requests"]) > 0:
                        first_request = parsed_args["requests"][0]
                        if isinstance(first_request, dict) and "query" in first_request:
                            preview_data["query"] = first_request["query"]
                
                # Extract provider from response if available
                # This is used by frontend for preview display
                if not is_async_skill and first_response and isinstance(first_response, dict):
                    if "provider" in first_response:
                        preview_data["provider"] = first_response["provider"]
                
                # Add result count (can be derived from results, but useful for frontend)
                if not is_async_skill:
                    preview_data["result_count"] = len(results) if results else 0
                
                # CRITICAL: Add full results in TOON format ONLY (no JSON)
                # The frontend can decode this TOON string to get all fields (page_age, profile.name, url, etc.)
                # This ensures the frontend receives the complete data structure in efficient TOON format
                # The same TOON string is also stored in chat history for persistence
                # We only store TOON - JSON can be generated from TOON when needed
                # 
                # IMPORTANT: Flatten nested objects before encoding to enable TOON tabular format
                # This approach is proven to work in toon_encoding_test.ipynb and saves 25-32% in token usage.
                # TOON tabular format eliminates repeated field names (title:, url:, etc.) by using:
                # results[N]{field1,field2,field3}:
                #   value1,value2,value3
                #   value4,value5,value6
                # Instead of repeating field names for each result (which wastes tokens).
                # 
                # The flattening function converts:
                # - profile: {name: "..."} → profile_name: "..."
                # - meta_url: {favicon: "..."} → meta_url_favicon: "..."
                # - extra_snippets: [...] → extra_snippets: "|".join([...])
                if not is_async_skill and not is_multimodal_result:
                    try:
                        # DEBUG: Log original JSON structure (first 15 lines)
                        json_before = json.dumps(results, indent=2) if len(results) == 1 else json.dumps({"results": results, "count": len(results)}, indent=2)
                        json_lines = json_before.split('\n')
                        if len(results) == 1:
                            # Single result - flatten and encode as TOON
                            # Note: Single result encoded directly (not wrapped in dict) for efficiency
                            flattened_result = _flatten_for_toon_tabular(results[0])
                            results_toon = encode(flattened_result)
                        else:
                            # Multiple results - flatten each result, then combine and encode as TOON
                            # Flattening enables TOON to use tabular format for uniform objects
                            # This matches the proven approach from toon_encoding_test.ipynb
                            flattened_results = [_flatten_for_toon_tabular(result) for result in results]
                            results_toon = encode({"results": flattened_results, "count": len(results)})
                        logger.debug(f"{log_prefix} TOON conversion (preview_data) length={len(results_toon)} chars")
                        
                        # Add TOON-encoded full results to preview_data (this is the ONLY place results are stored)
                        preview_data["results_toon"] = results_toon
                        logger.debug(
                            f"{log_prefix} Added full results in TOON format to preview_data ({len(results_toon)} chars). "
                            f"Frontend can decode TOON to get all fields. No JSON data stored."
                        )
                    except Exception as e:
                        # Fallback to JSON if TOON encoding fails (should rarely happen)
                        logger.warning(f"{log_prefix} TOON encoding failed for preview_data, falling back to JSON: {e}")
                        if len(results) == 1:
                            preview_data["results_toon"] = json.dumps(results[0])
                        else:
                            preview_data["results_toon"] = json.dumps({"results": results, "count": len(results)})
                
                # Inject embed_ref slugs into composite skill results (web search, flights, places, etc.)
                # CRITICAL: Slugs are generated HERE (once) so that:
                #   1. The LLM sees them in the tool result → can write [text](embed:ref) inline refs
                #   2. The SAME slugs are baked into child embed TOON by update_embed_with_results
                #      (which reads embed_ref from the result dict if already present)
                # Generating slugs in two places would produce different random suffixes → ref mismatch.
                # Skills whose results contain text-heavy content worth quoting verbatim.
                # A single source_quote_hint is added at the group level (not per result)
                # to remind the LLM it can use > [exact text](embed:ref) blockquote syntax.
                _QUOTABLE_SKILL_IDS = {"search", "read"}
                # Generate embed_ref slugs for ALL non-async/non-multimodal skills (not just
                # composite ones). Non-composite skills (e.g. web.read) produce a single result
                # that also needs an embed_ref so the LLM can reference it and QUOTE_VERIFY
                # can build its embed_ref→id map. Without this, the LLM invents refs like
                # "embed:1" which fail verification and get stripped.
                if not is_async_skill and not is_multimodal_result:
                    try:
                        from backend.core.api.app.services.embed_service import EmbedService as _EmbedSvc
                        _child_type = await _EmbedSvc.get_child_embed_type(
                            app_id, skill_id, cache_service=cache_service
                        )
                        _seen_refs: Dict[str, int] = {}
                        results_with_refs = []
                        for _r in results:
                            _raw_ref = _EmbedSvc._generate_embed_ref_slug(_child_type, _r)
                            _unique_ref = _EmbedSvc._unique_embed_ref(_raw_ref, _seen_refs)
                            _r_with_ref = dict(_r)
                            _r_with_ref["embed_ref"] = _unique_ref
                            results_with_refs.append(_r_with_ref)
                        logger.debug(
                            f"{log_prefix} Pre-generated embed_ref slugs for {len(results_with_refs)} "
                            f"{_child_type} results (single source of truth for tool result + child TOON)"
                        )
                        # Also annotate grouped_results so per-group embed calls use the same slugs.
                        # We match by position within each group to the flat results_with_refs list.
                        if grouped_results:
                            _ref_iter = iter(results_with_refs)
                            for _gr in grouped_results:
                                _gr_results = _gr.get("results", [])
                                _gr["results"] = []
                                for _grr in _gr_results:
                                    try:
                                        _grr_with_ref = next(_ref_iter)
                                    except StopIteration:
                                        _grr_with_ref = _grr  # safety fallback
                                    _gr["results"].append(_grr_with_ref)
                    except Exception as _slug_err:
                        logger.warning(f"{log_prefix} embed_ref slug pre-generation failed, falling back to per-embed generation: {_slug_err}")
                        results_with_refs = results
                else:
                    results_with_refs = results

                if learning_mode_active:
                    results_with_refs = [
                        apply_learning_mode_policy_to_skill_result(
                            app_id,
                            skill_id,
                            result,
                            learning_mode_context,
                        )
                        for result in results_with_refs
                    ]
                    if grouped_results:
                        for grouped_result in grouped_results:
                            request_results = grouped_result.get("results")
                            if isinstance(request_results, list):
                                grouped_result["results"] = [
                                    apply_learning_mode_policy_to_skill_result(
                                        app_id,
                                        skill_id,
                                        result,
                                        learning_mode_context,
                                    )
                                    for result in request_results
                                ]

                anonymous_embed_payloads: List[Dict[str, Any]] = []
                anonymous_embed_reference: Optional[str] = None
                if (
                    getattr(request_data, "is_anonymous", False)
                    and not is_async_skill
                    and not is_multimodal_result
                ):
                    try:
                        from backend.core.api.app.services.embed_service import EmbedService as _AnonymousEmbedSvc

                        child_type = await _AnonymousEmbedSvc.get_child_embed_type(
                            app_id,
                            skill_id,
                            cache_service=cache_service,
                        )
                        parent_embed_id = str(uuid.uuid4())
                        child_embed_ids = [str(uuid.uuid4()) for _ in results_with_refs]
                        now = int(time.time())
                        parent_content = {
                            "app_id": app_id,
                            "skill_id": skill_id,
                            "result_count": len(results_with_refs),
                            "embed_ids": child_embed_ids,
                            "status": "finished",
                            **{key: value for key, value in preview_data.items() if key != "results_toon"},
                            **_AnonymousEmbedSvc._build_parent_preview_metadata(app_id, skill_id, results_with_refs),
                        }
                        parent_content = _AnonymousEmbedSvc._sanitize_final_app_skill_content(
                            app_id,
                            skill_id,
                            parent_content,
                        )
                        anonymous_embed_payloads.append({
                            "embed_id": parent_embed_id,
                            "type": "app_skill_use",
                            "content": encode(_flatten_for_toon_tabular(parent_content)),
                            "status": "finished",
                            "embed_ids": child_embed_ids,
                            "app_id": app_id,
                            "skill_id": skill_id,
                            "created_at": now,
                            "updated_at": now,
                        })
                        for child_embed_id, result in zip(child_embed_ids, results_with_refs):
                            child_content = {
                                **_flatten_for_toon_tabular(result),
                                "type": child_type,
                                "app_id": app_id,
                                "skill_id": child_type,
                                "status": "finished",
                            }
                            anonymous_embed_payloads.append({
                                "embed_id": child_embed_id,
                                "type": child_type,
                                "content": encode(child_content),
                                "status": "finished",
                                "parent_embed_id": parent_embed_id,
                                "app_id": app_id,
                                "skill_id": child_type,
                                "created_at": now,
                                "updated_at": now,
                            })
                        anonymous_embed_reference = json.dumps({
                            "type": "app_skill_use",
                            "embed_id": parent_embed_id,
                            "app_id": app_id,
                            "skill_id": skill_id,
                        })
                        yield f"```json\n{anonymous_embed_reference}\n```\n\n"
                    except Exception as anonymous_embed_error:
                        logger.error(
                            "%s Failed to build transient anonymous embeds for '%s': %s",
                            log_prefix,
                            tool_name,
                            anonymous_embed_error,
                            exc_info=True,
                        )

                # Filter results WITH embed_refs for current LLM inference
                # Removes non-essential fields (URLs, thumbnails, etc.) to reduce noise
                # and make embed_ref more prominent. Full results are already stored in
                # preview_data["results_toon"] for UI rendering.
                if ignore_fields_for_inference and not is_async_skill:
                    filtered_results_with_refs = _filter_skill_results_for_llm(results_with_refs, ignore_fields_for_inference)
                else:
                    filtered_results_with_refs = results_with_refs

                # CRITICAL: Store FULL results (not filtered) in chat history for persistence
                # This ensures all fields from Brave search (page_age, profile.name, url, etc.) are available
                # for future LLM calls and UI rendering. The filtered version is only used for the current LLM call.
                # Convert FULL results to TOON format for chat history storage
                # TOON format reduces token usage by 30-60% compared to JSON while preserving all fields
                # 
                # IMPORTANT: Flatten nested objects before encoding to enable TOON tabular format
                # This ensures efficient encoding with tabular arrays instead of repeated field names
                if not is_async_skill and not is_multimodal_result:
                    try:
                        # DEBUG: Log original JSON structure (first 15 lines)
                        json_before = json.dumps(results_with_refs, indent=2) if len(results_with_refs) == 1 else json.dumps({"results": results_with_refs, "count": len(results_with_refs)}, indent=2)
                        json_lines = json_before.split('\n')
                        logger.info(f"{log_prefix} === TOON CONVERSION DEBUG (chat history) ===")
                        logger.info(
                            f"{log_prefix} TOON source payload prepared "
                            f"(json_length={len(json_before)}, line_count={len(json_lines)})"
                        )
                        # Source quote hint — added once per tool result group for quotable
                        # skills (web-search, news-search).  Tells the LLM it can use the
                        # > [verbatim text](embed:ref) blockquote syntax to cite sources.
                        # Placed at the wrapper level so it costs ~30 tokens total, not per result.
                        _sq_hint = (
                            "When citing specific facts from these results, quote only exact "
                            "1:1 text copied from title, description, or extra_snippets. "
                            "Do not shorten, paraphrase, remove parentheticals, add punctuation, "
                            "or stop before the source sentence continues. Use: > [verbatim "
                            "text](embed:the_result's_embed_ref). Modified or false quotes "
                            "are automatically removed."
                        ) if skill_id in _QUOTABLE_SKILL_IDS else None

                        # Embed ref display-text hint — added once per tool result group
                        # for ALL embed-producing skills.  Reinforces that the display text
                        # in [text](embed:ref) links must be a human-readable description
                        # (e.g. the result's title), NEVER the embed_ref slug or its suffix.
                        # Placed at the wrapper level (~40 tokens total, not per result).
                        _ref_hint = (
                            "IMPORTANT — inline link display text: when writing "
                            "[text](embed:ref), use the result's title or a short "
                            "description as 'text'. NEVER use the embed_ref itself, "
                            "its domain-suffix, or the random code as display text."
                        )
                        _map_view_hint = (
                            EMBEDS_MAP_VIEW_INSTRUCTION
                            if should_include_embeds_map_view_hint(
                                app_id,
                                skill_id,
                                _iter_user_request_texts(request_data),
                            )
                            else None
                        )

                        if len(filtered_results_with_refs) == 1:
                            # Single result - flatten and encode filtered result as TOON for LLM inference
                            flattened_result = _flatten_for_toon_tabular(filtered_results_with_refs[0])
                            if _sq_hint:
                                flattened_result["source_quote_hint"] = _sq_hint
                            flattened_result["embed_ref_hint"] = _ref_hint
                            if _map_view_hint:
                                flattened_result["embeds_map_view_hint"] = _map_view_hint
                            tool_result_content_str = encode(flattened_result)
                        else:
                            # Multiple results - flatten each filtered result, then combine and encode as TOON
                            # Flattening enables TOON to use tabular format for uniform objects
                            flattened_results = [_flatten_for_toon_tabular(result) for result in filtered_results_with_refs]
                            toon_wrapper: Dict[str, Any] = {"results": flattened_results, "count": len(filtered_results_with_refs)}
                            if _sq_hint:
                                toon_wrapper["source_quote_hint"] = _sq_hint
                            toon_wrapper["embed_ref_hint"] = _ref_hint
                            if _map_view_hint:
                                toon_wrapper["embeds_map_view_hint"] = _map_view_hint
                            tool_result_content_str = encode(toon_wrapper)

                        logger.debug(f"{log_prefix} TOON conversion (LLM inference) length={len(tool_result_content_str)} chars")

                        logger.debug(
                            f"{log_prefix} Skill '{tool_name}' executed successfully, returned {len(results)} result(s). "
                            f"Full results in preview_data (all fields preserved). "
                            f"Filtered to {len(filtered_results_with_refs)} result(s) for LLM call (ignored fields: {ignore_fields_for_inference or 'none'})"
                        )
                    except Exception as e:
                        # Fallback to JSON if TOON encoding fails — still use filtered results
                        logger.warning(f"{log_prefix} TOON encoding failed for skill '{tool_name}', falling back to JSON: {e}")
                        if len(filtered_results_with_refs) == 1:
                            tool_result_content_str = json.dumps(filtered_results_with_refs[0])
                        else:
                            tool_result_content_str = json.dumps({"results": filtered_results_with_refs, "count": len(filtered_results_with_refs)})
                
                # Async skills retain their authenticated Celery billing path. Anonymous
                # requests settle the conservative quote when provider work is dispatched.
                if not is_async_skill or getattr(request_data, "is_anonymous", False):
                    await _charge_skill_credits(
                        task_id=task_id,
                        execution_id=tool_call_id,
                        request_data=request_data,
                        app_id=app_id,
                        skill_id=skill_id,
                        discovered_apps_metadata=discovered_apps_metadata,
                        results=results,
                        parsed_args=parsed_args,
                        log_prefix=log_prefix,
                        grouped_results=grouped_results,
                        provider_result_data=provider_result_data,
                        directus_service=directus_service,
                        reserved_operation_ids=reserved_skill_operation_ids,
                    )

                if connected_account_journal_entries and not is_async_skill and not is_multimodal_result:
                    attach_connected_account_action_metadata(
                        results=results_with_refs,
                        journal_entries=connected_account_journal_entries,
                        undo_available=_calendar_undo_available(skill_id),
                    )

                # STEP 3: Create embeds from results
                # For multiple requests: Create one app_skill_use embed per request group
                # For single request: Update the existing placeholder embed
                # NOTE: Skip for async skills - the Celery task handles embed updates
                updated_embed_data_list: List[Dict[str, Any]] = []
                if not is_async_skill and not is_multimodal_result and cache_service and user_vault_key_id and directus_service:
                    try:
                        from backend.core.api.app.services.embed_service import EmbedService

                        # Use passed-in encryption_service
                        embed_service = EmbedService(
                            cache_service=cache_service,
                            directus_service=directus_service,
                            encryption_service=encryption_service
                        )

                        # Check if we have grouped results (multiple requests)
                        # Grouped results structure: [{"id": 1, "results": [...]}, {"id": 2, "results": [...]}, ...]
                        is_multiple_requests = (
                            grouped_results is not None and 
                            len(grouped_results) > 1 and
                            all(isinstance(r, dict) and "id" in r and "results" in r for r in grouped_results)
                        )
                        
                        if is_multiple_requests:
                            # Multiple requests: Update existing placeholders or create new embeds
                            redact_group_ids = app_id == "hosting"
                            logger.info(
                                f"{log_prefix} Processing {len(grouped_results)} separate embeds for multiple requests. "
                                f"Grouped results structure: "
                                f"{[{'id': '<redacted>' if redact_group_ids else r.get('id'), 'result_count': len(r.get('results', []))} for r in grouped_results]}"
                            )
                            
                            # Check if we have multiple placeholders stored (from inline creation)
                            placeholder_embeds_map = {}
                            if placeholder_embed_data and isinstance(placeholder_embed_data, dict) and placeholder_embed_data.get("multiple"):
                                # We have multiple placeholders - map them by request_id
                                # Normalize request_id types (int/str) for reliable matching
                                for placeholder in placeholder_embed_data.get("placeholders", []):
                                    placeholder_request_id = placeholder.get("request_id")
                                    if placeholder_request_id is not None:
                                        # Normalize to string for consistent matching (handles int/str mismatches)
                                        placeholder_request_id_key = str(placeholder_request_id)
                                        placeholder_embeds_map[placeholder_request_id_key] = placeholder
                                logger.info(
                                    f"{log_prefix} Found {len(placeholder_embeds_map)} placeholders to update for multiple requests. "
                                    f"Request IDs: {['<redacted>'] * len(placeholder_embeds_map) if redact_group_ids else list(placeholder_embeds_map.keys())}"
                                )
                            elif placeholder_embed_data and isinstance(placeholder_embed_data, dict) and "embed_id" in placeholder_embed_data:
                                # Fallback: Single placeholder was created (old behavior)
                                # This shouldn't happen with the new code, but handle gracefully
                                logger.warning(
                                    f"{log_prefix} Multiple requests detected but only single placeholder found. "
                                    f"This indicates the placeholder creation logic didn't detect multiple requests. "
                                    f"Creating new embeds for each request."
                                )
                            
                            # Extract request metadata from parsed_args for each request
                            # CRITICAL: Use the parsed_args stored during placeholder creation (with our modified IDs)
                            # instead of the freshly-parsed parsed_args from line 1568 which has original LLM IDs.
                            # The placeholder phase modifies request["id"] to be 1-indexed (1, 2, 3...) for consistency,
                            # but parsed_args is parsed separately in both phases from the same tool_arguments_str.
                            stored_parsed_args = placeholder_embed_data.get("parsed_args") if isinstance(placeholder_embed_data, dict) else None
                            args_for_metadata = stored_parsed_args if stored_parsed_args else parsed_args
                            requests_list = args_for_metadata.get("requests", []) if isinstance(args_for_metadata, dict) else []
                            request_metadata_map = {}
                            for req in requests_list:
                                if isinstance(req, dict) and "id" in req:
                                    request_metadata_map[req["id"]] = req
                            
                            # Debug: Log whether we used stored or fresh parsed_args
                            logger.debug(
                                f"{log_prefix} Building request_metadata_map: used_stored_parsed_args={stored_parsed_args is not None}, "
                                f"request_count={len(requests_list)}"
                            )
                            
                            # Hosting IDs may be caller-supplied domain names. Keep them for
                            # matching, but redact all grouped-request log surfaces.
                            grouped_result_ids = (
                                ["<redacted>"] * len(grouped_results) if redact_group_ids
                                else [str(gr.get("id")) for gr in grouped_results]
                            )
                            placeholder_ids_log = (
                                ["<redacted>"] * len(placeholder_embeds_map) if redact_group_ids
                                else list(placeholder_embeds_map.keys())
                            )
                            logger.info(
                                f"{log_prefix} Processing {len(grouped_results)} grouped results. "
                                f"Result request IDs: {grouped_result_ids}, Placeholder request IDs: {placeholder_ids_log}"
                            )
                            
                            for grouped_result in grouped_results:
                                request_id = grouped_result.get("id")
                                request_results = grouped_result.get("results", [])
                                
                                # Normalize request_id to string for consistent matching with placeholders
                                request_id_key = str(request_id) if request_id is not None else None
                                request_id_log = "<redacted>" if redact_group_ids else request_id
                                request_id_key_log = "<redacted>" if redact_group_ids else request_id_key
                                request_log_prefix = f"{log_prefix}[request_id={request_id_log}]"
                                
                                logger.debug(
                                    f"{log_prefix} Processing grouped result: request_id={request_id_log} (key={request_id_key_log}), "
                                    f"result_count={len(request_results)}, has_error={bool(grouped_result.get('error'))}"
                                )
                                
                                # Get request metadata (query, url, etc.) for this specific request
                                # Try both original request_id and normalized key
                                request_metadata = request_metadata_map.get(request_id, request_metadata_map.get(request_id_key, {}))
                                
                                # DEBUG: Log request_metadata_map keys and lookup results
                                logger.info(
                                    f"{log_prefix} [QUERY_DEBUG] request_metadata_map keys: "
                                    f"{['<redacted>'] * len(request_metadata_map) if redact_group_ids else list(request_metadata_map.keys())}, "
                                    f"request_id={request_id_log} (type={type(request_id).__name__}), "
                                    f"request_id_key={request_id_key_log}, "
                                    f"lookup result has query: {'query' in request_metadata}, "
                                    f"query value: {'<redacted>' if app_id == 'hosting' else request_metadata.get('query', 'NOT_FOUND')}"
                                )
                                
                                # Include provider info from first_response if available
                                request_metadata_with_provider = request_metadata.copy()
                                if first_response and isinstance(first_response, dict):
                                    if "provider" in first_response:
                                        request_metadata_with_provider["provider"] = first_response["provider"]
                                    if "providers" in first_response:
                                        request_metadata_with_provider["providers"] = first_response["providers"]
                                if app_id == "maps" and skill_id == "search":
                                    # Each request can use a different provider. Preserve maps
                                    # warnings and coverage on its parent, including zero hits.
                                    request_metadata_with_provider.update(maps_result_parent_metadata(grouped_result))
                                
                                # CRITICAL: Ensure query is present for UI rendering, even if request metadata is missing
                                # Some LLMs omit "query" in requests array; fall back to grouped_result fields if needed.
                                if isinstance(grouped_result, dict):
                                    for range_key in ("start_date", "end_date", "time_range"):
                                        if range_key not in request_metadata_with_provider and grouped_result.get(range_key):
                                            request_metadata_with_provider[range_key] = grouped_result[range_key]
                                    if "query" not in request_metadata_with_provider:
                                        logger.warning(
                                            f"{log_prefix} [QUERY_DEBUG] query NOT in request_metadata_with_provider, "
                                            f"checking grouped_result. grouped_result keys: {list(grouped_result.keys())}"
                                        )
                                        for fallback_key in ["query", "search_query", "q", "input", "url"]:
                                            fallback_value = grouped_result.get(fallback_key)
                                            if isinstance(fallback_value, str) and fallback_value.strip():
                                                request_metadata_with_provider["query"] = fallback_value
                                                logger.info(
                                                    f"{log_prefix} [QUERY_DEBUG] Found query via fallback key '{fallback_key}': "
                                                    f"{'<redacted>' if app_id == 'hosting' else fallback_value}"
                                                )
                                                break
                                        else:
                                            logger.warning(f"{log_prefix} [QUERY_DEBUG] No query found in grouped_result via any fallback key!")
                                    else:
                                        logger.info(
                                            f"{log_prefix} [QUERY_DEBUG] query found in request_metadata_with_provider: "
                                            f"{'<redacted>' if app_id == 'hosting' else request_metadata_with_provider.get('query')}"
                                        )
                                
                                # Distinguish a real failure from a successful zero-hit query.
                                #
                                # A skill legitimately returning an empty results list (e.g. Brave
                                # web search returning HTTP 200 with no matches for a very narrow
                                # query) must NOT be classified as a failure. Doing so previously
                                # caused the "App skill processing error" red banner to appear on
                                # otherwise successful chat answers whenever one sub-query in a
                                # parallel multi-search had no hits (prod issue
                                # 0d73ab38-8d0e-45ac-867d-471a2cec8f56, Linear OPE-405).
                                #
                                # Contract:
                                #   - `error` set  OR  `results` key missing  →  real failure
                                #   - `results: []` without error              →  zero-hit success
                                # Zero-hit success falls through to the success path, which calls
                                # embed_service.update_embed_with_results(results=[]) — that
                                # function already handles the empty case via
                                # _finalize_embed_no_results() (status="finished", no error).
                                request_is_real_failure = is_request_group_failure(app_id, skill_id, grouped_result)

                                if request_is_real_failure:
                                    # Request failed - update placeholder to error or create error embed
                                    error_message = grouped_result.get("error") or "Request failed with no results"
                                    logger.warning(
                                        f"{log_prefix} Request {request_id_log} failed: {error_message}."
                                    )
                                    
                                    # Check if we have a placeholder for this request (use normalized key)
                                    matching_placeholder = placeholder_embeds_map.get(request_id_key) if request_id_key else None
                                    if matching_placeholder:
                                        # Update existing placeholder to error status
                                        placeholder_embed_id = matching_placeholder.get("embed_id")
                                        logger.info(
                                            f"{log_prefix} Found matching placeholder for failed request {request_id_log}: "
                                            f"embed_id={placeholder_embed_id}, key={request_id_key_log}"
                                        )
                                        try:
                                            updated_error_embed = await embed_service.update_embed_status_to_error(
                                                embed_id=placeholder_embed_id,
                                                app_id=app_id,
                                                skill_id=skill_id,
                                                error_message=error_message,
                                                chat_id=request_data.chat_id,
                                                message_id=request_data.message_id,
                                                user_id=request_data.user_id,
                                                user_id_hash=request_data.user_id_hash,
                                                user_vault_key_id=user_vault_key_id,
                                                task_id=task_id,
                                                log_prefix=request_log_prefix
                                            )
                                            
                                            if updated_error_embed:
                                                # Generate embed_reference for the error embed
                                                # CRITICAL: Include app_id and skill_id so frontend can properly group embeds
                                                # by app+skill type (e.g., web.search embeds grouped separately from code.get_docs).
                                                # ALSO include query/provider when available so the UI can render the query
                                                # even when the embed is in error status.
                                                embed_reference_payload = {
                                                    "type": "app_skill_use",
                                                    "embed_id": placeholder_embed_id,
                                                    "app_id": app_id,
                                                    "skill_id": skill_id
                                                }
                                                # Include user-visible request metadata for UI rendering.
                                                for key in ["query", "provider", "providers", "start_date", "end_date", "time_range", "location"]:
                                                    if request_metadata_with_provider.get(key):
                                                        embed_reference_payload[key] = request_metadata_with_provider[key]
                                                updated_error_embed["embed_reference"] = json.dumps(embed_reference_payload)
                                                updated_error_embed["request_id"] = request_id
                                                updated_error_embed["request_metadata"] = request_metadata
                                                updated_embed_data_list.append(updated_error_embed)
                                                logger.info(
                                                    f"{log_prefix} Updated placeholder {placeholder_embed_id} to error for request {request_id_log}"
                                                )
                                                failed_embed_ids.add(placeholder_embed_id)
                                        except Exception as error_update_error:
                                            logger.warning(
                                                f"{log_prefix} Failed to update placeholder to error status: "
                                                f"{'<redacted>' if redact_group_ids else error_update_error}"
                                            )
                                    else:
                                        # No placeholder found - create new error embed
                                        # This may indicate a request_id mismatch between placeholder creation and skill result
                                        logger.warning(
                                            f"{log_prefix} No placeholder found for failed request {request_id_log} (key={request_id_key_log}). "
                                            f"Available placeholder keys: {placeholder_ids_log}. Creating new error embed."
                                        )
                                        error_embed_data = await embed_service.create_processing_embed_placeholder(
                                            app_id=app_id,
                                            skill_id=skill_id,
                                            chat_id=request_data.chat_id,
                                            message_id=request_data.message_id,
                                            user_id=request_data.user_id,
                                            user_id_hash=request_data.user_id_hash,
                                            user_vault_key_id=user_vault_key_id,
                                            task_id=task_id,
                                            metadata=request_metadata_with_provider,
                                            log_prefix=request_log_prefix
                                        )
                                        
                                        if error_embed_data:
                                            error_embed_id = error_embed_data.get("embed_id")
                                            updated_error_embed = await embed_service.update_embed_status_to_error(
                                                embed_id=error_embed_id,
                                                app_id=app_id,
                                                skill_id=skill_id,
                                                error_message=error_message,
                                                chat_id=request_data.chat_id,
                                                message_id=request_data.message_id,
                                                user_id=request_data.user_id,
                                                user_id_hash=request_data.user_id_hash,
                                                user_vault_key_id=user_vault_key_id,
                                                task_id=task_id,
                                                log_prefix=request_log_prefix
                                            )
                                            
                                            if updated_error_embed:
                                                updated_error_embed["request_id"] = request_id
                                                updated_error_embed["request_metadata"] = request_metadata
                                                updated_embed_data_list.append(updated_error_embed)
                                                failed_embed_ids.add(error_embed_id)
                                    continue
                                
                                # Request succeeded - update placeholder or create new embed (use normalized key)
                                matching_placeholder = placeholder_embeds_map.get(request_id_key) if request_id_key else None
                                if matching_placeholder:
                                    # Update existing placeholder with results
                                    placeholder_embed_id = matching_placeholder.get("embed_id")
                                    logger.info(
                                        f"{log_prefix} Updating placeholder {placeholder_embed_id} with results for request {request_id_log}"
                                    )
                                    
                                    # CRITICAL: Pass request_results directly — for grouped multi-request
                                    # skills, grouped_results[i]["results"] was already annotated with
                                    # pre-generated embed_ref slugs in the results_with_refs block above
                                    # (via in-place patch of grouped_results). So request_results here
                                    # already carries embed_ref → embed_service will reuse it, not regenerate.
                                    updated_embed_data = await embed_service.update_embed_with_results(
                                        embed_id=placeholder_embed_id,
                                        app_id=app_id,
                                        skill_id=skill_id,
                                        results=request_results,
                                        chat_id=request_data.chat_id,
                                        message_id=request_data.message_id,
                                        user_id=request_data.user_id,
                                        user_id_hash=request_data.user_id_hash,
                                        user_vault_key_id=user_vault_key_id,
                                        task_id=task_id,
                                        log_prefix=request_log_prefix,
                                        request_metadata=request_metadata_with_provider,
                                        learning_mode_context=getattr(request_data, "learning_mode", None),
                                        hosting_group=grouped_result if app_id == "hosting" and skill_id == "search_domains" else None,
                                    )
                                    
                                    if updated_embed_data:
                                        # Generate embed_reference for the updated embed (same embed_id, so same reference)
                                        # Note: Placeholder embeds were already yielded at creation time (line ~949)
                                        # Mark as "from_placeholder" so we don't yield duplicates later
                                        # CRITICAL: Include app_id and skill_id so frontend can properly group embeds
                                        # by app+skill type (e.g., web.search embeds grouped separately from code.get_docs).
                                        # ALSO include query/provider when available so the UI can render the query
                                        # even if the parent embed content is missing metadata.
                                        embed_reference_payload = {
                                            "type": "app_skill_use",
                                            "embed_id": placeholder_embed_id,
                                            "app_id": app_id,
                                            "skill_id": skill_id
                                        }
                                        # Include user-visible request metadata for UI rendering.
                                        for key in ["query", "provider", "providers", "start_date", "end_date", "time_range", "location"]:
                                            if request_metadata_with_provider.get(key):
                                                embed_reference_payload[key] = request_metadata_with_provider[key]
                                        updated_embed_data["embed_reference"] = json.dumps(embed_reference_payload)
                                        updated_embed_data["request_id"] = request_id
                                        updated_embed_data["request_metadata"] = request_metadata
                                        updated_embed_data["from_placeholder"] = True  # Flag: already yielded
                                        updated_embed_data_list.append(updated_embed_data)
                                        logger.info(
                                            f"{log_prefix} Updated placeholder {placeholder_embed_id} with results for request {request_id_log}: "
                                            f"child_count={len(updated_embed_data.get('child_embed_ids', []))}"
                                        )
                                    else:
                                        logger.warning(f"{log_prefix} Failed to update placeholder for request {request_id_log}")
                                else:
                                    # No placeholder found - create new embed
                                    # This is a NEW embed, not from a placeholder, so we'll need to yield it
                                    logger.info(
                                        f"{log_prefix} No placeholder found for request {request_id_log}, creating new embed"
                                    )
                                    embed_data = await embed_service.create_embeds_from_skill_results(
                                        app_id=app_id,
                                        skill_id=skill_id,
                                        results=request_results,
                                        chat_id=request_data.chat_id,
                                        message_id=request_data.message_id,
                                        user_id=request_data.user_id,
                                        user_id_hash=request_data.user_id_hash,
                                        user_vault_key_id=user_vault_key_id,
                                        task_id=task_id,
                                        log_prefix=request_log_prefix,
                                        request_metadata=request_metadata_with_provider,
                                        learning_mode_context=getattr(request_data, "learning_mode", None),
                                        hosting_group=grouped_result if app_id == "hosting" and skill_id == "search_domains" else None,
                                    )
                                    
                                    if embed_data:
                                        embed_data["request_id"] = request_id
                                        embed_data["request_metadata"] = request_metadata
                                        embed_data["from_placeholder"] = False  # Flag: newly created, needs yielding
                                        updated_embed_data_list.append(embed_data)
                                        logger.info(
                                            f"{log_prefix} Created embed {embed_data.get('parent_embed_id')} for request {request_id_log}: "
                                            f"child_count={len(embed_data.get('child_embed_ids', []))}"
                                        )
                                    else:
                                        logger.warning(f"{log_prefix} Failed to create embed for request {request_id_log}")
                            
                            # Stream embed references ONLY for newly created embeds (not from placeholders)
                            # Placeholder embed references were already yielded at creation time (line ~949)
                            # to allow the frontend to show "loading" state immediately.
                            # Yielding them again would cause duplicate embed references in the message.
                            for embed_data in updated_embed_data_list:
                                # Skip embeds that came from placeholders - they were already yielded
                                if embed_data.get("from_placeholder"):
                                    logger.debug(
                                        f"{log_prefix} Skipping duplicate yield for placeholder embed: "
                                        f"request_id={'<redacted>' if redact_group_ids else embed_data.get('request_id')}"
                                    )
                                    continue
                                    
                                embed_reference = embed_data.get("embed_reference")
                                if embed_reference:
                                    embed_code_block = f"```json\n{embed_reference}\n```\n\n"
                                    yield embed_code_block
                                    logger.debug(f"{log_prefix} Streamed embed reference for request "
                                                 f"{'<redacted>' if redact_group_ids else embed_data.get('request_id')}")
                        else:
                            # Single request: Update the existing placeholder embed
                            single_hosting_group = (
                                grouped_results[0]
                                if app_id == "hosting" and skill_id == "search_domains"
                                and grouped_results and len(grouped_results) == 1
                                else None
                            )
                            if placeholder_embed_data:
                                # CRITICAL: Check if placeholder_embed_data has "multiple" structure but we fell here
                                # because is_multiple_requests was False (e.g., skill returned non-grouped results)
                                # In this case, we need to update each placeholder with the same results
                                if isinstance(placeholder_embed_data, dict) and placeholder_embed_data.get("multiple"):
                                    # Multiple placeholders exist but results aren't grouped - update all with combined results
                                    placeholders_list = placeholder_embed_data.get("placeholders", [])
                                    logger.warning(
                                        f"{log_prefix} Multiple placeholders ({len(placeholders_list)}) but results not grouped. "
                                        f"Will update each placeholder with combined results."
                                    )
                                    
                                    for idx, placeholder in enumerate(placeholders_list):
                                        embed_id = placeholder.get("embed_id")
                                        if not embed_id:
                                            continue
                                        
                                        # Use placeholder's request_metadata if available
                                        placeholder_metadata = {
                                            "query": placeholder.get("query"),
                                            "provider": placeholder.get("provider", "Brave Search" if skill_id == "search" and app_id != "maps" else None)
                                        }
                                        # Filter out None values
                                        placeholder_metadata = {k: v for k, v in placeholder_metadata.items() if v is not None}

                                        final_preview_metadata = await _resolve_skill_preview_metadata(
                                            app_id=app_id,
                                            skill_id=skill_id,
                                            request_metadata=placeholder_metadata,
                                            discovered_apps_metadata=discovered_apps_metadata,
                                            log_prefix=log_prefix,
                                        )
                                        placeholder_metadata.update(final_preview_metadata)
                                        
                                        # CRITICAL: Pass results_with_refs (pre-generated embed_ref slugs)
                                        updated_embed_data = await embed_service.update_embed_with_results(
                                            embed_id=embed_id,
                                            app_id=app_id,
                                            skill_id=skill_id,
                                            results=results_with_refs,  # Pre-annotated with embed_ref
                                            chat_id=request_data.chat_id,
                                            message_id=request_data.message_id,
                                            user_id=request_data.user_id,
                                            user_id_hash=request_data.user_id_hash,
                                            user_vault_key_id=user_vault_key_id,
                                            task_id=task_id,
                                            log_prefix=f"{log_prefix}[placeholder_{idx}]",
                                            request_metadata=placeholder_metadata,
                                            learning_mode_context=getattr(request_data, "learning_mode", None),
                                            hosting_group=single_hosting_group,
                                        )
                                        
                                        if updated_embed_data:
                                            updated_embed_data_list.append(updated_embed_data)
                                            logger.info(
                                                f"{log_prefix} Updated placeholder {idx}/{len(placeholders_list)} "
                                                f"(embed_id={embed_id}) with combined results"
                                            )
                                else:
                                    # Standard single placeholder - extract its embed_id directly
                                    single_embed_id = placeholder_embed_data.get('embed_id')
                                    
                                    # Extract metadata from parsed_args for single request
                                    # This preserves input parameters (query, url, provider, etc.) in the embed
                                    single_request_metadata = {}
                                    if parsed_args and isinstance(parsed_args, dict):
                                        # Copy all input parameters except internal fields
                                        for key, value in parsed_args.items():
                                            if key not in ['requests']:  # Skip requests array for single request
                                                single_request_metadata[key] = value
                                        
                                        # If we have a requests array with one item, extract from that
                                        if "requests" in parsed_args and isinstance(parsed_args["requests"], list) and len(parsed_args["requests"]) > 0:
                                            first_request = parsed_args["requests"][0]
                                            if isinstance(first_request, dict):
                                                # Copy all fields from the first request
                                                for key, value in first_request.items():
                                                    if key != "id":  # Skip id field
                                                        single_request_metadata[key] = value
                                    
                                    # Validate/set provider for search skills against skill's known
                                    # providers list to prevent LLM hallucination.
                                    if skill_id == "search" or "provider" in single_request_metadata:
                                        validated_provider = _validate_skill_provider(
                                            provider=single_request_metadata.get("provider"),
                                            app_id=app_id,
                                            skill_id=skill_id,
                                            discovered_apps_metadata=discovered_apps_metadata,
                                            log_prefix=log_prefix,
                                        )
                                        if validated_provider is not None:
                                            single_request_metadata["provider"] = validated_provider

                                    final_preview_metadata = await _resolve_skill_preview_metadata(
                                        app_id=app_id,
                                        skill_id=skill_id,
                                        request_metadata=single_request_metadata,
                                        discovered_apps_metadata=discovered_apps_metadata,
                                        log_prefix=log_prefix,
                                    )
                                    single_request_metadata.update(final_preview_metadata)
                                    
                                    # DEBUG: Log what's being passed to update_embed_with_results
                                    if results and len(results) > 0:
                                        first_result = results[0]
                                        # Guard against non-dict results (e.g. images-view returns
                                        # a list of content blocks, not a dict)
                                        if isinstance(first_result, dict):
                                            logger.info(
                                                f"{log_prefix} [EMBED_DEBUG] BEFORE update_embed_with_results - "
                                                f"results[0] keys: {list(first_result.keys())}, "
                                                f"has_thumbnail={'thumbnail' in first_result}, "
                                                f"has_meta_url={'meta_url' in first_result}, "
                                                f"thumbnail={first_result.get('thumbnail')}, "
                                                f"meta_url={first_result.get('meta_url')}"
                                            )
                                        else:
                                            logger.info(
                                                f"{log_prefix} [EMBED_DEBUG] BEFORE update_embed_with_results - "
                                                f"results[0] type: {type(first_result).__name__}, "
                                                f"len: {len(first_result) if hasattr(first_result, '__len__') else 'N/A'}"
                                            )
                                    
                                    # CRITICAL: Pass results_with_refs so embed_service receives the
                                    # pre-generated embed_ref slugs (same slugs the LLM saw in the
                                    # tool_result_content_str). This prevents the slug-mismatch bug.
                                    updated_embed_data = await embed_service.update_embed_with_results(
                                        embed_id=single_embed_id,
                                        app_id=app_id,
                                        skill_id=skill_id,
                                        results=results_with_refs,
                                        chat_id=request_data.chat_id,
                                        message_id=request_data.message_id,
                                        user_id=request_data.user_id,
                                        user_id_hash=request_data.user_id_hash,
                                        user_vault_key_id=user_vault_key_id,
                                        task_id=task_id,
                                        log_prefix=log_prefix,
                                        request_metadata=single_request_metadata,
                                        learning_mode_context=getattr(request_data, "learning_mode", None),
                                        hosting_group=single_hosting_group,
                                    )

                                if updated_embed_data:
                                    updated_embed_data_list.append(updated_embed_data)
                                    logger.info(
                                        f"{log_prefix} Updated embed {updated_embed_data.get('embed_id')} with results: "
                                        f"child_count={len(updated_embed_data.get('child_embed_ids', []))}, "
                                        f"status={updated_embed_data.get('status')}"
                                    )
                                else:
                                    logger.warning(f"{log_prefix} Failed to update embed for '{tool_name}'")
                            else:
                                # No placeholder, create new embed
                                # CRITICAL: Pass results_with_refs (pre-generated embed_ref slugs)
                                embed_data = await embed_service.create_embeds_from_skill_results(
                                    app_id=app_id,
                                    skill_id=skill_id,
                                    results=results_with_refs,
                                    chat_id=request_data.chat_id,
                                    message_id=request_data.message_id,
                                    user_id=request_data.user_id,
                                    user_id_hash=request_data.user_id_hash,
                                    user_vault_key_id=user_vault_key_id,
                                    task_id=task_id,
                                    log_prefix=log_prefix,
                                    request_metadata=(parsed_args.get("requests", [{}])[0] if isinstance(parsed_args, dict) and isinstance(parsed_args.get("requests"), list) and parsed_args["requests"] and isinstance(parsed_args["requests"][0], dict) else None) if single_hosting_group else None,
                                    learning_mode_context=getattr(request_data, "learning_mode", None),
                                    hosting_group=single_hosting_group,
                                )
                                
                                if embed_data:
                                    updated_embed_data_list.append(embed_data)
                                    # Stream embed reference
                                    embed_reference = embed_data.get("embed_reference")
                                    if embed_reference:
                                        embed_code_block = f"```json\n{embed_reference}\n```\n\n"
                                        yield embed_code_block
                    except Exception as e:
                        logger.error(f"{log_prefix} Error creating/updating embeds for '{tool_name}': {e}", exc_info=True)
                        # Continue without embed update - don't fail the entire skill execution

                # For multimodal results (e.g. images.view), the embed update block was skipped above.
                # If a placeholder embed was created for this tool call, mark it as "finished"
                # using only the text block (strip image bytes — we don't want to cache MBs of
                # base64 image data in the embed content).
                if is_multimodal_result and placeholder_embed_data and cache_service and user_vault_key_id and directus_service:
                    try:
                        from backend.core.api.app.services.embed_service import EmbedService
                        embed_service_mm = EmbedService(
                            cache_service=cache_service,
                            directus_service=directus_service,
                            encryption_service=encryption_service
                        )
                        mm_embed_id = placeholder_embed_data.get("embed_id")
                        if mm_embed_id:
                            # Extract only the text blocks — skip image_url blocks to avoid
                            # storing large base64 blobs in the embed cache.
                            text_only_results = [
                                block for block in results[0]
                                if isinstance(block, dict) and block.get("type") == "text"
                            ]
                            if not text_only_results:
                                text_only_results = [{"type": "text", "text": f"[{tool_name}]"}]

                            # For images.view (and similar multimodal skills that reference an
                            # original upload embed), resolve file_path → original upload embed_id
                            # via the file_path_index so the finished TOON content includes
                            # embed_id. The frontend uses this to fetch S3/AES data from the
                            # original upload embed and display the decrypted image preview.
                            mm_request_metadata: dict[str, Any] | None = None
                            _mm_file_path_index = getattr(request_data, "embed_file_path_index", None) or {}
                            _mm_file_path = skill_arguments.get("file_path", "")
                            if _mm_file_path and _mm_file_path_index:
                                _mm_original_embed_id = _mm_file_path_index.get(_mm_file_path)
                                if _mm_original_embed_id:
                                    mm_request_metadata = {
                                        "embed_id": _mm_original_embed_id,
                                        "file_path": _mm_file_path,
                                    }
                                    logger.info(
                                        f"{log_prefix} Multimodal embed {mm_embed_id}: resolved "
                                        f"file_path='{_mm_file_path}' → original embed_id={_mm_original_embed_id}"
                                    )
                                else:
                                    logger.warning(
                                        f"{log_prefix} Multimodal embed {mm_embed_id}: file_path "
                                        f"'{_mm_file_path}' not found in file_path_index "
                                        f"(keys: {list(_mm_file_path_index.keys())})"
                                    )

                            logger.info(
                                f"{log_prefix} Updating multimodal placeholder embed {mm_embed_id} "
                                f"to finished (text-only, {len(text_only_results)} block(s))"
                            )
                            await embed_service_mm.update_embed_with_results(
                                embed_id=mm_embed_id,
                                app_id=app_id,
                                skill_id=skill_id,
                                results=text_only_results,
                                chat_id=request_data.chat_id,
                                message_id=request_data.message_id,
                                user_id=request_data.user_id,
                                user_id_hash=request_data.user_id_hash,
                                user_vault_key_id=user_vault_key_id,
                                task_id=task_id,
                                log_prefix=log_prefix,
                                request_metadata=mm_request_metadata,
                                learning_mode_context=getattr(request_data, "learning_mode", None),
                            )
                    except Exception as e:
                        logger.warning(f"{log_prefix} Failed to finalize multimodal placeholder embed: {e}", exc_info=True)

                # Publish "finished" status with preview data
                # This triggers WebSocket event to update the frontend embed preview
                # NOTE: Skip for async skills - status was already published in the async detection block above
                if not is_async_skill:
                    await _publish_skill_status(
                        cache_service=cache_service,
                        task_id=task_id,
                        request_data=request_data,
                        app_id=app_id,
                        skill_id=skill_id,
                        status="finished",
                        preview_data=preview_data if preview_data else None
                    )

                # Publish embed_update events to notify frontend that embeds have been updated
                # For multiple requests, publish one event per embed
                # NOTE: Skip for async skills - the Celery task handles WebSocket notifications
                # CRITICAL FIX: Skip embeds that already had send_embed_data published inside
                # update_embed_with_results() (flagged as from_placeholder=True). Publishing both
                # send_embed_data and embed_update for the same embed causes duplicate processing
                # on the frontend, resulting in "DUPLICATE DETECTED" warnings and wasted work.
                if not is_async_skill and updated_embed_data_list and cache_service:
                    try:
                        client = await cache_service.client
                        if client:
                            import json as json_lib
                            channel_key = f"websocket:user:{request_data.user_id_hash}"
                            
                            for embed_data in updated_embed_data_list:
                                # Skip embeds that were already sent via send_embed_data_to_client()
                                # inside update_embed_with_results() - sending embed_update would be
                                # redundant and cause the frontend to process the same embed twice
                                if embed_data.get("from_placeholder"):
                                    embed_id = embed_data.get("parent_embed_id") or embed_data.get("embed_id")
                                    logger.debug(
                                        f"{log_prefix} Skipping embed_update for {embed_id} - already sent via send_embed_data in update_embed_with_results"
                                    )
                                    continue

                                embed_id = embed_data.get("parent_embed_id") or embed_data.get("embed_id")
                                if not embed_id:
                                    continue
                                
                                embed_update_payload = {
                                    "type": "embed_update",
                                    "event_for_client": "embed_update",
                                    "embed_id": embed_id,
                                    "chat_id": request_data.chat_id,
                                    "message_id": request_data.message_id,
                                    "user_id_uuid": request_data.user_id,
                                    "user_id_hash": request_data.user_id_hash,
                                    "status": "finished",
                                    "child_embed_ids": embed_data.get("child_embed_ids", [])
                                }

                                await client.publish(channel_key, json_lib.dumps(embed_update_payload))
                                logger.debug(f"{log_prefix} Published embed_update event for embed {embed_id}")
                        else:
                            logger.warning(f"{log_prefix} Redis client not available, skipping embed_update events")
                    except Exception as e:
                        logger.error(f"{log_prefix} Error publishing embed_update events: {e}", exc_info=True)
                        # Don't fail if event publish fails
                
                # Track tool call info for code block generation
                # NOTE: With new embeds architecture, embed references are streamed as chunks
                # We still track tool_call_info for TOON code block (for backward compatibility and follow-up questions)
                # For multiple requests, track all embed references
                embed_references, embed_ids = collect_server_embed_provenance(
                    updated_embed_data_list, placeholder_embed_data,
                    app_id=app_id, skill_id=skill_id,
                )
                
                tool_call_info = {
                    "app_id": app_id,
                    "skill_id": skill_id,
                    "input": _sanitize_tool_call_input_for_storage(parsed_args),
                    "preview_data": preview_data,  # Metadata + results_toon (contains full TOON-encoded results)
                    "ignore_fields_for_inference": ignore_fields_for_inference,  # Fields excluded from LLM inference
                    "embed_reference": anonymous_embed_reference or (embed_references[0] if embed_references else None),  # First embed reference (for backward compatibility)
                    "embed_references": embed_references if len(embed_references) > 1 else None,  # All embed references (for multiple requests)
                    "embed_id": anonymous_embed_payloads[0]["embed_id"] if anonymous_embed_payloads else (embed_ids[0] if embed_ids else None),  # First embed ID (for backward compatibility)
                    "embed_ids": [embed["embed_id"] for embed in anonymous_embed_payloads] if anonymous_embed_payloads else (embed_ids if len(embed_ids) > 1 else None),  # All embed IDs (for multiple requests)
                    "anonymous_embeds": anonymous_embed_payloads or None,
                }
                tool_calls_info.append(tool_call_info)
                logger.debug(
                    f"{log_prefix} Tracked tool call info for '{tool_name}': "
                    f"app_id={app_id}, skill_id={skill_id}, embed_count={len(embed_ids)}, "
                    f"results_toon_length={len(preview_data.get('results_toon', ''))}"
                )

                # Track images-search execution so we can inject embed preview instructions
                if app_id == "images" and skill_id == "search":
                    images_search_executed = True

            except json.JSONDecodeError as e:
                if _is_task_tool_like(tool_name):
                    logger.warning("%s Invalid JSON in task tool arguments for %s", log_prefix, tool_name)
                    tool_result_content_str = json.dumps({
                        "status": "rejected",
                        "reason": "Invalid JSON in task tool arguments.",
                    })
                    ignore_fields_for_inference = None
                    current_message_history.append({
                        "tool_call_id": tool_call_id,
                        "role": "tool",
                        "name": tool_name,
                        "content": tool_result_content_str,
                    })
                    continue
                logger.error(f"{log_prefix} Invalid JSON in tool arguments for '{tool_name}': {e}")
                tool_result_content_str = json.dumps({"error": "Invalid JSON in function arguments.", "details": str(e)})
                # Set ignore_fields_for_inference to None since JSON parsing failed
                # This variable is used later when adding to message history
                ignore_fields_for_inference = None
                # Track error in tool calls info
                try:
                    app_id, skill_id = tool_name.split('-', 1)
                    tool_call_info = {
                        "app_id": app_id,
                        "skill_id": skill_id,
                        "input": _sanitize_tool_call_input_for_storage(tool_arguments_str),
                        "preview_data": {"results_toon": tool_result_content_str},  # Store error as TOON string
                        "error": "Invalid JSON in function arguments"
                    }
                    tool_calls_info.append(tool_call_info)
                except Exception:
                    pass  # Don't fail if tracking fails
                # Update embed status to error if placeholder exists
                try:
                    app_id, skill_id = tool_name.split('-', 1)
                    placeholder_embed_data = inline_placeholder_embeds.get(tool_call_id)
                    if placeholder_embed_data and cache_service and user_vault_key_id and directus_service:
                        from backend.core.api.app.services.embed_service import EmbedService
                        # Use passed-in encryption_service
                        embed_service = EmbedService(
                            cache_service=cache_service,
                            directus_service=directus_service,
                            encryption_service=encryption_service
                        )
                        error_eid = placeholder_embed_data.get('embed_id')
                        await embed_service.update_embed_status_to_error(
                            embed_id=error_eid,
                            app_id=app_id,
                            skill_id=skill_id,
                            error_message="Invalid JSON in function arguments",
                            chat_id=request_data.chat_id,
                            message_id=request_data.message_id,
                            user_id=request_data.user_id,
                            user_id_hash=request_data.user_id_hash,
                            user_vault_key_id=user_vault_key_id,
                            task_id=task_id,
                            log_prefix=log_prefix
                        )
                        if error_eid:
                            failed_embed_ids.add(error_eid)
                except Exception as embed_error:
                    logger.error(f"{log_prefix} Error updating embed to error status: {embed_error}", exc_info=True)
                # Publish error status
                try:
                    app_id, skill_id = tool_name.split('-', 1)
                    await _publish_skill_status(
                        cache_service=cache_service,
                        task_id=task_id,
                        request_data=request_data,
                        app_id=app_id,
                        skill_id=skill_id,
                        status="error",
                        error="Invalid JSON in function arguments"
                    )
                except Exception:
                    pass  # Don't fail if status publish fails
            except ValueError as e:
                # Invalid tool name format - include available tools in error message
                # so the LLM can self-correct on the next iteration
                available_tool_names = [t["function"]["name"] for t in available_tools_for_llm] if available_tools_for_llm else []
                logger.error(f"{log_prefix} Invalid tool name format '{tool_name}': {e}")
                tool_result_content_str = json.dumps({
                    "error": f"Tool '{tool_name}' does not exist.",
                    "available_tools": available_tool_names,
                    "hint": "Use one of the available tools listed above, or respond with text if no suitable tool exists."
                })
                # Set ignore_fields_for_inference to None since invalid tool name format
                # This variable is used later when adding to message history
                ignore_fields_for_inference = None
                # Track error in tool calls info
                try:
                    tool_call_info = {
                        "app_id": "unknown",
                        "skill_id": "unknown",
                        "input": _sanitize_tool_call_input_for_storage(tool_arguments_str),
                        "preview_data": {"results_toon": tool_result_content_str},  # Store error as TOON string
                        "error": f"Invalid tool name format: {str(e)}"
                    }
                    tool_calls_info.append(tool_call_info)
                except Exception:
                    pass  # Don't fail if tracking fails
                # Update embed status to error if placeholder exists
                try:
                    placeholder_embed_data = inline_placeholder_embeds.get(tool_call_id)
                    if placeholder_embed_data and cache_service and user_vault_key_id and directus_service:
                        from backend.core.api.app.services.embed_service import EmbedService
                        # Use passed-in encryption_service
                        embed_service = EmbedService(
                            cache_service=cache_service,
                            directus_service=directus_service,
                            encryption_service=encryption_service
                        )
                        # Try to extract app_id and skill_id, fallback to unknown
                        try:
                            app_id, skill_id = tool_name.split('-', 1)
                        except ValueError:
                            app_id = "unknown"
                            skill_id = "unknown"
                        error_eid2 = placeholder_embed_data.get('embed_id')
                        await embed_service.update_embed_status_to_error(
                            embed_id=error_eid2,
                            app_id=app_id,
                            skill_id=skill_id,
                            error_message="Invalid tool name format",
                            chat_id=request_data.chat_id,
                            message_id=request_data.message_id,
                            user_id=request_data.user_id,
                            user_id_hash=request_data.user_id_hash,
                            user_vault_key_id=user_vault_key_id,
                            task_id=task_id,
                            log_prefix=log_prefix
                        )
                        if error_eid2:
                            failed_embed_ids.add(error_eid2)
                except Exception as embed_error:
                    logger.error(f"{log_prefix} Error updating embed to error status: {embed_error}", exc_info=True)
                # Publish error status
                try:
                    app_id, skill_id = tool_name.split('-', 1)
                    await _publish_skill_status(
                        cache_service=cache_service,
                        task_id=task_id,
                        request_data=request_data,
                        app_id=app_id,
                        skill_id=skill_id,
                        status="error",
                        error="Invalid tool name format"
                    )
                except Exception:
                    pass  # Don't fail if status publish fails
            except Exception as e:
                if _is_task_tool_like(tool_name):
                    logger.warning("%s Task tool rejected before execution for %s: %s", log_prefix, tool_name, e.__class__.__name__)
                    current_message_history.append({
                        "tool_call_id": tool_call_id,
                        "role": "tool",
                        "name": tool_name,
                        "content": json.dumps({
                            "status": "rejected",
                            "reason": "Task tool execution failed before encrypted persistence.",
                        }),
                    })
                    continue
                logger.error(f"{log_prefix} Error executing tool '{tool_name}': {e}", exc_info=True)
                tool_result_content_str = json.dumps({"error": "Skill execution failed.", "details": str(e)})
                # Set ignore_fields_for_inference to None since skill execution failed
                # This variable is used later when adding to message history
                ignore_fields_for_inference = None
                # Track error in tool calls info
                try:
                    app_id, skill_id = tool_name.split('-', 1)
                    tool_call_info = {
                        "app_id": app_id,
                        "skill_id": skill_id,
                        "input": _sanitize_tool_call_input_for_storage(parsed_args if 'parsed_args' in locals() else tool_arguments_str),
                        "preview_data": {"results_toon": tool_result_content_str},  # Store error as TOON string
                        "error": str(e)
                    }
                    tool_calls_info.append(tool_call_info)
                except Exception:
                    pass  # Don't fail if tracking fails
                # Update embed status to error if placeholder exists
                try:
                    app_id, skill_id = tool_name.split('-', 1)
                    placeholder_embed_data = inline_placeholder_embeds.get(tool_call_id)
                    if placeholder_embed_data and cache_service and user_vault_key_id and directus_service:
                        from backend.core.api.app.services.embed_service import EmbedService
                        # Use passed-in encryption_service
                        embed_service = EmbedService(
                            cache_service=cache_service,
                            directus_service=directus_service,
                            encryption_service=encryption_service
                        )
                        error_eid3 = placeholder_embed_data.get('embed_id')
                        await embed_service.update_embed_status_to_error(
                            embed_id=error_eid3,
                            app_id=app_id,
                            skill_id=skill_id,
                            error_message=str(e),
                            chat_id=request_data.chat_id,
                            message_id=request_data.message_id,
                            user_id=request_data.user_id,
                            user_id_hash=request_data.user_id_hash,
                            user_vault_key_id=user_vault_key_id,
                            task_id=task_id,
                            log_prefix=log_prefix
                        )
                        if error_eid3:
                            failed_embed_ids.add(error_eid3)
                except Exception as embed_error:
                    logger.error(f"{log_prefix} Error updating embed to error status: {embed_error}", exc_info=True)
                # Publish error status
                try:
                    app_id, skill_id = tool_name.split('-', 1)
                    await _publish_skill_status(
                        cache_service=cache_service,
                        task_id=task_id,
                        request_data=request_data,
                        app_id=app_id,
                        skill_id=skill_id,
                        status="error",
                        error=str(e)
                    )
                except Exception:
                    pass  # Don't fail if status publish fails
            
            # Add tool response to message history
            # Store full results as TOON in content, and include ignore_fields_for_inference metadata
            # This allows follow-up requests to filter tool results correctly when reading from history
            if omitted_news_requests_for_call:
                omitted_queries = [
                    request.get("query") for request in omitted_news_requests_for_call
                    if isinstance(request, dict) and isinstance(request.get("query"), str)
                ]
                tool_result_content_str += "\n\n" + json.dumps({
                    "research_budget": {
                        "status": "partial",
                        "omitted_queries": omitted_queries,
                        "instruction": "These queries were not searched. Do not cite or invent results for them.",
                    }
                })

            tool_response_message = {
                "tool_call_id": tool_call_id,
                "role": "tool",
                "name": tool_name,
                "content": tool_result_content_str,  # TOON-encoded full results (all fields preserved)
                "ignore_fields_for_inference": ignore_fields_for_inference  # Store for follow-up requests
            }
            current_message_history.append(tool_response_message)

        if pending_project_operation_id:
            # The client job will resume this turn through its cached continuation.
            # Finish usage accounting below without another model iteration whose
            # only possible answer would be a redundant waiting message.
            tool_inference_iterations -= 1
            logger.info(
                "%s Project file operation %s dispatched; yielding to client completion",
                log_prefix, pending_project_operation_id,
            )
            break

        if focus_phase_runtimes and await evaluate_active_phases(
            "tools", f"{request_data.message_id}:{iteration}:tools", current_message_history,
        ):
            yield phase_state_marker()

        if agentic_context.first_party(request_data):
            from backend.shared.python_utils.recent_work_summary_client import mark_response_summary_active
            await mark_response_summary_active(request_data, task_id)
        if agentic_context.first_party(request_data) and iteration + 1 < max_iterations_with_recovery:
            authority = DirectionAuthority(request_data.user_id, request_data.chat_id,
                                           authoritative_context_turn_id(request_data), agentic_context.goal_revision(request_data.message_history))
            actions = [{"id": message.get("tool_call_id", str(index)), "kind": message.get("role"),
                        "summary": str(message.get("content", ""))[:1000], "source": "current_chat_tool_result"}
                       for index, message in enumerate(current_message_history)
                       if message.get("role") == "tool"][-12:]
            from backend.apps.ai.processing.accepted_plan_context import validate_accepted_plan_context
            accepted_plan_summary = await validate_accepted_plan_context(request_data, directus_service)
            direction_tasks = await fetch_direction_task_context(
                request_data, directus_service, visible_tasks=task_tool_context.visible_tasks if task_tool_context else [],
                explicit_dependency_task_ids=frozenset(str(row.get("task_id"))
                    for row in (task_tool_context.referenced_tasks if task_tool_context else []) if row.get("task_id")),
            )
            context = assemble_direction_context(
                accepted_plan_summary=accepted_plan_summary,
                explicit_dependencies=direction_tasks,
                authority=authority, message_history=request_data.message_history, recent_actions=actions,
                open_tasks=direction_tasks,
                effective_focus="\n\n".join(filter(None, (active_focus_prompt_section, project_phase_prompt_section))),
                effective_phase=";".join(str(r.state.phase_id) for r in focus_phase_runtimes),
            )
            assessment = await assess_chat_direction(context, model_id=decision_model, secrets_manager=secrets_manager)
            if assessment.outcome == "material_drift":
                pending_direction = context, assessment

        # === MAX ITERATIONS HANDLING ===
        # If we're on the second-to-last iteration and the LLM is still requesting tools,
        # force the next (final) iteration to generate an answer without tools.
        # This ensures the user ALWAYS gets an answer based on gathered information.
        if iteration == MAX_TOOL_CALL_ITERATIONS - 2:
            # We're on the second-to-last iteration - force the final iteration to answer
            force_no_tools = True
            if not budget_warning_injected:
                budget_warning_injected = True  # Also inject budget warning
            logger.info(
                f"{log_prefix} [MAX_ITERATIONS] Approaching max iterations ({iteration + 1}/{MAX_TOOL_CALL_ITERATIONS}). "
                f"Next iteration will force tool_choice='none' to generate final answer."
            )
        elif iteration == MAX_TOOL_CALL_ITERATIONS - 1:
            # We're on the last iteration - if we still have tool calls, that's unexpected
            # (because we should have forced no tools in the previous iteration)
            # Log this as a warning but don't show error to user - we already have tool results
            logger.warning(
                f"{log_prefix} [MAX_ITERATIONS] Final iteration reached with tool calls still pending. "
                f"This shouldn't happen if force_no_tools was set correctly. Breaking loop."
            )
            break

    final_billing_events = billing_usage_events()
    if (
        native_terminal_ready and native_state is not None and native_raw_final_output
        and successful_model_id == native_state.get("model_id")
        and not answer_recovery.active
    ):
        native_state["expected_visible_response"] = "".join(published_answer_text)
        native_state["raw_final_text"] = native_raw_final_text
        yield {
            "__native_cache_context__": True,
            "state": native_state,
            "raw_final_output": native_raw_final_output,
        }
    if final_billing_events:
        for billing_event in final_billing_events:
            yield billing_event
        logger.info(
            f"{log_prefix} [CUMULATIVE_TOKENS] Final totals: "
            f"{model_usage_tracker.total_input_tokens} input tokens, "
            f"{model_usage_tracker.total_output_tokens} output tokens, "
            f"{tool_inference_iterations} tool inference iteration(s)."
        )

    # Yield tool calls info as a special marker at the end of the stream
    # The stream consumer will extract this and format it as a code block
    if tool_calls_info:
        # Use a special dict marker that the stream consumer can detect
        yield {"__tool_calls_info__": tool_calls_info}
        logger.debug(f"{log_prefix} Yielding tool calls info for {len(tool_calls_info)} tool call(s)")

    # Yield failed embed IDs so the stream consumer can strip their references
    # from the final message content before persisting. Without this, the message
    # would contain embed references for embeds that no longer exist, causing
    # the client to re-request them on every page load.
    if failed_embed_ids:
        yield {"__failed_embed_ids__": failed_embed_ids}
        logger.info(
            f"{log_prefix} Yielding {len(failed_embed_ids)} failed embed ID(s) for content cleanup: "
            f"{failed_embed_ids}"
        )

    logger.info(f"{log_prefix} Main processing stream finished.")


def _normalize_skill_arguments(
    arguments: Dict[str, Any],
    app_id: str,
    skill_id: str,
    discovered_apps_metadata: Dict[str, Any],
    task_id: str,
    message_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Normalizes LLM-generated skill arguments to match the expected schema format.
    
    LLMs sometimes send flat arguments (e.g., {"prompt": "a cat", "aspect_ratio": "1:1"})
    instead of the required wrapped format (e.g., {"requests": [{"prompt": "a cat", "aspect_ratio": "1:1"}]}).
    This function detects the mismatch using the skill's tool_schema and wraps the arguments
    into the correct format.
    
    This handles the case where:
    - The tool_schema declares "requests" as a required top-level property of type "array"
    - The LLM sends flat arguments without a "requests" key
    - The flat arguments match the items schema of the "requests" array
    
    Special recovery case — empty arguments (LLM sends "{}"):
    - When the LLM provides completely empty arguments AND the skill requires a "requests"
      array with a "query" field (e.g. web-search), the last user message from message_history
      is used as the query. This covers a known bug where some LLM providers (e.g. Qwen via
      Cerebras) emit an empty tool-call arguments string for the web-search tool.
    
    Args:
        arguments: The parsed tool call arguments from the LLM
        app_id: The app ID
        skill_id: The skill ID
        discovered_apps_metadata: The full app metadata (contains tool_schema)
        task_id: Task ID for logging
        message_history: Optional conversation history used to recover a query when the LLM
            sends empty arguments. Each entry is a dict with at least "role" and "content".
        
    Returns:
        Normalized arguments dict. Returns the original arguments unchanged if no
        normalization is needed or if the schema can't be determined.
    """
    log_prefix = f"[Task ID: {task_id}]"
    
    # Look up the skill's tool_schema FIRST — we need to know whether this skill
    # expects a "requests" array before we can decide how to handle incoming args.
    app_metadata = discovered_apps_metadata.get(app_id)
    if not app_metadata or not app_metadata.skills:
        return arguments
    
    skill_def = None
    for skill in app_metadata.skills:
        if skill.id == skill_id:
            skill_def = skill
            break
    
    if not skill_def or not skill_def.tool_schema:
        return arguments
    
    schema = skill_def.tool_schema
    schema_properties = schema.get("properties", {})
    schema_required = schema.get("required", [])

    requests_schema = schema_properties.get("requests", {})
    if requests_schema.get("type") == "array":
        normalized = normalize_json_request_array(arguments)
        if normalized is not arguments:
            logger.warning(
                f"{log_prefix} [NORMALIZE] Decoded JSON request array for '{app_id}.{skill_id}'."
            )
            arguments = normalized
    
    schema_expects_requests = (
        "requests" in schema_properties
        and schema_properties["requests"].get("type") == "array"
        and "requests" in schema_required
    )
    
    if "requests" in arguments:
        # The LLM sent a "requests" key.
        if schema_expects_requests:
            items_schema = schema_properties["requests"].get("items", {})
            items_required = items_schema.get("required", [])

            normalized, normalized_string_items = normalize_string_query_request_items(
                arguments=arguments,
                item_required_fields=items_required,
            )
            if normalized_string_items:
                logger.warning(
                    f"{log_prefix} [NORMALIZE] LLM sent {normalized_string_items} string item(s) "
                    f"inside 'requests' for '{app_id}.{skill_id}'. Converted each string "
                    "to a request object with a 'query' field so placeholder metadata "
                    "and skill execution stay correlated."
                )
                return normalized

            # Schema also wants "requests" and item shape is already compatible.
            return arguments
        else:
            # Schema does NOT have "requests" (flat-schema skill like pdf.read/view/search).
            # The LLM mis-wrapped flat args as {"requests": [{"file_path": "x.pdf", ...}]}.
            # Extract the first item and flatten it so the skill receives the expected kwargs.
            requests_list = arguments.get("requests")
            if isinstance(requests_list, list) and len(requests_list) > 0:
                if len(requests_list) > 1:
                    logger.warning(
                        f"{log_prefix} [NORMALIZE] LLM sent {len(requests_list)} items in "
                        f"'requests' for flat-schema skill '{app_id}.{skill_id}' (schema has "
                        f"no 'requests' property). Using first item only and discarding the rest."
                    )
                flat_item = requests_list[0]
                if isinstance(flat_item, dict):
                    # Merge flat item with underscore-prefixed metadata keys from the outer dict.
                    normalized = {k: v for k, v in arguments.items() if k.startswith("_")}
                    normalized.update({k: v for k, v in flat_item.items() if not k.startswith("_")})
                    logger.warning(
                        f"{log_prefix} [NORMALIZE] Unwrapped 'requests[0]' into flat args for "
                        f"'{app_id}.{skill_id}'. Flat keys: {list(flat_item.keys())}. "
                        f"LLM incorrectly wrapped flat-schema skill args in a 'requests' array."
                    )
                    return normalized
            # Unexpected shape — return as-is and let validation raise a clear error.
            logger.warning(
                f"{log_prefix} [NORMALIZE] LLM sent 'requests' for flat-schema skill "
                f"'{app_id}.{skill_id}' but 'requests' value is not a non-empty list "
                f"(type={type(arguments.get('requests')).__name__}). Passing through as-is."
            )
            return arguments
    
    # No "requests" key in arguments.
    if not schema_expects_requests:
        # Flat args for flat-schema skill — no normalization needed.
        return arguments
    
    # The schema requires a "requests" array but the LLM sent flat arguments.
    # Extract non-metadata keys (keys that don't start with "_") as the request object.
    flat_request = {k: v for k, v in arguments.items() if not k.startswith("_")}
    
    if not flat_request:
        # LLM sent completely empty arguments (e.g. arguments="{}").
        # Attempt recovery: check if the "requests" items schema requires a "query" field.
        # If so, extract the last user message from history and use it as the query.
        # This covers a known Qwen/Cerebras bug where web-search is called with no args.
        items_schema = schema_properties["requests"].get("items", {})
        items_required = items_schema.get("required", [])
        
        if "query" in items_required and message_history:
            # Find the last user message in history (most recent first)
            last_user_text: Optional[str] = None
            for msg in reversed(message_history):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str) and content.strip():
                        last_user_text = content.strip()
                        break
                    elif isinstance(content, list):
                        # Some providers use content arrays (e.g. [{type: text, text: "..."}])
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                text = part.get("text", "").strip()
                                if text:
                                    last_user_text = text
                                    break
                        if last_user_text:
                            break
            
            if last_user_text:
                # Preserve metadata keys (underscore-prefixed) at the top level
                normalized = {k: v for k, v in arguments.items() if k.startswith("_")}
                normalized["requests"] = [{"query": last_user_text}]
                logger.warning(
                    f"{log_prefix} [NORMALIZE] LLM sent empty arguments ('{{}}') for "
                    f"'{app_id}.{skill_id}' which requires a 'requests' array. "
                    f"Recovered query from last user message: '{last_user_text[:100]}{'...' if len(last_user_text) > 100 else ''}'. "
                    f"This is a known LLM bug (Qwen/Cerebras emitting empty tool-call args)."
                )
                return normalized
        
        # No recovery possible — return as-is and let validation raise a clear error
        logger.warning(
            f"{log_prefix} [NORMALIZE] LLM sent empty arguments ('{{}}') for "
            f"'{app_id}.{skill_id}' which requires a 'requests' array. "
            f"Cannot recover (no query field in items schema or no message history). "
            f"Skill will fail with a validation error."
        )
        return arguments
    
    # Preserve metadata keys (underscore-prefixed) at the top level
    normalized = {k: v for k, v in arguments.items() if k.startswith("_")}

    # Handle common LLM mistake: sending plural array field (e.g. "urls": ["a", "b"])
    # when the schema expects singular field per request item (e.g. "url": "a").
    # Unpack the array into individual request items so each gets its own request.
    # Known case: Gemini sends {"urls": ["https://..."]} for web-read which expects
    # {"requests": [{"url": "https://..."}]}.
    items_schema = schema_properties.get("requests", {}).get("items", {})
    items_props = items_schema.get("properties", {})
    unpacked = False
    for key, value in list(flat_request.items()):
        singular_key = key.rstrip("s")  # "urls" → "url", "queries" → "query"
        if (isinstance(value, list) and len(value) > 0
                and singular_key != key  # Only if key is actually plural
                and singular_key in items_props  # Schema has the singular form
                and key not in items_props):  # Schema does NOT have the plural form
            # Unpack: each array element becomes a separate request item
            normalized["requests"] = [{singular_key: item} for item in value]
            logger.info(
                f"{log_prefix} [NORMALIZE] Unpacked plural field '{key}' ({len(value)} items) "
                f"into individual request items with singular field '{singular_key}' for "
                f"'{app_id}.{skill_id}'. LLM sent array instead of per-item format."
            )
            unpacked = True
            break

    if not unpacked:
        normalized["requests"] = [flat_request]
        logger.info(
            f"{log_prefix} [NORMALIZE] Wrapped flat arguments into 'requests' array for "
            f"'{app_id}.{skill_id}'. Original keys: {list(flat_request.keys())}. "
            f"LLM sent flat args instead of {{\"requests\": [...]}} format."
        )

    return normalized


def _validate_tool_arguments_against_schema(
    arguments: Dict[str, Any],
    app_id: str,
    skill_id: str,
    discovered_apps_metadata: Dict[str, AppYAML],
    task_id: str
) -> tuple[bool, Optional[str]]:
    """
    Validates tool call arguments against the original skill schema (with min/max constraints).
    
    The schema sent to LLM providers has minimum/maximum fields removed for compatibility,
    but we validate against the original schema from app.yml to ensure values are within
    acceptable ranges.
    
    Args:
        arguments: The parsed tool call arguments from the LLM
        app_id: The app ID
        skill_id: The skill ID
        discovered_apps_metadata: The full app metadata (contains original schemas with min/max)
        task_id: Task ID for logging
        
    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is None.
    """
    log_prefix = f"[Task ID: {task_id}]"
    
    # Get the skill definition from metadata
    app_metadata = discovered_apps_metadata.get(app_id)
    if not app_metadata or not app_metadata.skills:
        # Can't validate if metadata not available - allow through
        logger.debug(f"{log_prefix} App '{app_id}' not found in discovered apps metadata. Skipping validation.")
        return True, None
    
    skill_def = None
    for skill in app_metadata.skills:
        if skill.id == skill_id:
            skill_def = skill
            break
    
    if not skill_def or not skill_def.tool_schema:
        # Can't validate if schema not available - allow through
        logger.debug(f"{log_prefix} Skill '{skill_id}' in app '{app_id}' has no tool_schema. Skipping validation.")
        return True, None
    
    # Validate arguments against schema (recursively check min/max for integers)
    return _validate_value_against_schema(
        value=arguments,
        schema=skill_def.tool_schema,
        path="arguments"
    )


def _validate_value_against_schema(
    value: Any,
    schema: Dict[str, Any],
    path: str = ""
) -> tuple[bool, Optional[str]]:
    """
    Recursively validates a value against a JSON schema, checking minimum/maximum constraints.
    
    This function validates integer values against minimum/maximum constraints defined
    in the original schema (from app.yml). The schema sent to LLM providers has these
    fields removed, but we use the original schema for validation.
    
    Args:
        value: The value to validate
        schema: The JSON schema to validate against (from app.yml, with min/max intact)
        path: Current path in the schema (for error messages)
        
    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is None.
    """
    if not isinstance(schema, dict):
        return True, None
    
    schema_type = schema.get("type")
    
    # Validate integer constraints
    if schema_type == "integer" and isinstance(value, int):
        if "minimum" in schema and value < schema["minimum"]:
            return False, f"Value at '{path}' ({value}) is less than minimum ({schema['minimum']})"
        if "maximum" in schema and value > schema["maximum"]:
            return False, f"Value at '{path}' ({value}) is greater than maximum ({schema['maximum']})"
    
    # Recursively validate nested objects
    if schema_type == "object" and isinstance(value, dict):
        properties = schema.get("properties", {})
        for prop_name, prop_schema in properties.items():
            if prop_name in value:
                is_valid, error = _validate_value_against_schema(
                    value[prop_name],
                    prop_schema,
                    f"{path}.{prop_name}" if path else prop_name
                )
                if not is_valid:
                    return False, error
    
    # Recursively validate arrays
    if schema_type == "array" and isinstance(value, list):
        items_schema = schema.get("items")
        if items_schema:
            for i, item in enumerate(value):
                is_valid, error = _validate_value_against_schema(
                    item,
                    items_schema,
                    f"{path}[{i}]" if path else f"[{i}]"
                )
                if not is_valid:
                    return False, error
    
    return True, None
