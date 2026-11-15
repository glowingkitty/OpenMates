---
status: active
last_verified: 2026-11-15
key_files:
- scripts/host_load_guard.py
- scripts/host_resources.py
- scripts/claude_idle_chats.py
- scripts/claude_chat_waiters.py
- scripts/disk_coordinator.py
- scripts/claude_dispatch.py
- scripts/heavy_slot.py
- .claude/hooks/host-load-gate.sh
---

# Dev host resources: memory guard, chat lifecycle, disk

The dev server (16 cores, 31 GB, no swap) runs dozens of Claude Code chats, the dev
stack and local builds. Three parts keep it usable without manual cleanup.

## 1. Memory guard (`scripts/host_load_guard.py`)

Memory is judged by **pressure**, not by free RAM: the host blocks new work when
memory PSI `some avg10` > 20 (tasks really stall), MemAvailable < 1.5 GiB (the OOM
floor) or load1 > 3× CPUs, and resumes when PSI < 10, MemAvailable > 2.5 GiB and
load1 < 1.5× CPUs. The old rule (block below 3 GiB, resume above 5 GiB) held every
prompt for hours on 2026-11-14 with 4.5 GiB free, load 3/16 and PSI 0.

What an overload does:

| Caller | Effect |
| --- | --- |
| New prompt (UserPromptSubmit hook) | Held, never refused: the hook waits up to 9 min (spinner: "Waiting: the dev server is short on memory…"), then the prompt runs. Afterwards a system message says how long it waited. |
| New sub-agent (PreToolUse Agent) | Denied with a wait hint. |
| New session (SessionStart) | Instruction to wait (`host_load_guard.py wait`). |
| `heavy_slot.py run` | Waits for a slot; local runs also need their class cap plus a 3 GiB floor free. |

## 2. Chat lifecycle (`scripts/claude_idle_chats.py`, timer every 5 min)

| State | When | What happens |
| --- | --- | --- |
| Working | busy, waiting for a permission/answer, background command, or active within `idle_stop_minutes` | runs |
| Idle-stopped | idle ≥ `idle_stop_minutes` (60) and nothing open | SIGTERM (graceful); transcript kept; connector `send_message` resumes it with `claude --resume` |
| Done | idle ≥ `done_hours` (24), finished | listed in `status.json` for the connector to archive in the Claude app |

Activity is the session record's state time plus the newest record timestamp in
the transcript and sub-agent transcripts. File mtime is not used, because Claude
Code rewrites idle transcripts in place on bridge reconnects.

Never stopped: chats started by hand in a terminal (only Remote Control workers
and chats in a zellij pane of `zellij_sessions` are managed), the running chat, a
chat that is not idle, one with a background command, and one whose last turn is
a message without a reply (including a refused prompt). Idle stop and done also
keep a chat whose last reply asks something.

