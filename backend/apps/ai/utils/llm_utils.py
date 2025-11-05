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
                # Cerebras uses direct model ID, route via provider prefix
                fallback_model_id = f"{server_id}/{model_suffix}"
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
    transformed_messages = []
    for msg in message_history:
        role = "assistant"
        if msg.get("sender_name") == "user":
            role = "user"
        if "role" in msg:
            role = msg["role"]

        content_input = msg.get("content", "")
        plain_text_content = _extract_text_from_tiptap(content_input)
        
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
        if "/" in provider_model_id:
            parts = provider_model_id.split("/", 1)
            provider_prefix = parts[0]
            actual_model_id = parts[1]
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
                # Route Qwen via OpenRouter and pass full OpenRouter model id including upstream provider
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
    logger.debug(f"{log_prefix} Final payload being sent to LLM provider:\n"
                 f"System Prompt: {system_prompt}\n"
                 f"Messages: {json.dumps(llm_api_messages, indent=2)}")

    # Validate that model_id is not None before processing
    if model_id is None:
        error_msg = f"{log_prefix} model_id is None. Cannot proceed with LLM call. This usually indicates preprocessing failed."
        logger.error(error_msg)
        raise ValueError(error_msg)

    provider_prefix = ""
    actual_model_id = model_id
    if "/" in model_id:
        parts = model_id.split("/", 1)
        provider_prefix = parts[0]
        actual_model_id = parts[1]
    else:
        logger.warning(f"{log_prefix} model_id '{model_id}' does not contain a provider prefix.")

    # Default input payload assumes provider-native clients that want only the model suffix
    main_llm_input_details = {
        "task_id": task_id, "model_id": actual_model_id, "messages": llm_api_messages,
        "temperature": temperature, "tools": tools, "tool_choice": tool_choice, "stream": True
    }

    provider_client = None
    if provider_prefix == "mistral":
        provider_client = invoke_mistral_chat_completions
    elif provider_prefix == "google":
        provider_client = invoke_google_chat_completions
    elif provider_prefix == "anthropic":
        provider_client = invoke_anthropic_chat_completions
    elif provider_prefix == "openrouter":
        provider_client = invoke_openrouter_chat_completions
    elif provider_prefix == "cerebras":
        # Direct Cerebras API for ultra-fast inference
        provider_client = invoke_cerebras_chat_completions
    elif provider_prefix == "alibaba":
        # For Qwen via OpenRouter, override model_id to the full OpenRouter id including the upstream provider
        provider_client = invoke_openrouter_chat_completions
        main_llm_input_details["model_id"] = model_id
    elif provider_prefix == "openai":
        provider_client = invoke_openai_chat_completions
    else:
        err_msg = f"No provider client for main stream model_id: '{model_id}'."
        logger.error(f"{log_prefix} {err_msg}")
        yield f"[ERROR: Model provider for '{model_id}' not supported.]"
        return

    try:
        raw_chunk_stream = await provider_client(secrets_manager=secrets_manager, **main_llm_input_details)
        
        if hasattr(raw_chunk_stream, '__aiter__'):
            async for paragraph in aggregate_paragraphs(raw_chunk_stream):
                yield paragraph
        else:
            logger.error(f"{log_prefix} Expected a stream but did not receive one. Response type: {type(raw_chunk_stream)}")
            yield f"[ERROR: Expected a stream but received {type(raw_chunk_stream)}]"

    except (ValueError, IOError) as e:
        logger.error(f"{log_prefix} Client or stream error: {e}", exc_info=True)
        yield f"[ERROR: LLM stream failed - {e}]"
    except Exception as e:
        logger.error(f"{log_prefix} Unexpected error during main LLM stream: {e}", exc_info=True)
        yield f"[ERROR: An unexpected error occurred - {e}]"


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
