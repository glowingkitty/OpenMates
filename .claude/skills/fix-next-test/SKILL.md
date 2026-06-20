---
name: openmates:fix-next-test
description: Pick the next priority failing test, investigate root cause, fix it, and verify — one test at a time
user-invocable: true
argument-hint: "[spec-name] [--skip-session] [--rerun-only]"
---

## Instructions

You are fixing failing Playwright tests one at a time, in priority order. Each invocation picks the next test, investigates, fixes, and verifies.

### Arguments

- `<spec-name>`: Override auto-pick — fix this specific spec instead
- `--skip-session`: Skip `sessions.py start` (already in a session)
- `--rerun-only`: Just rerun all currently-failed tests and report results, don't fix anything

### Step 1: Lease the next deterministic failure group

Unless `<spec-name>` was provided as an argument, call the unified deterministic test control plane:

```bash
python3 scripts/tests.py next --lease --session <session-id> --json
```

This command ranks current failures, atomically records that this session is working on the selected group, and returns the failure reason, linked files, related group, and verification command. **Do not debug any unleased failure.**

### Step 2: Pick the Next Test

If `<spec-name>` was provided, use that directly and skip to Step 3.

Otherwise, use the JSON returned by `scripts/tests.py next --lease`. The picked group may cover multiple specs — fix them all in one pass since they share a root cause.

Print the picked group using the leased output:
```
LEASE: <lease_id>
NEXT: <entry.test>
CATEGORY: <entry.category>
ROOT CAUSE: <entry.reason>
FILES: <entry.linked_files>
VERIFY: <entry.verification_command>
```

### Step 3: Start Session (unless --skip-session)

```bash
python3 scripts/sessions.py start --mode bug --task "Fix failing test: <spec-name>"
```

### Step 4: Investigate Root Cause

The deterministic lease has already supplied the most relevant failure details and linked files. Fill in the gaps:

1. **Read the spec** — understand what the test expects
2. **Read the linked file(s)** — confirm the deterministic hypothesis before writing the fix
3. **If the hypothesis doesn't fit:** read the per-test failure MD report once (`test-results/reports/failed/<spec-name>.md`) for additional context
4. **State your diagnosis** before writing any fix:
   ```
   ROOT CAUSE: <what's actually broken>
   FIX PLAN: <what you'll change and why>
   AFFECTED SPECS: <which other failing specs this likely fixes>
   ```

### Step 5: Fix the Code

Apply the fix. Follow these rules:
- **Fix the app code**, not the test — unless the test itself has a wrong assertion
- **Never suppress console errors** in tests — fix the source
- **Never weaken assertions** — if a test expects something visible, make it visible
- **Check for shared root causes** — if 3 tests fail on `#login-otp-input`, fix the OTP component once
- **Minimal change** — fix exactly what's broken, don't refactor surrounding code

### Step 6: Verify

Run the fixed spec:
```bash
python3 scripts/tests.py run --spec <spec-name>.spec.ts
```

Wait for the result. If it passes, also run any related specs that share the same root cause.

If it fails again:
1. Read the new error
2. You get **one more attempt** with a different approach
3. If still failing after 2 attempts, report the status and move on

### Step 7: Deploy and Report

If the fix works:
```bash
python3 scripts/sessions.py deploy --session <ID> --title "fix: <what was fixed>" --message "<spec-name> and N other specs"
```

Print a summary:
```
FIXED: <spec-name>.spec.ts
ROOT CAUSE: <one-line summary>
COMMIT: <sha>
ALSO FIXED: <other specs if any>
REMAINING: <count of still-failing tests>
```

### Rules

- **One root cause per invocation** — fix one group, verify, deploy, then invoke again for the next
- **Never run vitest/playwright locally** — always dispatch via `scripts/tests.py run`
- **2-attempt limit** per test — don't spin wheels
- **Read before writing** — always read the failure report and source code before changing anything
- **Console errors are real bugs** — fix them in app code, never suppress
- **Skip Mailosaur/external service failures** — flag them and move to the next test
- **Always complete or release the lease** — after deploy call `python3 scripts/tests.py complete --lease <lease-id> --commit <sha>`; if blocked call `python3 scripts/tests.py release --lease <lease-id> --reason "<reason>"`
