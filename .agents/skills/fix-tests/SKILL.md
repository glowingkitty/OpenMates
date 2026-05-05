---
name: openmates:fix-tests
description: Read latest test failures and fix them — reads daily run results, categorizes failures by root cause, and fixes each group
user-invocable: true
argument-hint: "[--rerun] [spec-name]"
---

## Instructions

You are fixing test failures from the latest daily test run. Follow this exact sequence:

### Step 1: Delegate triage to the `test-failure-triager` subagent

Launch the `test-failure-triager` agent with this prompt:

> Triage the latest test failures. Read `test-results/last-failed-tests.json`, the per-test MD reports in `test-results/reports/failed/`, and cross-reference `logs/nightly-reports/pattern-consistency.json`. Return the structured JSON report of root-cause groups and your one-sentence recommendation.

The agent will return a compact JSON with `groups[]` (root cause, tier, suspect_files, suggested_fix_location, confidence) and a `skipped[]` list for external-service failures.

**Do NOT read the failure files yourself** — that floods the main context. The agent's isolated report is all you need.

If the agent reports zero groups (all skipped or empty), stop and report to the user.

**IMPORTANT RULE:** If any group's root cause is a `console.error`, you MUST fix the console error in application code — do NOT suppress it in the test.

### Step 2: Fix each group (highest tier first)

For each root cause group (start with the agent's recommended group, then the next-highest tier):
1. Read the `suspect_files` entries from the agent's JSON
2. Apply the fix at `suggested_fix_location`
3. Note which `affected_specs` are covered by this fix

### Step 3: Run Fixed Tests

After fixing, rerun only the failed specs:
```bash
python3 scripts/run_tests.py --only-failed
```

Or run specific specs:
```bash
python3 scripts/run_tests.py --spec <name>.spec.ts
```

### Step 4: Verify All Green

Check that all previously-failed tests now pass. If any still fail, go back to Step 3 for those.

### Rules

- **Always delegate triage** — use the `test-failure-triager` agent for Step 1. Never inline-read failure files in the main context.
- **Fix console errors in app code** — never suppress them in tests
- **NEVER run vitest/playwright locally** — always dispatch via `run_tests.py`
- **Group fixes by root cause** — one commit per root cause group, not per test
- **Trust the agent's git-blame** — it already cross-references recent commits and `pattern-consistency.json`
