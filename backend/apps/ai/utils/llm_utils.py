# backend/apps/ai/utils/llm_utils.py
# Utilities for interacting with Language Models (LLMs).

import logging
from typing import Dict, Any, List, Optional, AsyncIterator, Union
import copy
from pydantic import BaseModel
import json
import os
import importlib
import inspect
import asyncio
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Import response types (these are shared types, not provider-specific)
from backend.apps.ai.llm_providers.mistral_client import UnifiedMistralResponse as UnifiedMistralResponse, ParsedMistralToolCall
from backend.apps.ai.llm_providers.google_client import UnifiedGoogleResponse, ParsedGoogleToolCall as ParsedGoogleToolCall
from backend.apps.ai.llm_providers.anthropic_client import UnifiedAnthropicResponse, ParsedAnthropicToolCall
from backend.apps.ai.llm_providers.openai_shared import UnifiedOpenAIResponse, ParsedOpenAIToolCall, OpenAIUsageMetadata, _sanitize_schema_for_llm_providers
from backend.apps.ai.utils.stream_utils import aggregate_paragraphs
from backend.apps.ai.utils.timeout_utils import stream_with_first_chunk_timeout, FIRST_CHUNK_TIMEOUT_SECONDS, PREPROCESSING_TIMEOUT_SECONDS
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.config_manager import config_manager
from backend.core.api.app.services.cache import CacheService
from toon_format import decode, encode

logger = logging.getLogger(__name__)


def _discover_server_providers_from_modules() -> Dict[str, Any]:
    """
    Dynamically discover all server provider client functions by scanning the llm_providers directory.
    
    Scans all Python modules in backend/apps/ai/llm_providers/ and looks for functions
    matching the pattern: invoke_{server_id}_chat_completions
    
    Returns:
        Dictionary mapping server_id -> client_function
    """
    registry: Dict[str, Any] = {}
    
    # Get the path to llm_providers directory
    current_file = Path(__file__)
    llm_providers_dir = current_file.parent.parent / "llm_providers"
    
    if not llm_providers_dir.exists():
        logger.error(f"llm_providers directory not found: {llm_providers_dir}")
        return registry
    
    # Scan all Python files in the directory
    for module_file in llm_providers_dir.glob("*.py"):
        # Skip __init__.py and shared modules
        if module_file.name.startswith("__") or module_file.name == "openai_shared.py":
            continue
        
        module_name = module_file.stem  # filename without .py extension
        module_path = f"backend.apps.ai.llm_providers.{module_name}"
        
        try:
            # Import the module
            module = importlib.import_module(module_path)
            
            # Look for functions matching the pattern: invoke_{server_id}_chat_completions
            for name, obj in inspect.getmembers(module, inspect.isfunction):
                if name.startswith("invoke_") and name.endswith("_chat_completions"):
                    # Extract server_id from function name: invoke_{server_id}_chat_completions
                    server_id = name[len("invoke_"):-len("_chat_completions")]
                    
                    # Verify it's an async function (all our client functions are async)
                    if inspect.iscoroutinefunction(obj):
                        registry[server_id] = obj
                        logger.debug(f"Discovered server provider '{server_id}' from function {module_path}.{name}")
        
        except ImportError as e:
            logger.warning(f"Could not import module {module_path}: {e}")
        except Exception as e:
            logger.error(f"Error scanning module {module_path}: {e}", exc_info=True)
    
    logger.info(f"Discovered {len(registry)} server provider client functions from modules: {sorted(registry.keys())}")
    return registry


def _discover_server_ids_from_yaml() -> set:
    """
    Discover all server IDs from provider YAML configuration files.
    
    Scans all provider configs to find unique server IDs in the 'servers' arrays.
    
    Returns:
        Set of server IDs found in YAML configs
    """
    discovered_server_ids: set = set()
    # Access config_manager to ensure it's initialized (singleton pattern)
    # This triggers initialization on first access if not already done
    _ = config_manager.get_provider_configs()  # Ensure initialization
    all_provider_configs = config_manager._provider_configs or {}
    
    # Scan all provider configs to discover server IDs
    for provider_id, provider_config in all_provider_configs.items():
        models = provider_config.get("models", [])
        for model in models:
            if not isinstance(model, dict):
                continue
            servers = model.get("servers", [])
            for server in servers:
                if isinstance(server, dict):
                    server_id = server.get("id")
                    if server_id:
                        discovered_server_ids.add(server_id)
    
    logger.debug(f"Discovered server IDs from YAML configs: {sorted(discovered_server_ids)}")
    return discovered_server_ids


def _build_provider_registry() -> Dict[str, Any]:
    """
    Build provider client registry by discovering server IDs from YAML and matching them to client functions.
    
    This ensures we only register providers that are actually configured in YAML files,
    and provides validation that all configured servers have corresponding client functions.
    
    Returns:
        Dictionary mapping server_id -> client_function (only for servers found in YAML)
    """
    # First, discover all available client functions from modules
    all_available_clients = _discover_server_providers_from_modules()
    
    # Then, discover which server IDs are actually used in YAML configs
    discovered_server_ids = _discover_server_ids_from_yaml()
    
    # Build registry only for servers that are both:
    # 1. Configured in YAML files
    # 2. Have corresponding client functions
    registry: Dict[str, Any] = {}
    for server_id in discovered_server_ids:
        if server_id in all_available_clients:
            registry[server_id] = all_available_clients[server_id]
        else:
            logger.warning(
                f"Server '{server_id}' is configured in YAML but no client function found. "
                f"Expected function: invoke_{server_id}_chat_completions. "
                f"Available clients: {sorted(all_available_clients.keys())}"
            )
    
    logger.info(f"Provider registry built with {len(registry)} server providers from YAML configs: {sorted(registry.keys())}")
    return registry


# Build registry dynamically at module load time (ONCE at server startup) - NO HARDCODED NAMES!
# This discovers all server providers from YAML files and matches them to client functions.
# The registry is built once when this module is first imported and reused for all LLM requests.
# No performance overhead on individual requests - just a simple dictionary lookup.
PROVIDER_CLIENT_REGISTRY: Dict[str, Any] = _build_provider_registry()


def _get_provider_client(provider_prefix: str) -> Optional[Any]:
    """
    Get the provider client function for a given provider prefix.
    
    Args:
        provider_prefix: The provider prefix (e.g., "groq", "openrouter", "openai")
    
    Returns:
        The client function if found, None otherwise
    """
    return PROVIDER_CLIENT_REGISTRY.get(provider_prefix)


