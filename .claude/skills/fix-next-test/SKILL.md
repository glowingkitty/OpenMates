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

### Step 1: Load Current Failures

Read the latest failure state:

```bash
cat test-results/last-failed-tests.json | python3 -c "
import json, sys, re
data = json.load(sys.stdin)
tests = data['tests']
print(f'Run: {data[\"run_id\"]}')
print(f'Failed: {len(tests)}')
for t in tests:
    err = re.sub(r'\x1b\[[0-9;]*m', '', t.get('error', '')[:150])
    print(f'  {t[\"name\"]}: {err.split(chr(10))[0]}')
"
```

If `last-failed-tests.json` is missing, check `last-run.json` instead.

Also check for detailed failure reports:
```
test-results/reports/failed/<spec-name>.md
```

### Step 2: Pick the Next Test

If a `<spec-name>` argument was provided, use that. Otherwise, apply this priority ranking:

**Priority tiers (fix in this order):**

1. **Runtime JS errors** — tests that catch real `console.error` / `pageerror` in app code (e.g., null reference errors). These affect real users.
2. **Core flow regressions** — login/auth, encryption, chat sync failures. Multiple tests often share one root cause.
3. **UI element visibility** — `toBeVisible` failures on core UI elements (sidebar, chat items, recent chats). Usually a component/CSS change.
4. **Assertion mismatches** — tests that run but assert wrong values (language detection, content matching). Could be test logic or app behavior.
5. **Timeouts** — tests that hang. Often flaky infrastructure, but check if the waited-for condition is actually broken.
6. **External service errors** — Mailosaur 401, third-party API failures. Usually config/secrets, not code. Flag to user and skip.
7. **Test infrastructure** — mock not intercepting, test data stale, component preview issues. Low user impact.

**Skip these categories** (flag them but don't attempt to fix):
- Mailosaur API key errors (needs secret rotation, not code)
- Tests requiring manual intervention (e.g., passkey hardware)

Print the picked test and explain why it's next:
```
NEXT: <spec-name>.spec.ts
REASON: <why this is the highest priority>
CATEGORY: <tier number and name>
ALSO FIXES: <other specs likely fixed by the same root cause, if any>
```

### Step 3: Start Session (unless --skip-session)

```bash
python3 scripts/sessions.py start --mode bug --task "Fix failing test: <spec-name>"
```

### Step 4: Investigate Root Cause

1. **Read the failure report** — `test-results/reports/failed/<spec-name>.md` for full error context and screenshots
2. **Read the spec** — understand what the test expects
3. **Check git log** — `git log -5 -- <files-related-to-failure>` to see recent changes
4. **Read the app code** — find the component/service where the error originates
5. **State your diagnosis** before writing any fix:
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
python3 scripts/run_tests.py --spec <spec-name>.spec.ts
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
- **Never run vitest/playwright locally** — always dispatch via `run_tests.py`
- **2-attempt limit** per test — don't spin wheels
- **Read before writing** — always read the failure report and source code before changing anything
- **Console errors are real bugs** — fix them in app code, never suppress
- **Skip Mailosaur/external service failures** — flag them and move to the next test