Cap: at most `max_running` (20) chat processes. Beyond that the longest-idle
chats are suspended, those without an open question first; a chat with an open
question only after `cap_question_idle_hours` (4) without an answer.
`claude_dispatch.launch_claude_chat` (also used by the connector's `start_chat`)
asks `claude_idle_chats.py admit` first. When there is no room, the chat waits in
`logs/claude-dispatch/pending/` and the caller gets `ChatQueued`. The per-minute
`claude_dispatch.py issues` run starts queued chats oldest first.

Settings: `logs/claude-chat-lifecycle/config.json` (keys as in `DEFAULTS`).
Output: `status.json` (counts and the done list), `stopped.json` (stopped chats
with their resume command), `events.jsonl`. The connector reports archiving with
`claude_idle_chats.py mark --session <id> --state archived`. The counts appear in
the daily meeting briefing ("Chats waiting on you") and the connector's
chat_changes.

### Waiting on background work

A chat that waits on something is never stopped as idle, done or by the cap
(`scripts/claude_chat_waiters.py`). On 2026-11-15 chat d2a774d9 parked its CI step
on a disk-coordinator wait (disk at 91%) and told the owner "the coordinator
notifies me". Only the Codex adapter delivered such notices, so the lifecycle saw
an idle chat, stopped it after 64 min, and it stayed closed for two hours after
the disk was cleaned (TASK-662). Now one *waiter* list covers every kind:

| Waiter | Source | Over when | Timeout |
| --- | --- | --- | --- |
| disk | disk-coordinator ledger request with the chat id as `thread`, state waiting or granted | granted, or the coordinator marked a parked request ready | 6 h |
| ci | CI job of the chat's sessions.py session (`.claude/sessions.json` `agent_task_id`, queue column `owner`) in state queued, dispatching, submitted, running or attention | the job reaches success, failure or cancelled | 4 h |
| handoff, background | registered by the chat: `claude_chat_waiters.py add --kind handoff --on "<what>" [--timeout-minutes N]` | the other side runs `claude_chat_waiters.py fire --chat <id> --key <key> --message "…"` | 4 h |

A disk request that is older than a later request of the same chat that went
through does not count: the chat moved on (most of the 190 waiting ledger rows
on 2026-11-15 were such leftovers of CI result downloads).

- **Waking.** Each lifecycle cycle (5 min) wakes every chat whose wait is over,
  through one path for all kinds: an idle zellij-pane chat gets one line typed
  into its pane (`[chat lifecycle] A wait of this chat is over, so it was woken:
  …`); a chat that is not running (stopped by the lifecycle, killed with its
  zellij server, closed while waiting) is reopened with `claude --resume` and
  that line as its next message (`claude_dispatch.resume_chat`, tab `wake
  <id>`), within the cap of running chats. A busy chat is woken on a later
  cycle, a chat whose last reply asks the owner something waits for the answer,
  and an archived chat is never reopened. Each ready set is delivered once
  (`waiter_wakes.json`); a failed reopen is retried and listed as stalled. A CI
  job that ended while its live chat was active again (its own background
  waiter brought the result) does not wake it twice. Events `waiter_woken` /
  `waiter_wake_failed` go to `events.jsonl`.
- **Timeout.** A waiter past its timeout is `stalled`: it no longer keeps the
  chat from idle stop and is listed in `stalled`, but it still reopens the chat
  if it ends later.
- **Unreadable sources.** When the ledger or the CI queue cannot be read, every
  chat is kept that cycle, with a warning.
- **Status.** `status.json` has `waiting` (per chat: running or closed, the
  waiters with state waiting/ready/STALLED, since, stalled, ready) and the counts
  `waiting_running` and `waiting_closed`. The connector's `chat_changes` lists
  these chats under "Waiting on background work (disk, CI, handoff)" instead of
  "Finished a turn" or "Stopped by the chat lifecycle", and `host_status` counts
  them apart from idle chats with one line per chat. `claude_chat_waiters.py
  list` prints every chat's waiters.
- **Undelivered notifications.** Claude Code delivers a finished background job as a
  `<task-notification>` prompt. When the UserPromptSubmit host-load hook refuses it
  (transcript `system` record "UserPromptSubmit operation blocked by hook",
  `promptKept: false`) nothing re-delivers it (`scripts/claude_chat_pending.py`).
  Such a refused notification is
  undelivered until a later prompt carries the same task id; a later assistant
  reply clears it. Chats with undelivered notifications are kept, and `release`
  skips them and refusals with `promptKept: false`; for a kept prompt it presses
  Enter once per refusal (`released.json`).
- **One-time wake.** Each cycle wakes an idle pane chat with undelivered
  notifications once per task set (`woken.json`): Ctrl+U to empty the input box, a
  line naming the task ids and output files, Enter. Events `woken` / `wake_failed`
  go to `events.jsonl`.
- **Stalled list.** `status.json` has `stalled_chats` and a `stalled` list: chats
  woken without a reply, chats that could not be woken, busy chats or chats with
  a background command quiet for 30 minutes, waiters past their timeout, wakes
  that failed, and stopped or done chats whose transcript holds undelivered
  results (listed with the resume command, never woken).

Pushes that reach the user through `scripts/agent_question.py` (and
`scripts/e2b_credits.py`, which calls its `record_push`) are appended to
`logs/agent-questions/pushes.jsonl` (time, chat id and title, text, what it asks),
so the connector can match a push to its chat. Push text is scrubbed before
sending (`agent_question.scrub`): webhook URLs, emails, private keys, JWTs,
bearer and prefixed API tokens, `NAME=value` values and other long random tokens
become `[removed]`. Task and chat UUIDs, 40/64-char hex hashes, ENV/snake/kebab
names and presigned links to our own `openmates-*` buckets on the object storage
stay intact. Pushes longer than one Discord message go out as up to four parts,
split between words so links are never cut.

## 3. Host-resources tick (`scripts/host_resources.py`, every minute)

`host_load_guard.py monitor` (openmates-host-load-guard.timer) samples memory, then:

1. Memory overloaded: `claude_idle_chats.py reap --pressure` (idle limit
   `pressure_idle_minutes`, 15), at most every 5 min.
2. Healthy with more than 4 GiB free: `claude_idle_chats.py release --limit 2`
   resubmits prompts that an older hook version refused, when they are still
   typed in the chat's input box (checked with the probe below; a suggestion
   counts as lost, never as released).
