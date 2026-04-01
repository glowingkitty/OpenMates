---
name: openmates:next-tasks
description: Research daily priorities, detect stale statuses, clarify task details, and spawn sessions for next tasks
user-invocable: true
argument-hint: "[max-sessions: 2|3|4]"
---

## Instructions

You are helping the user identify which daily priority tasks have stale statuses, clarify task details through targeted questions, and spawn focused sessions for the next batch of work.

### Step 1: Gather Current State

Read all 3 data sources **in parallel**:

1. **Daily meeting state** — read `scripts/.daily-meeting-state.json`
2. **Recent git commits** — run `git log --oneline -30` to see what's been shipped since the meeting
3. **Linear task statuses** — for each task in `priorities[]` from the state file, call `mcp__linear__get_issue` to get the current status, labels, and completion state

### Step 2: Cross-Reference & Detect Staleness

Compare each priority task's `status_at_selection` (from the state file) against its current Linear status and recent git commits.

Build two lists:

**Stale Status Tasks** — tasks whose Linear status doesn't match reality:
- Task is "Todo" or "In Progress" in Linear but git shows commits that fix/complete it → suggest marking Done
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

| Task | Linear Status | Evidence | Suggested Action |
|------|--------------|----------|-----------------|
| OPE-XXX | In Progress | Commit abc1234 "fix: ..." merged | → Done |
| OPE-XXX | Todo | claude-is-working label, no commits in 2h | → Remove label, keep Todo |
```

Ask the user to confirm the status updates. Apply confirmed changes:
```
mcp__linear__save_issue with id, state, and updated labels
```

### Step 4: Present Available Tasks

Show the remaining tasks that are ready to be started:

```
## Ready to Start

| # | Task | Priority | Type | Summary |
|---|------|----------|------|---------|
| 1 | OPE-XXX: Title | Urgent | Bug | one-line summary |
| 2 | OPE-XXX: Title | High | Feature | one-line summary |
```

If fewer than 2 tasks remain from daily priorities, also check the broader Linear backlog:
```
mcp__linear__list_issues with state: "unstarted", team: "OpenMates", limit: 10
```

Rank by: Urgent/High priority first, then user-feedback label, then age.

### Step 5: Clarify Task Details (5 Rounds)

Before spawning sessions, ask **exactly 5 clarifying questions** — one question per round, waiting for the user's answer before asking the next.

**Question selection strategy** — pick the most useful questions from these categories based on the specific tasks:

1. **Scope boundaries** — "For OPE-XXX, should we also fix Y or just the reported Z?"
2. **Approach preference** — "OPE-XXX could be solved by A (quick) or B (thorough). Preference?"
3. **Priority ordering** — "Which of these should start first? Any dependencies between them?"
4. **Acceptance criteria** — "What does 'done' look like for OPE-XXX? Just the fix, or also a test?"
5. **Context the task is missing** — "OPE-XXX mentions X but doesn't specify Y. Do you have more context?"
6. **Risk awareness** — "OPE-XXX touches encryption/sync code. Should we be conservative or is a bigger refactor OK?"
7. **Testing expectations** — "Should OPE-XXX include a new E2E spec or just verify existing ones pass?"
8. **Related work** — "OPE-XXX might overlap with OPE-YYY. Should they be combined or kept separate?"

Pick the 5 most relevant questions based on the actual tasks. Don't ask generic questions — each question must reference a specific task ID and decision point.

Use `AskUserQuestion` for each round. Incorporate each answer into the session prompts.

### Step 6: Spawn Sessions

After all 5 questions are answered, determine the session count:
- Default: spawn up to 4 sessions (cap from `scripts/sessions.py`)
- If user passed `$ARGUMENTS` with a max-sessions value, use that instead
- Never spawn more sessions than available tasks

For each task, build a detailed prompt incorporating the user's answers from Step 5:

```bash
python3 scripts/sessions.py spawn-chat \
  --prompt "<detailed prompt with task context + user's clarifications>" \
  --name "<short-name-OPE-XX>" \
  --mode execute
```

**Prompt template for each session:**
```
Work on OPE-XXX: <title>.

<Full task description from Linear>

Context from user:
- <relevant answer from Q1>
- <relevant answer from Q3>

Acceptance criteria:
- <derived from user answers + task description>

Start by reading the Linear issue (mcp__linear__get_issue), then begin implementation.
```

Spawn all sessions in parallel (single bash call per session, but send all calls at once).

Present the attach commands:
```
Sessions spawned:
| Session | Task | Attach |
|---------|------|--------|
| fix-OPE-XXX | Title | zellij attach fix-OPE-XXX |
```

All sessions visible at http://localhost:8082.

## Rules

- **Always read daily-meeting-state.json first** — it defines today's priorities
- **Always cross-reference git commits** — don't suggest tasks that are already done
- **Exactly 5 question rounds** — no more, no less. One question per round, wait for answer.
- **Questions must be specific** — reference task IDs and concrete decisions, not generic
- **Never spawn sessions for user-owned tasks** (Figma design, video recording, etc.)
- **Never skip staleness check** — stale statuses cause confusion across sessions
- **Incorporate user answers into prompts** — the clarification step is useless if answers aren't passed to spawned sessions
- **Respect the 4-session cap** unless user explicitly overrides with max-sessions argument
