# Focus Modes Implementation

Focus modes are temporary system prompt modifications that help the AI assistant specialize for specific tasks. This document describes the technical implementation.

## Overview

Focus modes are treated as **tool calls** - similar to skills, but with special handling:

1. Preprocessor identifies relevant focus modes
2. Main processor generates `activate_focus_mode` / `deactivate_focus_mode` tools
3. LLM decides whether to activate a focus mode
4. Upon activation, processing restarts with the focus mode prompt in the system prompt

## Architecture

### Data Flow

1. **User sends message** → WebSocket handler extracts `active_focus_id` from chat metadata
2. **Preprocessor** → Identifies which focus modes could be relevant for the request
3. **Main Processor** → Generates focus mode tools if relevant modes exist or a mode is active
4. **LLM** → Decides to call `activate_focus_mode` or `deactivate_focus_mode`
5. **Tool Execution** → Updates chat metadata in cache and Directus, creates a `focus_mode_activation` embed
6. **Embed Streaming** → Backend yields a JSON embed reference inline in the message stream
7. **Restart** → Re-runs main processing with focus mode prompt in system prompt
8. **Frontend Rendering** → `FocusModeActivationRenderer` renders a `FocusModeActivationEmbed` Svelte component with a 4-second countdown, click-to-reject, and ESC key support
9. **User Rejection (optional)** → If user clicks or presses ESC during countdown, frontend sends a `chat_focus_mode_deactivate` WebSocket message to clear the focus mode for future messages

### Key Files

| Component                  | File                                                                                                                                                                                                                                  | Purpose                                                                                                                                        |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Preprocessor               | [`backend/apps/ai/processing/preprocessor.py`](../../../backend/apps/ai/processing/preprocessor.py)                                                                                                                                   | Identifies relevant focus modes                                                                                                                |
| Main Processor             | [`backend/apps/ai/processing/main_processor.py`](../../../backend/apps/ai/processing/main_processor.py)                                                                                                                               | Generates tools, handles activation embed creation and restart                                                                                 |
| Embed Service              | [`backend/core/api/app/services/embed_service.py#create_focus_mode_activation_embed()`](../../../backend/core/api/app/services/embed_service.py)                                                                                      | Creates, encrypts, and streams the focus mode activation embed                                                                                 |
| Deactivation Handler       | [`backend/core/api/app/routes/handlers/websocket_handlers/focus_mode_deactivate_handler.py`](../../../backend/core/api/app/routes/handlers/websocket_handlers/focus_mode_deactivate_handler.py)                                       | WebSocket handler for client-initiated focus mode deactivation                                                                                 |
| WebSocket Router           | [`backend/core/api/app/routes/websockets.py`](../../../backend/core/api/app/routes/websockets.py)                                                                                                                                     | Routes `chat_focus_mode_deactivate` messages                                                                                                   |
| Preprocessing Instructions | [`backend/apps/ai/base_instructions.yml`](../../../backend/apps/ai/base_instructions.yml)                                                                                                                                             | LLM instructions for focus mode selection                                                                                                      |
| Focus Mode Definitions     | App-specific `app.yml` files (e.g., `backend/apps/web/app.yml`)                                                                                                                                                                       | Focus mode metadata and system prompts                                                                                                         |
| Chat Schema                | [`backend/core/directus/schemas/chats.yml`](../../../backend/core/directus/schemas/chats.yml)                                                                                                                                         | `encrypted_active_focus_id` field                                                                                                              |
| AI Request Schema          | [`backend/core/api/app/schemas/ai_skill_schemas.py`](../../../backend/core/api/app/schemas/ai_skill_schemas.py)                                                                                                                       | `active_focus_id` in request                                                                                                                   |
| **Frontend**               |                                                                                                                                                                                                                                       |                                                                                                                                                |
| Activation Embed Component | [`frontend/packages/ui/src/components/embeds/FocusModeActivationEmbed.svelte`](../../../frontend/packages/ui/src/components/embeds/FocusModeActivationEmbed.svelte)                                                                   | Svelte 5 component: countdown UI, click/ESC rejection, activated state                                                                         |
| Activation Renderer        | [`frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/FocusModeActivationRenderer.ts`](../../../frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/FocusModeActivationRenderer.ts) | Mounts Svelte component, dispatches custom events for rejection/deactivation/details                                                           |
| Embed Registry             | [`frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/index.ts`](../../../frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/index.ts)                                             | Registers `focus-mode-activation` renderer                                                                                                     |
| Embed Types                | [`frontend/packages/ui/src/message_parsing/types.ts`](../../../frontend/packages/ui/src/message_parsing/types.ts)                                                                                                                     | Defines `focus-mode-activation` embed type, `focus_id` / `focus_mode_name` attributes                                                          |
| Embed Parsing              | [`frontend/packages/ui/src/message_parsing/embedParsing.ts`](../../../frontend/packages/ui/src/message_parsing/embedParsing.ts)                                                                                                       | Maps `focus_mode_activation` → `focus-mode-activation`, extracts metadata                                                                      |
| Context Menu               | [`frontend/packages/ui/src/components/embeds/EmbedContextMenu.svelte`](../../../frontend/packages/ui/src/components/embeds/EmbedContextMenu.svelte)                                                                                   | Deactivate / Details context menu items for focus mode embeds                                                                                  |
| Chat Message               | [`frontend/packages/ui/src/components/ChatMessage.svelte`](../../../frontend/packages/ui/src/components/ChatMessage.svelte)                                                                                                           | Detects focus mode embeds, configures context menu                                                                                             |
| Active Chat                | [`frontend/packages/ui/src/components/ActiveChat.svelte`](../../../frontend/packages/ui/src/components/ActiveChat.svelte)                                                                                                             | Global event listeners for deactivation (WebSocket), rejection (system message), details (deep link)                                           |
| i18n Strings               | [`frontend/packages/ui/src/i18n/sources/embeds.yml`](../../../frontend/packages/ui/src/i18n/sources/embeds.yml)                                                                                                                       | Translation keys: `focus_mode.activated`, `focus_mode.activating`, `focus_mode.reject_hint`, `context_menu.deactivate`, `context_menu.details` |

