# Codex Task lifecycle and global CLI

Codex task context, meeting collection and lifecycle transport use only global
`openmates`, inheriting the existing auth/account context. Failed binaries/auth
remain visible; no source CLI, profile override or alternate account is used.
Codex is the current source default; OpenCode records retain their identity.

The CLI list requests the existing server maximum of 500. Below that boundary,
it returns `complete: true`; at the boundary it fails `TASK_LIST_INCOMPLETE`
instead of claiming completeness. This conservative contract also rejects
undecryptable rows. More than 100 records work; inventories reaching 500 require
server pagination before exhaustive collection is possible. Status-filter unions
are no longer treated as exhaustive. This uses the existing first-party session /
approved-device encrypted Task route, unchanged auth/rate limits and no credits.

SessionStart/UserPromptSubmit activates at most one runnable Codex-owned Task;
existing active/blocked work is preserved. Explicit outcomes reuse `task_bridge`
in sessions state, and the CLI encrypted activity outbox. Activity acknowledgement
precedes status transition. Retried status reads avoid duplicate mutations;
failed/uncertain delivery retains pending intent for the next boundary. No paid
inference or commentary-triggered writes occur.

Before a final response, use `scripts/codex_task_lifecycle.py --help` to persist
in_progress, blocked or done with the current turn ID, exact summary and next
action. Blockers require a reason; approval blockers require a link. Stop checks
the current turn, authoritative Task state and final text. It does not infer
completion from prose or turn an active operation into a blocker. Already-blocked
work resumes through an explicit in_progress outcome after its dependency clears.
No Task is created or reassigned by these hooks. An unbound Task is reported as
missing context, not repaired by recreating records.

The global stable 0.18.0 build can compare newer than a current dev prerelease.
The supported explicit channel repair is `openmates update --channel dev
--allow-downgrade`; verify installed command capabilities afterward. Normal dev
publication remains the existing Publish CLI workflow and npm alpha channel.


## Shared API admission and deferred delivery

All hook/lifecycle global CLI requests share a nonblocking advisory lock beneath
canonical `logs/codex-task-context/`. The lock covers the subprocess, so concurrent
chats cannot create a request burst. Duplicate list reads within one short-lived
hook process reuse the same response; mutations invalidate that response. No
cross-account Task response cache is introduced and CLI auth environment is inherited.

HTTP429 establishes one shared cooldown: Retry-After seconds when present in CLI
stderr, otherwise120 seconds with exponential backoff up to1800 seconds. The
currently installed CLI does not expose the response headers, so the conservative
fallback applies. Timeouts establish30 seconds of cooldown. Other chats do not
invoke the CLI while the request slot is busy or cooldown is active. This gate
covers hook/helper requests, not manually invoked global CLI commands.

Pending lifecycle intent is saved before delivery and retains its delivery ID.
Rate limiting never acknowledges completion. A deferred Stop emits a visible
system warning and `continue:false`, avoiding an automatic retry loop; its
existing pending intent is reconciled at a later start/resume after cooldown.
No background retry scheduler or daemon restart is required. A final response
must disclose unacknowledged delivery instead of asserting persisted completion.
