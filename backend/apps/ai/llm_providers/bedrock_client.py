# backend/apps/ai/llm_providers/bedrock_client.py
# Unified AWS Bedrock client using the Converse API.
#
# Handles ALL Bedrock models (Anthropic Claude, Mistral, Meta Llama, Cohere, etc.)
# through a single provider-agnostic interface. The Converse API normalizes
# request/response formats across all model providers on Bedrock.
#
# Auto-discovered by the provider registry as "aws_bedrock" via the function name
# invoke_aws_bedrock_chat_completions().
#
# Architecture: docs/architecture/ai/ai-model-selection.md

import logging
import json
from typing import Dict, Any, List, Optional, Union, AsyncIterator
import boto3
from botocore.exceptions import ClientError
import tiktoken

from backend.core.api.app.utils.secrets_manager import SecretsManager
from .bedrock_shared import (
    BedrockUsageMetadata,
    ParsedBedrockToolCall,
    UnifiedBedrockResponse,
    RawBedrockResponse,
    is_aws_credential_error,
    format_aws_error_message,
    convert_messages_to_converse_format,
    convert_tools_to_converse_format,
    convert_tool_choice_to_converse_format,
)
from .openai_shared import calculate_token_breakdown

logger = logging.getLogger(__name__)

# --- Global State (singleton boto3 client) ---
_bedrock_client_initialized = False
_bedrock_runtime_client: Optional[boto3.client] = None
_aws_region: Optional[str] = None


async def _ensure_bedrock_client(secrets_manager: SecretsManager) -> None:
    """Initialize the boto3 bedrock-runtime client from shared AWS credentials in Vault."""
    global _bedrock_client_initialized, _bedrock_runtime_client, _aws_region

    if _bedrock_client_initialized:
        return

    secret_path = "kv/data/providers/aws"

    aws_access_key_id = await secrets_manager.get_secret(secret_path=secret_path, secret_key="access_key_id")
    aws_secret_access_key = await secrets_manager.get_secret(secret_path=secret_path, secret_key="secret_access_key")
    region = await secrets_manager.get_secret(secret_path=secret_path, secret_key="region")

    if not region:
        region = "eu-central-1"
        logger.info(f"AWS region not found in secrets. Defaulting to '{region}'.")

    if not all([aws_access_key_id, aws_secret_access_key]):
        logger.warning("AWS credentials not found at kv/data/providers/aws. AWS Bedrock will not be available.")
        _bedrock_client_initialized = True  # Mark as attempted to avoid retrying
        return

    try:
        _aws_region = region
        _bedrock_runtime_client = boto3.client(
            "bedrock-runtime",
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=region,
        )
        _bedrock_client_initialized = True
        logger.info(f"AWS Bedrock runtime client initialized for region '{region}'.")
    except Exception as e:
        logger.error(f"Failed to initialize AWS Bedrock client: {e}")
        _bedrock_client_initialized = True  # Mark as attempted


async def invoke_aws_bedrock_chat_completions(
    task_id: str,
    model_id: str,
    messages: List[Dict[str, str]],
    secrets_manager: Optional[SecretsManager] = None,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    stream: bool = False,
) -> Union[UnifiedBedrockResponse, AsyncIterator[Union[str, ParsedBedrockToolCall, BedrockUsageMetadata]]]:
    """
    Unified entry point for all AWS Bedrock model inference via the Converse API.

    This function is auto-discovered by the provider registry (llm_utils.py) as the
    handler for server_id="aws_bedrock". Any provider YAML can add an aws_bedrock
    server entry and it will route here automatically.
    """
    # Ensure client is initialized
    if not _bedrock_client_initialized and secrets_manager:
        await _ensure_bedrock_client(secrets_manager)

    if not _bedrock_runtime_client:
        error_msg = "AWS Bedrock client not available. Check AWS credentials at kv/data/providers/aws."
        logger.error(f"[{task_id}] {error_msg}")
        if stream:
            raise ValueError(error_msg)
        return UnifiedBedrockResponse(task_id=task_id, model_id=model_id, success=False, error_message=error_msg)

    log_prefix = f"[{task_id}] Bedrock Converse ({model_id}):"
    logger.info(f"{log_prefix} Attempting chat completion. Stream: {stream}. Tools: {'Yes' if tools else 'No'}. Choice: {tool_choice}")

    try:
        # Convert messages to Converse format
        system_prompts, converse_messages = convert_messages_to_converse_format(messages)

        if not converse_messages:
            err_msg = "Message history is empty after processing."
            if stream:
                raise ValueError(err_msg)
            return UnifiedBedrockResponse(task_id=task_id, model_id=model_id, success=False, error_message=err_msg)

        # Build Converse API request
        request_kwargs: Dict[str, Any] = {
            "modelId": model_id,
            "messages": converse_messages,
            "inferenceConfig": {
                "temperature": temperature,
                "maxTokens": max_tokens or 16384,
            },
        }

        if system_prompts:
            request_kwargs["system"] = system_prompts

        tool_config = convert_tools_to_converse_format(tools)
        if tool_config:
            request_kwargs["toolConfig"] = tool_config
            tool_choice_config = convert_tool_choice_to_converse_format(tool_choice, has_tools=True)
            if tool_choice_config:
                request_kwargs["toolConfig"]["toolChoice"] = tool_choice_config

        logger.debug(f"{log_prefix} Converse API request prepared.")

        if stream:
            return _iterate_converse_stream(task_id, model_id, request_kwargs, messages, log_prefix, tools=tools)
        else:
            return await _process_converse_response(task_id, model_id, request_kwargs, messages, log_prefix, tools=tools)

    except Exception as e:
        err_msg = f"Error during Bedrock Converse request preparation: {e}"
        logger.error(f"{log_prefix} {err_msg}", exc_info=True)
        if stream:
            raise ValueError(err_msg)
        return UnifiedBedrockResponse(task_id=task_id, model_id=model_id, success=False, error_message=err_msg)