## Implementation Details

### 1. Preprocessor Changes

**File:** `backend/apps/ai/processing/preprocessor.py`

Add `relevant_focus_modes` to `PreprocessingResult` model. The preprocessor LLM identifies which focus modes could be useful for the current request, similar to how it identifies `relevant_app_skills`.

The preprocessing instructions in `base_instructions.yml` need a new field that lists available focus modes and asks the LLM to select relevant ones.

### 2. Tool Generation

**File:** `backend/apps/ai/processing/main_processor.py`

Generate focus mode tools conditionally:

- **`activate_focus_mode`**: Generated when `preprocessing_results.relevant_focus_modes` is non-empty AND no focus mode is currently active. Parameters include an enum of relevant focus mode IDs with descriptions.

- **`deactivate_focus_mode`**: Generated when `request_data.active_focus_id` is set (a focus mode is active). No parameters needed.

Tool names use special prefix (e.g., `system-activate_focus_mode`) to distinguish from regular app skills.

### 3. Tool Execution, Embed Creation & Restart

**Files:** `backend/apps/ai/processing/main_processor.py`, `backend/core/api/app/services/embed_service.py`

When `activate_focus_mode` is called:

1. Update `active_focus_id` in cache via `CacheService`
2. Persist to Directus via Celery task (`persist_chat_active_focus_id`)
3. Create a `focus_mode_activation` embed via `embed_service.create_focus_mode_activation_embed()`
4. Yield the embed as a JSON embed reference (`json\n{...}\n`) into the message stream
5. Set `restart_required = True` flag
6. Break current tool execution loop
7. Re-construct system prompt with focus mode prompt included
8. Re-run the LLM call loop from iteration 0

The `create_focus_mode_activation_embed()` method:

- Creates an embed with content containing `focus_id`, `app_id`, `focus_mode_name`, and `status: "activated"`
- Encodes via TOON, encrypts, caches, and streams to the client via WebSocket (`send_embed_data_to_client`)
- Returns a JSON embed reference payload of type `focus_mode_activation`

