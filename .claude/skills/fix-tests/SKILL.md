---
name: openmates:fix-tests
description: Read latest test failures and fix them — reads daily run results, categorizes failures by root cause, and fixes each group
user-invocable: true
argument-hint: "[--rerun] [spec-name]"
---

## Instructions

You are fixing test failures from the latest daily test run. Follow this exact sequence:

### Step 1: Read Today's Failures

Read the pre-split failure list (most efficient path):

```bash
cat test-results/last-failed-tests.json | python3 -c "
import json, sys, re
data = json.load(sys.stdin)
tests = data['tests']
print(f'Run: {data[\"run_id\"]}')
print(f'Failed: {len(tests)}')
print()
for t in tests:
    err = re.sub(r'\x1b\[[0-9;]*m', '', t.get('error', '')[:200])
    print(f'  {t[\"name\"]}')
    print(f'    {err.split(chr(10))[0]}')
    print()
"
```

If `last-failed-tests.json` is missing or stale, fall back to the daily archive:
```bash
ls -t test-results/daily-run-*.json | head -1
```

Then read per-test failure reports for detailed error context:
```
test-results/reports/failed/*.md
```

If the `reports/failed/` directory is empty, regenerate reports:
```bash
python3 scripts/run_tests.py --only-failed --dry-run
```

### Step 2: Categorize Failures by Root Cause

Group the failures into root cause buckets. Common patterns:

| Pattern | Likely Root Cause | Fix Location |
|---------|------------------|--------------|
| `#login-password-input` / `#login-otp-input` not visible | Login flow UI changed | `PasswordAndTfaOtp.svelte` or `chat-test-helpers.ts` |
| `.settings-menu.visible` not found | Settings menu selector changed | Settings component or test selectors |
| `Mailosaur API error (401)` | Expired Mailosaur API key | `.env` or GitHub Actions secrets |
| `Translation issues: [T:key.name]` | Missing i18n translation key | `frontend/packages/ui/src/i18n/sources/` YAML files |
| `console.error` / `console error` in test output | Real application error surfaced in test | Fix the application code causing the console error |
| `data-status="finished"` not visible | Skill embed not completing | Backend skill or mock response issue |
| `Test timeout exceeded` | Slow operation or broken flow | Check what the test was waiting for |
| `No such container: api` | CI has no Docker — pytest integration test | Mark as CI-only or fix test to use mocks |

**IMPORTANT RULE:** If a test fails because of a console.error, you MUST fix the console error in application code — do NOT just suppress the error or make the test ignore it.

### Step 3: Fix Each Group

For each root cause group:
1. Investigate the source (read the relevant component/test/config)
2. Apply the fix
3. Note which specs are affected

### Step 4: Run Fixed Tests

After fixing, rerun only the failed specs:
```bash
python3 scripts/run_tests.py --only-failed
```

Or run specific specs:
```bash
python3 scripts/run_tests.py --spec <name>.spec.ts
```

### Step 5: Verify All Green

Check that all previously-failed tests now pass. If any still fail, go back to Step 3 for those.

### Rules

- **Fix console errors in app code** — never suppress them in tests
- **NEVER run vitest/playwright locally** — always dispatch via `run_tests.py`
- **Group fixes by root cause** — one commit per root cause group, not per test
- **Read the failed MD reports** for full error context before investigating
- **Check git log** for recent changes to failing components before deep-diving
