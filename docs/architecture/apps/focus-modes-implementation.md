---
status: active
last_verified: 2026-03-24
key_files:
- backend/apps/ai/processing/preprocessor.py
- backend/apps/ai/processing/main_processor.py
- backend/core/api/app/services/embed_service.py
- backend/core/api/app/routes/handlers/websocket_handlers/focus_mode_deactivate_handler.py
- frontend/packages/ui/src/components/embeds/focus_mode/FocusModeActivationEmbed.svelte
- frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/FocusModeActivationRenderer.ts
claims:
- id: arch-apps-focus-modes-implementation-behavior
  type: unit
  claim: Focus Modes Implementation is grounded in current source-of-truth files that parse or resolve successfully.
  source:
  - backend/apps/ai/processing/preprocessor.py
  - backend/apps/ai/processing/main_processor.py
  - backend/core/api/app/services/embed_service.py
  - backend/core/api/app/routes/handlers/websocket_handlers/focus_mode_deactivate_handler.py
  - frontend/packages/ui/src/components/embeds/focus_mode/FocusModeActivationEmbed.svelte
  test:
    file: scripts/tests/test_architecture_behavioral_claims.py
    command: python3 -m pytest scripts/tests/test_architecture_behavioral_claims.py
    assertion: arch-apps-focus-modes-implementation-behavior
  verified: '2026-06-11'
- id: arch-apps-focus-modes-implementation-source-1
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-apps-focus-modes-implementation-source-1
  anchors:
  - type: file_exists
    path: backend/apps/ai/processing/main_processor.py
- id: arch-apps-focus-modes-implementation-source-2
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-apps-focus-modes-implementation-source-2
  anchors:
  - type: file_exists
    path: backend/apps/ai/processing/preprocessor.py
- id: arch-apps-focus-modes-implementation-source-3
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-apps-focus-modes-implementation-source-3
  anchors:
  - type: file_exists
    path: backend/core/api/app/routes/handlers/websocket_handlers/focus_mode_deactivate_handler.py
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
5. **Tool execution** -> creates and streams a `focus_mode_activation` countdown embed, stores pending continuation context, and exits cleanly
6. **User decision** -> rejection resumes ordinary processing; otherwise auto-confirm publishes `focus_mode_activated`
7. **Client persistence** -> the first-party client encrypts the focus ID with the chat key and returns the encrypted value for persistence
8. **Processing restarts** with active focus state and the focus-mode prompt in the system prompt

### Backend: Tool Generation (`main_processor.py`)

- `activate_focus_mode`: generated when preprocessor finds relevant focus modes AND no mode is currently active. Parameters include enum of relevant focus mode IDs with descriptions.
- `deactivate_focus_mode`: generated when `active_focus_id` is set. No parameters.
- Tool names use `system-` prefix to distinguish from regular skills.
- Relevant focus modes are activation candidates only. They do not set `active_focus_id`, enable focus-specific routing, or suppress ordinary preselected skills.
- Active Deep research enables and forces its sub-chat delegation policy only after the activation continuation supplies `active_focus_id: web-research`.

### Backend: Activation Flow

When `activate_focus_mode` is called:
1. Create a `focus_mode_activation` embed via `embed_service.create_focus_mode_activation_embed()` (TOON-encoded, encrypted, cached, streamed to the client).
2. Store pending activation context in Redis with a bounded TTL.
3. Schedule `focus_mode_auto_confirm_task` and end the current processing task without assigning `active_focus_id`.
4. If the user rejects during the countdown, consume the pending context and resume without focus state.
5. Otherwise auto-confirm publishes `focus_mode_activated` and dispatches continuation with the active focus prompt.
6. The client encrypts the focus ID with the chat key, stores it locally, and sends `update_encrypted_active_focus_id` for server persistence.

### Project-owned focus modes

Project focus modes share the visible named focus and off control, while their
authority comes from the authenticated Project binding. Sending a structured
Project mention activates the selected Project's current default focus after
durable chat preflight and before inference. Its user-message chip links to the
Project page; rendering or clicking history does not activate a focus.

For natural-language requests, the client supplies only a bounded catalog of
decrypted Project names. The backend filters it against current ownership or
Team access before preprocessing selects relevant `project-<UUID>` candidates.
Main processing can request a candidate through `activate_focus_mode`, but the
Project embed shows **Grant access / Decline** and never schedules auto-confirm.
Only confirmation loads client-decrypted Project instructions, invokes the same
Project activation endpoint, persists the encrypted chat focus, and resumes the
original request through the existing async continuation mechanism.

Pending consent is tied to user, chat, Project, and current user turn, is consumed
once, and expires after twenty minutes. Reconnection can redisplay a still-valid
request through a fresh server event; historical embeds remain inert. Declining
prevents another Project access prompt during that turn. The active Project's
full instruction remains in each inference prompt even if no file executor is
currently available. Keys and durable Project contents retain client encryption.

Project focus off revokes the Project binding before clearing encrypted focus
metadata. Existing displayed chat content remains readable within its prior
access; future Project operations require the current authorization state.

### Phased focus modes

Focus instructions may include YAML frontmatter with `phases_version: 1` and an
ordered `phases` list. Each phase requires an `id`, `title`, `instructions`, and
nonempty `requirements`; each requirement has `id`, `text`, and an optional
`type` (`semantic` by default, or `user_confirmation`). The shared loader rejects
unknown fields, duplicate IDs/keys, aliases, invalid versions, and empty content.
The Markdown System prompt supplies global instructions. Project instruction text
uses the same schema; unphased text retains its existing behavior. See the
[Career insights definition](../../../backend/apps/jobs/focus_modes/career-insights/SKILL.md)
for a complete example.

`backend/apps/ai/processing/focus_phases.py` evaluates gates with Jev at user,
completed tool-batch, and completed assistant boundaries. Unmet, uncertain or
failed decisions retain the phase. Confirmation uses actual user input after
phase entry. Explicit requests can return to earlier phases, with a same-turn
no-bounce guard. Both normal and recovery prompts receive current-phase
instructions/requirements and only IDs/titles for other phases. Tool reselection
stays inside the Mate's authorized discovered app catalog and grants no access.

Clients encrypt phase progress separately in `encrypted_focus_phase_state` and
persist UUID-stable phase-change system history. Short-lived Redis compare-and-set
state rejects stale decisions and repeated boundaries. Catalog focus activation
and deactivation retain the independent Project base. Phase history links to
catalog or Project details; active-chat focus chrome remains unchanged. The
web and Apple detail views render the phase instructions and requirements.

The five clarification rounds are instruction text, with examples and a
recommendation for each question, waiting for the reply and considering research
before the next question. Users may skip or batch questions; there is no minimum
question-count gate. Current implementation evidence and outstanding real
inference/native checks are recorded in the
[Plan](../../plans/focus-mode-phases/plan.yml).

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
