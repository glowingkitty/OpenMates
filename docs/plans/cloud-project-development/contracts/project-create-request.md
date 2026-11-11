# Contract: client-executed Project creation (`openmates.project_create_request` v1)

Owner: plan `cloud-project-development`, package P9 (backend). Consumer: P10 (Rust
core, then web/Apple through it). Assertion: `projects.creation.assistant-inferred`.
Source of truth in code: `backend/core/api/app/services/project_create_request_service.py`
(payload builder and validation), `backend/apps/ai/processing/project_creation_routing.py`
(decision), `backend/core/api/app/routes/handlers/websocket_handlers/project_create_result_handler.py`
(completion report). Keep this file and those modules in sync.

Projects are client-side encrypted. The server never creates a Project, never sees
the Project key and never stores the Project name. It asks the chat's executor
client to create one, then verifies the result and resumes the same chat turn.

## 1. Capability

A client opts in by adding `project_create_requests` to the WebSocket
`client_capabilities` query parameter, next to `project_file_jobs` (both are
required). A connection without it never receives a request, and turns sent from
it never produce the `create_project` outcome, so older clients keep today's
behaviour (the assistant answers in the chat).

Requests go only to a device whose connection has both capabilities and whose
active chat is the request's chat (`ConnectionManager.can_execute_project_create`).

## 2. When the server asks

Preprocessing returns the routing-only outcome `create_project` when all of these hold:

- client capability above; not incognito, external, a sub-chat or any continuation;
- the chat has no active Project focus, no current Project, no staged Project routing,
  no pending Project focus proposal and no unanswered creation request;
- the user did not decline Project access/work, apps are enabled, and the message has
  no explicit `@focus`, `@skill` or `@plan` override;
- Stage-one routing is complete with `task_area == code` and its harm/misuse scores
  are below the configured thresholds;
- a Jev choice question classifies the request as `web_app` or `native_app` with
  confidence >= 0.7 (`single_file` and `none` never create a Project);
- a short naming call returns a non-empty Project name.

Any failure keeps today's behaviour; nothing is created and the reason is logged.
No main-model inference runs for that turn until the client reports back.

## 3. Request: server -> client

WebSocket event `project_create_requested`:

```json
{
  "type": "project_create_requested",
  "payload": {
    "chat_id": "<chat id>",
    "request_id": "project-create-request-<uuid4>",
    "pending_client_action": {
      "contract": "openmates.project_create_request",
      "version": 1,
      "request_id": "project-create-request-<uuid4>",
      "action": "create",
      "origin": "preprocessor",
      "chat_id": "<chat id>",
      "message_id": "<user message id of this turn>",
      "team_id": null,
      "name": "Recipe Manager",
      "description": "",
      "kind": "web_app",
      "subfolder": "web-app",
      "write_mode": "apply_and_show",
      "focus": {"activate": "immediate", "countdown_seconds": 0},
      "undo": {"available": true},
      "created_at": 1762790400,
      "expires_at": 1762791000,
      "notification_queued": false
    }
  }
}
```

Field rules:

| Field | Meaning |
| --- | --- |
| `contract`, `version` | Reject anything else; future versions bump `version`. |
| `request_id` | Opaque, unique; echo it unchanged. Pattern `project-create-request-<uuid4>`. |
| `origin` | `preprocessor`: assistant-inferred, the turn resumes after the report. `skill`: produced by the `projects.create` app skill (returned in its skill result, not via this event); same fields, `kind`/`subfolder` are `null`, `focus.activate` is `none`, and no report is expected. |
| `team_id` | Create the Project in this Team when set, else personal. |
| `name`, `description` | Plaintext proposal (<=120 / <=400 chars). Encrypt client-side like a user-created Project. |
| `kind`, `subfolder` | `web_app` -> `web-app`, `native_app` -> `native-app`. The application's files later live under `<subfolder>/` (P11). The client creates no files for this request. |
| `write_mode` | Always `apply_and_show`; send it as `write_mode` on create. |
| `focus.activate` | `immediate`: activate the default focus right after creation, no countdown and no confirmation. |
| `undo.available` | The created-Project card must offer Undo (section 6). |
| `expires_at` | Unix seconds. After it the server rejects the report; do not create the Project. |

`projects.create` skill results reuse this same `pending_client_action` object
(`status: waiting_for_client`).

## 4. What the client does

1. Generate `project_id` and `default_focus_id` (UUIDs), the Project key and wrappers,
   and encrypt name, description and settings exactly as for a user-created Project.
2. `POST /v1/projects` (`team_id` query when set) with `write_mode: "apply_and_show"`,
   `default_focus_id`, `created_at` = now (seconds or milliseconds) and the encrypted
   fields. Its `created_at` must not be more than 10 minutes older than the request.
3. `POST /v1/projects/{project_id}/focus/activate` with `{chat_id, focus_id:
   default_focus_id, instruction}` and **no** `activation_request_id`. This is the
   immediate "Work on <name>" focus; there is no countdown.
4. Show the created-Project card ("Created project <name>", Undo) in the chat.
5. Send the completion report (section 5).

If any step fails, report `failed` (and roll back what was created if possible).
If the user presses Undo before step 5, undo (section 6) and report `undone`.

## 5. Completion report: client -> server

WebSocket message `project_create_result`:

