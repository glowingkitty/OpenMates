---
name: openmates:organize-linear-tasks
description: Audit and reorganize all open Linear tasks — detect ghosts, duplicates, stale items, and missing metadata
user-invocable: true
argument-hint: "[--quick] [--section N]"
---

## Instructions

You are running a weekly audit of the OpenMates Linear backlog. This is an interactive, multi-section workflow that cross-references Linear tasks with git history, presents findings section-by-section, and applies only user-approved changes.

**Arguments:**
- `--quick` — skip comment fetching and task decomposition analysis (faster, less thorough)
- `--section N` — jump directly to section N (0-10) to resume an interrupted audit

---

### Step 1: Data Gathering

Gather all data upfront before any analysis. Run these in parallel where possible.

#### 1a. Fetch all open issues

Use `python3 scripts/linear.py list --team OPE --all --limit 100 --json` to fetch Linear issues from team OpenMates, then filter out Done and Canceled.
Fetch in batches if needed. For each issue, collect: identifier, title, description, state, priority, labels, project, milestone, createdAt, updatedAt, assignee.

Store the full list mentally — you'll reference it across all sections.

#### 1a-bis. Fetch completed issues for archival review

Also fetch ALL issues with state **Done** from team OpenMates. Collect: identifier, title, completedAt (or updatedAt), labels, project. These are used in Section 0 for archival cleanup.

#### 1b. Fetch organizational context

Run these in parallel where useful:
```bash
python3 scripts/linear.py states --team OPE --json
python3 scripts/linear.py labels --team OPE --json
```

#### 1c. Fetch comments (skip if `--quick` or if ALL tasks are < 14 days old)

For each open issue, fetch comments via `python3 scripts/linear.py get OPE-XX --comments --json`.
Record the date of the most recent comment per issue — this is the "last activity" signal for staleness detection.

**Optimization:** If the oldest open task is < 14 days old, skip comment fetching entirely — nothing can be stale. Use updatedAt as the activity signal instead.

#### 1d. Git cross-reference

Scan the past week of git history across all branches for task references:
```bash
git log --all --oneline --since="1 week ago" | grep -oP 'OPE-\d+' | sort | uniq -c | sort -rn
```

For each open task that appears in git, get its commit details:
```bash
git log --all --oneline --since="1 week ago" --grep="OPE-XX"
```

Also check for any OPE references in git that don't match an open task (orphaned commits):
```bash
git log --all --oneline --since="1 week ago" | grep -oP 'OPE-\d+' | sort -u
```

#### 1e. Present Overview

After gathering, show a quick summary before diving into sections:

```
## Backlog Audit — Overview

Open tasks: XX (Backlog: X, Todo: X, In Progress: X, In Review: X)
Projects: X | Milestones: X | Labels: X
Git references found (past week): X tasks mentioned in Y commits
Tasks with no description: X
Tasks with no priority: X

Starting analysis...
```

---

### Step 2: Section 0 — Delete Done Tasks

Linear's free plan has a 250-issue limit. This section permanently deletes completed tasks older than 24 hours to keep the workspace clean.

Filter the Done issues fetched in Step 1a-bis:
- Only show tasks where completedAt (or updatedAt if completedAt unavailable) is **more than 24 hours ago**
- Skip tasks completed in the last 24 hours — they may still need review or follow-up

Present findings:

```
## 0. Delete Done Tasks — Completed >24h Ago (N found)

| # | Task | Title | Completed | Project | Labels |
|---|------|-------|-----------|---------|--------|
| 1 | OPE-XX | "Fix auth race condition" | 3 days ago | Web App | Bug |
```

Use `AskUserQuestion` with options:
- **all** — delete all listed tasks
- **pick** — go through one by one (keep / delete)
- **skip** — skip this section, keep all

