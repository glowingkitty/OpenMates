# Task inline embeds: shared contract

Owner decision (Marco, 22 Nov): creating and editing a Task works like code,
sheet and document embeds. Every lane implements against this file.

## 1. Authoring (assistant output)

Creation is an inline fenced block in the assistant reply, never a tool call:

````
```openmates_task
{"title": "Three minutes by an open window", "description": "Short daily pause.",
 "due_date": "2026-11-24", "status": "todo", "assignee": "user", "project": "Kitchen renovation"}
```
````

- Fence languages: `openmates_task` (canonical) and alias `omtask`.
- Fields: `title` (required, nonblank, <= 200 chars), `description` (optional,
  <= 4000), `status` (`backlog|todo|in_progress|blocked`, default `todo`;
  `done` allowed only in edits), `due_date` (optional, `YYYY-MM-DD` or an ISO
  timestamp with offset), `assignee` (default `user`; `user|openmates` in a
  personal chat; in a Team chat a Team member's name/username or `openmates`),
  `project` (optional; a Project name or ref the chat context knows),
  `plan` (optional; the Plan reference, links the Task to that Plan).
- A `start_sub_chats` Task link may name a Task written earlier in the same
  reply by its exact title (the model never sees the new Task id).
- Staging refusals (e.g. an unknown Plan) show on the card as errors.
- Unknown fields are a validation warning, not a failure.

## 2. Validation

`backend/apps/ai/utils/task_fences.py` (pure, unit-tested) returns
`TaskFenceResult(status: "valid"|"invalid", model, source_json, title, errors, warnings)`.
Each error is `{field, code, message}` with codes such as `missing_title`,
`title_too_long`, `invalid_status`, `invalid_due_date`, `unknown_assignee`,
`unknown_project`, `team_tasks_unsupported`, `invalid_json`. Assignee and
Project checks take a context (`known_assignees`, `known_projects`) from the
request; the parser itself does no I/O.

Python API (lane A1 implements, lane A2 imports):

```python
TASK_FENCE_LANGUAGES = frozenset({"openmates_task", "omtask"})
def is_task_fence(language: str | None) -> bool: ...
@dataclass(frozen=True)
class TaskFenceContext:
    is_team: bool = False
    known_assignees: dict[str, str] = {}   # lowercased name/username -> member id (Team only)
    known_projects: dict[str, str] = {}    # lowercased name or ref -> project id
@dataclass(frozen=True)
class TaskFenceResult:
    status: str            # "valid" | "invalid"
    model: dict | None     # normalized: title, description, status, due_date, due_at (unix s|None),
                           # assignee_type ("user"|"openmates"|"member"), assignee_id, assignee_name,
                           # project_id, project_name
    source_json: str       # canonical pretty JSON (indent=2, sorted known keys first) = diff target
    title: str
    errors: list[dict]     # {field, code, message}
    warnings: list[dict]
def validate_task_fence(source: str, *, context: TaskFenceContext, allow_done: bool = False) -> TaskFenceResult: ...
def task_validation_feedback(errors: list[dict]) -> str: ...   # one plain line per error, for history
```

## 3. Stream consumer

On a closed `openmates_task` fence the stream consumer:
1. validates it;
2. when valid, stages the Task create through the existing client-persisted
   task job path (`execute_task_tool_call(TASK_TOOL_CREATE, …)` or a thin
   shared helper), with `title`, `description`, `status`, `assignee_type`,
   `due_at`, `linked_project_ids`, `link_to_chat=True`;
3. creates a finished embed of backend type `task` / frontend type
   `tasks-task` with the content below, and replaces the fence with the normal
   JSON embed reference (same as calendar/mindmap JSON content embeds);
4. when invalid, still creates the embed (status `error` content, no Task),
   so the card shows the errors.

Embed content (TOON/JSON, vault-encrypted in cache like every embed and
client re-encrypted; Task plaintext never leaves the existing encryption
model):

```
{type: "task", app_id: "tasks", task_id, title, description, status,
 due_date, assignee_type, assignee_name, project_name, project_id,
 task_source (canonical pretty JSON of the fence, the diff target),
 validation: {status: "valid"|"invalid", errors: [...], warnings: [...]},
 task_update_job_id}
```

`task_id` is internal (opens the Task); it is never displayed.

## 4. Editing via diff

The assistant edits a Task with ```` ```diff:<embed_ref> ```` against the
embed's `task_source`, exactly like sheets/documents (base diff-editing
instruction lists tasks). The diff applier patches `task_source`, re-validates,
stages a Task `update` job (title/description private patch; status,
assignee, due_at safe metadata), and writes one new embed version (existing
`version_history_rows` path). Invalid result: no Task change, the embed keeps
its content and the card shows the validation errors. Undo on the card
restores the previous version and applies the matching Task update.

## 5. Feedback to the assistant

When an embed is serialized into the next turn's history, a task embed with
`validation.status == "invalid"` includes its errors, so the assistant can fix
it with a diff.

## 6. Removed

- The `tasks.create` app skill (app.yml entry, `create_skill.py`, its tool
  schema and instructions). Legacy `tasks/create` embeds in old chats stay
  read-only renderable.
- The native runtime tool `task_create` (creation is the fence everywhere).
  `task_update/block/complete/unblock/move/reorder` stay for queue execution.
- The chat system event for Task creation (Rust core
  `task_job_payload.rs` no longer writes a system message for `created`).
- Raw IDs anywhere: system events, titles, links, cards use the title or the
  visible short id (`TASK-123`), never a UUID.

## 7. Rendering (web, Apple, CLI)

Card: task icon (`task.svg`, `--color-app-tasks` gradient), title, due date,
status chip; validation errors listed on the card. Fullscreen: the Task detail
plus the version timeline with one Undo. Inline embed links
`[title](embed:<ref>)` to a task embed show the task icon like other embed links.
