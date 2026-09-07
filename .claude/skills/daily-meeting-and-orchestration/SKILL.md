---
name: daily-meeting-and-orchestration
description: Clarify daily priorities, review the last working day's chats and tasks, approve assignments, and coordinate chats through completion, including fallback during chat-service outages.
---

# Daily Meeting & Chat Orchestration

## Meeting style and task records

- Ask one question at a time, include **Recommendation:** with a brief reason
  and **Examples:** with concrete outcomes, then wait for the answer.
- Use only existing OpenMates tasks and activities for priorities, backlog,
  decisions, and handoffs. Reuse existing tasks and search before creating one.
- Each worker owns its task updates; its subagents report to that worker. Check
  that important progress, learnings, decisions, corrections, blockers, and
  completion are recorded and acknowledged. Search older activity when needed.
  Record coordination decisions without duplicating worker updates or heartbeats.
- `preview` / `dry-run`: read and propose without changing tasks or controlling chats.

Follow the steps below in order. After approval, repeat the monitoring step until
work finishes or a user decision is needed.

## Step 1: Establish today's focus

1. Ask about this week's priorities, using recorded decisions as context. If
   unclear, establish today's priority first. Clarify project scope, available
   time, or deadlines only when needed; default to the current project.

## Step 2: Review the last working day

1. In the user's timezone, search backward from yesterday through at most
   30 calendar days. Select the most recent day with relevant chat activity,
   using message/work timestamps. Automated heartbeats alone do not count.
2. Review **all chats from that day**, their tasks, and important activities.
   Group children with their parent and deduplicate copied fork history. Compare
   intended outcomes with actual progress, completion evidence, and blockers.
3. Recognize the shutdown marker (allow whitespace/apostrophe variations):
   `Its 23:00, this chat will be shutdown for today and may resume tomorrow.`
   Flag these chats for possible resumption, checking subsequent activity first.
   Review unmarked chats too; the marker does not authorize resumption.
4. If no chats exist in the full window, plan from tasks and user priorities.
   Disclose inaccessible or truncated history rather than treating it as empty.
   Check today's active chats before assigning duplicate work.
5. Surface health issues and upcoming commitments when they affect today's
   priorities. Keep the meeting focused rather than running a fixed audit agenda.

## Step 3: Propose assignments and get approval

- Recommend a disposition for each reviewed chat: resume, replace with a fresh
  chat, defer to todo/backlog, or no further work. Preserve useful findings in
  task activities; suggest code notes only when useful to future maintainers.
- Present suggestions as four compact tables (mark empty groups “None”):
  - **Chats to resume:** Title/link | Short resume instruction | Checkpoint | Completion criteria.
  - **New chats:** Title | Short assignment | Checkpoint | Completion criteria.
  - **Human tasks today:** Title | Action | Due date | Checkpoint | Completion criteria.
  - **Tasks for another day:** Title | Description summary | Todo/Backlog | Due date | Checkpoint | Completion criteria.
  Keep cells to short phrases, rank by today's relevance, and avoid repeating rows
  in prose. Use “—” for an unset due date; distinguish proposed dates from agreed ones.
  Create deferred tasks through the OpenMates CLI, reusing existing tasks when found.
- The tables are a concise review surface. Send each worker a separate, detailed
  instruction with its goal, task link, context, saved work, scope limits,
  dependencies, required checks, checkpoint, and completion criteria. Do not use
  the shortened table instruction as the entire worker prompt.
- Resume existing chats by default. Replace when conflicting context or repeated
  misunderstanding warrants it. Transfer approved requirements, decisions,
  learnings, saved work, and remaining checks; establish one active owner.
- Get approval for the daily plan before launching or resuming work. That approval
  covers the stated work modes, in-focus additions, and urgent corrections.
  Preserve existing approvals and task-specific boundaries; cancellation still
  requires user input.

## Step 4: Launch or resume approved chats

- Run **at most six worker chats concurrently**, across all runtimes and delegated
  workers; exclude this orchestrator. Count existing work before every start,
  resume, fallback, or added request. Uncertain/running workers retain their slots.
  Put overflow tasks in **Todo**. A task with **Urgent priority** may launch beyond
  six; show the exception explicitly, preserve platform limits, and do not promote
  tasks to Urgent merely to bypass the cap. This exception does not waive approval,
  scope, or ownership rules. Normal work waits until the active total is below six.

- Launch independent assignments using supported chat controls. Verify acceptance
  and task identity; reconcile uncertain launches before retrying. Preserve
  existing chat/worktree identity on resume. Keep launching under one coordinator.

## Step 5: Monitor and handle changes

- Establish monitoring before promising checks. For managed chats, register each
  worker after launch/resume with `python3 scripts/sessions.py monitor register
  --session <coordinator-id> --worker <chat-id> --started-at <launch-ISO-time>
  --until <tonight-23:00-ISO-time>`. Use timezone-qualified timestamps. Confirm
  `monitor status --session <coordinator-id>` shows the schedule. The runtime
  delivers checkpoints across turns; do not use shell sleeps or fake ready events.
- Keep the coordinator Task **in progress** while monitoring. A worker's blocker
  or a user question does not block the coordinator. Answer questions, then retain
  the other workers' schedules. Remove completed/deliberately paused workers with
  `monitor remove --session <coordinator-id> --worker <chat-id>`; use `monitor stop
  --session <coordinator-id>` when orchestration ends or the user stops it.

