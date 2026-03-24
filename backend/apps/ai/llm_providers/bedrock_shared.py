# backend/apps/ai/llm_providers/bedrock_shared.py
# Shared utilities and models for AWS Bedrock Converse API.
#
# This module provides provider-agnostic types and conversion functions for
# the Bedrock Converse API, which works uniformly across all Bedrock models
# (Anthropic Claude, Mistral, Meta Llama, Cohere, etc.).
#
# Architecture: docs/architecture/ai/ai-model-selection.md

import logging
import json
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


# --- Pydantic Models for Structured Bedrock Response ---

class BedrockUsageMetadata(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int
    user_input_tokens: Optional[int] = None
    system_prompt_tokens: Optional[int] = None


class ParsedBedrockToolCall(BaseModel):
    tool_call_id: str
    function_name: str
    function_arguments_raw: str
    function_arguments_parsed: Dict[str, Any]
    parsing_error: Optional[str] = None


class RawBedrockResponse(BaseModel):
    text: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    usage_metadata: Optional[BedrockUsageMetadata] = None


class UnifiedBedrockResponse(BaseModel):
    task_id: str
    model_id: str
    success: bool = False
    error_message: Optional[str] = None
    direct_message_content: Optional[str] = None
    tool_calls_made: Optional[List[ParsedBedrockToolCall]] = None
    raw_response: Optional[RawBedrockResponse] = None
    usage: Optional[BedrockUsageMetadata] = None


# --- AWS Credential Error Detection ---

CREDENTIAL_ERROR_CODES = frozenset([
    'UnrecognizedClientException',
    'InvalidUserID.NotFound',
    'InvalidClientTokenId',
    'SignatureDoesNotMatch',
    'InvalidAccessKeyId',
    'AccessDenied',
    'InvalidSecurity',
    'TokenRefreshRequired',
])


def is_aws_credential_error(client_error: ClientError) -> bool:
    """Check if a ClientError is related to AWS credentials/authentication."""
    error_code = client_error.response.get('Error', {}).get('Code', '')
    return error_code in CREDENTIAL_ERROR_CODES


def format_aws_error_message(client_error: ClientError) -> str:
    """Format a clear error message for AWS errors, with special handling for credential issues."""
    error_code = client_error.response.get('Error', {}).get('Code', 'Unknown')
    error_message = client_error.response.get('Error', {}).get('Message', str(client_error))

    if is_aws_credential_error(client_error):
        return (
            f"AWS Bedrock authentication/credential error: {error_code} - {error_message}. "
            f"The AWS credentials (access key ID, secret access key, or security token) "
            f"are invalid, expired, or have been deactivated. Please verify the credentials in the secrets manager."
        )
    return f"AWS Bedrock API error ({error_code}): {error_message}"


# --- Message Conversion: OpenAI format → Converse API format ---

def convert_messages_to_converse_format(
    messages: List[Dict[str, Any]]
) -> tuple[Optional[List[Dict[str, Any]]], List[Dict[str, Any]]]:
    """
    Convert OpenAI-format messages to Bedrock Converse API format.

    Returns:
        Tuple of (system_prompts, converse_messages) where:
        - system_prompts: List of system prompt blocks for the Converse API, or None
        - converse_messages: List of messages in Converse format
    """
    system_prompts = None
    converse_messages = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        # Extract system prompt(s)
        if role == "system":
            if system_prompts is None:
                system_prompts = []
            system_prompts.append({"text": content})
            continue

        # Handle tool results — Converse API uses "user" role with toolResult blocks
        if role == "tool":
            tool_call_id = msg.get("tool_call_id", "")
            tool_content = _convert_tool_result_content(content)
            converse_messages.append({
                "role": "user",
                "content": [{
                    "toolResult": {
                        "toolUseId": tool_call_id,
                        "content": tool_content,
                    }
                }]
            })
            continue

        # Handle assistant messages with tool calls
        if role == "assistant":
            assistant_content = _convert_assistant_content(msg)
            if assistant_content:
                converse_messages.append({
                    "role": "assistant",
                    "content": assistant_content,
                })
            continue

        # Regular user/assistant text messages
        if isinstance(content, str):
            converse_messages.append({
                "role": role,
                "content": [{"text": content}] if content else [{"text": " "}],
            })
        elif isinstance(content, list):
            # Multimodal content blocks
            converse_content = _convert_multimodal_content(content)
            converse_messages.append({
                "role": role,
                "content": converse_content,
            })

    return system_prompts, converse_messages


def _convert_tool_result_content(content: Any) -> List[Dict[str, Any]]:
    """Convert tool result content to Converse format."""
    if isinstance(content, list):
        # Multimodal tool result (images + text from skills)
        result = []
        for block in content:
            block_type = block.get("type", "")
            if block_type == "text":
                result.append({"text": block.get("text", "")})
            elif block_type == "image_url":
                image_block = _convert_image_url_to_converse(block)
                if image_block:
                    result.append(image_block)
            else:
                logger.warning(f"[bedrock_shared] Unknown content block type in tool result: {block_type}")
        return result if result else [{"text": ""}]
    # Plain text
    return [{"text": str(content) if content else ""}]


def _convert_assistant_content(msg: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """Convert assistant message content to Converse format, including tool_calls."""
    content_blocks = []

    # Add text content
    text_content = msg.get("content")
    if text_content and isinstance(text_content, str):
        content_blocks.append({"text": text_content})

    # Add tool use blocks from OpenAI-format tool_calls
    tool_calls = msg.get("tool_calls", [])
    for tc in tool_calls:
        func = tc.get("function", {})
        args_str = func.get("arguments", "{}")
        try:
            args = json.loads(args_str) if isinstance(args_str, str) else args_str
        except json.JSONDecodeError:
            args = {}
        content_blocks.append({
            "toolUse": {
                "toolUseId": tc.get("id", ""),
                "name": func.get("name", ""),
                "input": args,
            }
        })

    return content_blocks if content_blocks else None


def _convert_multimodal_content(content_blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert multimodal content blocks to Converse format."""
    result = []
    for block in content_blocks:
        block_type = block.get("type", "")
        if block_type == "text":
            result.append({"text": block.get("text", "")})
        elif block_type == "image_url":
            image_block = _convert_image_url_to_converse(block)
            if image_block:
                result.append(image_block)
    return result if result else [{"text": " "}]


def _convert_image_url_to_converse(block: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Convert an OpenAI image_url block to Converse image format."""
    image_url_data = block.get("image_url", {})
    url = image_url_data.get("url", "")

    if url.startswith("data:") and ";base64," in url:
        header, b64_data = url.split(";base64,", 1)
        mime_type = header[len("data:"):]  # e.g. "image/webp"
        # Converse API format values: "png", "jpeg", "gif", "webp"
        format_map = {
            "image/png": "png",
            "image/jpeg": "jpeg",
            "image/jpg": "jpeg",
            "image/gif": "gif",
            "image/webp": "webp",
        }
        img_format = format_map.get(mime_type, "png")
        return {
            "image": {
                "format": img_format,
                "source": {"bytes": b64_data},
            }
        }

    logger.warning(f"[bedrock_shared] image_url block has non-data URL (not supported): {url[:60]}")
    return {"text": f"[image: {url[:60]}]"}


# --- Tool Conversion: OpenAI format → Converse toolConfig ---

def convert_tools_to_converse_format(
    tools: Optional[List[Dict[str, Any]]]
) -> Optional[Dict[str, Any]]:
    """
    Convert OpenAI-format tools to Bedrock Converse API toolConfig.

    Returns:
        Converse API toolConfig dict, or None if no tools provided.
    """
    if not tools:
        return None

    tool_specs = []
    for tool_def in tools:
        if tool_def.get("type") == "function":
            func = tool_def.get("function", {})
            tool_specs.append({
                "toolSpec": {
                    "name": func.get("name"),
                    "description": func.get("description", ""),
                    "inputSchema": {
                        "json": func.get("parameters", {}),
                    }
                }
            })

    if not tool_specs:
        return None

    return {"tools": tool_specs}


def convert_tool_choice_to_converse_format(
    tool_choice: Optional[str],
    has_tools: bool
) -> Optional[Dict[str, Any]]:
    """
    Convert OpenAI-format tool_choice to Converse API toolChoice.

    Converse API supports:
    - {"auto": {}} — model decides (default)
    - {"any": {}} — model must use a tool
    - {"tool": {"name": "tool_name"}} — force specific tool
    """
    if not has_tools or not tool_choice or tool_choice == "auto":
        return None

    if tool_choice == "required":
        return {"any": {}}
    if tool_choice == "none":
        return None

    # Specific tool name
    return {"tool": {"name": tool_choice}}
