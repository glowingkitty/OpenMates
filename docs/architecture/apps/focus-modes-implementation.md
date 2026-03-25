---
status: active
last_verified: 2026-03-24
key_files:
  - backend/apps/ai/processing/preprocessor.py
  - backend/apps/ai/processing/main_processor.py
  - backend/core/api/app/services/embed_service.py
  - backend/core/api/app/routes/handlers/websocket_handlers/focus_mode_deactivate_handler.py
  - frontend/packages/ui/src/components/embeds/FocusModeActivationEmbed.svelte
  - frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/FocusModeActivationRenderer.ts
---

# Focus Modes Implementation

> Focus modes are temporary system prompt modifications that specialize the AI for specific tasks, treated as tool calls with activation/deactivation/restart semantics.

## Why This Exists

Allows the LLM to dynamically switch into specialized modes (e.g., "web research", "code planning") by modifying the system prompt mid-conversation. Users can reject activation during a countdown or deactivate via context menu.

## How It Works

### Data Flow

1. **User sends message** -> WebSocket handler extracts `active_focus_id` from chat metadata
2. **Preprocessor** identifies relevant focus modes from available list
3. **Main Processor** generates `activate_focus_mode` / `deactivate_focus_mode` tools
4. **LLM** decides to call activation/deactivation
5. **Tool execution** -> updates cache + Directus, creates `focus_mode_activation` embed
6. **Embed streamed** as JSON reference inline in message stream
7. **Processing restarts** with focus mode prompt in system prompt

### Backend: Tool Generation (`main_processor.py`)

- `activate_focus_mode`: generated when preprocessor finds relevant focus modes AND no mode is currently active. Parameters include enum of relevant focus mode IDs with descriptions.
- `deactivate_focus_mode`: generated when `active_focus_id` is set. No parameters.
- Tool names use `system-` prefix to distinguish from regular skills.

### Backend: Activation Flow

When `activate_focus_mode` is called:
1. Update `active_focus_id` in cache via `CacheService`
2. Persist to Directus via Celery task (`persist_chat_active_focus_id`)
3. Create `focus_mode_activation` embed via `embed_service.create_focus_mode_activation_embed()` (TOON-encoded, encrypted, cached, streamed to client)
4. Set `restart_required = True`, break tool loop
5. Re-construct system prompt with focus mode prompt, re-run LLM call from iteration 0

### Backend: Deactivation

**AI-initiated:** Clear cache, persist to Directus, create system message, restart without focus mode prompt.

**Client-initiated** (`focus_mode_deactivate_handler.py`): WebSocket message `chat_focus_mode_deactivate` with `chat_id` + `focus_id`. Handler clears cache, dispatches Celery task to clear Directus, sends ACK.

### Frontend: Activation UI (`FocusModeActivationEmbed.svelte`)

Renders inline in chat as a compact card:

1. **Countdown phase (4 seconds):** App icon, focus mode name, "Activate in N sec..." with progress bar. User can click card or press ESC to reject.
2. **Activated phase:** Card shows "Focus activated" with green accent.
3. **Rejected phase:** Card hidden. `focusModeRejected` event dispatched. `ActiveChat.svelte` sends WebSocket deactivation + local system message.

**Context menu** (via `ChatMessage.svelte`): "Deactivate" -> WebSocket deactivation. "Details" -> deep-link to settings.

**ESC handling:** Global `document.addEventListener('keydown')` registered on mount, cleaned up on destroy.

### Frontend: Renderer and Registry

- `FocusModeActivationRenderer.ts` mounts the Svelte component, dispatches custom events
- Registered as `focus-mode-activation` in `embed_renderers/index.ts`
- Embed type and attributes defined in `message_parsing/types.ts` and `embedParsing.ts`

### Cache & Persistence

- `encrypted_active_focus_id` stored in chat's `list_item_data` cache key via `CacheService`
- Persisted to `chats` collection in Directus (field already exists in schema)
- Frontend syncs via phased sync handler

## Edge Cases

- Focus mode IDs are encrypted with chat-specific key (zero-knowledge)
- Server validates focus mode ID against available modes before activation
- Focus mode prompt loaded at system prompt beginning with markers (lines ~682-696 in `main_processor.py`)

## Related Docs

- [Function Calling](./function-calling.md) -- tool preselection and execution
- [Message Processing](../messaging/message-processing.md) -- overall pipeline
- [Focus Modes Overview](../../user-guide/apps/focus-modes.md) -- user-facing documentation
