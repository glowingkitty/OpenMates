# backend/apps/ai/llm_providers/openai_shared.py
# Shared utilities and models for OpenAI implementations (including via OpenRouter)

import logging
from typing import Dict, Any, List, Optional, Union
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# --- Token Calculation Helpers ---

def calculate_token_breakdown(messages: List[Dict[str, Any]], model_id: str, tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, int]:
    """
    Calculate the breakdown of tokens between system prompt and user input.
    Provides estimates based on tiktoken encoding.
    """
    try:
        import tiktoken
        import json
        encoding = None
        try:
            # Try to get encoding for the specific model
            encoding = tiktoken.encoding_for_model(model_id)
        except Exception:
            # Fallback to common encodings
            for enc_name in ["o200k_base", "cl100k_base", "p50k_base"]:
                try:
                    encoding = tiktoken.get_encoding(enc_name)
                    break
                except Exception:
                    continue
        
        if not encoding:
            logger.warning(f"Could not find any suitable tiktoken encoding for model {model_id}")
            return {"system_prompt_tokens": 0, "user_input_tokens": 0}
        
        system_tokens = 0
        user_tokens = 0
        
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if not content:
                continue
            
            # Simple token count for content
            tokens = len(encoding.encode(str(content)))
            if role == "system":
                system_tokens += tokens
            else:
                # user, assistant (history), or tool
                user_tokens += tokens
        
        # Include tool definitions in system tokens if provided
        if tools:
            try:
                tools_json = json.dumps(tools)
                tool_tokens = len(encoding.encode(tools_json))
                system_tokens += tool_tokens
                logger.debug(f"Added {tool_tokens} tokens for tool definitions to system_prompt_tokens")
            except Exception as tool_err:
                logger.warning(f"Failed to calculate tool tokens: {tool_err}")
                
        logger.info(f"Token breakdown calculated for {model_id}: system={system_tokens}, user={user_tokens}")
        return {
            "system_prompt_tokens": system_tokens,
            "user_input_tokens": user_tokens
        }
    except Exception as e:
        logger.error(f"Error calculating token breakdown for {model_id}: {e}")
        return {"system_prompt_tokens": 0, "user_input_tokens": 0}

# --- Pydantic Models for Structured OpenAI Response ---

class OpenAIUsageMetadata(BaseModel):
    """
    Usage metadata for OpenAI API calls (including via OpenRouter).
    Tracks token counts for billing and monitoring.
    """
    input_tokens: int
    output_tokens: int
    total_tokens: int
    user_input_tokens: Optional[int] = None
    system_prompt_tokens: Optional[int] = None

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
    'minimum' and 'maximum' fields for integer and number types, even though these are valid 
    JSON Schema fields. This function removes these fields to ensure compatibility.
    
    Note: The original schema (with min/max) is kept in app.yml and used for
    validation when we receive tool call arguments from the LLM.
    
    Args:
        schema: The JSON schema dictionary to sanitize
        
    Returns:
        A sanitized copy of the schema with minimum/maximum fields removed from integer and number properties
    """
    if not isinstance(schema, dict):
        return schema
    
    # Create a copy to avoid modifying the original
    sanitized = schema.copy()
    
    # Convert type list (e.g., type: [string, integer]) to anyOf format
    # Some LLM providers (Cerebras, Google) don't support list types and require anyOf instead
    # This must be done BEFORE processing nested structures
    if isinstance(sanitized.get("type"), list):
        type_list = sanitized.pop("type")
        # Convert to anyOf format: anyOf: [{type: "string"}, {type: "integer"}]
        sanitized["anyOf"] = [{"type": t} for t in type_list if isinstance(t, str)]
        # After converting to anyOf, we still need to recursively sanitize the anyOf items
        # This will be handled by the anyOf processing below
    
    # If this is a property definition with type 'integer' or 'number', remove minimum/maximum
    # Cerebras and other providers reject schemas with minimum/maximum for both integer and number types
    if sanitized.get("type") in ("integer", "number"):
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