# backend/apps/ai/utils/llm_utils.py
# Utilities for interacting with Language Models (LLMs).

import logging
from typing import Dict, Any, List, Optional, AsyncIterator, Union
import copy
from pydantic import BaseModel
import json
import os
from dotenv import load_dotenv

load_dotenv()

from backend.apps.ai.llm_providers.mistral_client import invoke_mistral_chat_completions, UnifiedMistralResponse as UnifiedMistralResponse, ParsedMistralToolCall
from backend.apps.ai.llm_providers.google_client import invoke_google_chat_completions, UnifiedGoogleResponse, ParsedGoogleToolCall as ParsedGoogleToolCall
from backend.apps.ai.llm_providers.anthropic_client import invoke_anthropic_chat_completions, UnifiedAnthropicResponse, ParsedAnthropicToolCall
from backend.apps.ai.llm_providers.openai_openrouter import invoke_openrouter_chat_completions
from backend.apps.ai.llm_providers.openai_client import invoke_openai_chat_completions
from backend.apps.ai.llm_providers.cerebras_wrapper import invoke_cerebras_chat_completions
from backend.apps.ai.llm_providers.openai_shared import UnifiedOpenAIResponse, ParsedOpenAIToolCall, OpenAIUsageMetadata
from backend.apps.ai.utils.stream_utils import aggregate_paragraphs
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.config_manager import config_manager

logger = logging.getLogger(__name__)

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
        
        # Build transformed model ID based on server type
        if default_server_id == "openrouter":
            # OpenRouter model IDs already include provider prefix (e.g., "qwen/qwen3-235b-a22b-2507")
            transformed_model_id = f"{default_server_id}/{server_model_id}"
        elif default_server_id == "cerebras":
            # Cerebras uses direct model ID (e.g., "qwen3-235b-a22b-2507")
            transformed_model_id = f"{default_server_id}/{server_model_id}"
        else:
            # For other servers, use the server's model_id directly
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
            
            # Build fallback model ID based on server type
            # For openrouter, use the full model_id as-is (it already includes provider prefix)
            # For other servers, construct "server/provider/model-id" or "server/model-id"
            if server_id == "openrouter":
                # OpenRouter model IDs already include provider prefix (e.g., "mistralai/mistral-small-3.2-24b-instruct")
                fallback_model_id = f"{server_id}/{server_model_id}"
            elif server_id == "cerebras":
                # Cerebras uses direct model ID from server config
                fallback_model_id = f"{server_id}/{server_model_id}"
            else:
                # For other servers, use the server's model_id directly
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


