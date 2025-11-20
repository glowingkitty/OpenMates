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


def _sanitize_schema_for_llm_providers(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively sanitizes a JSON schema to remove fields that LLM providers don't accept.
    
    Many LLM providers (Cerebras, OpenAI, OpenRouter, etc.) reject schemas with 
    'minimum' and 'maximum' fields for integer types, even though these are valid 
    JSON Schema fields. This function removes these fields to ensure compatibility.
    
    Note: The original schema (with min/max) is kept in app.yml and used for
    validation when we receive tool call arguments from the LLM.
    
    Args:
        schema: The JSON schema dictionary to sanitize
        
    Returns:
        A sanitized copy of the schema with minimum/maximum fields removed from integer properties
    """
    if not isinstance(schema, dict):
        return schema
    
    # Create a copy to avoid modifying the original
    sanitized = schema.copy()
    
    # If this is a property definition with type 'integer', remove minimum/maximum
    if sanitized.get("type") == "integer":
        # Remove minimum and maximum fields (LLM providers don't accept them)
        sanitized.pop("minimum", None)
        sanitized.pop("maximum", None)
    
    # Recursively sanitize nested structures
    if "properties" in sanitized:
        sanitized["properties"] = {
            key: _sanitize_schema_for_llm_providers(value)
            for key, value in sanitized["properties"].items()
        }
    
    if "items" in sanitized:
        sanitized["items"] = _sanitize_schema_for_llm_providers(sanitized["items"])
    
    if "allOf" in sanitized:
        sanitized["allOf"] = [
            _sanitize_schema_for_llm_providers(item) for item in sanitized["allOf"]
        ]
    
    if "anyOf" in sanitized:
        sanitized["anyOf"] = [
            _sanitize_schema_for_llm_providers(item) for item in sanitized["anyOf"]
        ]
    
    if "oneOf" in sanitized:
        sanitized["oneOf"] = [
            _sanitize_schema_for_llm_providers(item) for item in sanitized["oneOf"]
        ]
    
    return sanitized


def _map_tools_to_openai_format(tools: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """
    Maps the internal tool format to OpenAI's expected format.
    
    Also sanitizes tool schemas to remove fields that LLM providers don't accept
    (e.g., minimum/maximum for integer types). The original schemas in app.yml
    are preserved for validation purposes.
    
    Args:
        tools: List of tool definitions in internal format
        
    Returns:
        List of tool definitions in OpenAI format with sanitized schemas, or None if no valid tools
    """
    if not tools:
        return None
    
    # Sanitize each tool's schema before returning
    # This removes minimum/maximum fields from integer properties that LLM providers reject
    sanitized_tools = []
    for tool in tools:
        if not isinstance(tool, dict) or "function" not in tool:
            # Skip invalid tools
            sanitized_tools.append(tool)
            continue
        
        # Create a copy of the tool
        sanitized_tool = tool.copy()
        sanitized_function = tool["function"].copy()
        
        # Sanitize the parameters schema
        if "parameters" in sanitized_function:
            sanitized_function["parameters"] = _sanitize_schema_for_llm_providers(
                sanitized_function["parameters"]
            )
        
        sanitized_tool["function"] = sanitized_function
        sanitized_tools.append(sanitized_tool)
    
    return sanitized_tools