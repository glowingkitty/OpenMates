---
name: openmates:next-tasks
description: Pick the single highest-priority next task, clarify it, and start working on it
user-invocable: true
argument-hint: "[OPE-XXX]"
---

## Instructions

You are helping the user pick **one task** to work on next and start working on it in this session. No spawning separate sessions — you do the work right here.

### Step 1: Gather Current State

Read all 3 data sources **in parallel**:

1. **Daily meeting state** — read `scripts/.daily-meeting-state.json`
2. **Recent git commits** — run `git log --oneline -30` to see what's been shipped since the meeting
3. **Current tracker tasks** — list open GitHub Issues by default. Also query retained Linear tasks with `python3 scripts/linear.py list --team OPE --all --limit 100` when the work may involve programmatically stored/recorded issues, marketing, sensitive/private work, or existing OPE priorities. **Every relevant non-Done/non-Canceled task must be fetched — never truncate.** Sort Todo before Backlog when Linear state is present, then by priority.

### Step 2: Cross-Reference & Detect Staleness

Compare each priority task's `status_at_selection` (from the state file) against its current tracker status and recent git commits.

Build two lists:

**Stale Status Tasks** — tasks whose tracker status doesn't match reality:
- Task is open/Todo/In Progress but git shows commits that fix/complete it → suggest closing or marking Done
- Task has `claude-is-working` label but no recent commits and no active session → suggest removing label
- Task is "In Progress" but was completed in a previous session → suggest marking Done/In Review
- Task is "Todo" but another task's commits address the same issue → suggest marking Done or linking

**Available Next Tasks** — priority tasks that are:
- Still in Todo status (genuinely not started)
- Not labeled `claude-is-working` (no active session)
- Not user-owned tasks (skip tasks where owner is "User" in the daily meeting summary)

### Step 3: Present Staleness Report

Show the user which tasks have stale statuses with evidence:

```
## Status Updates Needed

| Task | Status | Evidence | Suggested Action |
|------|--------------|----------|-----------------|
| OPE-XXX | In Progress | Commit abc1234 "fix: ..." merged | → Done |
| OPE-XXX | Todo | claude-is-working label, no commits in 2h | → Remove label, keep Todo |
```

Ask the user to confirm the status updates. Apply confirmed GitHub changes with GitHub tools. Apply confirmed Linear-only changes with `python3 scripts/linear.py update ...`. Do not use Linear MCP tools.

### Step 4: Present Available Tasks & Recommend One

Show the remaining tasks that are ready to be started:

```
## Ready to Start

| # | Task | Priority | Type | Summary |
|---|------|----------|------|---------|
| 1 | OPE-XXX: Title | Urgent | Bug | one-line summary |
| 2 | OPE-XXX: Title | High | Feature | one-line summary |
```

If fewer than 2 tasks remain from daily priorities, use the full task list already fetched in Step 1 (all non-Done/non-Canceled tasks). Filter to tasks not already in daily priorities.

Rank by: **Todo before Backlog**, then Urgent/High priority first, then user-feedback label, then age.

**Recommend the #1 ranked task** and ask the user: "I recommend starting with OPE-XXX. Good to go, or pick a different one?"

If user passed `$ARGUMENTS` with a task ID (e.g. `OPE-123`), skip the recommendation — use that task directly.

### Step 5: Clarify the Chosen Task

Ask **up to 3 clarifying questions** about the single chosen task — one question per round, waiting for the user's answer before asking the next. Stop early if the task is clear enough.

**Question selection strategy** — pick the most useful questions from:

1. **Scope boundaries** — "Should we also fix Y or just the reported Z?"
2. **Approach preference** — "This could be solved by A (quick) or B (thorough). Preference?"
3. **Acceptance criteria** — "What does 'done' look like? Just the fix, or also a test?"
4. **Context the task is missing** — "The task mentions X but doesn't specify Y. Do you have more context?"
5. **Risk awareness** — "This touches encryption/sync code. Conservative or bigger refactor OK?"
6. **Testing expectations** — "Should this include a new E2E spec or just verify existing ones pass?"

Questions must be specific to the chosen task. Skip obvious ones.

### Step 6: Start Working

After clarification, **start working on the task in this session**:

1. Run `python3 scripts/sessions.py start --mode <bug|feature|docs> --task "OPE-XXX: <title>" --task-id OPE-XXX`
2. Decide spec size using `docs/contributing/guides/spec-driven-development.md`.
3. For bugs, run `reproduce-first` before fix code when user-visible behavior is wrong.
4. For full-spec feature/risk work, run `specify`, then `plan-from-spec`, then `tasks-from-spec` before implementation.
5. For inline-spec work, write scenarios and acceptance criteria in the session before code.
6. Follow the standard tracker workflow (read issue, mark In Progress, implement, deploy).
7. Incorporate the user's answers from Step 5 into your approach.

Do NOT spawn separate sessions. Do NOT ask to spawn sessions. Work on the task right here.

## Rules

- **ONE task only** — pick one, work on it, finish it. No multi-session spawning.
- **Always read daily-meeting-state.json first** — it defines today's priorities
- **Always fetch ALL Linear tasks** — use no limit (or limit: 200) with pagination. Never truncate the task list. Sort: Todo before Backlog, then by priority (Urgent → High → Medium → Low → No priority)
- **Always cross-reference git commits** — don't suggest tasks that are already done
- **Max 3 question rounds** — stop early if task is clear. One question per round, wait for answer.
- **Questions must be specific** — reference the chosen task ID and concrete decisions, not generic
- **Never pick user-owned tasks** (Figma design, video recording, etc.)
- **Never skip staleness check** — stale statuses cause confusion
- **Work in this session** — no spawning, no delegating. You are the one doing the work.
- **Full-spec gates apply** — teams, billing, auth, privacy, encryption, sync, sharing, permissions, provider integrations, migrations, new APIs, app skills, embed types, background jobs, cron jobs, and Directus schema changes need `specify` before code.
