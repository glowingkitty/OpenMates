# Thinking Models Architecture

> **Status**: ✅ Implemented (Phase 1-3 complete)

## Overview

This document outlines the architecture for supporting "thinking" or "reasoning" models across multiple LLM providers (Google Gemini, Anthropic Claude, and OpenAI o-series). The goal is to create a provider-agnostic system that:

1. Streams thinking content in real-time (paragraph by paragraph)
2. Stores thinking content securely (encrypted) alongside message content
3. Displays a collapsible "Thinking..." UI that expands to show full reasoning
4. Preserves thinking signatures for verification

### Design Decision: No Function Calls During Thinking

**We intentionally do NOT enable function calls during the thinking process.** All providers support a mode where thinking completes first, then function calls happen in the regular output:

- **Google Gemini**: Thinking parts are separate from function calls (default behavior)
- **Anthropic Claude**: Don't use `interleaved-thinking-2025-05-14` beta header → thinking completes before tool use
- **OpenAI o-series**: Internal reasoning completes before function calls (only mode available)

This simplifies the architecture significantly:
- Thinking content is **pure text** (no embed references)
- Function calls only happen in the **regular response** phase
- Existing embed handling remains unchanged
- Simpler UI rendering (thinking is just markdown, no embedded skills)

---

## Provider Comparison

### Google Gemini (2.5/3 series)
- **Thinking Config**: `thinking_config` with `thinking_budget` and `include_thoughts`
- **Response Format**: `Part` objects with `.thought` boolean attribute
- **Streaming**: Thinking parts streamed separately from text parts
- **Function Calls**: Separate from thinking parts (NOT interleaved within thinking)
- **Signature**: `thought_signature` field on thinking parts

