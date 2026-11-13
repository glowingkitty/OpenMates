---
status: active
last_verified: 2026-11-02
key_files:
- scripts/claude_dispatch.py
- backend/scripts/check_prod_chat_failures.py
- backend/core/api/app/utils/claude_issue_dispatch.py
- backend/core/docker-compose.override.yml
---

# Claude chat dispatch (admin issue reports and production chat failures)

Two automations open a new Claude Code chat on the dev-server Remote Control
bridge, so the chat shows up in the owner's Claude app and can ask the admin
for input there. Both go through `scripts/claude_dispatch.py`, which runs from
the canonical checkout through cron and opens each chat as its own tab
(named after the chat title) in the persistent zellij session `claude`:

```bash
zellij --session claude action new-tab --name "<title>" -- \
  claude --remote-control "<title>" --model <model> --effort <effort> --permission-mode auto "<prompt>"
```

Issue chats run on `claude-opus-5-5` at `medium` effort
(`CLAUDE_DISPATCH_ISSUE_MODEL`, `CLAUDE_DISPATCH_ISSUE_EFFORT`). Production
chat-failure chats and every other chat started through `launch_claude_chat`
(the private voice connector, daily-meeting decision handovers) default to
`claude-opus-5-5` at `high` effort (`CLAUDE_DISPATCH_MODEL`, `CLAUDE_DISPATCH_EFFORT`).

Fable (`claude-fable-5-2`) is never a default: `launch_claude_chat` refuses it
unless the caller relays an explicit user request (`explicit_model=True`), also
when an environment override names it, and marks such chats with
`OPENMATES_FABLE_REQUESTED=1`. The `fable-guard` SessionStart hook
(`scripts/fable_guard.py`) catches Fable chats started any other way and makes
them stop and ask the user before any work; a prompt naming Fable confirms it.
Each launch is logged with its model in `logs/claude-dispatch/launches.jsonl`.

Chats are interactive sessions, not `claude --bg` jobs. Background jobs are
retired after about 8 hours idle at a prompt, so a chat waiting for the admin's
answer went offline in the Claude app and could not be resumed there. A tab
stays connected until it is closed. If the `claude` zellij session is missing
or exited, the dispatcher recreates it with a `remote-control` tab running the
`claude remote-control` bridge (for chats started from the app). It sets
`XDG_RUNTIME_DIR` because cron lacks it and zellij would not see the live session.

Prompts are built only from validated identifiers and server-defined labels.
No report text or log message text is ever put into a prompt. The chat reads
those details itself through the debug tooling and treats them as data.

## 1. Admin issue report → Claude chat (development server)

1. On the development web app (`isDevEnvironment()`), admins see **Send to
   Claude chat directly** in Report Issue. It is on by default and can be
   switched off for each report.
2. `POST /v1/settings/issues` with `send_to_claude_chat=true` calls
   `handoff_admin_issue()`. It only acts when the user is an admin **and**
   `SERVER_ENVIRONMENT=development`; it fails closed otherwise. It atomically
   writes `issue-<SHORT>.json` (`kind`, `issue_id`, `short_issue_id`,
   `queued_at`) to `CLAUDE_DISPATCH_QUEUE_DIR`.
   - That directory exists only through the dev compose override:
     `logs/claude-dispatch/queue` → `/app/claude-dispatch-queue`.
   - The issue row gets `agent_action=claude_chat` and
     `agent_status=queued|unavailable`.
   - The response returns `claude_chat_status`, which the confirmation page
     shows.
3. Cron `* * * * *` runs `claude_dispatch.py issues`. It validates the IDs,
   opens one chat per issue (at most 3 per run) with `/debug-issue <id> --env
   dev`, and moves the file to `logs/claude-dispatch/processed/{ok,failed}/`.

## 2. Hourly production chat-failure check

Cron `17 * * * *` runs `claude_dispatch.py prod-errors`. That runs
`backend/scripts/check_prod_chat_failures.py` in the dev `api` container,
which queries production OpenObserve through the Admin Debug API
(`/o2/search`, Vault key `admin_debug_cli.prod_api_key`).

The check uses only signals that users cannot fake:

| Source | Counts as a failure | Why it is trustworthy |
| --- | --- | --- |
| Traces | `ai_terminal_class` in failed_before_main/failed_during_main/billing_failed/soft_limited/worker_interrupted, or `ai_status_class=error` on a user-facing phase | Structured attributes set by server code from reviewed enums (`ai_observability.py`) |
| Logs | `ERROR`/`CRITICAL` JSON lines whose logger `name` is one of the allowlisted chat-pipeline loggers on `app-ai-worker`, `app-ai-routing-worker` (or the API `message_received_handler`) | The logger name and level are set by the JSON formatter, not by message text |

Rules the check follows:

- It never matches free text. The API logs request query strings verbatim, so
  a `LIKE '%marker%'` search can be triggered by anyone who sends a request.
- Provider, tool and `main.iteration` span errors are reported as **context**
  only. They usually recover through fallbacks and never open a chat on their
  own.
- It does not use the `[CHAT_FAILURE_EMAIL]` alert as a signal, because
  `failure_stage()` also reacts to error strings in model output.
- Log messages are reduced to a one-way fingerprint (logger + normalized
  shape). Only fingerprints, labels, counts, trace IDs and task IDs leave the
  checker.

When new impact fingerprints appear (24 h cooldown per fingerprint, state in
`logs/claude-dispatch/prod-errors-state.json`), one chat is opened with the
following instructions:

- investigate against `origin/main`;
- fix on dev when the cause is clear;
- ask the admin in the chat when the cause is unclear, risky, needs a
  production change or needs a product decision.

If a query fails, the run exits 2 and writes an `error` report; it is never
treated as "no failures". Every run writes
`logs/nightly-reports/prod-chat-failures.json` for the daily meeting.

## Operations

```bash
# crontab (dev server)
* * * * * cd /home/superdev/projects/OpenMates && python3 scripts/claude_dispatch.py issues >> logs/claude-dispatch/cron.log 2>&1
17 * * * * cd /home/superdev/projects/OpenMates && python3 scripts/claude_dispatch.py prod-errors >> logs/claude-dispatch/cron.log 2>&1

python3 scripts/claude_dispatch.py prod-errors --dry-run   # check without opening a chat
tail logs/claude-dispatch/launches.jsonl                    # launched chats
```

Resume a dispatched chat from the Claude app (it keeps its title) or on the
server with `zellij attach claude` and switch to its tab. Close the tab (or
`/exit`) when the chat is finished; chats are not retired automatically.
