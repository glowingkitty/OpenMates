---
status: active
last_verified: 2026-03-24
key_files:
  - backend/apps/ai/llm_providers/google_client.py
  - backend/apps/ai/llm_providers/types.py
  - backend/apps/ai/processing/main_processor.py
  - backend/apps/ai/tasks/stream_consumer.py
  - backend/apps/ai/utils/llm_utils.py
  - backend/apps/ai/utils/stream_utils.py
  - frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts
  - frontend/packages/ui/src/types/chat.ts
---

# Thinking Models

> Streams model reasoning/thinking content separately from the main response, with dedicated Redis channels and encrypted storage.

## Why This Exists

Some models (notably Google Gemini) expose their intermediate reasoning as "thinking" content. This gives users transparency into the model's reasoning process. Thinking content needs separate streaming, storage, and encryption because it follows different display patterns than the main response text.

## How It Works

### Streaming Architecture

1. Provider stream emits mixed chunk types (text, tool calls, usage, thinking metadata) via unified `UnifiedStreamChunk` types defined in [`types.py`](../../backend/apps/ai/llm_providers/types.py).
2. `call_main_llm_stream` in [`llm_utils.py`](../../backend/apps/ai/utils/llm_utils.py) forwards raw provider chunks without paragraph aggregation.
3. [`main_processor.py`](../../backend/apps/ai/processing/main_processor.py) aggregates text into paragraphs for the main assistant output, while passing non-string chunks (including thinking) through immediately.
4. [`stream_consumer.py`](../../backend/apps/ai/tasks/stream_consumer.py) publishes thinking chunks to a dedicated Redis channel as they arrive -- no buffering.
5. The frontend receives thinking events and updates the UI in real-time.

### Redis Channels

| Channel | Purpose |
|---------|---------|
| `chat_stream::{chat_id}` | Main response stream |
| `chat_stream_thinking::{chat_id}` | Thinking content stream |

### Event Types

- **`thinking_chunk`**: Incremental reasoning content
- **`thinking_complete`**: Completion marker with signature and token metadata

### Provider Support

- **Google Gemini**: Exposes thinking content and signatures via the `google-genai` SDK ([`google_client.py`](../../backend/apps/ai/llm_providers/google_client.py))
- **Anthropic/OpenAI**: Current integration does not emit visible thinking chunks in this stack

### Storage and Encryption

Thinking data is stored as encrypted message metadata, following the same chat encryption model:

| Field | Purpose |
|-------|---------|
| `encrypted_thinking_content` | The reasoning text (encrypted) |
| `encrypted_thinking_signature` | Provider signature if available |
| `has_thinking` | Boolean flag for quick checks |
| `thinking_token_count` | Token count for billing/display |

These fields are defined in the message type in [`chat.ts`](../../frontend/packages/ui/src/types/chat.ts) and handled in [`chatSyncServiceHandlersAI.ts`](../../frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts).

## Edge Cases

- **Non-thinking models**: When a model does not emit thinking chunks, the thinking Redis channel receives no events and the UI shows no thinking section.
- **Thinking vs main text**: Thinking content is streamed immediately as chunks arrive. Main assistant text uses paragraph-buffered streaming for readability. This is an intentional asymmetry.

## Related Docs

- [AI Model Selection](./ai-model-selection.md) -- how models are chosen
- [Message Processing](../messaging/message-processing.md) -- full pipeline
