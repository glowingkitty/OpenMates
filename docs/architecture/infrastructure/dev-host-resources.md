---
status: active
last_verified: 2026-11-14
key_files:
- scripts/host_load_guard.py
- scripts/host_resources.py
- scripts/claude_idle_chats.py
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

## 3. Host-resources tick (`scripts/host_resources.py`, every minute)

`host_load_guard.py monitor` (openmates-host-load-guard.timer) samples memory, then:

1. Memory overloaded: `claude_idle_chats.py reap --pressure` (idle limit
   `pressure_idle_minutes`, 15), at most every 5 min.
2. Healthy with more than 4 GiB free: `claude_idle_chats.py release --limit 2`
   resubmits prompts that an older hook version refused. They still sit in the
   chat's input box, so Enter sends them.
3. Disk: more than 92% used or less than 20 GiB free on the repository
   filesystem. Cleanup belongs to the disk coordinator; the tick checks that
   `openmates-disk-coordinator.service` runs.
4. A memory or disk problem that lasts 20 min despite self-healing sends one
   "feedback needed" Discord push per incident (`agent_question.py`).
   `resources_recovered` is logged when it ends.

State: `logs/host-load-guard/resources.json`; events in `logs/host-load-guard/events.jsonl`.

## Setup

`scripts/host-load-guard-setup.sh` and `scripts/claude-idle-chats-setup.sh` install
the systemd user timers.
