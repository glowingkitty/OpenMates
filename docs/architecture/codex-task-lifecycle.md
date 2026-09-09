# Codex Tasks and the global CLI

The current Codex runtime uses [Task cache and delivery](codex-task-cache.md).
The globally installed `openmates` CLI retains the personal dev-testing login;
foreground `remote-access` owns Project sync and durable delayed delivery.

Every repository chat receives all of its linked Tasks from the selected Project
cache, including status, existing blockers, shortened description and latest
activity. Orchestrators also see their registered workers' Tasks. Unchanged tools
add no repeated context or Task API requests.

Create and link with `openmates tasks create --title "Concrete outcome"
--external-chat codex:<current-chat-id> --project <project-id>`. Ordinary CLI
creation is unlinked. Break complex work into multiple Tasks and dependencies.
Update status when work changes and activity at useful milestones. Wait for
acknowledgement before claiming ownership or reporting completion.

The old `codex_task_lifecycle.py` per-turn outcome protocol is a legacy fallback,
not the current agent workflow. Do not invoke it to satisfy an exact-summary or
next-action final-text requirement. Repository-wide cached context bypasses those
old lifecycle and response-table checks. Existing chat history may still contain
old instructions; current repository instructions take precedence.

During an outage, preserve queued operation IDs and let the foreground process
retry. Previously owned work can continue; a pending new claim grants no ownership.
If the executable is unavailable, use the private queue writer documented in the
Task-cache guide. Never change account/profile to get around an auth failure.
Signup smoke tests use explicitly isolated state and never replace the global
engineering Tasks login.