- Check each launched/resumed chat at **5, 10, 15, and 20 minutes**, then every
  **20 minutes**. New workers start their own cadence. Preserve schedules across
  recovery. Use a supported scheduler or responsive active loop; disclose when
  monitoring cannot continue instead of promising unattended checks.
- Compare actual work and evidence against the assignment. Distinguish progress,
  external waits, drift, and completion. Leave healthy work uninterrupted;
  correct urgent drift within approved scope. Honor user acceptance, waived
  checks, scope changes, and stop instructions.
- Group shared infrastructure failures under one recovery owner. Request
  user-only action once, verify recovery, and resume affected work with decisions
  preserved. Continue unaffected chats.
- For repeated failed approaches, no measurable progress, or disproportionate
  effort, explain the evidence and recommend narrowing or cancellation. Wait for
  the user's decision and pause orchestration of only that chat; keep monitoring
  others. Report if the worker remains running. Do not cancel it or send further
  continuation instructions while awaiting the decision.
- Evaluate additional requests against today's focus. If they fit, reuse/create
  the task and launch within the approved scope and six-chat limit. Otherwise capture them in todo
  or backlog. Preserve explicit deadlines; suggest due dates only with a reason.
  Ask before materially changing today's focus.

## Step 6: Summarize completed work and ask what comes next

- Verify outcomes and required checks before marking work complete. Idle, blocked,
  awaiting-input, and nightly-paused chats are not done. Ensure tasks retain
  important results, decisions, blockers, and precise next steps.
- **Once all chats are done**, summarize outcomes and fetch still-open tasks.
  Sort by relevance to today's focus: direct outcomes, enabling dependencies,
  related improvements, then unrelated work. Include deadlines, blockers, task
  links, and brief reasons for the ranking. Label any incomplete list.
- Ask **What would you like to work on next?** Include a recommendation and
  concrete examples from those tasks, or suggest ending the day when appropriate.
  Wait for the answer before launching the next batch. If nothing remains, ask
  whether to finish or define a new goal. If chats are blocked, ask the needed
  blocker decision instead of treating them as complete. After the answer, return
  to Step 3 for the selected work; reuse approval already given in that answer.

## Step 7: Close the day when requested or shutdown begins

- Respect nightly shutdown and explicit stops. Preserve handoffs in task activity;
  do not resume work that night automatically. Reassess it at the next meeting.
  This step can interrupt any earlier step; do not wait for every chat to finish.

## Chat-service fallback

- If the web UI is down, check the local OpenCode server separately. Use its
  API and the repository chat commands to inspect/manage existing chats when
  healthy; a browser or proxy failure does not mean workers stopped.
- If the server is unavailable, read local transcripts and task activities.
  Distinguish stale history from live status. Do not restart the service or
  resume nightly-stopped chats merely because the UI is unavailable.
- If spawning fails, reconcile the response, session list, and worker state.
  Retry once only for a confirmed transient failure with no accepted worker.
  Then use Codex for the approved assignment rather than repeatedly spawning.
- Use a Codex subagent when available, or a tracked `codex exec` session. Pass
  the same goal, scope, approvals, task link, saved work, and remaining checks.
  Keep one owner: unresolved OpenCode execution status blocks a duplicate
  takeover, but independent work can proceed. Record the fallback in task activity.
- Apply the same monitoring and completion rules to Codex workers. Keep their
  session IDs and outputs; do not switch ownership back automatically when the
  service recovers. Never bypass permissions to make a fallback work.

## Repository tools

Resolve the repository root before running commands, even when invoked from a
home-directory chat. Follow its instructions and load sibling skills by their
repository path when they are not globally listed.

- Tasks: use `openmates_task` when available; otherwise consult
  `docs/user-guide/cli/tasks.md` and `openmates tasks --help`.
- History: `python3 scripts/sessions.py chat recent --days 30 --limit <n> --json`,
  `chat read <id-or-url> --json`, and `chat search <id-or-url> <query>`.
  The recent inventory uses session-update timestamps and limits; verify message
  dates and expand coverage as needed. Use available project histories and
  read-only storage queries when the inventory is insufficient.
- Launch: follow the `spawn-chat` skill and
  `python3 scripts/sessions.py spawn-chat --help`; pass the complete assignment
  through `--prompt-file` in the approved mode. Use supported runtime controls
  for resumption and existing repository coordination for shared resources.
- UI-independent control: use the configured `OPENCODE_SERVER_URL` (default
  `http://127.0.0.1:4096`) for a bounded health/status check. Resume an approved
  existing chat with `python3 scripts/sessions.py restore <id> --mode <plan|execute>
  --prompt "<next instruction>"`; inspect its result before retrying.
- Codex fallback: check `codex exec --help`, then use
  `codex exec --cd <assigned-workspace> --json - < <assignment-file>` with the
  appropriate existing permission settings. Track the process and returned thread
  ID; resume that ID with `codex exec resume <thread-id> - < <instruction-file>`.
  Workers follow repository session/worktree rules and use OpenMates CLI task
  activity commands. Do not assume the injected `openmates_task` tool is available.
