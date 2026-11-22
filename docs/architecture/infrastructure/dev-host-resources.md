---
status: active
last_verified: 2026-11-15
key_files:
- scripts/host_load_guard.py
- scripts/host_resources.py
- scripts/claude_idle_chats.py
- scripts/claude_chat_waiters.py
- scripts/disk_coordinator.py
- scripts/host_disk_root.py
- scripts/host_disk_usage.py
- scripts/host_disk_budgets.py
- scripts/claude_dispatch.py
- scripts/zellij/chat-session.kdl
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

## 2. Chat lifecycle (`scripts/claude_idle_chats.py`, timer every minute)

| State | When | What happens |
| --- | --- | --- |
| Working | busy, waiting for a permission, background command or waiter, or its turn ended less than `idle_stop_minutes` (3) ago | runs, holds a slot |
| Idle-stopped | turn ended ≥ `idle_stop_minutes` ago and nothing runs or waits in the background, also when it waits on the owner's answer or parked itself | SIGTERM (graceful); transcript and open question kept; connector `send_message` or its waiter resumes it with `claude --resume` |
| Archived | reported done with a ✅ push (no `--paused-until`), no ❓ after it, its reply does not end with a question, no waiter (the push decides: wording such as "waiting on your answer" inside a report does not keep it open) | pane chat: `/exit` (archives its Claude app session) and its pane closed; otherwise stopped as done with `reported_done` and archived by the connector without approval |
| Done | idle ≥ `done_hours` (24), finished | listed in `status.json` for the connector to archive in the Claude app |

Owner rule (2026-11-20): only working chats and chats waiting on a background job
hold one of the `max_running` slots. After the weekly usage reset 13 of 20 slots
were held by idle chats for about an hour, and new chats could not start.

Activity is the session record's state time plus the newest record timestamp in
the transcript and sub-agent transcripts. File mtime is not used, because Claude
Code rewrites idle transcripts in place on bridge reconnects.