### Anthropic Claude (3.7+/4 series)
- **Thinking Config**: `thinking` object with `type: "enabled"` and `budget_tokens`
- **Response Format**: `thinking` content blocks followed by `text` content blocks
- **Streaming**: `thinking_delta` events for thinking, `text_delta` for response
- **Function Calls**: Happen AFTER thinking completes (we don't use interleaved thinking beta)
- **Signature**: `signature` field on thinking blocks for verification
- **Redaction**: `redacted_thinking` blocks when content flagged by safety systems

### OpenAI o-series (o1, o3, o4-mini)
- **Thinking Config**: Automatic (no explicit enable)
- **Response Format**: Reasoning tokens are internal/hidden
- **Streaming**: Reasoning is NOT exposed in API output
- **Function Calls**: Supported, but reasoning process is opaque
- **Signature**: N/A (reasoning not exposed)

---

## Architecture Design

### 1. Data Model Changes

#### Message Model (Frontend: `types/chat.ts`)

```typescript
export interface Message {
  // ... existing fields ...
  
  // NEW: Thinking/Reasoning fields (encrypted for zero-knowledge)
  encrypted_thinking_content?: string;      // Encrypted thinking markdown (streamed)
  encrypted_thinking_signature?: string;    // Encrypted signature for verification (Anthropic/Gemini)
  
  // Decrypted fields (computed on-demand, never stored)
  thinking_content?: string;                // Decrypted thinking markdown
  thinking_signature?: string;              // Decrypted signature
  
  // Metadata (not encrypted - for UI rendering and cost tracking)
  has_thinking?: boolean;                   // Quick check if message has thinking content
  thinking_token_count?: number;            // Token count for thinking (for cost tracking)
}
```

**Note**: Since function calls don't happen during thinking, we don't need embed-related fields in thinking. The `EmbedStoreEntry` interface remains unchanged.

### 2. Backend Streaming Architecture

#### Unified Thinking Stream Format

Create a provider-agnostic stream chunk type that all providers normalize to:

```python
# backend/apps/ai/llm_providers/types.py

from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

class StreamChunkType(Enum):
    TEXT = "text"                    # Final response text
    THINKING = "thinking"            # Thinking/reasoning content
    TOOL_CALL = "tool_call"          # Function/tool call
    THINKING_SIGNATURE = "signature" # Thinking signature (Anthropic/Gemini)
    USAGE = "usage"                  # Token usage metadata

class UnifiedStreamChunk(BaseModel):
    """Provider-agnostic stream chunk for thinking models."""
    type: StreamChunkType
    content: Optional[str] = None           # Text content (for TEXT/THINKING)
    tool_call: Optional[Any] = None         # Tool call data (for TOOL_CALL)
    signature: Optional[str] = None         # Signature (for THINKING_SIGNATURE)
    usage: Optional[Dict[str, int]] = None  # Usage data (for USAGE)
```

#### Modified Stream Consumer

```python
# backend/apps/ai/tasks/stream_consumer.py (conceptual)

async def _consume_main_processing_stream(...):
    """
    Modified to handle thinking streams separately from response streams.
    
    Stream Flow (simplified - no tool calls during thinking):
    1. Receive THINKING chunks → publish to thinking Redis channel
    2. Receive THINKING_SIGNATURE → store with message
    3. Thinking completes
    4. Receive TOOL_CALL → execute (existing handling, happens AFTER thinking)
    5. Receive TEXT chunks → publish to main response Redis channel
    """
    
    thinking_buffer = []
    thinking_signature = None
    thinking_complete = False
    
    async for chunk in llm_stream:
        if isinstance(chunk, UnifiedStreamChunk):
            if chunk.type == StreamChunkType.THINKING:
                thinking_buffer.append(chunk.content)
                # Publish thinking chunk to separate Redis channel
                await publish_thinking_chunk(
                    task_id=task_id,
                    thinking_content=chunk.content
                )
                
            elif chunk.type == StreamChunkType.THINKING_SIGNATURE:
                thinking_signature = chunk.signature
                thinking_complete = True
                # Publish thinking complete event
                await publish_thinking_complete(task_id, thinking_signature)
                
            elif chunk.type == StreamChunkType.TOOL_CALL:
                # Tool calls only happen AFTER thinking is complete
                # Use existing tool call handling (unchanged)
                yield chunk
                
            elif chunk.type == StreamChunkType.TEXT:
                # Normal response text - existing handling
                yield chunk.content
```

### 3. Redis Streaming Channels

Add separate channel for thinking content:

```python
# Channel naming convention
MAIN_RESPONSE_CHANNEL = f"chat_stream::{chat_id}"           # Existing
THINKING_CHANNEL = f"chat_stream_thinking::{chat_id}"       # NEW

# Thinking chunk payload (streamed paragraph by paragraph)
{
    "type": "thinking_chunk",
    "task_id": "...",
    "content": "Let me analyze this step by step..."
}

# Thinking complete payload
{
    "type": "thinking_complete",
    "task_id": "...",
    "signature": "...",           # Provider signature for verification
    "total_tokens": 1234          # Token count for cost tracking
}
```

### 4. Frontend Architecture

#### WebSocket Handler Updates

```typescript
// chatSyncServiceHandlersAI.ts (conceptual)

// Subscribe to thinking channel alongside main response channel
async function subscribeToAIStream(chatId: string, taskId: string) {
    // Existing main response subscription
    subscribeToChannel(`chat_stream::${chatId}`, handleMainResponse);
    
    // NEW: Thinking subscription
    subscribeToChannel(`chat_stream_thinking::${chatId}`, handleThinkingResponse);
}

function handleThinkingResponse(payload: ThinkingPayload) {
    if (payload.type === 'thinking_chunk') {
        // Append to thinking buffer in message state
        appendToMessageThinking(payload.task_id, payload.content);
    } else if (payload.type === 'thinking_complete') {
        // Finalize thinking - store signature and token count
        finalizeMessageThinking(payload.task_id, {
            signature: payload.signature,
            totalTokens: payload.total_tokens
        });
    }
}
```

#### Thinking UI Component

```svelte
<!-- ThinkingSection.svelte -->
<script lang="ts">
    import { slide } from 'svelte/transition';
    import ReadOnlyMessage from './ReadOnlyMessage.svelte';
    import Icon from './Icon.svelte';
    import { parse_message } from '../message_parsing/parser';
    
    let {
        thinkingContent = '',
        isStreaming = false,
        isExpanded = false
    }: {
        thinkingContent: string;
        isStreaming: boolean;
        isExpanded: boolean;
    } = $props();
    
    // Generate summary text for collapsed state
    const collapsedSummary = $derived(() => {
        if (isStreaming) return 'Thinking...';
        return 'Thought process';
    });
    
    // Parse thinking content for display (plain markdown, no embeds)
    const parsedThinkingContent = $derived(() => {
        if (!thinkingContent) return null;
        return parse_message(thinkingContent, 'read', { unifiedParsingEnabled: true });
    });
</script>

<div class="thinking-section" class:streaming={isStreaming}>
    <!-- Collapsed Header (always visible) -->
    <button 
        class="thinking-header"
        onclick={() => isExpanded = !isExpanded}
        aria-expanded={isExpanded}
    >
        <Icon name={isStreaming ? 'loader' : 'brain'} class="thinking-icon" />
        <span class="thinking-summary">{collapsedSummary}</span>
        <Icon name={isExpanded ? 'chevron-up' : 'chevron-down'} class="expand-icon" />
    </button>
    
    <!-- Expanded Content -->
    {#if isExpanded && parsedThinkingContent}
        <div class="thinking-content" transition:slide>
            <ReadOnlyMessage 
                content={parsedThinkingContent}
                isStreaming={isStreaming}
            />
        </div>
    {/if}
</div>

<style>
    .thinking-section {
        margin-bottom: 12px;
        border-radius: 8px;
        background: var(--color-surface-secondary);
        border: 1px solid var(--color-border-subtle);
        overflow: hidden;
    }
    
    .thinking-section.streaming {
        border-color: var(--color-accent-secondary);
    }
    
    .thinking-header {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 10px 14px;
        width: 100%;
        background: transparent;
        border: none;
        cursor: pointer;
        color: var(--color-text-secondary);
        font-size: 13px;
    }
    
    .thinking-header:hover {
        background: var(--color-surface-hover);
    }
    
    .thinking-icon {
        width: 16px;
        height: 16px;
        opacity: 0.7;
    }
    
    .streaming .thinking-icon {
        animation: spin 1s linear infinite;
    }
    
    .thinking-summary {
        flex: 1;
        text-align: left;
    }
    
    .thinking-content {
        padding: 0 14px 14px;
        border-top: 1px solid var(--color-border-subtle);
        background: var(--color-surface-primary);
    }
    
    @keyframes spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
    }
</style>
```

#### ChatMessage Integration

```svelte
<!-- ChatMessage.svelte (additions) -->
<script lang="ts">
    // ... existing code ...
    
    let {
        // ... existing props ...
        thinkingContent = undefined,
        isThinkingStreaming = false
    }: {
        // ... existing types ...
        thinkingContent?: string;
        isThinkingStreaming?: boolean;
    } = $props();
    
    let thinkingExpanded = $state(false);
</script>

<!-- In template, before main message content -->
{#if thinkingContent || isThinkingStreaming}
    <ThinkingSection
        {thinkingContent}
        isStreaming={isThinkingStreaming}
        bind:isExpanded={thinkingExpanded}
    />
{/if}

<!-- Existing message content -->
<div class="chat-message-text">
    <!-- ... existing ReadOnlyMessage ... -->
</div>
```

### 5. Provider-Specific Implementations

#### Google Gemini Client

```python
# backend/apps/ai/llm_providers/google_client.py

async def _iterate_stream_response() -> AsyncIterator[Union[str, UnifiedStreamChunk, ...]]:
    """Modified to yield UnifiedStreamChunk for thinking parts."""
    
    async for chunk in stream_iterator:
        if chunk.candidates:
            for part in chunk.candidates[0].content.parts:
                # Check if this is a thinking part
                if getattr(part, 'thought', False):
                    yield UnifiedStreamChunk(
                        type=StreamChunkType.THINKING,
                        content=part.text
                    )
                elif part.text:
                    # Regular text - yield as string (unchanged from current behavior)
                    yield part.text
                    
        # Handle thinking signature if present
        if hasattr(chunk, 'thought_signature') and chunk.thought_signature:
            yield UnifiedStreamChunk(
                type=StreamChunkType.THINKING_SIGNATURE,
                signature=chunk.thought_signature
            )
```

#### Anthropic Client

```python
# backend/apps/ai/llm_providers/anthropic_client.py

async def _iterate_stream_response() -> AsyncIterator[Union[str, UnifiedStreamChunk, ...]]:
    """
    Modified to handle Anthropic's thinking_delta events.
    NOTE: We do NOT use interleaved-thinking-2025-05-14 beta header,
    so tool calls only happen AFTER thinking completes.
    """
    
    async for event in stream_iterator:
        if event.type == 'content_block_delta':
            if event.delta.type == 'thinking_delta':
                yield UnifiedStreamChunk(
                    type=StreamChunkType.THINKING,
                    content=event.delta.thinking
                )
            elif event.delta.type == 'signature_delta':
                yield UnifiedStreamChunk(
                    type=StreamChunkType.THINKING_SIGNATURE,
                    signature=event.delta.signature
                )
            elif event.delta.type == 'text_delta':
                # Regular text - yield as string (unchanged)
                yield event.delta.text
```

#### OpenAI Client (o-series)

```python
# backend/apps/ai/llm_providers/openai_client.py

async def _iterate_openai_direct_stream() -> AsyncIterator[Union[str, UnifiedStreamChunk, ...]]:
    """
    OpenAI o-series models don't expose reasoning content.
    Reasoning happens internally before the response.
    We only track reasoning token counts from usage metadata for cost calculation.
    
    No changes needed for thinking support - just ensure we capture
    reasoning_tokens from usage metadata when available.
    """
    async for chunk in stream_resp:
        # Standard text handling (unchanged)
        if delta.content:
            yield delta.content
            
        # Capture reasoning tokens from usage metadata (for cost tracking)
        if hasattr(chunk, 'usage') and chunk.usage:
            reasoning_tokens = getattr(chunk.usage, 'reasoning_tokens', 0)
            if reasoning_tokens > 0:
                yield UnifiedStreamChunk(
                    type=StreamChunkType.USAGE,
                    usage={
                        'reasoning_tokens': reasoning_tokens,
                        'prompt_tokens': chunk.usage.prompt_tokens,
                        'completion_tokens': chunk.usage.completion_tokens
                    }
                )
```

### 6. Storage & Encryption

#### Directus Schema Update

```sql
-- Add thinking fields to messages collection
ALTER TABLE messages ADD COLUMN IF NOT EXISTS encrypted_thinking_content TEXT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS encrypted_thinking_signature TEXT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS has_thinking BOOLEAN DEFAULT FALSE;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS thinking_token_count INTEGER;
```

#### Encryption Flow

```typescript
// chatKeyManagement.ts (additions)

export async function encryptThinkingFields(
    dbInstance: ChatDatabaseInstance,
    message: Message,
    chatId: string
): Promise<Message> {
    const chatKey = getOrGenerateChatKey(dbInstance, chatId);
    const encryptedMessage = { ...message };
    
    // Encrypt thinking content
    if (message.thinking_content) {
        encryptedMessage.encrypted_thinking_content = 
            await encryptWithChatKey(message.thinking_content, chatKey);
    }
    delete encryptedMessage.thinking_content;
    
    // Encrypt thinking signature (required for multi-turn conversations)
    if (message.thinking_signature) {
        encryptedMessage.encrypted_thinking_signature = 
            await encryptWithChatKey(message.thinking_signature, chatKey);
    }
    delete encryptedMessage.thinking_signature;
    
    return encryptedMessage;
}
```

---

## Implementation Plan

### Phase 1: Backend Infrastructure
1. Create `UnifiedStreamChunk` types and enums in `backend/apps/ai/llm_providers/types.py`
2. Add thinking Redis channels to stream consumer
3. Modify Google Gemini client to yield thinking chunks (filter `part.thought=True`)
4. Update `stream_consumer.py` to publish thinking to separate channel

### Phase 2: Database & Storage
1. Add Directus schema migrations (4 new fields on messages)
2. Update IndexedDB schema (add thinking fields to messages)
3. Add thinking encryption/decryption to `chatKeyManagement.ts`

### Phase 3: Frontend UI
1. Create `ThinkingSection.svelte` component (collapsible, expandable)
2. Update `ChatMessage.svelte` to render thinking above response
3. Add WebSocket handlers for `chat_stream_thinking::` channel
4. Update message state management for thinking content streaming

### Phase 4: Anthropic Integration
1. Add Anthropic extended thinking support (enable thinking config)
2. Handle `thinking_delta` and `signature_delta` events in streaming
3. Handle `redacted_thinking` blocks gracefully

### Phase 5: OpenAI Integration
1. Track reasoning tokens from usage metadata for cost calculation
2. No UI changes needed (reasoning is internal/hidden)

### Phase 6: Testing & Polish
1. Add loading animation to thinking section during streaming
2. Test across all providers (Gemini, Anthropic, OpenAI)
3. Ensure signature preservation works for multi-turn conversations

---

## Key Considerations

### Streaming Behavior

- Stream thinking paragraph by paragraph (same as regular content)
- Use `aggregate_paragraphs()` for both thinking and response streams
- Thinking content is pure text (no embed references to handle)

### Signatures

- Anthropic requires signature verification when passing thinking blocks back
- Google may have similar `thought_signature` field
- Store signatures encrypted with message for multi-turn conversations

### Graceful Degradation

- **Non-thinking models**: No thinking UI shown (existing behavior unchanged)
- **OpenAI o-series**: No thinking UI (reasoning is internal) - just track token costs
- **Anthropic redacted thinking**: Show "[Some reasoning was hidden for safety reasons]"
- **Mid-stream failure**: Display partial thinking content with error indicator

---

## API Changes Summary

### New Redis Channels
- `chat_stream_thinking::{chat_id}` - Thinking content stream

### New Message Fields
- `encrypted_thinking_content` - Encrypted thinking markdown
- `encrypted_thinking_signature` - Encrypted provider signature (for multi-turn)
- `has_thinking` - Quick check flag (boolean)
- `thinking_token_count` - Token count for cost tracking

### No Changes to Embeds
Since function calls don't happen during thinking, embed handling remains unchanged.
