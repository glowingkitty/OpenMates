---
status: active
last_verified: 2026-03-24
key_files:
  - backend/apps/ai/processing/postprocessor.py
  - backend/apps/ai/base_instructions.yml
  - backend/apps/ai/tasks/ask_skill_task.py
  - frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts
  - frontend/packages/ui/src/components/ActiveChat.svelte
  - frontend/packages/ui/src/types/chat.ts
---

# Follow-up and New Chat Suggestions

> Post-processing generates contextual follow-up suggestions for active chats and topic suggestions for the welcome screen, with skill/focus-mode prefix validation.

## Why This Exists

After each assistant response, the system generates actionable suggestions that help users explore topics further, discover app skills (web search, image generation, etc.), and start focus modes. This increases engagement and helps users discover platform capabilities they might not know about.

## How It Works

### Generation Pipeline

The post-processor ([`postprocessor.py`](../../backend/apps/ai/processing/postprocessor.py)) runs after each assistant response completes. It calls a lightweight LLM with the conversation context and generates:

1. **Follow-up suggestions** (6 per response): Shown under the last assistant message. Each suggestion carries a `[app_id-skill_id]` or `[app_id-focus_id]` prefix indicating which skill/focus to invoke.
2. **New chat suggestions** (6 per response): Added to a rolling pool of 30. Up to 10 randomly shuffled suggestions display on the welcome screen.

The `handle_postprocessing()` function receives the user message, assistant response, chat summary, chat tags, and lists of available skills and focus modes. It uses the `postprocess_response_tool` definition from [`base_instructions.yml`](../../backend/apps/ai/base_instructions.yml).

### Prefix Validation

The `sanitize_suggestions()` function validates every suggestion's prefix against known skill, focus mode, and memory IDs:

- Valid prefixes (e.g., `[web-search]`, `[jobs-career_insights]`) pass through
- Invalid/hallucinated prefixes are replaced with `[ai]` fallback
- Suggestions with fewer than 4 words in the body are dropped
- Memory prefixes are only allowed in follow-up suggestions (not new chat)

### Incognito Handling

Post-processing is skipped entirely for incognito chats -- no suggestions are generated or stored.

### Storage and Encryption

**Follow-up suggestions**: Stored encrypted in the chat message record under `encrypted_follow_up_request_suggestions`. Encrypted with the chat-specific key client-side. Replaced when the next assistant response completes.

**New chat suggestions**: Stored in a separate collection, encrypted with the master encryption key (not chat-specific). Includes `chat_id` for provenance tracking. Not deleted when the source chat is deleted. The 30 most recent are kept.

Both are stored in IndexedDB (client-side) and Directus (server-side), synced via the standard phased sync mechanism.

### Frontend Integration

- [`chatSyncServiceHandlersAI.ts`](../../frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts): Receives suggestions from WebSocket, encrypts and stores them
- [`ActiveChat.svelte`](../../frontend/packages/ui/src/components/ActiveChat.svelte): Displays follow-up suggestions under the last assistant message (first 3 visible by default)
- Suggestions support fuzzy search/filter as the user types in the message input
- Clicking a suggestion copies it to the input field
- New chat suggestions are deleted from both client and server after being clicked and sent

### Additional Post-Processing Outputs

The same LLM call also generates:

- **`harmful_response`**: Score 0-10 for detecting harmful responses
- **`chat_summary`**: Updated summary (max 20 words) of the conversation
- **`daily_inspiration_topic_suggestions`**: 3 topic phrases for personalized daily inspiration
- **`top_recommended_apps_for_user`**: Top 5 app ID recommendations based on context

## Edge Cases

- **Skill/focus hallucination**: LLMs sometimes invent non-existent skill prefixes. The sanitizer catches these and falls back to `[ai]`.
- **Very short suggestions**: Suggestions under 4 words are dropped as too vague.
- **Language handling**: Follow-up suggestions use the conversation language (`output_language`). New chat suggestions use the user's UI language (`user_system_language`).

## Related Docs

- [Message Processing](../messaging/message-processing.md) -- full pipeline context
- [AI Model Selection](./ai-model-selection.md) -- how models are chosen