Never stopped: chats started by hand in a terminal (only Remote Control workers
and chats in a zellij pane of `zellij_sessions` are managed), the running chat, a
chat that is not idle, one with a background command or an open waiter, and one
whose last turn is a message without a reply (including a refused prompt). A chat
that waits on the owner is stopped but stays listed as waiting with its question
(stopped.json `open_question`, the briefing's waiting chats).

Each cycle also declines Claude Code's auto-mode setup offer ("Teach auto mode
about your environment?", Esc) in pane chats, which otherwise sat behind it for
days as `waiting`, and tidies the managed zellij sessions: panes whose process
ended (seen dead in two cycles 2 minutes apart; with their tab when it was the
only pane), empty tabs, and the `zellij:link` background plugin. On 2026-11-20 the
`claude` session held 58 dead panes and 57 empty tabs of 72, and the link plugin's
thread had used 43 CPU hours; closing them took the server from about 110% CPU
and 900 MB to 29% and 180 MB with every chat still running.

Waking after a wait reopens at most `wake_batch` (3) closed chats per cycle, a
finished job's result before a timer, then by the chat's Task priority (hourly
Tasks copy), and leaves `free_slots` (4) slots for new chats. A handoff waiter
past its timeout shows as "timed out" (not STALLED) and is dropped 24 hours later;
only timed-out disk, CI and background waiters count as stalled.

Cap: at most `max_running` (20) chat processes. Beyond that the longest-idle
chats are suspended, those without an open question first.
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

### Only done, asking or waiting chats are closed (TASK-7707)

Owner rule 2026-11-21: the lifecycle closes a chat only when it reported done (✅ push), asked
the owner (❓ push or a closing question) or registered a waiter. A turn that ends any other way
gets a continue prompt typed into its pane (`scripts/claude_chat_continue.py`: once per turn
end, retried after 10 minutes, at most 3 in a row without tool work); a chat that cannot be
woken or does not act keeps running and is listed as stalled. Running background sub-agents
keep their chat open. The cap never suspends such a chat; memory pressure may, and then a
timer waiter reopens it after 30 minutes. The zellij tidy leaves a session alone when its pane
listing is incomplete (no terminal pane, panes without tab, or a live pane missing) and closes
an empty tab only after seeing it empty twice: on 2026-11-20 it closed every tab of the
`claude` session twice, with working chats in them.

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

Every chat tells the user on Discord exactly once when it is done or blocked,
with `scripts/agent_question.py`: `done` sends "✅ <short title>: <result>" (also
for a parked or paused chat, with `--paused-until`), `ask` sends "❓ <short
title>: <decision>. Recommendation: …". The chat writes the short text itself because
the push is read on a phone lock screen (`scripts/discord_summary.py`): done at most 110
characters, ask (question plus recommendation) at most 120, title at most 30 characters
(Task id removed); a link counts as one character. Markdown, Task/chat ids, commit hashes,
list markers and icons the chat wrote are stripped, so exactly one icon goes out. Text over
the limit is rejected (exit 1, "rewrite it in under N characters, one sentence"); the rejection
count is kept per chat and kind in `logs/agent-questions/rejections/<chat-id>.json` (dry runs
do not count, a delivered push resets it). After two rejections one headless `claude -p --model
haiku` call shortens the scrubbed text (platform login, no tools, no project instructions; a
tiny comparison is below), and if that fails or is still too long the text is cut
at a word boundary with "…". The production monitors (`prod_email_health.py`,
`prod_tls_health.py`) build their 🚨/✅ lines with `discord_summary.alert` (one line, 140
characters). No progress pushes, never both for one event, one of each kind per chat per 20
minutes. These pushes (and `scripts/e2b_credits.py`'s, which calls its
`record_push`) are appended to `logs/agent-questions/pushes.jsonl` (time, kind
`done`/`ask`/empty for other alerts, chat id and title, text, what it asks), so
the connector can match a push to its chat and label it ✅ done or ❓ needs input.
Fallback model comparison (2026-11-20, four long summaries to 110 characters): Haiku kept
4/4 within the limit (about 5-45 s per call depending on host load), Sonnet 1/4 (about 4 s);
Haiku is the cheaper model and the one that obeyed the limit. A Gemini key is not
available on the dev host (vault only), so it was not compared. Each call is capped at
$0.25 and 120 s.
Chats the host starts by itself (issue and production-failure chats,
`claude_dispatch.launch_claude_chat`) get the same rule appended to their prompt
and their title in `CLAUDE_CHAT_TITLE`. A ❓ push stays an open question until
the user's next prompt: the chat lifecycle never idle-stops such a chat, and the
briefing's waiting chats show the pushed question, also for a closed chat.

Queued chat starts: when the weekly Claude usage has 10% or less left, the dev
connector's start_chat (and a send_message that would reopen a closed chat with
new work) is not run but stored as a timer waiter (`claude_chat_waiters.add_start`,
usage-checked, at the reset + 5 minutes, moved to 17:00 when that falls in
marketing time and the build gate would hold it). Its Task is created at once.
The connector starts it when the timer fires without any Discord push (a start is
not a ✅ event; ✅ is only for a finished or parked chat); after three failed
attempts it sends one ❓. `run="now"`, `run_at` and the connector tools
`list_scheduled_chats`, `cancel_scheduled_chat` and `run_queued_chat` control it;
the briefing lists the queue under "Scheduled chats". Push text is scrubbed before
sending (`agent_question.scrub`): webhook URLs, emails, private keys, JWTs,
bearer and prefixed API tokens, `NAME=value` values and other long random tokens
become `[removed]`. Task and chat UUIDs, 40/64-char hex hashes, ENV/snake/kebab
names and presigned links to our own `openmates-*` buckets on the object storage
stay intact. Pushes longer than one Discord message go out as up to four parts,
split between words so links are never cut.