When `deactivate_focus_mode` is called (AI-initiated):

1. Clear `active_focus_id` in cache
2. Persist to Directus
3. Create system message (type: `focus_mode_deactivated`)
4. Set `restart_required = True`
5. Re-run without focus mode prompt

### 4. Client-Initiated Deactivation

**File:** `backend/core/api/app/routes/handlers/websocket_handlers/focus_mode_deactivate_handler.py`

When the user rejects (during countdown) or deactivates (via context menu) a focus mode from the frontend, the client sends a `chat_focus_mode_deactivate` WebSocket message with `chat_id` and `focus_id`. The handler:

1. Clears `encrypted_active_focus_id` from cache via `cache_service.update_chat_active_focus_id(encrypted_focus_id=None)`
2. Dispatches a Celery task (`persist_chat_active_focus_id`) to set the field to `None` in Directus
3. Sends an acknowledgment message back to the client

This ensures that all subsequent AI turns process messages without the focus mode prompt, even if the initial AI response was already generated with the focus mode active.

### 5. Frontend Activation UI

**Component:** `FocusModeActivationEmbed.svelte`

The focus mode activation embed renders inline in the chat as a compact card:

1. **Countdown phase** (4 seconds):
   - Displays the app icon, focus mode name, and a "Activate in N sec..." status
   - Animated progress bar counts down from 100% to 0%
   - User can **click the card** or **press ESC** to reject the activation
   - Helper text below the card: "Click or press ESC to prevent focus mode & continue regular chat"

2. **Activated phase** (after countdown):
   - Card updates to show "Focus activated" with a green accent
   - Progress bar disappears
   - Click-to-reject and ESC listener are disabled

3. **Rejected phase** (if user cancels):
   - Card is hidden entirely (`isRejected = true`)
   - `focusModeRejected` custom event is dispatched
   - `ActiveChat.svelte` handles the event by:
     a. Sending `chat_focus_mode_deactivate` WebSocket message to backend
     b. Adding a local system message to the chat: "Focus mode '{name}' was rejected"

**Context Menu:** Right-clicking (or long-pressing) the activation card triggers the embed context menu via `ChatMessage.svelte`, which shows:

- **Deactivate** — Dispatches `focusModeDeactivated` event → WebSocket deactivation
- **Details** — Dispatches `focusModeDetailsRequested` event → Deep-links to the focus mode in settings/app store

**ESC Key Handling:** The component registers a global `document.addEventListener('keydown', ...)` listener on mount that calls the rejection handler when ESC is pressed during the countdown phase. The listener is cleaned up on unmount.

The frontend syncs `encrypted_active_focus_id` via phased sync. See [`backend/core/api/app/routes/handlers/websocket_handlers/phased_sync_handler.py`](../../../backend/core/api/app/routes/handlers/websocket_handlers/phased_sync_handler.py).

## Focus Mode Prompt Loading

**Already Implemented:** The main processor already loads focus mode prompts when `active_focus_id` is set. See lines 682-696 in `main_processor.py`.

The focus mode prompt is inserted at the beginning of the system prompt, wrapped with markers for clarity.

## Cache & Persistence

### Cache Updates

Use existing `CacheService` methods to update `encrypted_active_focus_id` in the chat's `list_item_data` cache key.

### Directus Updates

Persist `encrypted_active_focus_id` changes via Celery task to the `chats` collection. The field already exists in the schema.

## Security Considerations

- Focus mode IDs are encrypted with the chat-specific key (zero-knowledge architecture)
- Server validates focus mode ID against available focus modes before activation
- System messages use `role: "system"` to distinguish from user/assistant messages

## Related Documentation

- [Focus Modes Overview](./focus-modes.md) - User-facing documentation
- [Function Calling](./function-calling.md) - How skills/tools work
- [App Settings & Memories](./settings-and-memories.md) - Similar system message pattern
- [Message Processing](../architecture/message-processing.md) - Overall processing pipeline