2b. Every tick: `claude_chat_inputs.py watch` refreshes
   `logs/claude-chat-lifecycle/inputs.json` (see "Input boxes" below).
3. Disk: more than 92% used or less than 20 GiB free on the repository
   filesystem. Cleanup belongs to the disk coordinator; the tick checks that
   `openmates-disk-coordinator.service` runs.
4. A memory or disk problem that lasts 20 min despite self-healing sends one
   "feedback needed" Discord push per incident (`agent_question.py`).
   `resources_recovered` is logged when it ends.
5. zellij: each zellij server (the `claude` session holds every pane chat) is
   checked for more than 2 GiB RSS or more than 200% CPU since the previous
   tick (`zellij_over_limit` event). Over a limit for 5 min sends one push.
   Nothing is restarted automatically: a restart kills every chat pane in it.

## zellij session

All pane chats and the `remote-control` bridge run as tabs of one headless
zellij session, so its server's memory is the sum of every pane's scrollback.
On 2026-11-14 it grew to 8.5 GiB with about 20 chats on the default
10,000-line scrollback and two bar plugins per tab. The kernel then OOM-killed
it, and every chat in it went down with it. The same night, two `systemctl --user restart openmates-dev-mcp-broker` runs
killed it again. The broker had started the server, so the server and every pane
lived in the broker's cgroup (`KillMode=control-group`). `claude_dispatch.ensure_zellij_session`
now starts a new server with `systemd-run --user --scope`
(`openmates-zellij-claude-<epoch>.scope`). Panes are the server's children and
stay in that scope, so restarting the broker or a timer no longer kills chats.
The owner's `~/.config/zellij/config.kdl`
therefore sets `scroll_buffer_size 2000`, `default_layout "compact"` (one bar
plugin per tab) and `session_serialization false` (nothing resurrects sessions;
`claude_dispatch.ensure_zellij_session` recreates a missing one). Chat history
lives in Claude transcripts, not pane scrollback: a killed chat reopens with
`claude --resume <id> --remote-control <title>` in a new tab. The lifecycle's
idle stop and cap of 20 keep the number of panes bounded, so a failing
`openmates-claude-idle-chats.service` is a direct path back to this overload.

State: `logs/host-load-guard/resources.json`; events in `logs/host-load-guard/events.jsonl`.

## 4. Unfinished work in worktrees (`scripts/worktree_wip.py`)

Before the dev-to-main pull request of 2026-11-15 the release-readiness gate
reported 42 blocking worktrees: 31 were clean and already on dev (the gate
blocked on anything idle under 96 h), the rest held uncommitted work of chats
that had ended or been stopped (TASK-9700). Now:

- Snapshots: the Stop hook `.claude/hooks/wip-snapshot.sh` (every turn end) and
  the `openmates-worktree-wip-sweep` timer (every 30 min) commit each dirty
  session worktree to `refs/openmates/wip/<session>` in the shared object store,
  through a temporary index (the worktree, its index and HEAD are untouched;
  files over 25 MiB are listed, not committed). The ref outlives the worktree
  and the chat. It is pushed only to a configured private remote
  (`wip_remote` in `logs/worktree-wip/config.json` or `OPENMATES_WIP_REMOTE`);
  the public `origin` is refused, because WIP has passed no deploy gate.
