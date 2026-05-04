---
name: openmates:reproduce-first
description: Reproduce a bug via an E2E spec (red) before any fix code, then verify green. Use at the start of any bug-fix session where a user-visible behavior is wrong.
user-invocable: true
argument-hint: "<issue-id | short description of the bug>"
---

## Instructions

You are enforcing the test-first workflow from `.Codex/rules/testing.md`. No fix code may be written until a spec has reproduced the bug (red). Follow these steps **in order**:

### Step 1 — Understand the bug

Parse the argument:
- If it looks like a Linear issue (`OPE-\d+`), call `mcp__linear__get_issue` + `mcp__linear__extract_images` + `mcp__linear__list_comments` for full context. Then follow the Linear pickup protocol from `.Codex/rules/linear-tasks.md` (move to In Progress, post pickup comment).
- Otherwise treat the argument as a free-text description and ask the user any clarifying questions needed to reach a concrete reproduction path (max 3 questions, one at a time, per `.Codex/rules/planning.md`).

State your understanding in 2-3 sentences and get confirmation before continuing.

### Step 2 — Find or propose a spec

Run:
```bash
python3 scripts/sessions.py check-tests --session <session-id>
```

If the session has no modified files yet (fresh session), search directly:
```bash
ls frontend/apps/web_app/tests/ | grep -i <keyword>
```

Three outcomes:

**(a) Existing spec covers this area** → use it. Open the spec, identify whether its current assertions would catch this bug. If yes, jump to Step 3. If no, extend it with a focused assertion that would fail today, then jump to Step 3.

**(b) No spec exists** → propose a minimal E2E test (user flow, assertions, target file). **Wait for user confirmation before writing test code.** After confirmation, write the spec.

**(c) Spec exists but feels wrong** → ask the user whether to extend an adjacent spec or create a new one. Do not guess.

### Step 3 — Run the spec and confirm RED

```bash
python3 scripts/run_tests.py --spec <name>.spec.ts
```

The spec MUST fail. This is the proof the bug is real and the test catches it.

- **If the spec passes** → your assertion doesn't actually cover the bug. Go back to Step 2 and sharpen the assertion. Do not proceed.
- **If the spec fails for an unrelated reason** (flaky, infra) → debug the flake first, then rerun.
- **If the spec fails for the expected reason** → continue to Step 4.

Post a Linear milestone comment (if a Linear issue is linked): "Reproduced in `<spec-name>.spec.ts` — red as expected."

### Step 4 — Fix the bug

Only now write fix code. Keep the change minimal — just enough to turn the spec green. Follow the KISS/DRY rules from `AGENTS.md`. Do not refactor adjacent code.

### Step 5 — Rerun the spec and confirm GREEN

```bash
python3 scripts/run_tests.py --spec <name>.spec.ts
```

The same spec MUST pass. This is the proof the fix works.

- **If still failing** → diagnose, adjust, rerun. 2 tries max per the debugging rule; on the 3rd attempt stop and reload `sessions.py context --doc debugging`.
- **If passing** → run any adjacent specs the fix could affect to catch regressions (ask `sessions.py check-tests --session <id>` again now that files have been modified).

### Step 6 — Close the loop

1. Summarize in 2-3 sentences what the bug was and how the fix closes it.
2. If a Linear issue is linked, post the completion comment and update status per `.Codex/rules/linear-tasks.md`.
3. Deploy via `/deploy` or `sessions.py deploy`. The deploy gate will confirm the spec was run in this session.

## Rules

- **No fix code before a red spec.** This is non-negotiable. If you catch yourself editing source files before Step 3, stop and restart at Step 2.
- **Never suppress a failing test** to make it pass. Fix the underlying bug.
- **Never run playwright/vitest locally** — always dispatch via `run_tests.py` (per `.Codex/rules/testing.md`).
- **Use `data-testid` selectors only** when writing or extending specs — never CSS classes.
- **One spec per bug** when reasonable. If the same fix closes multiple user-reported bugs, one spec covering the shared root cause is fine.
- **Ask before creating new specs.** Extending is cheaper than creating; the user may know an existing spec you missed.
