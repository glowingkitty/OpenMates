# backend/apps/ai/llm_providers/openai_shared.py
# Shared utilities and models for OpenAI implementations (including via OpenRouter)

import logging
from typing import Dict, Any, List, Optional, Union
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# --- Pydantic Models for Structured OpenAI Response ---

class OpenAIUsageMetadata(BaseModel):
    """
    Usage metadata for OpenAI API calls (including via OpenRouter).
    Tracks token counts for billing and monitoring.
    """
    input_tokens: int
    output_tokens: int
    total_tokens: int

class RawOpenAIChatCompletionResponse(BaseModel):
    """
    Raw response structure from OpenAI API.
    Maps directly to the JSON structure returned by the API.
    """
    text: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    usage_metadata: Optional[OpenAIUsageMetadata] = None

class ParsedOpenAIToolCall(BaseModel):
    """
    Structured representation of a tool call from OpenAI.
    Includes both raw arguments string and parsed arguments dict.
    """
    tool_call_id: str
    function_name: str
    function_arguments_raw: str
    function_arguments_parsed: Dict[str, Any]
    parsing_error: Optional[str] = None

class UnifiedOpenAIResponse(BaseModel):
    """
    Unified response object for OpenAI API calls.
    Provides a consistent interface regardless of streaming or non-streaming mode.
    """
    task_id: str
    model_id: str
    success: bool = False
    error_message: Optional[str] = None
    direct_message_content: Optional[str] = None
    tool_calls_made: Optional[List[ParsedOpenAIToolCall]] = None
    raw_response: Optional[RawOpenAIChatCompletionResponse] = None
    usage: Optional[OpenAIUsageMetadata] = None


def _map_tools_to_openai_format(tools: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """
    Maps the internal tool format to OpenAI's expected format.
    
    Args:
        tools: List of tool definitions in internal format
        
    Returns:
        List of tool definitions in OpenAI format, or None if no valid tools
    """
    if not tools:
        return None
    
    # Pass through as-is since our internal format matches OpenAI's format
    return tools