**For approved deletions, use the Linear GraphQL API directly** (the MCP doesn't expose delete):
```bash
API_KEY="$LINEAR_API_KEY"
# Get UUID from identifier
UUID=$(curl -s -X POST https://api.linear.app/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: $API_KEY" \
  -d '{"query": "{ issue(id: \"OPE-XX\") { id } }"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['issue']['id'])")
# Delete
curl -s -X POST https://api.linear.app/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: $API_KEY" \
  -d "{\"query\": \"mutation { issueDelete(id: \\\"$UUID\\\") { success } }\"}"
```

**Batch deletions** into a single bash script for efficiency — don't make 18 sequential tool calls.

> **Note:** `issueDelete` is a soft delete — issues go to trash and can be restored for 30 days in Linear.

Report the count of deleted tasks for the summary.

---

### Step 2.5: Section 0.5 — In Review Cleanup

Many "In Review" tasks are actually done — the review step is often skipped. Check all In Review tasks and ask which are truly complete.

Present findings:

```
## 0.5. In Review Cleanup — Are These Done? (N found)

| # | Task | Title | In Review Since | Has Git Commits |
|---|------|-------|-----------------|-----------------|
| 1 | OPE-XX | "Fix passkey login crash" | 2 days | Yes (3 commits) |
| 2 | OPE-YY | "Remove npm validation from deploy" | 1 day | Yes (1 commit) |
```

Use `AskUserQuestion`:
- **all done** — mark all as Done
- **pick** — go through one by one
- **skip** — leave all in In Review

---

### Step 3: Section 1 — Ghost Tasks (done in git, open in Linear)

> From this section onward, exclude any tasks handled in Sections 0 and 0.5.

Cross-reference the git history from Step 1d with open tasks. A "ghost task" is one where:
- Commits in the past week clearly reference OPE-XX
- The commit messages suggest the work is complete (e.g., "fix:", "feat:", "implement", "close", "resolve")
- But the Linear task is still in Todo, In Progress, or Backlog

Present findings — **always include title in every table**:

```
## 1. Ghost Tasks — Completed in Code, Open in Linear (N found)

| # | Task | Title | Status | Commits (past week) | Last Commit | Suggested Action |
|---|------|-------|--------|---------------------|-------------|-----------------|
| 1 | OPE-XX | "Fix chat pagination" | Todo | 2 commits | 2026-03-28 | → Mark Done |
```

Use `AskUserQuestion` with options:
- **all** — mark all as Done
- **pick** — go through one by one
- **skip** — skip this section

For approved items, call `python3 scripts/linear.py update OPE-XX --state Done`.

Remove approved ghost tasks from your working set for subsequent sections.

---

### Step 3.5: Section 1.5 — `claude-is-working` Label Cleanup

Find tasks with the `claude-is-working` label that are in Done, In Review, or Backlog status — these likely have stale labels from ended sessions.

Present findings:

```
## 1.5. Stale `claude-is-working` Labels (N found)

| # | Task | Title | Status | Label Should Be Removed? |
|---|------|-------|--------|--------------------------|
| 1 | OPE-XX | "Fix show more chats" | Done | Yes — task is done |
| 2 | OPE-YY | "Improve home search" | In Progress | Maybe — check if session is active |
```

Use `AskUserQuestion`:
- **all** — remove `claude-is-working` from all listed
- **pick** — go through one by one
- **skip** — leave as-is

---

### Step 4: Section 2 — Stale Tasks

A task is stale if:
- **Backlog** status AND updatedAt/last comment > 30 days ago AND no git commits reference it
- **Todo** status AND updatedAt/last comment > 14 days ago AND no git commits reference it
- **In Progress** status AND updatedAt/last comment > 7 days ago AND no git commits in the past week

Present findings:

```
## 2. Stale Tasks — No Activity (N found)

| # | Task | Title | Status | Last Activity | Age | Suggested Action |
|---|------|-------|--------|---------------|-----|-----------------|
| 1 | OPE-XX | "Old feature request" | Backlog | 45 days ago | Created 60d ago | → Cancel or re-prioritize |
```

Use `AskUserQuestion` — for each stale task, options are:
- **cancel** — delete the task
- **backlog** — move to Backlog (demote)
- **keep** — leave as-is (user confirms it's still relevant)
- **skip** — skip this section entirely

Apply approved changes. Remove deleted tasks from working set.

---

### Step 5: Section 3 — Duplicate / Merge Candidates

Compare all remaining open tasks for duplicates or near-duplicates:
- Normalize titles: lowercase, strip prefixes (Feat:, Fix:, Docs:, etc.), strip common words
- Flag pairs where titles share >60% of significant words
- Flag pairs where descriptions mention the same files, components, or error messages
- **Detect title prefix stacking**: flag titles starting with "Fix: Fix:", "Feat: Feat:", etc.

Present findings:

```
## 3. Duplicate / Merge Candidates (N pairs found)

### Pair 1:
- **OPE-XX**: "Fix encryption key sync on mobile" (In Progress, High)
- **OPE-YY**: "Encryption key not syncing across devices" (Todo, Medium)
- **Overlap**: Both reference encryption key sync, likely same issue
```

Use `AskUserQuestion` per pair:
- **merge** — close the lower-priority one, add a comment linking to the kept one
- **relate** — keep both but note they're related (comment on both)
- **skip** — they're different, leave both

For merges: mark the duplicate as Done (the work was done under the other task), post comment on both linking them. Remove merged tasks from working set.

---

### Step 6: Section 4 — Unclear Tasks

Flag tasks that need clarification:
- Title is < 5 words AND no description
- Title contains only vague terms ("fix thing", "update stuff", "do the thing")
- Description is empty or < 20 characters
- Title is a question without context
- **Title has prefix stacking** ("Fix: Fix:", "Feat: Feat:")

Present findings — **always include the full title**:

```
## 4. Unclear Tasks — Need Better Titles or Descriptions (N found)

| # | Task | Title | Has Description | Created |
|---|------|-------|-----------------|---------|
| 1 | OPE-XX | "fix it" | No | 15 days ago |
| 2 | OPE-YY | "Fix: Fix: update the component" | No | 8 days ago |
```

For EACH unclear task, use `AskUserQuestion`:
- "What did you mean by **OPE-XX: 'fix it'**? I'll update the title and add a description."

Based on the user's response, call `python3 scripts/linear.py update OPE-XX --title "..." --description-file <file>` to update the title and description.

If the user says they don't remember or it's no longer relevant, delete the task.

---

### Step 7: Section 5 — Priority Audit

Flag tasks with priority issues:
- **No priority set** — any task in Todo or In Progress without a priority
- **Questionable priority** — Urgent/High priority but sitting in Backlog for >7 days (was it actually urgent?)
- **Low priority In Progress** — someone started a low-priority task while high-priority items wait

Present findings — **always include title**:

```
## 5. Priority Audit (N issues found)

### Missing Priority (X tasks):
| # | Task | Title | Status | Labels | Suggested Priority |
|---|------|-------|--------|--------|--------------------|
| 1 | OPE-XX | "Critical auth bug" | In Progress | Bug | → High (2) |
```

Use `AskUserQuestion` with approval per group. Apply priority changes via `python3 scripts/linear.py update OPE-XX --priority N`.

---

### Step 8: Section 6 — Label Cleanup

Analyze label usage across all remaining open tasks:
- Tasks with NO labels at all
- Tasks where labels seem wrong (e.g., a backend Python task labeled "frontend")
- Unused labels that exist but aren't on any open tasks
- Tasks that should have the `Idea` label (questions, brain dumps, "what if" titles)

Present findings — **always include title**:

```
## 6. Label Cleanup (N issues found)

### Unlabeled Tasks (X):
| # | Task | Title | Status | Suggested Labels |
|---|------|-------|--------|-----------------|
| 1 | OPE-XX | "Fix API rate limiting" | Todo | → Bug, Backend |
```

Use `AskUserQuestion` for approval. Apply label changes via `python3 scripts/linear.py update OPE-XX --add-label ...` or `--remove-label ...`.

For unused labels, offer to delete them via the GraphQL API:
```bash
curl -s -X POST https://api.linear.app/graphql \
  -H "Authorization: $LINEAR_API_KEY" \
  -d '{"query": "mutation { issueLabelDelete(id: \"LABEL_UUID\") { success } }"}'
```

---

### Step 9: Section 7 — Milestone / Project Assignment

Analyze unassigned tasks and suggest organization:
- Tasks not assigned to any project or milestone
- Clusters of related tasks that could form a new milestone
- Tasks that clearly fit an existing project/milestone based on title/description/labels

Present findings — **always include title**:

```
## 7. Milestone / Project Assignment (N unassigned tasks)

### Fit Existing Projects (X tasks):
| # | Task | Title | Suggested Project | Reason |
|---|------|-------|-------------------|--------|
| 1 | OPE-XX | "Encrypt embed metadata" | Web App | Related to encryption |
```

Use `AskUserQuestion` for approvals. Apply available issue updates via `python3 scripts/linear.py update ...`. If project/milestone changes are needed and the CLI does not support the operation yet, add the missing CLI command before changing live data.

---

### Step 10: Section 8 — Task Decomposition (skip if `--quick`)

Flag tasks that appear too large and should be split:
- Description mentions 3+ distinct deliverables or areas
- Title contains "and" joining unrelated concerns (e.g., "Fix auth and redesign settings")
- Task has been In Progress for >5 days without completion

Present findings:

```
## 8. Tasks That Should Be Split (N found)

### OPE-XX: "Rebuild encryption and update key management and fix sync"
**Current status**: In Progress (8 days)
**Suggested split**:
1. "Rebuild encryption architecture" (core crypto changes)
2. "Update key management flow" (key generation, storage, rotation)
3. "Fix cross-device sync" (WebSocket sync, conflict resolution)
```

Use `AskUserQuestion` per task — the user confirms or adjusts the split. For approved splits:
1. Create subtasks with `python3 scripts/linear.py create ...` when the CLI supports the needed parent linkage; otherwise add the missing CLI command before changing live data
2. Post a comment on the parent linking to the new subtasks

---

### Step 11: Section 9 — Orphaned Commits

From the git scan in Step 1d, find OPE-XX references that don't match any current open task:
- The referenced task doesn't exist at all
- The referenced task was already Done or Canceled before the commit

Present findings:

```
## 9. Orphaned Commits — Git References Without Matching Open Tasks (N found)

| # | Reference | Commit | Status |
|---|-----------|--------|--------|
| 1 | OPE-999 | abc1234 "fix OPE-999 crash" | Task doesn't exist |
| 2 | OPE-50 | def5678 "partial work on OPE-50" | Task already Done |
```

This section is **informational only**. Use `AskUserQuestion` to ask:
- Should any of these orphaned references become new tasks?
- Are any of these typos in commit messages (wrong task number)?

Create new tasks if the user requests.

---

### Step 12: Summary

Present a complete recap of everything changed during this audit:

```
## Audit Complete — Summary

| Action | Count | Details |
|--------|-------|---------|
| Done tasks deleted | X | OPE-XX, OPE-YY |
| In Review → Done | X | OPE-XX, OPE-YY |
| Tasks closed (ghost) | X | OPE-XX, OPE-YY |
| claude-is-working cleaned | X | OPE-XX |
| Tasks deleted (stale) | X | OPE-XX |
| Tasks merged (duplicate) | X | OPE-XX → merged into OPE-YY |
| Titles/descriptions updated | X | OPE-XX, OPE-YY |
| Priorities set/changed | X | OPE-XX (→High), OPE-YY (→Low) |
| Labels updated | X | OPE-XX, OPE-YY |
| Stale labels deleted | X | label-name |
| Project/milestone assigned | X | OPE-XX → Project "Web App" |
| New milestones created | X | "Performance Optimization" |
| Tasks split | X | OPE-XX → 3 subtasks |
| New tasks created | X | From orphaned commits |

**Remaining open tasks: XX** (was YY at start)
**Net reduction: Z tasks cleaned up**
```

---

## Rules

- **NEVER use Canceled state for cleanup — always use `issueDelete` via GraphQL API**
- **Always include the task TITLE in every table** — never show just the ID
- **Never apply changes without explicit user confirmation** per section
- **Always show what will change** before changing it — no silent mutations
- **Use `AskUserQuestion`** at each section boundary for approval
- **Progressive reduction** — tasks closed/deleted in early sections are excluded from later analyses
- **Git lookback is 1 week** — matches the intended weekly cadence
- **Staleness thresholds**: Backlog >30d, Todo >14d, In Progress >7d (all measured from last activity: max of updatedAt, last comment date)
- **Skip staleness check for young backlogs** — if oldest task < 14 days, skip Section 2 entirely
- **For ghost task detection**: require the commit message to clearly reference the task identifier (OPE-XX), not just a keyword overlap
- **Duplicate detection**: compare normalized titles (lowercase, stripped prefixes) — flag >60% word overlap
- **Detect prefix stacking**: flag "Fix: Fix:", "Feat: Feat:" patterns for title cleanup
- **Large backlog warning**: if >50 open issues, warn the user that data gathering will take a few minutes
- **Track all changes** in a running log for the final summary
- **Do not re-fetch data** between sections — use the data gathered in Step 1
- **Respect `--quick` flag**: skip comment fetching (Step 1c) and task decomposition (Step 10)
- **Respect `--section N` flag**: skip directly to the specified section number (still run data gathering)
- **Batch GraphQL operations**: when deleting multiple issues, use a single bash script with a loop, not individual tool calls
- **Delete helper**: always use the `$LINEAR_API_KEY` environment variable — it's available in the shell
