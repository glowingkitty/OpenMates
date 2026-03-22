# Thinking Models Architecture

Status: implemented and active.

## Purpose

This document describes how OpenMates handles model reasoning/thinking streams across providers, how that data is surfaced in chat, and where the source-of-truth implementation lives.

The current behavior is:

- Thinking content is streamed as provider chunks as they arrive.
- Thinking content is not paragraph-buffered before publish.
- Main assistant text still uses paragraph-oriented streaming for readability.

## Scope

Supported provider behavior in the current codebase:

- Google Gemini: exposes thinking content and signatures.
- Anthropic/OpenAI: current integration paths do not emit visible thinking chunks in the same way as Gemini in this stack.

## Runtime Flow

1. Provider stream emits mixed chunk types (text, tool calls, usage, thinking metadata where available).
2. `call_main_llm_stream` forwards raw provider chunks without paragraph aggregation.
3. `main_processor` aggregates string text into paragraphs for assistant output while passing non-string chunks through immediately.
4. `stream_consumer` publishes thinking chunks to a dedicated Redis channel as soon as they arrive.
5. Frontend receives `thinking_chunk` / `thinking_complete`, updates in-memory UI state, and persists thinking metadata for message history.

## Redis Channels

- Main response stream channel: `chat_stream::{chat_id}`
- Thinking stream channel: `chat_stream_thinking::{chat_id}`

Thinking event payloads use:

- `thinking_chunk`: incremental reasoning content chunk
- `thinking_complete`: completion marker with signature/token metadata when available

## Storage and Encryption

Thinking fields are part of message metadata and follow the chat encryption model used in the UI database layer.

Key fields used by the frontend message model:

- `encrypted_thinking_content`
- `encrypted_thinking_signature`
- `has_thinking`
- `thinking_token_count`

## Source of Truth (Implementation Files)

Backend stream and provider pipeline:

- `backend/apps/ai/utils/llm_utils.py`
- `backend/apps/ai/processing/main_processor.py`
- `backend/apps/ai/tasks/stream_consumer.py`
- `backend/apps/ai/llm_providers/google_client.py`
- `backend/apps/ai/llm_providers/types.py`
- `backend/apps/ai/utils/stream_utils.py`

Frontend event handling, state, and persistence:

- `frontend/packages/ui/src/services/chatSyncService.ts`
- `frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts`
- `frontend/packages/ui/src/components/ActiveChat.svelte`
- `frontend/packages/ui/src/components/ChatHistory.svelte`
- `frontend/packages/ui/src/components/ChatMessage.svelte`
- `frontend/packages/ui/src/services/db/chatKeyManagement.ts`
- `frontend/packages/ui/src/types/chat.ts`

## Notes

- This document intentionally avoids embedded code examples. Refer to the files above for the live implementation.
- If behavior differs from this document, treat the listed source files as canonical and update this document accordingly.