```json
{"type": "project_create_result", "payload": {
  "chat_id": "<chat id>",
  "request_id": "project-create-request-<uuid4>",
  "status": "created",
  "project_id": "<uuid>",
  "focus_id": "<default focus uuid>"
}}
```

- `status`: `created` | `failed` | `undone`.
- `created` requires `project_id` and `focus_id` (the default focus id used in step 3).
- `failed` / `undone` may carry `error_code` (`^[A-Z0-9_]{1,64}$`), e.g.
  `PROJECT_KEY_WRAP_FAILED`. No name or other plaintext is sent.

The server verifies, in order: payload shape; the sending device can execute
creation for this chat; the request is the chat's current, unexpired request of
this user and its `message_id` is still the chat's latest user turn. For
`created` additionally: chat access, write access to the Project, Project not
archived and new for this request, Project `write_mode == apply_and_show`, and
the chat's active Project focus binding is this Project and `focus_id`. Then one
report wins (later or second-tab reports are rejected) and the request is cleared.

Replies to the sending socket:

- `{"type": "project_create_confirmed", "payload": {"chat_id", "request_id", "status"}}`
- `{"type": "project_create_error", "payload": {"chat_id", "request_id", "code"}}`
  with codes such as `INVALID_PROJECT_CREATE_RESULT`, `PROJECT_EXECUTOR_NOT_READY`,
  `PROJECT_CREATE_REQUEST_EXPIRED`, `PROJECT_CREATE_REQUEST_STALE`,
  `PROJECT_CREATE_NOT_NEW`, `PROJECT_CREATE_WRITE_MODE_MISMATCH`,
  `PROJECT_FOCUS_REQUIRED`, `PROJECT_NOT_FOUND`, `CHAT_NOT_FOUND`.
  After an error the turn is not resumed; the client may fix the cause (for example
  activate the focus) and resend while the request is unexpired, or report `failed`.

For `created`, before the turn resumes, the server also publishes the existing
`focus_mode_activated` event `{chat_id, focus_id}` to all of the user's devices.
`focus_id` is the verified binding's default focus id (bare UUID, the value
`GET /v1/projects/focus/current` returns), so each client encrypts it with the chat
key and stores it with `update_encrypted_active_focus_id` exactly as for an
accepted focus. In the Rust core this frame is the only writer of that field for
this flow (`ProjectCreateState::mark_focus_persisted`; card field `focusPersisted`).

## 6. Same-turn continuation

For `created` the resumed assistant message starts with one persisted
`focus_mode_activation` embed, before any answer text or application embed. It
is already active (`status: activated`, no countdown, no accept/reject) and only
appears while the chat's focus binding is still this Project and focus (an Undo
before the turn resumes shows none). Fields: `focus_id: "project-<project_id>"`,
`app_id: "projects"`, `focus_mode_name: "Work on <name>"`, plus
`project_created: true`, `project_id`, `project_focus_id` (the bare default focus
id persisted as the active focus) and `project_name` (the proposed name, the
same plaintext the request already carried). Clients render it as the
"Created project <name>" card with Undo.

After `project_create_confirmed` the original turn resumes as an async continuation
(`skill_id` `project_create_request`). For `created` the new Project focus is active,
so the main model receives the Project file tools under the Apply and show policy and
is told to write the application's files under `<subfolder>/` without asking. For
`failed` / `undone` the turn resumes with Project access declined for that turn and
the assistant answers in the chat. The model-visible completion contains no Project
name.

## 7. Undo

Undo removes the Project and its focus and leaves the chat and its embeds intact:

1. `POST /v1/projects/focus/deactivate` with `{chat_id}`.
2. `DELETE /v1/projects/{project_id}?confirmation_project_id={project_id}`
   (`team_id` query when set; Team deletion needs owner/admin).

Undo before the report: also send `project_create_result` with `status: undone`.
Undo after the report: the running turn loses Project authority at once (file tools
fail closed because the focus binding no longer validates); no message is needed.

## 8. Expiry and limits

Requests live 10 minutes (`PROJECT_CREATE_REQUEST_TTL`). One pending request per
chat; a new user turn makes the old one stale. A client that cannot complete must
report `failed` so the turn answers in the chat instead of waiting until expiry.

## 9. Open points for later packages

- Resolved in P10: the created-Project card persists in the Project's own
  encrypted settings, no new store and no backend change. The creating client
  writes `settings.creation = {origin: "assistant_request", request_id, chat_id,
  kind, subfolder}` next to `default_focus` in `encrypted_settings` (Project key).
  A reload finds the card through the chat's active focus binding
  (`GET /v1/projects/focus/current`) and the Project's settings, and only a
  Project whose `creation.chat_id` equals the chat counts. Core API:
  `Projects::created_for_chat`, `Projects::undo_created`; CLI: `projects created
  --chat`, `projects undo-create --chat`. The card is not shown once the focus is
  deactivated or the Project is deleted. Within a turn the core also returns the
  cards as `SendOutcome.project_creations` (camelCase: name, projectId, focusId,
  subfolder, kind, status, undoAvailable, confirmed, errorCode).
- A client advertises `project_create_requests` on the socket **and** in the
  turn request's `client_capabilities` (the preprocessor reads the latter), next
  to `project_file_jobs`. The core opts in via `SendOptions.project_create_requests`.
- After a `project_create_error` for a created Project the core deletes the
  Project and reports `failed` once (never for expired/stale), so no orphan stays.
- Native app requests get the Project and files but no live preview yet.