def _extract_text_from_tiptap(tiptap_content: Any) -> str:
    if isinstance(tiptap_content, str):
        return tiptap_content
    if not isinstance(tiptap_content, dict) or "type" not in tiptap_content:
        if not isinstance(tiptap_content, (str, dict, list)):
            try:
                return str(tiptap_content)
            except:
                return ""
        return ""

    text_parts = []
    content_type = tiptap_content.get("type")
    
    # Handle text nodes
    if content_type == "text" and "text" in tiptap_content:
        text_parts.append(tiptap_content["text"])
    
    # Handle code embed nodes - convert to markdown code blocks
    elif content_type == "codeEmbed" and "attrs" in tiptap_content:
        attrs = tiptap_content.get("attrs", {})
        language = attrs.get("language", "")
        content = attrs.get("content", "")
        # Format as markdown code block
        text_parts.append(f"```{language}\n{content}\n```")
    
    # Handle web embed nodes
    elif content_type == "webEmbed" and "attrs" in tiptap_content:
        attrs = tiptap_content.get("attrs", {})
        url = attrs.get("url", "")
        text_parts.append(f"[Web Link]({url})")
    
    # Handle video embed nodes
    elif content_type == "videoEmbed" and "attrs" in tiptap_content:
        attrs = tiptap_content.get("attrs", {})
        url = attrs.get("url", "")
        text_parts.append(f"[Video]({url})")
    
    # Handle hard breaks
    elif content_type == "hardBreak":
        text_parts.append("\n")

    # Recursively process content arrays
    if "content" in tiptap_content and isinstance(tiptap_content["content"], list):
        for sub_content in tiptap_content["content"]:
            text_parts.append(_extract_text_from_tiptap(sub_content))
    
    return "".join(text_parts)

def resolve_default_server_from_provider_config(model_id: str) -> tuple:
    """
    Resolves the default server and transformed model ID from provider configuration.
    
    This function looks up a model in its provider config and returns the default_server
    and the transformed model_id that should be used for routing to that server.
    
    Args:
        model_id: Full model ID in format "provider/model-id" (e.g., "alibaba/qwen3-235b-a22b-2507")
    
    Returns:
        Tuple of (default_server_id, transformed_model_id) where:
        - default_server_id: The ID of the default server (e.g., "cerebras", "openrouter")
        - transformed_model_id: The model ID formatted for the default server (e.g., "cerebras/qwen3-235b-a22b-2507")
        Returns (None, None) if model not found or no default_server configured.
    """
    try:
        # Parse provider and model ID
        if "/" not in model_id:
            logger.debug(f"Model ID '{model_id}' does not contain provider prefix. Cannot resolve default server.")
            return (None, None)
        
        provider_id, model_suffix = model_id.split("/", 1)
        
        # Get provider config
        provider_config = config_manager.get_provider_config(provider_id)
        if not provider_config:
            logger.debug(f"Provider config not found for '{provider_id}'. Cannot resolve default server for '{model_id}'.")
            return (None, None)
        
        # Find the model in the provider config
        models = provider_config.get("models", [])
        model_config = None
        for model in models:
            if isinstance(model, dict) and model.get("id") == model_suffix:
                model_config = model
                break
        
        if not model_config:
            logger.debug(f"Model '{model_suffix}' not found in provider '{provider_id}' config. Cannot resolve default server.")
            return (None, None)
        
        # Get default server and servers list
        default_server_id = model_config.get("default_server")
        servers = model_config.get("servers", [])
        
        if not default_server_id:
            logger.debug(f"Model '{model_id}' has no default_server configured.")
            return (None, None)
        
        if not servers:
            logger.debug(f"Model '{model_id}' has no servers configured.")
            return (None, None)
        
        # Find the default server in the servers list
        default_server_config = None
        for server in servers:
            if not isinstance(server, dict):
                continue
            if server.get("id") == default_server_id:
                default_server_config = server
                break
        
        if not default_server_config:
            logger.warning(f"Default server '{default_server_id}' not found in servers list for model '{model_id}'.")
            return (None, None)
        
        # Get the server's model_id
        server_model_id = default_server_config.get("model_id")
        if not server_model_id:
            logger.warning(f"Default server '{default_server_id}' has no model_id configured for model '{model_id}'.")
            return (None, None)
        
        # Build transformed model ID - all servers use the same format: "server_id/server_model_id"
        # The server_model_id from YAML config is already in the correct format for that server
        transformed_model_id = f"{default_server_id}/{server_model_id}"
        
        logger.debug(f"Resolved default server '{default_server_id}' for model '{model_id}': '{transformed_model_id}'")
        return (default_server_id, transformed_model_id)
        
    except Exception as e:
        logger.error(f"Error resolving default server for model '{model_id}': {e}", exc_info=True)
        return (None, None)


def resolve_fallback_servers_from_provider_config(model_id: str) -> List[str]:
    """
    Resolves fallback server model IDs from provider configuration.
    
    This function looks up a model in its provider config and returns a list of
    fallback server model IDs (excluding the default_server). This allows fallback
    servers to be configured in provider YAML files instead of hardcoded in app.yml.
    
    Args:
        model_id: Full model ID in format "provider/model-id" (e.g., "mistral/mistral-small-latest")
    
    Returns:
        List of fallback model IDs in format "server/model-id" or "server/provider/model-id"
        (e.g., ["openrouter/mistralai/mistral-small-3.2-24b-instruct"])
        Returns empty list if no fallbacks are configured or model not found.
    """
    try:
        # Parse provider and model ID
        if "/" not in model_id:
            logger.warning(f"Model ID '{model_id}' does not contain provider prefix. Cannot resolve fallbacks.")
            return []
        
        provider_id, model_suffix = model_id.split("/", 1)
        
        # Get provider config
        provider_config = config_manager.get_provider_config(provider_id)
        if not provider_config:
            logger.debug(f"Provider config not found for '{provider_id}'. Cannot resolve fallbacks for '{model_id}'.")
            return []
        
        # Find the model in the provider config
        models = provider_config.get("models", [])
        model_config = None
        for model in models:
            if isinstance(model, dict) and model.get("id") == model_suffix:
                model_config = model
                break
        
        if not model_config:
            logger.debug(f"Model '{model_suffix}' not found in provider '{provider_id}' config. Cannot resolve fallbacks.")
            return []
        
        # Get default server and servers list
        default_server_id = model_config.get("default_server")
        servers = model_config.get("servers", [])
        
        if not servers:
            logger.debug(f"Model '{model_id}' has no servers configured. No fallbacks available.")
            return []
        
        # Build fallback list (all servers except the default_server)
        fallback_models = []
        for server in servers:
            if not isinstance(server, dict):
                continue
            
            server_id = server.get("id")
            server_model_id = server.get("model_id")
            
            if not server_id or not server_model_id:
                continue
            
            # Skip the default server (it's the primary, not a fallback)
            if server_id == default_server_id:
                continue
            
            # Build fallback model ID - all servers use the same format: "server_id/server_model_id"
            # The server_model_id from YAML config is already in the correct format for that server
            fallback_model_id = f"{server_id}/{server_model_id}"
            
            fallback_models.append(fallback_model_id)
            logger.debug(f"Resolved fallback server '{server_id}' for model '{model_id}': '{fallback_model_id}'")
        
        if fallback_models:
            logger.info(f"Resolved {len(fallback_models)} fallback server(s) for model '{model_id}': {fallback_models}")
        else:
            logger.debug(f"No fallback servers found for model '{model_id}' (default_server: '{default_server_id}')")
        
        return fallback_models
        
    except Exception as e:
        logger.error(f"Error resolving fallback servers for model '{model_id}': {e}", exc_info=True)
        return []