def _transform_message_history_for_llm(message_history: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    Transforms message history from internal format to LLM API format.
    
    This function converts messages from the internal format (which may include
    sender_name, created_at, category, etc.) to the standard OpenAI-compatible
    format (role and content only).
    
    Args:
        message_history: List of message dictionaries in internal format
        
    Returns:
        List of message dictionaries in LLM API format (role, content)
    """
    transformed_messages = []
    for idx, msg in enumerate(message_history):
        role = "assistant"
        if msg.get("sender_name") == "user":
            role = "user"
        if "role" in msg:
            role = msg["role"]

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
        
        log_output_extra = {
            "task_id": task_id, "success": response.success, "error_message": response.error_message,
            "tool_calls_made": [tc.model_dump() for tc in response.tool_calls_made] if response.tool_calls_made else None,
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
            
            # For providers that support multiple servers (e.g., alibaba), resolve the default server
            if temp_provider_prefix == "alibaba":
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
                    logger.warning(f"[{task_id}] LLM Utils: Could not resolve default server for '{provider_model_id}'. Using original routing.")
                    provider_prefix = temp_provider_prefix
                    actual_model_id = temp_actual_model_id
            else:
                provider_prefix = temp_provider_prefix
                actual_model_id = temp_actual_model_id
        else:
            logger.warning(f"[{task_id}] LLM Utils: model_id '{provider_model_id}' does not contain a provider prefix.")
            return LLMPreprocessingCallResult(error_message=f"Invalid model_id format: '{provider_model_id}'")

        try:
            if provider_prefix == "mistral":
                response = await invoke_mistral_chat_completions(
                    task_id=task_id, model_id=actual_model_id, messages=transformed_messages_for_llm,
                    secrets_manager=secrets_manager, tools=[current_tool_definition], tool_choice="required", stream=False
                )
                return handle_response(response, expected_tool_name)

            elif provider_prefix == "google":
                response = await invoke_google_chat_completions(
                    task_id=task_id, model_id=actual_model_id, messages=transformed_messages_for_llm,
                    secrets_manager=secrets_manager, tools=[current_tool_definition], tool_choice="required", stream=False
                )
                return handle_response(response, expected_tool_name)

            elif provider_prefix == "anthropic":
                response = await invoke_anthropic_chat_completions(
                    task_id=task_id, model_id=actual_model_id, messages=transformed_messages_for_llm,
                    secrets_manager=secrets_manager, tools=[current_tool_definition], tool_choice="required", stream=False
                )
                return handle_response(response, expected_tool_name)
            
            elif provider_prefix == "openrouter":
                # For explicit openrouter usage, allow nested upstream provider in actual_model_id
                response = await invoke_openrouter_chat_completions(
                    task_id=task_id, model_id=actual_model_id, messages=transformed_messages_for_llm,
                    secrets_manager=secrets_manager, tools=[current_tool_definition], tool_choice="required", stream=False
                )
                return handle_response(response, expected_tool_name)
            
            elif provider_prefix == "cerebras":
                # Direct Cerebras API for ultra-fast inference
                response = await invoke_cerebras_chat_completions(
                    task_id=task_id, model_id=actual_model_id, messages=transformed_messages_for_llm,
                    secrets_manager=secrets_manager, tools=[current_tool_definition], tool_choice="required", stream=False
                )
                return handle_response(response, expected_tool_name)
            
            elif provider_prefix == "alibaba":
                # This should not happen after server resolution, but keep as fallback
                # Route Qwen via OpenRouter and pass full OpenRouter model id including upstream provider
                logger.warning(f"[{task_id}] LLM Utils: Alibaba provider detected in preprocessing without server resolution. Using OpenRouter as fallback.")
                response = await invoke_openrouter_chat_completions(
                    task_id=task_id, model_id=provider_model_id, messages=transformed_messages_for_llm,
                    secrets_manager=secrets_manager, tools=[current_tool_definition], tool_choice="required", stream=False
                )
                return handle_response(response, expected_tool_name)
            
            elif provider_prefix == "openai":
                response = await invoke_openai_chat_completions(
                    task_id=task_id, model_id=actual_model_id, messages=transformed_messages_for_llm,
                    secrets_manager=secrets_manager, tools=[current_tool_definition], tool_choice="required", stream=False
                )
                return handle_response(response, expected_tool_name)
            
            else:
                err_msg_no_provider = f"No provider client implemented for preprocessing model_id: '{provider_model_id}'."
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
        # Retryable errors: 503, 502, 504, timeout, service unavailable, unreachable backend
        retryable_indicators = ["503", "502", "504", "timeout", "service unavailable", "unreachable_backend", "connection"]
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
    
    # Resolve fallback servers for models that support multiple servers (e.g., alibaba)
    fallback_servers = []
    if "/" in model_id and model_id.startswith("alibaba/"):
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
        
        # For providers that support multiple servers (e.g., alibaba), resolve the default server
        if provider_prefix == "alibaba":
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
        # Retryable errors: 503, 502, 504, 404 (not found - endpoint/model might not exist on this server), 
        # timeout, service unavailable, unreachable backend, missing API key
        retryable_indicators = [
            "503", "502", "504", "404", "timeout", "service unavailable", "unreachable_backend", 
            "connection", "api key", "failed to retrieve", "not found", "http error"
        ]
        return any(indicator.lower() in error_message.lower() for indicator in retryable_indicators)

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
        
        # Default input payload assumes provider-native clients that want only the model suffix
        # For openrouter, we may need to pass the original model_id for provider override resolution
        server_llm_input_details = {
            "task_id": task_id, 
            "model_id": server_actual_model_id, 
            "messages": llm_api_messages,
            "temperature": temperature, 
            "tools": tools, 
            "tool_choice": tool_choice, 
            "stream": True
        }
        
        # For openrouter, if we transformed from alibaba, pass original model_id for provider override resolution
        # But only if this is the primary server; for fallback servers, use the server's model_id directly
        if server_provider_prefix == "openrouter" and original_model_id.startswith("alibaba/"):
            # Check if this is a fallback server (has "qwen/" prefix in the model_id)
            # If it's a fallback, use the server's model_id; otherwise use original for provider overrides
            if "qwen/" in server_actual_model_id:
                # This is a fallback server, use its model_id directly
                server_llm_input_details["model_id"] = server_actual_model_id
                logger.debug(f"{attempt_log_prefix} Using fallback server model_id '{server_actual_model_id}' for openrouter")
            else:
                # This is the primary server, use original for provider override resolution
                server_llm_input_details["model_id"] = original_model_id
                logger.debug(f"{attempt_log_prefix} Using original model_id '{original_model_id}' for openrouter to enable provider override resolution")

        # Select provider client based on server provider prefix
        provider_client = None
        if server_provider_prefix == "mistral":
            provider_client = invoke_mistral_chat_completions
        elif server_provider_prefix == "google":
            provider_client = invoke_google_chat_completions
        elif server_provider_prefix == "anthropic":
            provider_client = invoke_anthropic_chat_completions
        elif server_provider_prefix == "openrouter":
            provider_client = invoke_openrouter_chat_completions
        elif server_provider_prefix == "cerebras":
            # Direct Cerebras API for ultra-fast inference
            provider_client = invoke_cerebras_chat_completions
        elif server_provider_prefix == "alibaba":
            # This should not happen after server resolution, but keep as fallback
            # Route Qwen via OpenRouter and pass full OpenRouter model id including upstream provider
            logger.warning(f"{attempt_log_prefix} Alibaba provider detected without server resolution. Using OpenRouter as fallback.")
            provider_client = invoke_openrouter_chat_completions
            server_llm_input_details["model_id"] = server_model_id
        elif server_provider_prefix == "openai":
            provider_client = invoke_openai_chat_completions
        else:
            err_msg = f"No provider client for main stream model_id: '{server_model_id}'."
            logger.error(f"{attempt_log_prefix} {err_msg}")
            last_error = err_msg
            # If this is the last server to try, yield error
            if len(attempted_servers) >= len(servers_to_try):
                yield f"[ERROR: Model provider for '{server_model_id}' not supported.]"
            continue

        try:
            logger.info(f"{attempt_log_prefix} Attempting to call provider client")
            raw_chunk_stream = await provider_client(secrets_manager=secrets_manager, **server_llm_input_details)
            
            if hasattr(raw_chunk_stream, '__aiter__'):
                # Success! Yield the stream
                logger.info(f"{attempt_log_prefix} Successfully connected to provider. Streaming response...")
                async for paragraph in aggregate_paragraphs(raw_chunk_stream):
                    yield paragraph
                # Successfully completed - return from function
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
    log_prefix = f"[{task_id}] LLM Utils (Main Stream Aggregated Output):"
    
    if os.getenv("SERVER_ENVIRONMENT") == "development":
        if error_message:
            log_details = {"task_id": task_id, "error": error_message, "partial_response_if_any": aggregated_response or "N/A", "event_type": "llm_main_stream_aggregated_output_error"}
            logger.error(f"{log_prefix} Error during stream processing: {error_message}", extra=log_details)
        else:
            response_snippet = aggregated_response[:1000] + "..." if len(aggregated_response) > 1000 else aggregated_response
            log_details = {"task_id": task_id, "aggregated_response_length": len(aggregated_response), "aggregated_response_snippet": response_snippet, "event_type": "llm_main_stream_aggregated_output_success"}
            logger.info(f"{log_prefix} Successfully aggregated stream. Length: {len(aggregated_response)}", extra=log_details)
    else:
        if error_message:
            logger.error(f"{log_prefix} Error during stream processing: {error_message}. Detailed logging skipped.")
        else:
            logger.info(f"{log_prefix} Successfully aggregated stream. Length: {len(aggregated_response)}. Detailed logging skipped.")