async def _process_converse_response(
    task_id: str,
    model_id: str,
    request_kwargs: Dict[str, Any],
    messages: List[Dict[str, str]],
    log_prefix: str,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> UnifiedBedrockResponse:
    """Process non-streaming response from Bedrock Converse API."""
    try:
        response = _bedrock_runtime_client.converse(**request_kwargs)
        logger.info(f"{log_prefix} Received non-streamed response from Bedrock Converse API.")

        # Calculate token breakdown estimate from input messages
        token_breakdown = calculate_token_breakdown(messages, model_id, tools=tools)

        # Parse usage from Converse response
        usage_data = response.get("usage", {})
        usage_metadata = BedrockUsageMetadata(
            input_tokens=usage_data.get("inputTokens", 0),
            output_tokens=usage_data.get("outputTokens", 0),
            total_tokens=usage_data.get("inputTokens", 0) + usage_data.get("outputTokens", 0),
            user_input_tokens=token_breakdown.get("user_input_tokens"),
            system_prompt_tokens=token_breakdown.get("system_prompt_tokens"),
        )

        raw_response = RawBedrockResponse(usage_metadata=usage_metadata)
        unified_resp = UnifiedBedrockResponse(
            task_id=task_id, model_id=model_id, success=True,
            raw_response=raw_response, usage=usage_metadata,
        )

        # Parse content blocks from the output message
        output_message = response.get("output", {}).get("message", {})
        content_blocks = output_message.get("content", [])

        text_content = []
        tool_calls = []

        for block in content_blocks:
            if "text" in block:
                text_content.append(block["text"])
            elif "toolUse" in block:
                tool_use = block["toolUse"]
                tool_calls.append({
                    "id": tool_use.get("toolUseId", ""),
                    "name": tool_use.get("name", ""),
                    "input": tool_use.get("input", {}),
                })

        if tool_calls:
            unified_resp.tool_calls_made = []
            for tc in tool_calls:
                args_dict = tc["input"]
                unified_resp.tool_calls_made.append(ParsedBedrockToolCall(
                    tool_call_id=tc["id"],
                    function_name=tc["name"],
                    function_arguments_parsed=args_dict,
                    function_arguments_raw=json.dumps(args_dict),
                ))
            logger.info(f"{log_prefix} Call resulted in {len(unified_resp.tool_calls_made)} tool call(s).")
        elif text_content:
            unified_resp.direct_message_content = "".join(text_content)
            raw_response.text = unified_resp.direct_message_content
            logger.info(f"{log_prefix} Call resulted in a direct message response.")
        else:
            unified_resp.error_message = "Response has no text or tool calls."
            logger.warning(f"{log_prefix} {unified_resp.error_message}")

        # Check stop reason for truncation
        stop_reason = response.get("stopReason", "")
        if stop_reason and stop_reason not in ("end_turn", "tool_use"):
            logger.warning(f"{log_prefix} Response ended with stopReason='{stop_reason}'")

        return unified_resp

    except ClientError as e_api:
        err_msg = format_aws_error_message(e_api)
        logger.error(f"{log_prefix} {err_msg}", exc_info=True)
        if is_aws_credential_error(e_api):
            logger.warning(
                f"{log_prefix} AWS credentials appear to be invalid or deactivated. "
                f"Error code: {e_api.response.get('Error', {}).get('Code', 'Unknown')}"
            )
        return UnifiedBedrockResponse(task_id=task_id, model_id=model_id, success=False, error_message=err_msg)
    except Exception as e:
        logger.error(f"{log_prefix} Failed to parse Bedrock Converse response: {e}", exc_info=True)
        return UnifiedBedrockResponse(task_id=task_id, model_id=model_id, success=False, error_message=str(e))


async def _iterate_converse_stream(
    task_id: str,
    model_id: str,
    request_kwargs: Dict[str, Any],
    messages: List[Dict[str, str]],
    log_prefix: str,
    tools: Optional[List[Dict[str, Any]]] = None,
) -> AsyncIterator[Union[str, ParsedBedrockToolCall, BedrockUsageMetadata]]:
    """Handle streaming response from Bedrock Converse Stream API."""
    logger.info(f"{log_prefix} Stream connection initiated.")

    output_buffer = ""
    usage = None
    current_tool_call: Optional[Dict[str, Any]] = None
    tool_input_json_buffer = ""

    try:
        response = _bedrock_runtime_client.converse_stream(**request_kwargs)

        # Calculate token breakdown estimate from input messages
        token_breakdown = calculate_token_breakdown(messages, model_id, tools=tools)

        stream = response.get("stream")
        if stream:
            for event in stream:
                # Text content delta
                if "contentBlockDelta" in event:
                    delta = event["contentBlockDelta"].get("delta", {})
                    if "text" in delta:
                        text_chunk = delta["text"]
                        output_buffer += text_chunk
                        yield text_chunk
                    elif "toolUse" in delta:
                        # Tool use input is streamed as JSON fragments
                        tool_input_json_buffer += delta["toolUse"].get("input", "")

                # Content block start (text or toolUse)
                elif "contentBlockStart" in event:
                    start = event["contentBlockStart"].get("start", {})
                    if "toolUse" in start:
                        tool_use = start["toolUse"]
                        current_tool_call = {
                            "id": tool_use.get("toolUseId", ""),
                            "name": tool_use.get("name", ""),
                        }
                        tool_input_json_buffer = ""

                # Content block stop — emit completed tool call
                elif "contentBlockStop" in event:
                    if current_tool_call:
                        try:
                            args = json.loads(tool_input_json_buffer) if tool_input_json_buffer else {}
                        except json.JSONDecodeError:
                            args = {}
                            logger.warning(f"{log_prefix} Failed to parse tool input JSON: {tool_input_json_buffer[:100]}")

                        parsed_tool_call = ParsedBedrockToolCall(
                            tool_call_id=current_tool_call["id"],
                            function_name=current_tool_call["name"],
                            function_arguments_parsed=args,
                            function_arguments_raw=tool_input_json_buffer or "{}",
                        )
                        logger.info(f"{log_prefix} Yielding tool call from stream: {current_tool_call['name']}")
                        yield parsed_tool_call
                        current_tool_call = None
                        tool_input_json_buffer = ""

                # Message stop — check stop reason
                elif "messageStop" in event:
                    stop_reason = event["messageStop"].get("stopReason", "")
                    if stop_reason and stop_reason not in ("end_turn", "tool_use"):
                        logger.warning(f"{log_prefix} Response ended with stopReason='{stop_reason}'")
                        if stop_reason == "max_tokens":
                            yield "\n\n---\n*This response was cut short because it reached the model's maximum output length. You can ask the AI to continue.*"

                # Metadata with usage
                elif "metadata" in event:
                    usage_data = event["metadata"].get("usage", {})
                    if usage_data:
                        usage = BedrockUsageMetadata(
                            input_tokens=usage_data.get("inputTokens", 0),
                            output_tokens=usage_data.get("outputTokens", 0),
                            total_tokens=usage_data.get("inputTokens", 0) + usage_data.get("outputTokens", 0),
                            user_input_tokens=token_breakdown.get("user_input_tokens"),
                            system_prompt_tokens=token_breakdown.get("system_prompt_tokens"),
                        )

        # Yield final usage information
        if usage:
            yield usage
        else:
            # Estimate usage if not provided
            logger.warning(f"{log_prefix} Stream finished without usage data. Estimating tokens with tiktoken.")
            try:
                encoding = tiktoken.get_encoding("cl100k_base")
                input_text = ""
                for msg in messages:
                    msg_content = msg.get("content", "")
                    if isinstance(msg_content, str):
                        input_text += msg_content
                estimated_input = len(encoding.encode(input_text))
                estimated_output = len(encoding.encode(output_buffer))
                usage = BedrockUsageMetadata(
                    input_tokens=estimated_input,
                    output_tokens=estimated_output,
                    total_tokens=estimated_input + estimated_output,
                    user_input_tokens=token_breakdown.get("user_input_tokens"),
                    system_prompt_tokens=token_breakdown.get("system_prompt_tokens"),
                )
                yield usage
            except Exception as e:
                logger.error(f"{log_prefix} Failed to estimate tokens with tiktoken: {e}", exc_info=True)

        logger.info(f"{log_prefix} Stream finished.")

    except ClientError as e:
        err_msg = format_aws_error_message(e)
        logger.error(f"{log_prefix} {err_msg}", exc_info=True)
        if is_aws_credential_error(e):
            logger.warning(
                f"{log_prefix} AWS credentials appear to be invalid or deactivated during streaming. "
                f"Error code: {e.response.get('Error', {}).get('Code', 'Unknown')}"
            )
        raise IOError(err_msg) from e
    except Exception as e_stream:
        err_msg = f"Unexpected error during Bedrock Converse streaming: {e_stream}"
        logger.error(f"{log_prefix} {err_msg}", exc_info=True)
        raise IOError(f"Bedrock Converse Streaming Error: {e_stream}") from e_stream
