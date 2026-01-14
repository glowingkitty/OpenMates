# backend/apps/ai/llm_providers/types.py
"""
Unified types for thinking/reasoning models across all LLM providers.

This module provides provider-agnostic types for handling thinking content
from models like Google Gemini (thinking), Anthropic Claude (extended thinking),
and OpenAI o-series (internal reasoning - not exposed).

Design Decision: Function calls do NOT happen during thinking.
- Google Gemini: Thinking parts are separate from function calls (default)
- Anthropic: We don't use interleaved-thinking-2025-05-14 beta header
- OpenAI: Reasoning is internal/hidden, function calls happen after

This means thinking content is always pure text (no embed references).
"""

from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel


class StreamChunkType(Enum):
    """
    Types of stream chunks that can be yielded during LLM streaming.
    
    TEXT: Regular response text (final answer)
    THINKING: Thinking/reasoning content from models that expose it
    TOOL_CALL: Function/tool call request (happens AFTER thinking completes)
    THINKING_SIGNATURE: Cryptographic signature for thinking verification (Anthropic/Gemini)
    THINKING_REDACTED: Redacted thinking content (Anthropic safety feature)
    USAGE: Token usage metadata
    """
    TEXT = "text"
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    THINKING_SIGNATURE = "thinking_signature"
    THINKING_REDACTED = "thinking_redacted"
    USAGE = "usage"


class UnifiedStreamChunk(BaseModel):
    """
    Provider-agnostic stream chunk for thinking models.
    
    This unified type allows the stream consumer to handle thinking content
    consistently across all providers (Google Gemini, Anthropic Claude, etc.)
    
    Attributes:
        type: The type of this stream chunk
        content: Text content (for TEXT or THINKING types)
        tool_call: Tool call data (for TOOL_CALL type) - any parsed tool call type
        signature: Thinking signature for verification (for THINKING_SIGNATURE type)
        usage: Token usage metadata (for USAGE type)
        
    Usage:
        Yield UnifiedStreamChunk instances from provider clients when thinking
        content is detected. The stream consumer will route these to the
        appropriate Redis channel (main response vs thinking).
    """
    type: StreamChunkType
    content: Optional[str] = None
    tool_call: Optional[Any] = None  # ParsedGoogleToolCall, ParsedAnthropicToolCall, etc.
    signature: Optional[str] = None
    usage: Optional[Dict[str, int]] = None
    
    class Config:
        # Allow arbitrary types for tool_call field
        arbitrary_types_allowed = True


class ThinkingMetadata(BaseModel):
    """
    Metadata about thinking content for a message.
    
    This is stored alongside the message and used for:
    - UI display (has_thinking flag for showing thinking section)
    - Cost tracking (thinking_token_count)
    - Multi-turn conversations (signature for verification)
    
    Attributes:
        has_thinking: Whether the message has thinking content
        thinking_token_count: Number of tokens used for thinking
        thinking_signature: Provider signature for verification
    """
    has_thinking: bool = False
    thinking_token_count: int = 0
    thinking_signature: Optional[str] = None


# Type alias for thinking content that will be streamed
ThinkingContent = str
