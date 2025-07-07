# backend/apps/ai/llm_providers/anthropic_shared.py
# Shared utilities and models for Anthropic implementations

import logging
from typing import Dict, Any, List, Optional, Union
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Caching configuration
CACHE_TOKEN_THRESHOLD = 1024  # Minimum tokens required for caching
CHARS_PER_TOKEN_ESTIMATE = 4  # Conservative estimate for token counting

# --- Pydantic Models for Structured Anthropic Response ---

class AnthropicUsageMetadata(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cache_creation_input_tokens: Optional[int] = 0
    cache_read_input_tokens: Optional[int] = 0

class RawAnthropicChatCompletionResponse(BaseModel):
    text: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    usage_metadata: Optional[AnthropicUsageMetadata] = None

class ParsedAnthropicToolCall(BaseModel):
    tool_call_id: str
    function_name: str
    function_arguments_raw: str
    function_arguments_parsed: Dict[str, Any]
    parsing_error: Optional[str] = None

class UnifiedAnthropicResponse(BaseModel):
    task_id: str
    model_id: str
    success: bool = False
    error_message: Optional[str] = None
    direct_message_content: Optional[str] = None
    tool_calls_made: Optional[List[ParsedAnthropicToolCall]] = None
    raw_response: Optional[RawAnthropicChatCompletionResponse] = None
    usage: Optional[AnthropicUsageMetadata] = None


def _should_cache_content(content: str) -> bool:
    """Determine if content should be cached based on token threshold"""
    if not content:
        return False
    
    # Conservative estimation: ~4 chars per token
    estimated_tokens = len(content) / CHARS_PER_TOKEN_ESTIMATE
    return estimated_tokens >= CACHE_TOKEN_THRESHOLD


def _map_tools_to_anthropic_format(tools: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    if not tools:
        return None
    
    anthropic_tools = []
    for tool_def in tools:
        if tool_def.get("type") == "function":
            func = tool_def.get("function", {})
            anthropic_tools.append({
                "name": func.get("name"),
                "description": func.get("description"),
                "input_schema": func.get("parameters", {})
            })
    
    return anthropic_tools if anthropic_tools else None


def _prepare_system_with_caching(system_prompt: str) -> Union[str, List[Dict[str, Any]]]:
    """Prepare system prompt with caching if it meets threshold"""
    if not system_prompt:
        return system_prompt
    
    if _should_cache_content(system_prompt):
        logger.debug(f"System prompt ({len(system_prompt)} chars) will be cached.")
        return [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"}
            }
        ]
    else:
        logger.debug(f"System prompt ({len(system_prompt)} chars) too short for caching.")
        return system_prompt


def _prepare_messages_with_caching(messages: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Prepare messages with selective caching for content over threshold"""
    anthropic_messages = []
    
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        
        # Handle tool responses - convert to user message with tool result
        if role == "tool":
            anthropic_messages.append({
                "role": "user",
                "content": f"Tool result: {content}"
            })
            continue
        
        # Apply selective caching based on content length
        if _should_cache_content(content):
            logger.debug(f"Message from {role} ({len(content)} chars) will be cached.")
            anthropic_messages.append({
                "role": role,
                "content": [
                    {
                        "type": "text",
                        "text": content,
                        "cache_control": {"type": "ephemeral"}
                    }
                ]
            })
        else:
            logger.debug(f"Message from {role} ({len(content)} chars) too short for caching.")
            anthropic_messages.append({
                "role": role,
                "content": content
            })
            
    return anthropic_messages


def _prepare_messages_for_anthropic(messages: List[Dict[str, str]]) -> (Optional[Union[str, List[Dict[str, Any]]]], List[Dict[str, Any]]):
    """Prepare messages for Anthropic API with caching support"""
    system_prompt = None
    processed_messages = list(messages)
    
    # Extract system prompt if present
    if processed_messages and processed_messages[0].get("role") == "system":
        system_prompt_content = processed_messages.pop(0)["content"]
        system_prompt = _prepare_system_with_caching(system_prompt_content)

    # Process remaining messages with selective caching
    anthropic_messages = _prepare_messages_with_caching(processed_messages)
            
    return system_prompt, anthropic_messages