- Lifecycle: before the chat lifecycle stops a chat whose worktree holds files
  not on dev, it snapshots the worktree and types one finish prompt into the
  chat's pane; the chat gets 60 min to commit, test and deploy, or to park the
  work. A chat that cannot be woken (Remote Control worker), does not act or
  is stopped under memory pressure is stopped with its work snapshotted and is
  listed in `status.json` (`stopped_with_unfinished_work`; `unfinished_work`
  and `stalled` while it stays stopped), which `chat_changes` and
  `chat_housekeeping` show.
- Parking: work that must wait (an owner answer, another priority) is parked
  by its chat: `worktree_wip.py park --session <id> --reason "<why>"`. A parked
  worktree is not woken and does not block the release; the park ends when the
  worktree changes.
- Readiness: `sessions.py worktree release-readiness` judges content, not idle
  time. Clean, integrated or duplicated worktrees and integration-checkout
  residue older than 2 h pass; unfinished unparked work blocks. The
  `openmates-worktree-readiness` timer runs it nightly (02:30 UTC) after a
  sweep, writes `logs/worktree-wip/readiness.json` for the daily meeting
  ("Unfinished work in worktrees") and resumes up to 3 stopped owner chats with
  a finish prompt (`claude_dispatch.resume_chat`), once per worktree state.
  Owners without a transcript on the host are listed for the owner.
- Rule (`CLAUDE.md`, `AGENTS.md`): done means committed, tested and deployed
  to dev; a chat never ends its work with uncommitted changes.

## Setup

`scripts/host-load-guard-setup.sh` and `scripts/claude-idle-chats-setup.sh` install
the systemd user timers. `scripts/worktree-wip-setup.sh` installs the WIP sweep and nightly readiness timers.

## Input boxes: typed text or Claude's suggestion

Claude Code shows its predicted next prompt as grey ghost text in an empty input
box, and `zellij action dump-screen` has no colours, so a dump cannot tell it from
a message someone typed and did not send. On 2026-11-14/15 this made the dev
connector's send_message refuse six chats for hours ("its input box still holds an
earlier unsent message ... held while the dev host is overloaded"), and `release`
pressed Enter on them every minute without effect: every one was a suggestion over
an empty box. The host-load hook held no prompt in that time (no `prompt_held`
event); since 1661195 it never refuses and lets a prompt run after at most 9 min.

`claude_chat_inputs.probe` types one letter: a suggestion disappears and the box
shows only that letter; typed text gets it appended. The letter is deleted again.
`watch` records per running pane chat the shown text and when it was first seen,
and probes text that stays unchanged for 10 min in an idle chat once
(`verdict`: `typed`, `suggestion` or `unchecked`; `unsent_input` event for typed
text). It never presses Enter.

The connector (private, outside this repo) uses the same probe before typing:
a suggestion never blocks a message; typed text is never merged with a new one.
send_message `held=auto` replaces typed text older than 30 min (age from
`inputs.json`, a copy is logged) and otherwise shows both texts for the caller to
choose `replace` or `send_first`. host_status lists the typed entries as the queue
of unsent messages.

Unconfirmed deliveries (2026-11-15, 76c8264a: a send to a busy chat sat in its box for
2 h): a busy chat either takes a typed message into its queue, which Claude Code writes
to the transcript only when the current step ends, or leaves it in the box (Enter not
taken; long text shows as `[Pasted text #N]`). The connector presses Enter again at
once while its text is still in the box, and lists every delivery it could not confirm
in `logs/claude-chat-lifecycle/connector-deliveries.json`. Its broker re-checks them
every 30 s: delivered once the transcript shows them, Enter again while they sit in
the box, otherwise `undelivered` (shown in host_status and chat_changes, never
dropped). `watch` reads that file and records a chat whose box shows such a delivery
as `typed` (source `connector`, age from when it was typed) even while the chat is
busy, without probing it.