def _transform_message_history_for_llm(message_history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Transforms message history from internal format to LLM API format.
    
    This function converts messages from the internal format (which may include
    sender_name, created_at, category, etc.) to the standard OpenAI-compatible
    format (role, content, tool_calls, tool_call_id, etc.).
    
    Args:
        message_history: List of message dictionaries in internal format
        
    Returns:
        List of message dictionaries in LLM API format
        - For user/assistant: {"role": str, "content": str, "tool_calls": [...] (optional)}
        - For tool: {"role": "tool", "tool_call_id": str, "content": str}
    """
    transformed_messages = []
    for idx, msg in enumerate(message_history):
        role = "assistant"
        if msg.get("sender_name") == "user":
            role = "user"
        if "role" in msg:
            role = msg["role"]

        # Handle tool role messages (tool results from skill execution)
        # OpenAI-compatible APIs require: {"role": "tool", "tool_call_id": str, "content": str}
        if role == "tool":
            tool_call_id = msg.get("tool_call_id")
            if not tool_call_id:
                logger.warning(f"Tool message at index {idx} missing tool_call_id, skipping")
                continue
            
            content_input = msg.get("content", "")
            # Tool content is already plain text (TOON or JSON), not Tiptap JSON
            plain_text_content = content_input if isinstance(content_input, str) else str(content_input)
            
            # Check if this tool result has ignore_fields_for_inference metadata
            # If so, filter the results before sending to LLM (to reduce token usage)
            # This ensures follow-up requests also respect the filtering
            # For example, fields like "type", "hash", "meta_url.favicon", "thumbnail.original" 
            # will be removed from tool results in follow-up requests
            ignore_fields_for_inference = msg.get("ignore_fields_for_inference")
            if ignore_fields_for_inference and plain_text_content:
                try:
                    # Import filtering function (lazy import to avoid circular dependency)
                    from backend.apps.ai.processing.main_processor import _filter_skill_results_for_llm
                    
                    # Try to decode TOON content
                    try:
                        decoded_content = decode(plain_text_content)
                        original_length = len(plain_text_content)
                        
                        # Filter the decoded content
                        if isinstance(decoded_content, dict):
                            # Single result or wrapper dict
                            if "results" in decoded_content:
                                # Multiple results wrapped in dict (format: {"results": [...], "count": N})
                                filtered_results = _filter_skill_results_for_llm(
                                    decoded_content.get("results", []),
                                    ignore_fields_for_inference
                                )
                                filtered_content = {"results": filtered_results, "count": len(filtered_results)}
                                logger.debug(
                                    f"Filtered {len(filtered_results)} tool result(s) from history. "
                                    f"Removed fields: {ignore_fields_for_inference}"
                                )
                            else:
                                # Single result dict (e.g., SearchResponse with "previews" array)
                                filtered_results = _filter_skill_results_for_llm(
                                    [decoded_content],
                                    ignore_fields_for_inference
                                )
                                filtered_content = filtered_results[0] if filtered_results else decoded_content
                                logger.debug(
                                    f"Filtered single tool result from history. "
                                    f"Removed fields: {ignore_fields_for_inference}"
                                )
                        elif isinstance(decoded_content, list):
                            # List of results
                            filtered_results = _filter_skill_results_for_llm(
                                decoded_content,
                                ignore_fields_for_inference
                            )
                            filtered_content = filtered_results
                            logger.debug(
                                f"Filtered {len(filtered_results)} tool result(s) from history (list format). "
                                f"Removed fields: {ignore_fields_for_inference}"
                            )
                        else:
                            # Unknown structure, use as-is
                            filtered_content = decoded_content
                            logger.warning(
                                f"Tool result from history has unknown structure (type: {type(decoded_content)}). "
                                f"Cannot filter. Using as-is."
                            )
                        
                        # Re-encode as TOON for LLM
                        plain_text_content = encode(filtered_content)
                        filtered_length = len(plain_text_content)
                        logger.debug(
                            f"Filtered tool result from history: {original_length} -> {filtered_length} chars "
                            f"(saved {original_length - filtered_length} chars, ~{(original_length - filtered_length)/4:.0f} tokens). "
                            f"Removed fields: {ignore_fields_for_inference}"
                        )
                    except Exception as decode_error:
                        # If TOON decode fails, try JSON
                        logger.debug(f"TOON decode failed, trying JSON: {decode_error}")
                        try:
                            decoded_content = json.loads(plain_text_content)
                            original_length = len(plain_text_content)
                            
                            if isinstance(decoded_content, dict):
                                if "results" in decoded_content:
                                    # Multiple results wrapped in dict
                                    filtered_results = _filter_skill_results_for_llm(
                                        decoded_content.get("results", []),
                                        ignore_fields_for_inference
                                    )
                                    filtered_content = {"results": filtered_results, "count": len(filtered_results)}
                                    logger.debug(
                                        f"Filtered {len(filtered_results)} tool result(s) from history (JSON format, multiple). "
                                        f"Removed fields: {ignore_fields_for_inference}"
                                    )
                                else:
                                    # Single result dict
                                    filtered_results = _filter_skill_results_for_llm(
                                        [decoded_content],
                                        ignore_fields_for_inference
                                    )
                                    filtered_content = filtered_results[0] if filtered_results else decoded_content
                                    logger.debug(
                                        f"Filtered single tool result from history (JSON format). "
                                        f"Removed fields: {ignore_fields_for_inference}"
                                    )
                            elif isinstance(decoded_content, list):
                                # List of results
                                filtered_results = _filter_skill_results_for_llm(
                                    decoded_content,
                                    ignore_fields_for_inference
                                )
                                filtered_content = filtered_results
                                logger.debug(
                                    f"Filtered {len(filtered_results)} tool result(s) from history (JSON format, list). "
                                    f"Removed fields: {ignore_fields_for_inference}"
                                )
                            else:
                                filtered_content = decoded_content
                                logger.warning(
                                    f"Tool result from history has unknown structure (type: {type(decoded_content)}). "
                                    f"Cannot filter. Using as-is."
                                )
                            
                            # Re-encode as TOON (preferred) or JSON (fallback)
                            try:
                                plain_text_content = encode(filtered_content)
                                filtered_length = len(plain_text_content)
                                logger.debug(
                                    f"Filtered tool result from history (JSON->TOON): {original_length} -> {filtered_length} chars "
                                    f"(saved {original_length - filtered_length} chars). "
                                    f"Removed fields: {ignore_fields_for_inference}"
                                )
                            except Exception:
                                plain_text_content = json.dumps(filtered_content)
                                logger.debug(
                                    f"TOON encoding failed, using JSON. Removed fields: {ignore_fields_for_inference}"
                                )
                        except Exception:
                            # If both TOON and JSON decode fail, use content as-is
                            logger.warning(
                                f"Failed to decode tool result content for filtering (TOON and JSON decode failed). "
                                f"Using content as-is. This may result in higher token usage."
                            )
                except ImportError:
                    # If import fails (circular dependency), use content as-is
                    logger.warning(
                        f"Could not import _filter_skill_results_for_llm for filtering tool results. "
                        f"Using content as-is. This may result in higher token usage."
                    )
                except Exception as e:
                    # If filtering fails for any reason, use content as-is
                    logger.warning(
                        f"Failed to filter tool result using ignore_fields_for_inference: {e}. "
                        f"Using content as-is. This may result in higher token usage."
                    )
            
            transformed_messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": plain_text_content
            })
            continue
        
        # Handle assistant messages with tool_calls
        if role == "assistant" and "tool_calls" in msg:
            content_input = msg.get("content", "")
            plain_text_content = _extract_text_from_tiptap(content_input) if content_input else None
            
            assistant_msg = {
                "role": "assistant",
                "tool_calls": msg["tool_calls"]  # Preserve tool_calls structure
            }
            if plain_text_content:
                assistant_msg["content"] = plain_text_content
            transformed_messages.append(assistant_msg)
            continue
        
        # Handle regular user/assistant messages
        content_input = msg.get("content", "")
        plain_text_content = _extract_text_from_tiptap(content_input)
        
        # Always append the message, even if content is empty, to preserve message count
        # Empty messages might be important for maintaining conversation context
        transformed_messages.append({"role": role, "content": plain_text_content})
    
    return transformed_messages

class LLMPreprocessingCallResult(BaseModel):
    arguments: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    raw_provider_response_summary: Optional[Dict[str, Any]] = None

async def call_preprocessing_llm(
    task_id: str,
    model_id: str,
    message_history: List[Dict[str, str]],
    tool_definition: Dict[str, Any],
    secrets_manager: Optional[SecretsManager] = None,
    user_app_settings_and_memories_metadata: Optional[Dict[str, List[str]]] = None,
    dynamic_context: Optional[Dict[str, Any]] = None,
    fallback_models: Optional[List[str]] = None  # List of fallback model IDs to try if primary fails
) -> LLMPreprocessingCallResult:
    logger.info(f"[{task_id}] LLM Utils: Calling preprocessing LLM {model_id}.")

    current_tool_definition = copy.deepcopy(tool_definition)
    if "function" in current_tool_definition and "description" in current_tool_definition["function"]:
        tool_desc = current_tool_definition["function"]["description"]
        
        app_data_placeholder = "{AVAILABLE_APP_SETTINGS_AND_MEMORIES}"
        if user_app_settings_and_memories_metadata:
            app_data_str = "; ".join([f"{app_id}: {', '.join(keys)}" for app_id, keys in user_app_settings_and_memories_metadata.items()])
            tool_desc = tool_desc.replace(app_data_placeholder, app_data_str if app_data_str else "No app settings or memories currently have data for this user.")
        else:
            tool_desc = tool_desc.replace(app_data_placeholder, "No app settings or memories currently have data for this user.")

        if dynamic_context:
            for key, value in dynamic_context.items():
                placeholder = f"{{{key}}}"
                value_str = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
                tool_desc = tool_desc.replace(placeholder, value_str)
                
        current_tool_definition["function"]["description"] = tool_desc
        logger.debug(f"[{task_id}] LLM Utils: Preprocessing tool description updated: {tool_desc[:300]}...")
    else:
        logger.warning(f"[{task_id}] LLM Utils: Preprocessing tool definition issue. Cannot inject dynamic context. Def: {current_tool_definition}")

    transformed_messages_for_llm = _transform_message_history_for_llm(message_history)

    def handle_response(response: Union[UnifiedMistralResponse, UnifiedGoogleResponse, UnifiedAnthropicResponse, UnifiedOpenAIResponse], expected_tool_name: str) -> LLMPreprocessingCallResult:
        current_raw_provider_response_summary = response.model_dump(exclude_none=True, exclude={'raw_response'})
        
        # Sanitize tool_calls_made to remove sensitive content (chat_summary, chat_tags)
        sanitized_tool_calls = []
        if response.tool_calls_made:
            for tc in response.tool_calls_made:
                tc_dict = tc.model_dump()
                # Sanitize function_arguments_parsed if it contains sensitive fields
                if "function_arguments_parsed" in tc_dict and isinstance(tc_dict["function_arguments_parsed"], dict):
                    sanitized_args = tc_dict["function_arguments_parsed"].copy()
                    if "chat_summary" in sanitized_args and isinstance(sanitized_args["chat_summary"], str):
                        sanitized_args["chat_summary"] = {"length": len(sanitized_args["chat_summary"]), "content": "[REDACTED_CONTENT]"}
                    if "chat_tags" in sanitized_args and isinstance(sanitized_args["chat_tags"], list):
                        sanitized_args["chat_tags"] = {"count": len(sanitized_args["chat_tags"]), "content": "[REDACTED_CONTENT]"}
                    tc_dict["function_arguments_parsed"] = sanitized_args
                # Also sanitize function_arguments_raw if it's a string that might contain sensitive data
                if "function_arguments_raw" in tc_dict and isinstance(tc_dict["function_arguments_raw"], str):
                    # For raw JSON strings, we can't easily parse and sanitize, so just mark it
                    tc_dict["function_arguments_raw"] = "[REDACTED_RAW_ARGS]"
                sanitized_tool_calls.append(tc_dict)
        
        log_output_extra = {
            "task_id": task_id, "success": response.success, "error_message": response.error_message,
            "tool_calls_made": sanitized_tool_calls if sanitized_tool_calls else None,
            "raw_provider_response_summary": current_raw_provider_response_summary, "event_type": "llm_preprocessing_output"
        }
        if os.getenv("SERVER_ENVIRONMENT") == "development":
            logger.info(f"[{task_id}] Preprocessing LLM call output", extra=log_output_extra)
        else:
            logger.info(f"[{task_id}] Preprocessing LLM call completed. Success: {response.success}. Detailed logging skipped.")

        if response.success and response.tool_calls_made:
            for tool_call in response.tool_calls_made:
                if tool_call.function_name == expected_tool_name:
                    if tool_call.parsing_error:
                        err_msg = f"Failed to parse arguments for tool '{expected_tool_name}': {tool_call.parsing_error}"
                        return LLMPreprocessingCallResult(error_message=err_msg, raw_provider_response_summary=current_raw_provider_response_summary)
                    return LLMPreprocessingCallResult(arguments=tool_call.function_arguments_parsed, raw_provider_response_summary=current_raw_provider_response_summary)
            
            err_msg_tool_not_found = f"Expected tool '{expected_tool_name}' not found in tool calls."
            return LLMPreprocessingCallResult(error_message=err_msg_tool_not_found, raw_provider_response_summary=current_raw_provider_response_summary)

        elif not response.success:
            err_msg_client_fail = f"Client call failed for preprocessing: {response.error_message}"
            return LLMPreprocessingCallResult(error_message=err_msg_client_fail, raw_provider_response_summary=current_raw_provider_response_summary)
        else:
            err_msg_no_tool_call = f"Preprocessing LLM ({model_id}) did not make the expected tool call."
            return LLMPreprocessingCallResult(error_message=err_msg_no_tool_call, raw_provider_response_summary=current_raw_provider_response_summary)

    expected_tool_name = current_tool_definition.get("function", {}).get("name")
    if not expected_tool_name:
        error_msg = "Preprocessing tool definition is missing function name."
        return LLMPreprocessingCallResult(error_message=error_msg)

    # Helper function to check provider health from cache
    async def _is_provider_unhealthy_preprocessing(provider_id: str) -> bool:
        """Check if provider is marked as unhealthy in cache."""
        try:
            cache_service = CacheService()
            cache_key = f"health_check:provider:{provider_id}"
            client = await cache_service.client
            if client:
                health_data_json = await client.get(cache_key)
                if health_data_json:
                    if isinstance(health_data_json, bytes):
                        health_data_json = health_data_json.decode('utf-8')
                    health_data = json.loads(health_data_json)
                    status = health_data.get("status", "unknown")
                    return status == "unhealthy"
        except Exception as e:
            logger.debug(f"[{task_id}] LLM Utils: Could not check health status for '{provider_id}': {e}. Proceeding with attempt.")
        return False  # If cache miss or error, proceed (don't block on missing health data)
    
    # Helper function to call a single provider
    async def _call_single_provider(provider_model_id: str) -> LLMPreprocessingCallResult:
        """Calls a single provider with the given model_id. Returns result with error if provider fails."""
        provider_prefix = ""
        actual_model_id = provider_model_id
        
        # Check if model_id needs server resolution (e.g., alibaba provider)
        # If the provider has a default_server configured, resolve it and transform the model_id
        if "/" in provider_model_id:
            parts = provider_model_id.split("/", 1)
            temp_provider_prefix = parts[0]
            temp_actual_model_id = parts[1]
            
            # Always try to resolve default server for ANY provider (not just hardcoded ones)
            # This allows any provider to have a default_server configured in their YAML
            # For example: "openai/gpt-oss-safeguard-20b" can be routed to Groq or OpenRouter
            default_server_id, transformed_model_id = resolve_default_server_from_provider_config(provider_model_id)
            if default_server_id and transformed_model_id:
                logger.debug(f"[{task_id}] LLM Utils: Resolved default server '{default_server_id}' for preprocessing model '{provider_model_id}'. Using transformed model_id: '{transformed_model_id}'")
                # Update provider_model_id to use the transformed version with server prefix
                provider_model_id = transformed_model_id
                # Re-parse the transformed model_id
                if "/" in provider_model_id:
                    parts = provider_model_id.split("/", 1)
                    provider_prefix = parts[0]
                    actual_model_id = parts[1]
                else:
                    logger.warning(f"[{task_id}] LLM Utils: Transformed model_id '{provider_model_id}' does not contain a provider prefix.")
                    return LLMPreprocessingCallResult(error_message=f"Invalid transformed model_id format: '{provider_model_id}'")
            else:
                # No server resolution - use original provider
                provider_prefix = temp_provider_prefix
                actual_model_id = temp_actual_model_id
        else:
            logger.warning(f"[{task_id}] LLM Utils: model_id '{provider_model_id}' does not contain a provider prefix.")
            return LLMPreprocessingCallResult(error_message=f"Invalid model_id format: '{provider_model_id}'")
        
        # Check health status from cache before attempting
        is_unhealthy = await _is_provider_unhealthy_preprocessing(provider_prefix)
        if is_unhealthy:
            return LLMPreprocessingCallResult(error_message=f"Provider '{provider_prefix}' is marked as unhealthy in cache")

        try:
            # Sanitize tool definition for provider-agnostic compatibility (remove min/max from integer schemas)
            # This ensures all providers receive sanitized tools regardless of their mapping function
            sanitized_tool_definition = current_tool_definition.copy()
            if "function" in sanitized_tool_definition and "parameters" in sanitized_tool_definition["function"]:
                sanitized_tool_definition["function"] = sanitized_tool_definition["function"].copy()
                sanitized_tool_definition["function"]["parameters"] = _sanitize_schema_for_llm_providers(
                    sanitized_tool_definition["function"]["parameters"]
                )
            
            # Use dynamic registry - no hardcoded provider names!
            provider_client = _get_provider_client(provider_prefix)
            
            if provider_client:
                # Call the provider client dynamically - all have same signature
                # Pass sanitized tool definition to ensure provider-agnostic behavior
                # Wrap with timeout (5 seconds for preprocessing requests - should complete quickly)
                try:
                    response = await asyncio.wait_for(
                        provider_client(
                            task_id=task_id, 
                            model_id=actual_model_id, 
                            messages=transformed_messages_for_llm,
                            secrets_manager=secrets_manager, 
                            tools=[sanitized_tool_definition],  # Use sanitized tool (min/max removed) for all providers
                            tool_choice="required", 
                            stream=False
                        ),
                        timeout=PREPROCESSING_TIMEOUT_SECONDS  # Use 5 second timeout for preprocessing
                    )
                    return handle_response(response, expected_tool_name)
                except asyncio.TimeoutError:
                    return LLMPreprocessingCallResult(error_message=f"Request timeout after {PREPROCESSING_TIMEOUT_SECONDS}s")
            
            # No provider found
            err_msg_no_provider = (
                f"No provider client found for preprocessing model_id: '{provider_model_id}'. "
                f"Provider prefix: '{provider_prefix}'. "
                f"Available providers: {sorted(PROVIDER_CLIENT_REGISTRY.keys())}"
            )
            return LLMPreprocessingCallResult(error_message=err_msg_no_provider)
        except Exception as e:
            # Catch any unexpected exceptions from provider calls
            logger.error(f"[{task_id}] LLM Utils: Exception calling provider {provider_model_id}: {e}", exc_info=True)
            return LLMPreprocessingCallResult(error_message=f"Exception calling provider {provider_model_id}: {str(e)}")

    # Determine if an error is retryable (should try fallback)
    def is_retryable_error(error_message: Optional[str]) -> bool:
        """Check if error is retryable (e.g., 503, timeout, service unavailable)."""
        if not error_message:
            return False
        # Non-retryable errors: 401 (auth), 400 (bad request)
        non_retryable_indicators = ["401", "unauthorized", "bad request", "400"]
        if any(indicator.lower() in error_message.lower() for indicator in non_retryable_indicators):
            return False
        # Retryable errors: 503, 502, 504, 500, timeout, service unavailable, unreachable backend, unhealthy
        retryable_indicators = [
            "503", "502", "504", "500", "timeout", "service unavailable", "unreachable_backend", 
            "connection", "unhealthy", "http error"
        ]
        return any(indicator.lower() in error_message.lower() for indicator in retryable_indicators)

    # Try primary provider first
    providers_to_try = [model_id]
    if fallback_models:
        providers_to_try.extend(fallback_models)
    
    attempted_providers = []
    last_error = None
    
    for provider_model_id in providers_to_try:
        attempted_providers.append(provider_model_id)
        logger.info(f"[{task_id}] LLM Utils: Attempting preprocessing with provider: {provider_model_id} (attempt {len(attempted_providers)}/{len(providers_to_try)})")
        
        result = await _call_single_provider(provider_model_id)
        
        # If successful, return immediately
        if result.arguments and not result.error_message:
            logger.info(f"[{task_id}] LLM Utils: Preprocessing succeeded with provider: {provider_model_id}")
            return result
        
        # If error is not retryable (e.g., 401, 400), fail immediately without trying fallbacks
        if result.error_message and not is_retryable_error(result.error_message):
            logger.warning(f"[{task_id}] LLM Utils: Provider {provider_model_id} failed with non-retryable error: {result.error_message}. Not trying fallbacks.")
            return result
        
        # Store error for final reporting if all providers fail
        last_error = result.error_message
        logger.warning(f"[{task_id}] LLM Utils: Provider {provider_model_id} failed with retryable error: {result.error_message}. Trying next provider...")
    
    # All providers failed
    error_summary = f"All {len(providers_to_try)} provider(s) failed. Attempted providers: {', '.join(attempted_providers)}. Last error: {last_error}"
    logger.error(f"[{task_id}] LLM Utils: {error_summary}")
    return LLMPreprocessingCallResult(error_message=error_summary)


async def call_main_llm_stream(
    task_id: str,
    model_id: str,
    system_prompt: str,
    message_history: List[Dict[str, str]],
    temperature: float,
    secrets_manager: Optional[SecretsManager] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None
) -> AsyncIterator[str]:
    log_prefix = f"[{task_id}] LLM Utils (Main Stream - {model_id}):"
    logger.info(f"{log_prefix} Preparing to call. Temp: {temperature}. Tools: {len(tools) if tools else 0}. Choice: {tool_choice}")

    transformed_user_assistant_messages = _transform_message_history_for_llm(message_history)
    llm_api_messages = [{"role": "system", "content": system_prompt}] if system_prompt else []
    llm_api_messages.extend(transformed_user_assistant_messages)

    # Sanitize tools for all providers (remove min/max from integer schemas)
    # This ensures provider-agnostic behavior - all providers get sanitized tools
    # Tools are sanitized here before being passed to any provider-specific mapping function
    sanitized_tools = None
    if tools:
        sanitized_tools = []
        for tool in tools:
            if not isinstance(tool, dict) or "function" not in tool:
                sanitized_tools.append(tool)
                continue
            
            # Create a copy of the tool
            sanitized_tool = tool.copy()
            sanitized_function = tool["function"].copy()
            
            # Sanitize the parameters schema (remove min/max for all providers)
            if "parameters" in sanitized_function:
                sanitized_function["parameters"] = _sanitize_schema_for_llm_providers(
                    sanitized_function["parameters"]
                )
            
            sanitized_tool["function"] = sanitized_function
            sanitized_tools.append(sanitized_tool)
        
        logger.debug(f"{log_prefix} Sanitized {len(sanitized_tools)} tool(s) for provider-agnostic compatibility (removed min/max from integer schemas)")

    # Log the exact input being sent to the LLM
    logger.info(f"{log_prefix} Message history transformation: {len(message_history)} input messages -> {len(transformed_user_assistant_messages)} transformed messages")
    logger.debug(f"{log_prefix} Final payload being sent to LLM provider:\n"
                 f"System Prompt: {system_prompt}\n"
                 f"Messages: {json.dumps(llm_api_messages, indent=2)}")

    # Validate that model_id is not None before processing
    if model_id is None:
        error_msg = f"{log_prefix} model_id is None. Cannot proceed with LLM call. This usually indicates preprocessing failed."
        logger.error(error_msg)
        raise ValueError(error_msg)

    # Store original model_id for fallback resolution and provider override resolution (needed for openrouter)
    original_model_id = model_id
    
    # Resolve fallback servers for models that support multiple servers (e.g., alibaba, openai)
    fallback_servers = []
    if "/" in model_id and (model_id.startswith("alibaba/") or model_id.startswith("openai/")):
        # Resolve fallback servers from provider config
        fallback_servers = resolve_fallback_servers_from_provider_config(model_id)
        if fallback_servers:
            logger.info(f"{log_prefix} Resolved {len(fallback_servers)} fallback server(s) for model '{model_id}': {fallback_servers}")

    # Check if model_id needs server resolution (e.g., alibaba provider)
    # If the provider has a default_server configured, resolve it and transform the model_id
    provider_prefix = ""
    actual_model_id = model_id
    if "/" in model_id:
        parts = model_id.split("/", 1)
        provider_prefix = parts[0]
        actual_model_id = parts[1]
        
        # For providers that support multiple servers (e.g., alibaba, openai), resolve the default server
        if provider_prefix in ["alibaba", "openai"]:
            default_server_id, transformed_model_id = resolve_default_server_from_provider_config(model_id)
            if default_server_id and transformed_model_id:
                logger.info(f"{log_prefix} Resolved default server '{default_server_id}' for model '{model_id}'. Using transformed model_id: '{transformed_model_id}'")
                # Update model_id to use the transformed version with server prefix
                model_id = transformed_model_id
                # Re-parse the transformed model_id
                if "/" in model_id:
                    parts = model_id.split("/", 1)
                    provider_prefix = parts[0]
                    actual_model_id = parts[1]
                else:
                    logger.warning(f"{log_prefix} Transformed model_id '{model_id}' does not contain a provider prefix.")
            else:
                logger.warning(f"{log_prefix} Could not resolve default server for '{model_id}'. Falling back to original routing.")
    else:
        logger.warning(f"{log_prefix} model_id '{model_id}' does not contain a provider prefix.")

    # Build list of servers to try: primary server + fallback servers
    servers_to_try = [model_id]
    if fallback_servers:
        servers_to_try.extend(fallback_servers)
        logger.info(f"{log_prefix} Will try {len(servers_to_try)} server(s): primary='{servers_to_try[0]}', fallbacks={servers_to_try[1:]}")

    # Determine if an error is retryable (should try fallback)
    def is_retryable_error(error_message: Optional[str]) -> bool:
        """Check if error is retryable (e.g., 503, timeout, service unavailable, missing API key, 404)."""
        if not error_message:
            return False
        # Non-retryable errors: 401 (auth), 400 (bad request) - these won't be fixed by trying another server
        non_retryable_indicators = ["401", "unauthorized", "bad request", "400"]
        if any(indicator.lower() in error_message.lower() for indicator in non_retryable_indicators):
            return False
        # Retryable errors: 503, 502, 504, 500, 404 (not found - endpoint/model might not exist on this server), 
        # timeout, service unavailable, unreachable backend, missing API key
        retryable_indicators = [
            "503", "502", "504", "500", "404", "timeout", "service unavailable", "unreachable_backend", 
            "connection", "api key", "failed to retrieve", "not found", "http error", "timeouterror"
        ]
        return any(indicator.lower() in error_message.lower() for indicator in retryable_indicators)

    # Helper function to check provider health from cache
    async def _is_provider_unhealthy(provider_id: str) -> bool:
        """Check if provider is marked as unhealthy in cache."""
        try:
            cache_service = CacheService()
            cache_key = f"health_check:provider:{provider_id}"
            client = await cache_service.client
            if client:
                health_data_json = await client.get(cache_key)
                if health_data_json:
                    if isinstance(health_data_json, bytes):
                        health_data_json = health_data_json.decode('utf-8')
                    health_data = json.loads(health_data_json)
                    status = health_data.get("status", "unknown")
                    return status == "unhealthy"
        except Exception as e:
            logger.debug(f"{log_prefix} Could not check health status for '{provider_id}': {e}. Proceeding with attempt.")
        return False  # If cache miss or error, proceed (don't block on missing health data)
    
    # Try each server in order until one succeeds
    attempted_servers = []
    last_error = None
    
    for server_model_id in servers_to_try:
        attempted_servers.append(server_model_id)
        attempt_log_prefix = f"{log_prefix} [Attempt {len(attempted_servers)}/{len(servers_to_try)}: {server_model_id}]"
        
        # Parse the server model_id to get provider prefix and actual model_id
        server_provider_prefix = ""
        server_actual_model_id = server_model_id
        server_original_model_id = original_model_id  # Keep original for openrouter
        
        if "/" in server_model_id:
            parts = server_model_id.split("/", 1)
            server_provider_prefix = parts[0]
            server_actual_model_id = parts[1]
        
        # Check health status from cache before attempting
        is_unhealthy = await _is_provider_unhealthy(server_provider_prefix)
        if is_unhealthy:
            # Skip unhealthy providers unless all servers are unhealthy
            if len(attempted_servers) < len(servers_to_try):
                logger.warning(f"{attempt_log_prefix} Provider '{server_provider_prefix}' is marked as unhealthy in cache. Skipping to next server.")
                continue
            else:
                # Last server - try anyway (might have recovered)
                logger.warning(f"{attempt_log_prefix} Provider '{server_provider_prefix}' is marked as unhealthy, but it's the last server. Attempting anyway.")
        
        # Default input payload assumes provider-native clients that want only the model suffix
        # For openrouter, we may need to pass the original model_id for provider override resolution
        # Use sanitized_tools (with min/max removed) for all providers to ensure provider-agnostic behavior
        server_llm_input_details = {
            "task_id": task_id, 
            "model_id": server_actual_model_id, 
            "messages": llm_api_messages,
            "temperature": temperature, 
            "tools": sanitized_tools,  # Use sanitized tools (min/max removed) for all providers
            "tool_choice": tool_choice, 
            "stream": True
        }
        
        # For openrouter, if the original model has provider_overrides configured, 
        # we need to pass the original model_id (e.g., "alibaba/qwen3-235b-a22b-2507") 
        # instead of the transformed one (e.g., "openrouter/qwen/qwen3-235b-a22b-2507")
        # so that OpenRouter can resolve provider overrides correctly.
        # Check if this is the primary server (not a fallback) and if provider_overrides exist
        if server_provider_prefix == "openrouter" and "/" in original_model_id:
            provider_id, model_suffix = original_model_id.split("/", 1)
            provider_config = config_manager.get_provider_config(provider_id)
            if provider_config:
                for model in provider_config.get("models", []):
                    if isinstance(model, dict) and model.get("id") == model_suffix:
                        # Check if this model has provider_overrides configured
                        if model.get("provider_overrides"):
                            # Check if this is the primary server (first in servers_to_try)
                            # For primary server, use original model_id for provider override resolution
                            # For fallback servers, use the server's model_id directly
                            if len(attempted_servers) == 1:  # Primary server
                                server_llm_input_details["model_id"] = original_model_id
                                logger.debug(f"{attempt_log_prefix} Using original model_id '{original_model_id}' for openrouter to enable provider override resolution")
                            else:  # Fallback server
                                server_llm_input_details["model_id"] = server_actual_model_id
                                logger.debug(f"{attempt_log_prefix} Using fallback server model_id '{server_actual_model_id}' for openrouter")
                            break

        # Select provider client using dynamic registry - no hardcoded provider names!
        provider_client = _get_provider_client(server_provider_prefix)
        
        if not provider_client:
            # Check if this is a provider that should have been resolved to a server
            # (e.g., alibaba should have been resolved to openrouter or cerebras)
            # This shouldn't happen if server resolution is working correctly
            err_msg = (
                f"No provider client found for main stream model_id: '{server_model_id}'. "
                f"Provider prefix: '{server_provider_prefix}'. "
                f"Available providers: {sorted(PROVIDER_CLIENT_REGISTRY.keys())}"
            )
            logger.error(f"{attempt_log_prefix} {err_msg}")
            last_error = err_msg
            # If this is the last server to try, yield error
            if len(attempted_servers) >= len(servers_to_try):
                yield f"[ERROR: Model provider for '{server_model_id}' not supported. Available: {', '.join(sorted(PROVIDER_CLIENT_REGISTRY.keys()))}]"
            continue

        try:
            logger.info(f"{attempt_log_prefix} Attempting to call provider client")
            raw_chunk_stream = await provider_client(secrets_manager=secrets_manager, **server_llm_input_details)
            
            if hasattr(raw_chunk_stream, '__aiter__'):
                # Success! Wrap stream with timeout for first chunk
                logger.info(f"{attempt_log_prefix} Successfully connected to provider. Streaming response with {FIRST_CHUNK_TIMEOUT_SECONDS}s timeout for first chunk...")
                try:
                    # Wrap stream with first chunk timeout
                    timeout_stream = stream_with_first_chunk_timeout(raw_chunk_stream, FIRST_CHUNK_TIMEOUT_SECONDS)
                    async for paragraph in aggregate_paragraphs(timeout_stream):
                        yield paragraph
                    # Successfully completed - return from function
                    return
                except TimeoutError as timeout_err:
                    # First chunk timeout - treat as retryable error
                    error_msg = f"First chunk timeout: {str(timeout_err)}"
                    logger.error(f"{attempt_log_prefix} {error_msg}")
                    last_error = error_msg
                    if len(attempted_servers) < len(servers_to_try):
                        logger.warning(f"{attempt_log_prefix} Timeout error detected. Will try next server if available.")
                        continue
                    else:
                        yield f"[ERROR: LLM stream failed - {timeout_err}]"
                        return
            else:
                error_msg = f"Expected a stream but did not receive one. Response type: {type(raw_chunk_stream)}"
                logger.error(f"{attempt_log_prefix} {error_msg}")
                last_error = error_msg
                # If this is the last server to try, yield error
                if len(attempted_servers) >= len(servers_to_try):
                    yield f"[ERROR: Expected a stream but received {type(raw_chunk_stream)}]"
                continue

        except (ValueError, IOError) as e:
            error_msg = str(e)
            logger.error(f"{attempt_log_prefix} Client or stream error: {e}", exc_info=True)
            last_error = error_msg
            
            # Check if error is retryable
            if is_retryable_error(error_msg):
                logger.warning(f"{attempt_log_prefix} Retryable error detected. Will try next server if available.")
                # If this is not the last server, continue to next server
                if len(attempted_servers) < len(servers_to_try):
                    continue
            else:
                # Non-retryable error - fail immediately
                logger.warning(f"{attempt_log_prefix} Non-retryable error detected. Not trying fallback servers.")
                yield f"[ERROR: LLM stream failed - {e}]"
                return
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"{attempt_log_prefix} Unexpected error during main LLM stream: {e}", exc_info=True)
            last_error = error_msg
            
            # Check if error is retryable
            if is_retryable_error(error_msg):
                logger.warning(f"{attempt_log_prefix} Retryable error detected. Will try next server if available.")
                # If this is not the last server, continue to next server
                if len(attempted_servers) < len(servers_to_try):
                    continue
            else:
                # Non-retryable error - fail immediately
                logger.warning(f"{attempt_log_prefix} Non-retryable error detected. Not trying fallback servers.")
                yield f"[ERROR: An unexpected error occurred - {e}]"
                return
    
    # All servers failed
    error_summary = f"All {len(servers_to_try)} server(s) failed. Attempted servers: {', '.join(attempted_servers)}. Last error: {last_error}"
    logger.error(f"{log_prefix} {error_summary}")
    yield f"[ERROR: LLM stream failed - All servers failed. Last error: {last_error}]"


def log_main_llm_stream_aggregated_output(task_id: str, aggregated_response: str, error_message: Optional[str] = None):
    """
    Log aggregated LLM stream output with sanitization.
    Even in development mode, we don't log actual response content, only metadata.
    """
    log_prefix = f"[{task_id}] LLM Utils (Main Stream Aggregated Output):"
    
    if os.getenv("SERVER_ENVIRONMENT") == "development":
        if error_message:
            # For errors, we still don't log the actual response content
            log_details = {
                "task_id": task_id,
                "error": error_message,
                "partial_response_length": len(aggregated_response) if aggregated_response else 0,
                "partial_response_content": "[REDACTED_CONTENT]",
                "event_type": "llm_main_stream_aggregated_output_error"
            }
            logger.error(f"{log_prefix} Error during stream processing: {error_message}", extra=log_details)
        else:
            # Sanitize: show only length, not actual content
            log_details = {
                "task_id": task_id,
                "aggregated_response_length": len(aggregated_response),
                "aggregated_response_content": "[REDACTED_CONTENT]",
                "event_type": "llm_main_stream_aggregated_output_success"
            }
            logger.info(f"{log_prefix} Successfully aggregated stream. Length: {len(aggregated_response)}", extra=log_details)
    else:
        if error_message:
            logger.error(f"{log_prefix} Error during stream processing: {error_message}. Detailed logging skipped.")
        else:
            logger.info(f"{log_prefix} Successfully aggregated stream. Length: {len(aggregated_response)}. Detailed logging skipped.")
