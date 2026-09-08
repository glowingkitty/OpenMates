---
name: daily-meeting-and-orchestration
description: Ask today’s priorities first, review previous and current work plus saved priorities and CLI Tasks, ask four clarification rounds, then propose and orchestrate approved assignments.
---

# Daily meeting and orchestration

## Role and output

This is the **orchestrator's** contract. Workers keep their normal output.
Every orchestrator response, including commentary and clarification, contains:

| Task | Status | Evidence / next action | Your input |
|---|---|---|---|
| [Title](codex://threads/<id>) | Working / Waiting / Blocked / Parked / Done / Not checked | Short outcome or exact blocker quote → next action | — |

Before assignment, use one “None started — planning” row. Include every managed
task, link its title, and state the last actual check time. Cached rows are not
fresh checks. For each problem quote a short **exact** worker sentence, attributed
by its task link; never invent or paraphrase a quotation. Highlight only decisions
that actually require the user. Do not repeat table content in paragraphs.

Use `python3 scripts/codex_orchestration.py --session <id> table` for deterministic
rows. The role-specific hook supplies this contract at start, resume, compaction
and tool boundaries. Stop supports one formatting correction when final text is
available; Codex does not expose interception of every commentary message.

Ask one decision at a time with **Recommendation:** and concrete **Examples:**,
then wait. Do not ask again for decisions or scope already approved.

## Required meeting sequence

**Priorities → research → four clarification rounds → proposal → approval.**
Do not skip or reorder these stages on a new daily meeting. On resume, load the
dated record and continue the unfinished stage without repeating answered rounds.

### 1. Ask today's priorities FIRST

Your first reply asks **“What are your priorities for today?”**, then waits.
Do not inspect other chats, git, CI or OpenMates Tasks before that answer.
Reading this skill and resolving the timezone are setup, not meeting research.
If the opening user message already explicitly states today's priorities, retain
that answer rather than asking for it again. Never substitute yesterday's goals
or inferred priorities for today's user answer.

Save the user's answer verbatim with its message ID via `codex_meeting.py
--timezone <zone> --meeting-thread <this-uuid> --record priorities
--text-file <answer-file> --message-id <human-message-id>`.
The collector refuses research without this dated priorities record.

### 2. Research the full picture

Run `python3 scripts/codex_meeting.py --timezone <zone>
--meeting-thread <this-uuid> --output <private-local-json>`, then inspect relevant
full histories/activity. The compact excerpts are indexes, not completion proof.
Use all five inputs:

| Input | What to establish |
|---|---|
| Yesterday / last working day | Codex tasks, outcomes and git commits; resume/complete candidates |
| **Today so far** | Running, waiting, idle and completed Codex task outcomes, today's commits; avoid duplicated work or reopening completed work |
| **Yesterday's agreed priorities** | What was planned, what shipped, and what carries over; distinguish proposals from approved focus |
| **OpenMates via CLI** | Backlog, todo, in-progress, blocked and done Tasks; relevant activities, decisions, deadlines and dependencies |
| Nightly CI | Source-bound coverage/results, missing reports and notification status |

Daily records are private, gitignored text files at the canonical repository's
`logs/daily-meetings/YYYY-MM-DD.json`. They retain priorities, four answers,
proposed focus, approval and linked meeting identity. Multiple meetings on a day
remain separate; revisions preserve earlier decisions. Load yesterday's file,
fall back to the last recorded day within 30 days, and include the old
`scripts/.daily-meeting-state.json` as explicitly dated legacy evidence when present.
Missing records are unknown, never invented priorities. These meeting records
complement OpenMates Tasks; they are not a second task backlog.

For Codex history include archived tasks and children; deduplicate inherited fork
messages. If yesterday has no relevant work, search back up to 30 calendar days.
Always keep today's activity alongside that prior-day review. Running work from
an earlier day is included even without a new message today. Idle is not Done:
verify completion from outcomes, required checks and Task activity. Group child
work with its parent. Disclose inaccessible/truncated history.

The collector calls the OpenMates CLI across all task statuses; inspect relevant
`openmates tasks activity list <task> --max-entries 10 --newest-first --json`
before deciding priorities. The CLI snapshot is not full activity history, and
unknown pagination or failed reads must remain visible.

Keep CI job batches separate from specs and cases. Do not sum overlapping reruns
or substitute stale summaries. Missing coverage or notification receipts are
explicit gaps. Suspected signup/billing/basic-chat failures warrant investigation
today; other bugs compete with the user's goals, without an endless debug campaign.

### 3. Ask FOUR clarifying questions

After research, ask **exactly four rounds**, labeled **1/4** through **4/4**,
**one question per response, waiting for each answer**. These are additional to
the initial priorities question. Include Recommendation and concrete Examples.
Tailor each question to the gathered evidence and prior answers; do not ask the
user to restate known information or choose technical implementation trivia.
Useful decisions concern priority conflicts, carryovers, capacity/deadlines and
scope/completion expectations. Never batch all four or replace them with a plan.

Persist each actual answer using `--record answer --text-file <answer-file>
--message-id <human-message-id>` with the same timezone/meeting-thread flags.
If the user explicitly changes the meeting process, follow their instruction;
do not fabricate answers to satisfy a guard.

### 4. Propose today's focus and assignments

Only after all four answers, propose the focus and a compact linked table of:
**Continue already running / Resume / Complete and close / Start new / Defer**.
Compare yesterday's intended priorities with outcomes and today's existing work.
Show why the proposed assignments fit today's stated goals, with scope and proof
of completion. Include OpenMates Task IDs and existing Codex links.

Save the proposal with `--record proposal --text-file <proposal-file>`; this
command rejects proposals before four distinct answers. Ask for approval, then
record it with `--record approve --text-file <approval-file>
--message-id <human-message-id>`. A priorities answer is not assignment approval.
Update the dated record and OpenMates activity when approved focus changes.

## Approve and assign

Propose concise assignments with outcome, owner, dependency and completion proof.
Get approval before starting/resuming tasks; preserve existing authorization.
Resume useful existing tasks by default. Replacement needs a clear reason and
handoff of decisions, evidence, remaining work and original scope.

Each worker must use its own existing repository session/worktree. Search and
reuse its OpenMates Task, connect its Codex identity, and record meaningful task
activity via the CLI. Include goal, task ID, scope, saved findings and remaining
verification in the handoff. Keep it concise. Verify accepted launches rather
than retry uncertain submissions. Use supported Codex task controls; never use
retired OpenCode `monitor`, `restore` or launcher commands.

There is **no orchestrator-imposed worker cap** and **no nightly clock cutoff**.
Respect actual platform/CI capacity and current file/runtime ownership.
Small direct prerequisites fit the assignment; substantial new work, cancellation
or reassignment needs the user's decision. Do not turn a product task into a
separate tooling project without it.

## Observe, decide, report

Register workers with the documented `codex_orchestration.py register` command.
Use one foreground `serve` owner or an explicitly approved service integration;
do not promise background monitoring without an actual running observer.
The observer reads compact metadata and the existing CI cache every 30 seconds.
In an active Codex task prefer batched `wait_threads` cursors for direct inspection;
read detailed history only for changed workers or anomalies.

- After a **real user instruction**, affected workers are reviewed at minutes
  **1, 2, 3; 13, 23, 33; every 20 minutes for two hours; then every 30 minutes**.
  Register its genuine message ID with `user-instruction`. Unrelated user messages,
  worker-origin pushes, coordinator messages and heartbeats do not reset cadence.
- Completion/failure and registered dependency/job changes can trigger earlier
  review. Unchanged heartbeat metadata stays quiet. A timestamp is not progress.
- Record `progress` only with new relevant evidence: cause, fix, verification,
  usable artifact or resolved dependency. A failed test with a new finding can
  count; repeated failures, speculation and chatter cannot.
- After **30 minutes without new outcome evidence**, park that worker for
  orchestration. No rereads or nudges; its actual execution continues. Keep
  registered CI completion watches. A new relevant dependency or user instruction
  rearms only affected workers. When all are parked, give one summary and end
  active polling unless a registered external-job watch remains.
- A worker instruction requires new evidence, a cleared dependency or concrete
  drift. Record `instruction` first, send its short evidence + next action once
  using supported task controls, then record its accepted receipt. At the next
  review record its effect: advanced / unchanged / worsened. Inspect the previous
  outcome before another instruction. Idle is never a reason to say “continue”.
- Record meaningful milestones using `openmates tasks activity add <task>
  --as-assignee --delivery-id <stable-sha256> --message <summary>`. Verify the
  acknowledgement; reconcile/flush the existing outbox after uncertain delivery.
  No heartbeat activities. Read task activity on start/resume/compaction.

## Visual evidence on every relevant completed run

For **every completed browser `.spec.ts` run**, pass or fail, fetch its source-bound
CI receipt and run the returned `codex_evidence_command`. Deliver all available
recordings per spec, test attempt and profile, plus blocker/failure images.
Use **explicit S3 Markdown links** for images and videos, with filenames beside
videos. Link the exact component preview URL when applicable. Inline embeds are
optional; raw HTML players and local paths do not satisfy Codex delivery.

Actual **OpenMates CLI product E2E** uses `cli_video_capture.py`; deliver its
recording on success, nonzero exit and timeout. Ordinary scripts, unit tests,
routine shell commands and routine CLI use do not require terminal recordings.

Keep test / recording / upload / delivery outcomes separate. Never rerun a test
just to retry uploading. Never replace a failed run's missing video with older
footage. Report capture-stage unavailability explicitly. Acknowledge evidence only
after its links were actually posted; refresh expired links from retained media.
Presigned links expire after 48 hours. Upload only shareable test media, never
credentials, private user data, auth state or raw logs. Required proof review
and user visual-intent decisions remain in force.

## Completion and stops

Verify required evidence and acknowledged Task activity before marking Done.
Idle, waiting and parked do not mean complete. Explicit user stops disable future
orchestration wakeups; never cancel workers as a side effect. Otherwise continue
useful approved work without a clock-based shutdown. When done, show remaining
ranked work without launching unapproved assignments.

Commands, failure recovery, limitations and concrete output examples:
`docs/architecture/codex-orchestration.md`.
