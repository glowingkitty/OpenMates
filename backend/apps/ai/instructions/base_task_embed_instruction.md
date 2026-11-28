
**Creating and Editing Tasks**

When the user asks to create, track, or edit a Task, use the Task workflow even if the request includes a date or deadline. A Task due date belongs on the Task. Only schedule a reminder when the user asks for a notification or scheduled follow-up. Use the Tasks search skill to find existing Tasks.

Create a Task only by writing an inline `openmates_task` block in your reply, at the point where the task card should appear. Never call a tool to create a task. Write one block per task, containing one JSON object:

```openmates_task
{"title": "Three minutes by an open window", "description": "Short daily pause.", "due_date": "2026-11-24", "status": "todo", "assignee": "user", "project": "Kitchen renovation"}
```

**Fields:**
- `title` (required, at most 200 characters), `description` (optional, at most 4000 characters).
- `status`: `backlog`, `todo`, `in_progress` or `blocked`. Default `todo`. Use `done` only when editing an existing task.
- `due_date`: optional, `YYYY-MM-DD` (a real date) or an ISO timestamp with a UTC offset.
- `assignee`: `user` (default) or `openmates` in a personal chat. Task creation through a chat is available in Personal chats. Only assign `openmates` when the user clearly asks OpenMates to do the work.
- `project`: optional, only a Project name or ref that is known in this chat.
- `plan`: optional, only the Plan reference you got back when that Plan was created; it links the task to the Plan.
- Do not add other fields, never write task ids, and never claim a task exists before its block.

To start a sub-chat for a task you just wrote, link it with the task's exact title as the id (`{kind: "task", plan_id, id: "<title>"}`).

If a task card reports problems (for example an unknown Project or an invalid date), fix it with a diff against that task, not with a new block.

**Editing an existing task:** patch the task source of the task embed with a `diff:<embed_ref>` block, the same way as for code or documents. The task source is the pretty-printed JSON shown above, one field per line:

```diff:three-minutes-by-an-open-window-k8D
@@ -2,5 +2,5 @@
   "title": "Three minutes by an open window",
   "description": "Short daily pause.",
-  "status": "todo",
+  "status": "done",
   "due_date": "2026-11-24",
   "assignee": "user"
```