Proof on pushes (`scripts/push_proof.py`, owner decision 21 Nov 2026): `--attach FILE`
(repeatable) sends screenshots and videos as real files in the same Discord message
(webhook multipart, at most 10 files and about 9.5 MiB per message). A screenshot over
4 MiB or over the remaining budget is re-encoded as JPEG and scaled down; a video that
does not fit is re-encoded once with ffmpeg (H.264, at most 1280 px wide), and if it
still does not fit it goes to the private 7-day bucket of the AI test users videos
(`agent-pushes/<chat-id>/…`, signed link valid 7 days) and the push carries the link.
`--link URL` adds an existing signed link to our own private buckets; other links are
refused. Attachments and links come on top of the short-text limit. Proof can show
user-like data, so it goes only to the push webhook and the private bucket, never into
the repository; `.auth`, `ci-private` and `.env*` paths are refused. The push log
records attached file names and links under `proof`.
Proof is required only when the chat has something visual to show: a session of the
chat changed UI files (`.svelte`, `.css`, `.scss`, `.mjml`, Swift views, Apple asset
catalogs, email templates; test files excluded), or ran a finished `e2e`, `component`,
`visual-smoke` or `apple-ui` CI job. Such a push without `--attach`/`--link` is refused
(exit 1, also in dry runs) unless `--no-proof "<why>"`, which sends a loud "No
screenshot or video" line. Research, backend, security, docs and tooling pushes are
never asked for proof; the wording of the push plays no part.

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
3. Disk: two alert levels on the repository filesystem, 75% and 85% used (or
   less than 10 GiB available, the coordinator's hard floor), each its own
   incident that re-arms 2 points below its level. The alert names the largest
   growers of the last 24 h and every category over its budget, from the hourly
   size log (section 5). Cleanup belongs to the disk coordinator; the tick
   checks that `openmates-disk-coordinator.service` runs.
4. A memory or disk problem that lasts 20 min despite self-healing sends one
   "feedback needed" Discord push per incident (`agent_question.py`).
   `resources_recovered` is logged when it ends.
5. zellij: each zellij server (the `claude` session holds every pane chat) is
   checked for more than 2 GiB RSS or more than 200% CPU since the previous
   tick (`zellij_over_limit` event). Self-healing runs on that tick: the
   session's bar plugin panes (compact-bar, tab-bar, status-bar) are closed
   (`zellij_bars_closed` event). Terminal panes, so chats, are never touched.
   Still over a limit after 5 min sends one push naming what healing did.
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
The server starts with `scripts/zellij/chat-session.kdl`: one terminal pane per
tab and no bar plugins, and tabs created later inherit it. On 2026-11-16 the
server ran at up to 1,400% CPU and again reached 10 GiB before an OOM kill, with
every chat idle. All of that CPU was in zellij's `plugin-exec` threads: the 18
per-tab compact-bar plugins fell behind on events in a session no client
watches. Closing them brought the server to 4% CPU and 890 MB → 241 MB within a
minute. Pane polling was not a factor (one `zellij action` call per minute).
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

## 5. Disk budgets (TASK-7646)

On 2026-11-16 three chats waited on the disk coordinator at 90% used. Measured
causes: the admission floor (30 GiB plus a 2 GiB margin, on top of 12 GiB of
ext4 root reserve) blocked work with 31 GiB still free; reservations were sized
far above real use (a CI result reserved 768 MB, median use 1.6 MB); and the
cleanup reached none of the large holders: about 49 GB of Rust build output
(per-worktree `target/` and `target/apple-core/cargo`), 38 GB of overlay2 layer
folders no image or container uses (invisible to `docker system prune`), 4 GB
of container json logs and a 2.8 GB journal. Approved by the owner on
2026-11-17: per-category size budgets that the coordinator enforces, one hard
floor of 10 GiB as an emergency line only, and alerts at 75% and 85%. The
target steady state is about 57% of the 300 GB disk.

Root-only part (`scripts/host_disk_root.py`, installed by
`sudo bash scripts/host-disk-root-setup.sh` as `/usr/local/sbin/openmates-host-disk-root`,
timer `openmates-host-disk-root.timer`, Sundays 03:30 UTC):

- Orphaned overlay2 layers: a folder is kept when Docker's layer database
  (`cache-id`, `mount-id`, `init-id`), the GraphDriver data of any image or
  container, or any BuildKit state file outside `content/` names it, or when a
  kept folder stacks on it (`lower` chain). Of the rest, only folders untouched
  for 7 days are deleted, with their `l/` short link. With no reference at all,
  or more than 90% of folders unreferenced, the tool refuses to delete. Folder
  names are 64 hex characters (older engines) or 25 base-36 characters.
- Container json logs over 100 MB are truncated in place.
- The journal is vacuumed to 1 GiB and capped there by
  `/etc/systemd/journald.conf.d/openmates-size.conf`.
- `openmates-host-disk-root report` lists without deleting; every run writes
  `/var/lib/openmates-host-disk/report.json` (world-readable).

Hourly size log (`scripts/host_disk_usage.py`, user timer
`openmates-host-disk-usage.timer` from `scripts/host-disk-usage-setup.sh`):
`record` measures each category with `du` at idle IO priority (about 15 s) and
appends one line to `logs/host-disk/usage.jsonl` (60 days kept); `status`
prints sizes, budgets and 24 h growth. Categories and budgets (GB):

| Category | Holds | Budget |
|---|---|---|
| rust | `~/.cache/openmates-rust-*` and `~/.cache/*-target`, and every cargo target folder (it holds `.rustc_info.json` or a cargo `CACHEDIR.TAG`) at any depth in the checkout, the worktrees and `/tmp` | 25 |
| ci_artifacts | `logs/ci-runs`, `logs/ci-candidates`, `test-results/` (mostly `test-results/ci-runs`) | 10 |
| scratchpads | `/tmp/claude-<uid>` (2 per chat) | 6 |
| worktrees | agent and sub-agent worktrees, without their `target/` | 15 |
| docker_images (+ build cache) | `docker system df` | 20 |
| docker_logs | container json logs (root report; Docker default rotation 3 x 10 MB once active) | 1 |
| journal | `journalctl --disk-usage` | 1 |

Unbudgeted categories are measured too (proof_recordings, runtime, toolchains, checkout,
other_projects, home_other, system_logs, Docker volumes and containers, Docker
layer data that only the root report sees); `other` is the remainder of the
filesystem's used space. A path inside a path of an earlier category counts only
once, in the earlier one.

Enforcement (`scripts/host_disk_budgets.py`, inside the coordinator's `host`
cleanup kind, which the coordinator now runs every hour and every 30 min from
75% used): each budgeted category over its target loses whole units, least
recently used first, until it fits. The target is the budget, or 80% of it from
75% used on, so cleanup works long before the 10 GiB floor.

| Category | Unit | Kept |
|---|---|---|
| rust | one cargo target folder, or one subfolder of `~/.cache/openmates-rust-target` | a cargo/rustc process names it or works in its worktree; used in the last hour |
| ci_artifacts | one run in `test-results/ci-runs`, `logs/ci-runs`, `logs/ci-candidates` | a non-terminal CI job references it; changed in the last hour |
| scratchpads | one entry of a chat's scratch folder; every chat first down to 2 GB | open or in use; changed in the last 6 h |
| worktrees | `node_modules` or `.svelte-kit` of an agent or sub-agent worktree | a process works in it; any file in it changed in the last 12 h |

Only rebuildable data is a unit; worktrees themselves, WIP refs, recovery
archives and source are never removed (worktrees still leave only through the
24 h expiry). Docker images and BuildKit cache share one 20 GB budget in
`scripts/docker-cleanup.sh`: the build cache keeps what the budget leaves after
the images (80% of it from 75% on), never a full prune. The 2026-11-17 dry run
at 79% used would have freed 26.8 GB (rust 38 to 17 GB, 852 old CI runs 4 GB).

The setup script also runs the cleanup once and sets Docker's default log
rotation in `/etc/docker/daemon.json` (validated with `dockerd --validate`;
active after the next Docker restart, which the script does not do). The ext4 root reserve is lowered
once by hand to 3 GiB (`sudo tune2fs -r 786432 <root device>`).

## 6. Real-inference tests run in isolated CI, not on dev (TASK-5616)

The dev test lock (TASK-8552) is gone: deploys and dev restarts never wait for a test. Tests that
need real AI inference are `real-inference-*.spec.ts` specs in the `real_inference` group of
`scripts/ci_coverage_manifest.json`, submitted like any e2e spec
(`ci_coordinator.py submit --mode e2e --spec real-inference-<name>.spec.ts`), one per job.
Each run gets its own throwaway stack:

- The job uses the protected `real-inference` GitHub environment (dispatch from `dev` only). Its
  dev-only provider keys reach only the step that starts the stack, never dependency installs,
  the diagnostics step or the Playwright process, and pass by name into the run's own Vault
  (`REAL_INFERENCE_PROVIDERS` in `scripts/ci_environment.py`). Only providers whose dev key
  differs from production's are listed; models without a key there fall through to the next
  model of their bounded chain, and Jev (routing and the fail-closed answer-safety check) is
  required.
- The stack's network stays internal; HTTPS leaves only through the runner gateway's allowlist
  of exactly those providers' hosts (`REAL_INFERENCE_HOSTS` in `scripts/ci_tcp_gateway.py`).
- Uploaded stack logs drop outgoing request lines and redact key-shaped values.

- The job sets `OPENMATES_CI_REAL_INFERENCE=1` and clears `E2E_USE_MOCKS`/`E2E_USE_LIVE_MOCKS`.
  Specs call `requireRealInference(label, BASE_URL)` from
  `frontend/apps/web_app/tests/helpers/real-inference-guard.ts`, which allows exactly that job
  (on its own localhost stack) or a manual run against a `.dev.` host, and refuses every other
  CI job and any fixture replay.
- Python installs in this workflow are hash-locked and resolved from releases older than 7 days
  (`.github/requirements/`, guarded by `scripts/tests/test_ci_pip_installs_locked.py`).

Every real-inference E2E spec that can work with those providers is in the group. A spec stays
out only while it needs a provider key that is not in the list, an E2B sandbox, an
operator-installed provider package, outside websites or a fixture that exists only on dev; it
joins the group once that is solved. The dev-host `*_real_test.py` runners still work against
dev for manual checks, without any lock; a deploy or restart may interrupt them.

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

Deliveries to busy chats (2026-11-15, 76c8264a: a send sat in the box for 2 h;
2026-11-17, f1250b91: "NOT confirmed" although the chat had queued it). Claude Code
records a message taken into a busy chat's queue at once as a `queue-operation`
`enqueue` record, and the `queued_command` attachment only when the current step ends;
the connector reads both, and the "⎿  Queued" mark on screen. Escalation: (1) the
message is typed and queued (Enter is pressed again while the text still sits in the
box); (2) not queued or received within 60 s, the connector presses Esc and sends it as
the chat's next prompt; (3) never while a risky step runs (the last tool call without a
result, also inside a running sub-agent: deploy, git write, production SSH, migration,
Vault write, file write). It waits until that step ended. A message that meets an open
question dialog is held and typed when the dialog is answered. Replies start with
Delivered, Queued, Delivered after interrupt, Waiting for a risky step, Held, NOT sent
or Failed. Open and confirmed deliveries are kept in
`logs/claude-chat-lifecycle/connector-deliveries.json` and re-checked by the broker
every 10 s; host_status and chat_changes list them (undelivered with the text to
resend, open, delivered with how). `watch` reads that file and records a chat whose
box shows such a delivery as `typed` (source `connector`, age from when it was typed)
even while the chat is busy, without probing it.

