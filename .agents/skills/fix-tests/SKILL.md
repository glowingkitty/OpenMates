---
name: fix-tests
description: Read latest test failures and fix them — reads daily run results, categorizes failures by root cause, and fixes each group
user-invocable: true
argument-hint: "[--rerun] [spec-name]"
---

## Instructions

You are fixing test failures from the latest daily test run. Follow this exact sequence:

### Step 1: Use the deterministic failure queue

Call the unified test control plane to classify current failures:

```bash
python3 scripts/tests.py triage
```

Then lease one group at a time before reading source or debugging:

```bash
python3 scripts/tests.py next --lease --session <session-id> --json
```

If the command returns no unleased failed test groups, stop and report to the user.

**IMPORTANT RULE:** If any group's root cause is a `console.error`, you MUST fix the console error in application code — do NOT suppress it in the test.

### Step 2: Fix each leased group

For each leased root-cause group:
1. Read the lease JSON's `entry.linked_files`
2. Confirm the diagnosis against the failure details before editing
3. Apply the smallest app or test fix that addresses that root cause
4. Note which related tests are covered by the fix

### Step 3: Run Fixed Tests

After fixing, rerun only the failed specs:
```bash
python3 scripts/tests.py run --only-failed
```

Or run specific specs:
```bash
python3 scripts/tests.py run --spec <name>.spec.ts
```

### Step 4: Verify All Green

Check that all previously-failed tests now pass. If any still fail, go back to Step 3 for those.

### Rules

- **Always lease first** — use `scripts/tests.py next --lease` before debugging so parallel workers do not collide.
- **Fix console errors in app code** — never suppress them in tests
- **NEVER run vitest/playwright locally** — always dispatch via `scripts/tests.py run`
- **Group fixes by root cause** — one commit per root cause group, not per test
- **Complete or release leases** — call `scripts/tests.py complete --lease <id> --commit <sha>` after deploy or `scripts/tests.py release --lease <id> --reason "<reason>"` when blocked
