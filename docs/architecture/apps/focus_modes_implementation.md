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
5. **Tool Execution** → Updates chat metadata, creates system message, triggers restart
6. **Restart** → Re-runs main processing with focus mode prompt in system prompt
7. **UI** → Displays system message showing focus mode change in chat history

### Key Files

| Component | File | Purpose |
|-----------|------|---------|
| Preprocessor | [`backend/apps/ai/processing/preprocessor.py`](../../../backend/apps/ai/processing/preprocessor.py) | Identifies relevant focus modes |
| Main Processor | [`backend/apps/ai/processing/main_processor.py`](../../../backend/apps/ai/processing/main_processor.py) | Generates tools, handles restart |
| Preprocessing Instructions | [`backend/apps/ai/base_instructions.yml`](../../../backend/apps/ai/base_instructions.yml) | LLM instructions for focus mode selection |
| Focus Mode Definitions | App-specific `app.yml` files (e.g., `backend/apps/web/app.yml`) | Focus mode metadata and system prompts |
| System Message Handler | [`backend/core/api/app/routes/handlers/websocket_handlers/system_message_handler.py`](../../../backend/core/api/app/routes/handlers/websocket_handlers/system_message_handler.py) | Persists focus mode events |
| Chat Schema | [`backend/core/directus/schemas/chats.yml`](../../../backend/core/directus/schemas/chats.yml) | `encrypted_active_focus_id` field |
| AI Request Schema | [`backend/core/api/app/schemas/ai_skill_schemas.py`](../../../backend/core/api/app/schemas/ai_skill_schemas.py) | `active_focus_id` in request |

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

### 3. Tool Execution & Restart

**File:** `backend/apps/ai/processing/main_processor.py`

When `activate_focus_mode` is called:
1. Update `active_focus_id` in cache via `CacheService`
2. Persist to Directus via Celery task
3. Create system message in chat history (type: `focus_mode_activated`)
4. Set `restart_required = True` flag
5. Break current tool execution loop
6. Re-construct system prompt with focus mode prompt included
7. Re-run the LLM call loop from iteration 0

When `deactivate_focus_mode` is called:
1. Clear `active_focus_id` in cache
2. Persist to Directus
3. Create system message (type: `focus_mode_deactivated`)
4. Set `restart_required = True`
5. Re-run without focus mode prompt

### 4. System Messages

**Existing Infrastructure:** `backend/core/api/app/routes/handlers/websocket_handlers/system_message_handler.py`

Focus mode events use the same system message infrastructure as app settings/memories responses. Message content is JSON with a `type` field:

- `focus_mode_activated`: Contains `focus_id`, `app_id`, timestamp
- `focus_mode_deactivated`: Contains previous `focus_id`, timestamp

These messages are stored in chat history and synced across devices.

### 5. Frontend Display

System messages for focus mode changes should be rendered differently from regular messages - showing a status indicator rather than message bubble.

The frontend already syncs `encrypted_active_focus_id` via phased sync. See [`backend/core/api/app/routes/handlers/websocket_handlers/phased_sync_handler.py`](../../../backend/core/api/app/routes/handlers/websocket_handlers/phased_sync_handler.py).

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

- [Focus Modes Overview](./focus_modes.md) - User-facing documentation
- [Function Calling](./function_calling.md) - How skills/tools work
- [App Settings & Memories](./app_settings_and_memories.md) - Similar system message pattern
- [Message Processing](../message_processing.md) - Overall processing pipeline
