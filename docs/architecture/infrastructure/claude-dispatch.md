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
`claude-opus-5-5` at `medium` effort (`CLAUDE_DISPATCH_MODEL`, `CLAUDE_DISPATCH_EFFORT`).

Effort cap (owner, 2026-11-22): no chat runs above `medium`. `cap_effort` lowers
`high`, `xhigh`, `max` and unknown values, including environment overrides and
queued starts. A resumed chat (waiter, WIP wake-up, connector reopen) keeps its
original effort from its transcript (`chat_effort`), capped at `medium`.

Engine routing uses the weekly Claude reading from `scripts/claude_usage_guard.py`
and the owner’s explicit model choice. With more than 30% left, the host keeps Opus
for complex work and Sonnet for simple work. At 30% or less, new chats default to
`gpt-6.2-sol`. Security and encryption stay on Claude above 10% remaining. A model
the owner names always wins.

Below 10% remaining, active Claude work writes its handover on the Task at the
next turn boundary. The lifecycle suppresses Claude wake-ups and sends stopped
work with a saved handover to a fresh Codex chat. It keeps the workspace and Task
and archives the source chat. A stopped chat without a saved handover waits.
The live voice call is exempt. The host can designate one already-running job
to finish in the current weekly window. That designation expires at reset.

Codex work waits when Codex is unavailable. When a rate-limit window reaches
zero, the dispatcher sends a single short capacity notice and resumes queue
draining after capacity returns. The usage guard stores its reading in
`~/.cache/openmates/usage-guard/weekly-model.json`.

Codex chats (`scripts/codex_chats.py`): `gpt-6.2-sol` by default, `gpt-6.2-astra` only
when named, effort fixed at `medium`, opened as a tab of the `claude` zellij session with
`OPENMATES_CHAT_ID` (= `CLAUDE_CODE_SESSION_ID`) so sessions, waiters, pushes and Task
links work unchanged. They share the running-chat cap (`claude_idle_chats admit`), are
stopped by the lifecycle after their ✅/❓ push like Claude chats (`codex_chats.reap`), and
are mirrored as Claude-format transcripts (`~/.openmates/codex-chats/transcripts/`) for
list_chats, chat_detail and the briefing. They obey the same rules: `AGENTS.md` is
generated from `CLAUDE.md`, rules and skills (`scripts/agents_md.py`; `sessions.py deploy`
regenerates it in every deploy, so a rule change never leaves it stale on dev; CI
`agents-md-sync.yml` fails on drift), and the fixed `.codex/hooks.json` sends every Codex
hook event to `scripts/codex_hook_adapter.py`, which runs the matching hooks of
`.claude/settings.json` (apply_patch is split into one Edit/Write payload per file) plus
two built-in guards (sub-agents keep model and medium effort; the Codex hooks and config
cannot be changed or switched off from a chat). Git hooks, the deploy freeze and the push
rules in `agent_question.py` are engine-independent already. `codex_setup.py check`
must pass before a Codex chat starts; a stale `AGENTS.md` only warns there, it never
refuses a start (owner, 23 Nov).

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

Before a tab opens, `launch_claude_chat` asks the chat lifecycle for room
(`claude_idle_chats.py admit`, cap of running chat processes). When the cap is
full, the chat waits in `logs/claude-dispatch/pending/` and the caller gets
`ChatQueued`; the `issues` cron run starts queued chats oldest first. Details:
[dev-host-resources.md](dev-host-resources.md).

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

## AI test-user reports

Owner, 23 Nov 2026: after each daily run, `scripts/ai_test_users_triage.py` sorts every
issue (kept findings grouped by cause per environment):

- Clear functional errors start a chat by themselves: console errors or exceptions, hangs
  or timeouts, raw JSON or code shown instead of an embed, failed sends, crashes, broken
  flows. The run calls `claude_dispatch.launch_test_user_chat(issue_id, short_id, env)`
  directly (same title, prompt, small-fix scope and daily cap as the queue path).
- Subjective UI, design or wording findings, slow but finished answers and findings the
  environment may explain (suspect) never start a chat. The run message lists them as
  waiting for Marco's approval; `python3 scripts/ai_test_users.py debug --env <env> --issue
  <short>` starts the chat once he approves (outside the daily cap).
- Before a chat starts, open OpenMates Tasks, running Claude chats (`agent_peers.peers`) and
  the debug chats the pipeline started in the last 2 days
  (`~/.openmates/ai-test-users/debug-chats.jsonl`) are checked for the same issue id, short
  id or a similar title; a match is linked in the message instead of a new chat. When the
  Tasks cannot be listed, no chat starts and the message says so.
- `python3 scripts/ai_test_users.py message --run <run-id>` is a dry run of a run's message
  (routes and coverage are real; nothing starts).

Issue requests in `queue/` may also carry `"origin": "ai_test_user"` and `"env": "dev"|"prod"`
(any other origin is rejected), written with
`claude_dispatch.queue_test_user_issue(issue_id, short_id, env)` (atomic write).

Rule: an AI test user never triggers feature work or large changes. Its investigation chat
(`AI test user issue <short>: investigate`) uses `ai_user_issue_prompt`: it classifies the
report first and implements only a small, clear bug; features, design/wording opinions,
product decisions, large changes and architecture decisions become one OpenMates Task for the
owner (label `ai-test-users`) and the chat stops without editing code. Such chats never ask
the owner questions mid-chat.

- Cap: at most 3 such chats per UTC day (`test-user-issues-state.json` next to the launch
  log). Above it the queue file moves to `processed/deferred/` and the launch log records a
  `deferred` line; the run message shows a deferred issue as "no debug chat yet".
- Enforcement: the chat starts with `OPENMATES_CHANGE_SCOPE=small-fix`. `sessions.py start`
  stores `change_scope` on the session (never dropped afterwards) and `sessions.py deploy`
  refuses when `scripts/change_scope.py` finds more than 6 changed files, more than 150
  changed non-test lines, a new non-test source file, a change under
  `backend/core/directus/schemas/`, migrations, `docs/plans/`, `specifications/`, or a new
  API route decorator.
