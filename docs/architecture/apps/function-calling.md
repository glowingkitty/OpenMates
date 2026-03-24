---
status: active
last_verified: 2026-03-24
key_files:
  - backend/apps/ai/processing/main_processor.py
  - backend/apps/ai/processing/preprocessor.py
  - backend/apps/ai/processing/tool_generator.py
  - backend/apps/ai/base_instructions.yml
  - backend/apps/base_skill.py
---

# Function Calling

> How the LLM triggers app skills and focus modes during conversations via tool preselection and function calling.

## Why This Exists

Enables the LLM to automatically invoke app skills (web search, image generation, etc.) and activate focus modes based on conversation context. Tool preselection keeps the system scalable as apps grow.

## How It Works

### Integration with Message Processing

1. User sends a message
2. **Pre-processing** (`preprocessor.py`) analyzes the request and preselects relevant tools
3. **Main processing** (`main_processor.py`) sends preselected tools to the LLM
4. LLM decides which functions to call
5. Function calls are executed via `skill_executor.py`
6. Results incorporated into the assistant's response

### Tool Definitions

Tools are generated from app `app.yml` files by `tool_generator.py`. Only skills with `stage: "production"` are exposed.

**Naming format:** `{app_id}-{skill_id}` (e.g., `web-search`, `videos-get_transcript`). Hyphens required for compatibility with providers like Cerebras.

**Automatic `id` field injection:** `_inject_id_field_if_needed()` in `tool_generator.py` auto-adds an `id` field to tool schemas with `requests` arrays, so skills don't need to define it in `app.yml`.

### Tool Preselection (`preprocessor.py`)

Filters tools during pre-processing to avoid sending all tools to the LLM:

1. Pre-processing LLM receives a simplified list of skill names and focus mode names
2. Outputs `relevant_app_skills`, `relevant_app_focus_modes`, and `relevant_app_settings_and_memories` (all in `app_id-item_id` format)
3. Each preselected tool is validated (exists, available, not deactivated by user)
4. Only validated tools get full definitions loaded for main processing

**Benefits:** Scalable to hundreds of skills, reduced token usage, better LLM accuracy, privacy (only relevant settings/memories requested from client).

### Skill Execution

1. Parse function name: `web-search` -> `app_id: "web"`, `skill_id: "search"`
2. Route to correct app
3. Execute skill's `execute()` method
4. Multiple requests (up to 5) processed in parallel via `asyncio.gather()`

### Focus Mode Activation

1. Parse function name: `web.research` -> `app_id: "web"`, `focus_mode_id: "research"`
2. Update chat state (cache + Directus)
3. Include focus mode instructions in system prompt
4. Confirm activation to user

See [Focus Modes Implementation](./focus-modes-implementation.md) for full activation/deactivation flow.

### Error Handling

On failure: error details provided to LLM, retry with different parameters allowed, can fall back to responding without the function call.

### Configuration

- `base_instructions.yml` -- LLM instructions for when/how to use tools
- Each app's `app.yml` -- skill and focus mode definitions with tool schemas
- `main_processor.py` -- tool generation and execution orchestration
- `preprocessor.py` -- preselection logic

## Related Docs

- [Message Processing](../messaging/message-processing.md) -- complete processing pipeline
- [Focus Modes Implementation](./focus-modes-implementation.md) -- focus mode technical details
- [REST API](./rest-api.md) -- programmatic API access
