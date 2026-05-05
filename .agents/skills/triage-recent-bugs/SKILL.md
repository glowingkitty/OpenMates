---
name: openmates:triage-recent-bugs
description: Discover recent user-reported bugs on Linear, investigate them in parallel, replicate, fix, deploy, and verify end-to-end — composing issue-forensics, encryption-flow-tracer, and test-failure-triager.
user-invocable: true
argument-hint: "[hours=2]"
---

## Instructions

You are orchestrating the full triage → fix → verify workflow for recent user-reported bugs. `$ARGS` is the lookback window in hours (default `2`).

This skill composes existing specialist agents — it does NOT introduce a new agent. Delegate all `debug.py` inspection and failure triage work. Keep main context clean.

---

### Step 1: Discover recent bugs

Compute the cutoff timestamp:

```bash
date -u -d '${ARGS:-2} hours ago' --iso-8601=seconds
```

Then query Linear:

```
mcp__linear__list_issues
  createdAt: "<iso-cutoff>"
  orderBy: createdAt
  limit: 20
```

Filter locally to `labels` containing `Bug` and `status` in `Todo | Backlog | In Progress`. Show the user a numbered list and **ask which to work on**. Default: all bug-labeled issues in the window.

### Step 2: Cluster by chat URL (duplicate detection)

Before spinning up forensics, scan descriptions for `openmates.org/share/chat/<id>` URLs and group issues by chat ID. Multiple bugs against the same chat are often the **same root cause** reported from different angles (lesson: OPE-376 + OPE-377 were the same bug).

Present clusters to the user: _"OPE-376 and OPE-377 reference the same chat — likely duplicates. Investigate together?"_

### Step 3: Start a session

```bash
python3 scripts/sessions.py start --mode bug --task "triage N recent user bugs from last <hours>h"
```

Capture the session ID. All subsequent `sessions.py track`/`deploy` calls must use it.

### Step 4: Mark every selected issue In Progress

For each issue, in parallel:

```
mcp__linear__save_issue
  id: "OPE-XX"
  state: "In Progress"
  labels: ["Bug", "Codex-is-working"]
```

Then post a pickup comment with the session ID (`mcp__linear__save_comment`). **Do not skip the pickup comment** — this is required by `.Codex/rules/linear-tasks.md`.

### Step 5: Parallel forensics

Spawn one `issue-forensics` agent per bug in a **single message** (multiple Agent tool calls in parallel). If a symptom mentions "decryption", "content decryption failed", key mismatch, or sync bugs, **also** spawn `encryption-flow-tracer` alongside it.

Each agent prompt must contain:
- The Linear issue ID
- The internal Directus issue ID from the description (extract via regex `Internal issue ID:\s*\`([a-f0-9-]+)\``)
- A hint to extract screenshots via `mcp__linear__extract_images`
- Instruction to return a compact report under 250 words

**Never run `debug.py` yourself.** The agents isolate noisy timeline output.

### Step 6: Synthesize and plan

Build a table: `| Issue | Category | Suspect file:line | Blast radius | Effort |`. Recommend a priority order. **Ask the user** to confirm scope before writing any code.

### Step 7: Test-first per fix (mandatory)

For each fix, follow `.Codex/rules/testing.md`:
1. Run `sessions.py check-tests --session <id>` to find existing specs.
2. If a spec exists: run it first (`run_tests.py --spec <name>`) to confirm it reproduces the bug.
3. If none exists: propose a minimal repro test (pytest unit, vitest unit, or Playwright spec). **Wait for user confirmation.**
4. Write the test, run it red.
5. Apply the fix.
6. Run the test green.

**Never run vitest or Playwright locally.** Always dispatch via `run_tests.py`.

### Step 8: Track files explicitly

`sessions.py track --session <id> --file <path>` **every file you edit, at edit time**. The auto-hook does not fire reliably for every edit (lesson from the OPE-376/377/378/380 run).

### Step 9: Deploy gate

```bash
python3 scripts/sessions.py prepare-deploy --session <id>
```

Review the planned file list. **Abort if it includes files outside the bug scope** — those belong to another session.

Then deploy:

```bash
python3 scripts/sessions.py deploy \
  --session <id> \
  --title "fix(multi): OPE-XXX ..., OPE-YYY ..." \
  --message "OPE-XXX: <what changed and why>. OPE-YYY: ..."
```

**Pre-existing lint errors:** if `Lint: FAILED` fires on a line that `git blame` proves was not touched by this session, re-run with `--no-verify` and cite the blame SHA in the deploy reason. Do not use `--no-verify` to sidestep your own lint errors.

### Step 10: Wait for push to land, then for Vercel

```bash
git ls-remote origin dev | awk '{print $1}'  # confirm remote matches local HEAD
```

Then poll Vercel **with backoff, not fixed sleeps**:

```bash
python3 backend/scripts/debug.py vercel --n 1 | grep -E "Status|Commit"
```

Wait until the latest commit shown is **your** commit and status is `READY`. If `ERROR`, invoke `/fix-vercel`.

### Step 11: Re-verify on the deployed SHA

Re-dispatch the test suites **after** Vercel is READY so CI checks out your commit:

```bash
docker exec api python -m pytest <new-test-paths> -v
python3 scripts/run_tests.py --suite vitest
```

**Confirm the new tests actually ran.** Compare `jq '.summary.total' test-results/last-run.json` against the pre-run count — if it didn't grow by the expected number, the test file was silently dropped (import failure in the CI node environment). Fix the test file (add `vi.mock` stubs for problematic imports) and re-dispatch.

This is the #1 mistake from the inaugural run of this workflow — treat it as a hard checkpoint.

### Step 12: Close Linear

For each fixed issue, in parallel:

1. `mcp__linear__save_comment` with:
   - Root cause (1 sentence)
   - Fix summary (1 sentence)
   - Files changed
   - Commit SHA
   - Test evidence ("CI vitest run 24150665520 → 218/218 passed, +3 new tests")
2. `mcp__linear__save_issue` with `state: "In Review"` and remove `Codex-is-working` label.

### Step 13: End session

```bash
python3 scripts/sessions.py end --session <id>
```

---

## Rules

- **Compose, don't duplicate.** Use `issue-forensics`, `encryption-flow-tracer`, `test-failure-triager` — never re-implement what they do.
- **Cluster before investigating.** Same chat URL → likely same root cause. Investigate together.
- **Track every file as you edit it.** The session auto-hook is unreliable.
- **Pickup comment is mandatory.** Never skip `save_comment` on the In-Progress transition.
- **Verify CI ran your tests.** Compare `.summary.total` before/after. Silent test-file drops are a known failure mode.
- **Never vitest/playwright locally.** Always `run_tests.py`.
- **`--no-verify` only with `git blame` evidence** of pre-existing lint failures.
- **Wait for push BEFORE dispatching CI.** `git ls-remote` first.
- **One batched commit** per triage run with multi-issue title: `fix(multi): OPE-XXX ..., OPE-YYY ...`.

## When to use

- "check recent user bugs from the last N hours"
- "triage today's bug reports"
- "fix all the bugs from this morning"
- After the daily standup identifies a cluster of overnight reports

## When NOT to use

- Single issue with a known ID → use `/debug-issue` instead
- Test failures (not user reports) → use `/fix-tests`
- Vercel build failures → use `/fix-vercel`
