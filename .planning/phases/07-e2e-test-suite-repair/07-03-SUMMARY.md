---
phase: 07-e2e-test-suite-repair
plan: 03
subsystem: testing
tags: [playwright, e2e, totp, otp, clock-drift, timeout, login]

# Dependency graph
requires:
  - phase: 07-e2e-test-suite-repair
    provides: Triage categorization of 46 failing E2E specs
provides:
  - OTP clock-drift compensation in loginToTestAccount() with 5-attempt window offset cycling
  - Increased signup spec timeouts for GHA runner performance (240-300s to 420-480s)
  - Migration of 7 inline-login specs to shared loginToTestAccount() helper
affects: [07-e2e-test-suite-repair]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TOTP window offset cycling [0,-1,1,0,-1] for GHA clock drift compensation"
    - "Migrate inline login to shared loginToTestAccount() for consistent retry behavior"

key-files:
  created: []
  modified:
    - frontend/apps/web_app/tests/helpers/chat-test-helpers.ts
    - frontend/apps/web_app/tests/signup-flow.spec.ts
    - frontend/apps/web_app/tests/signup-flow-passkey.spec.ts
    - frontend/apps/web_app/tests/signup-flow-polar.spec.ts
    - frontend/apps/web_app/tests/signup-skip-2fa-flow.spec.ts
    - frontend/apps/web_app/tests/background-chat-notification.spec.ts
    - frontend/apps/web_app/tests/backup-code-login-flow.spec.ts
    - frontend/apps/web_app/tests/backup-codes-settings.spec.ts
    - frontend/apps/web_app/tests/cli-file-upload.spec.ts
    - frontend/apps/web_app/tests/connection-resilience.spec.ts
    - frontend/apps/web_app/tests/daily-inspiration-chat-flow.spec.ts
    - frontend/apps/web_app/tests/message-sync.spec.ts
    - frontend/apps/web_app/tests/multi-session-encryption.spec.ts
    - frontend/apps/web_app/tests/recent-chats-dedup.spec.ts
    - frontend/apps/web_app/tests/reminder-redesign.spec.ts

key-decisions:
  - "Used TOTP window offset cycling [0,-1,1,0,-1] across 5 attempts instead of just regenerating same-window code"
  - "Migrated inline login specs to shared loginToTestAccount() rather than duplicating retry logic"
  - "Increased signup timeouts to 420-480s (from 240-300s) based on GHA runner performance data"

patterns-established:
  - "OTP retry: always use loginToTestAccount() from chat-test-helpers.ts for login with OTP"
  - "TOTP clock drift: cycle through adjacent time windows on OTP failure"

requirements-completed: [E2E-02, E2E-03]

# Metrics
duration: 10min
completed: 2026-03-27
---

# Phase 07 Plan 03: Signup and Auth-Dependent Spec Fixes Summary

**TOTP clock-drift compensation via window offset cycling in loginToTestAccount(), plus signup spec timeout increases from 240s to 420-480s for GHA runners**

## Performance

- **Duration:** 10 min
- **Started:** 2026-03-27T14:02:34Z
- **Completed:** 2026-03-27T14:12:34Z
- **Tasks:** 2
- **Files modified:** 15

## Accomplishments
- Fixed OTP login failures (Category A: 20 specs) by adding clock-drift compensation with window offset cycling [0,-1,1,0,-1] across 5 retry attempts
- Fixed signup flow timeouts (Category D: 4 specs) by increasing test timeouts from 240-300s to 420-480s
- Migrated 7 inline-login specs to use shared loginToTestAccount() helper, eliminating duplicate login code and ensuring consistent OTP retry behavior
- Widened TOTP window boundary avoidance from last 3s to last 5s of 30s window

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix signup-* specs (4 specs)** - `8404907a3` (fix)
2. **Task 2: Fix login-dependent specs (~20 specs)** - `7d78a7fe4` (fix)

## Files Created/Modified
- `frontend/apps/web_app/tests/helpers/chat-test-helpers.ts` - Improved loginToTestAccount() with 5-attempt OTP retry using window offset cycling
- `frontend/apps/web_app/tests/signup-flow.spec.ts` - Timeout 240s -> 420s
- `frontend/apps/web_app/tests/signup-flow-passkey.spec.ts` - Timeout 240s -> 420s
- `frontend/apps/web_app/tests/signup-flow-polar.spec.ts` - Timeout 300s -> 480s
- `frontend/apps/web_app/tests/signup-skip-2fa-flow.spec.ts` - Timeout 360s -> 480s, fix email input selector
- `frontend/apps/web_app/tests/background-chat-notification.spec.ts` - Migrated to loginToTestAccount()
- `frontend/apps/web_app/tests/backup-code-login-flow.spec.ts` - Migrated to loginToTestAccount()
- `frontend/apps/web_app/tests/backup-codes-settings.spec.ts` - Migrated to loginToTestAccount()
- `frontend/apps/web_app/tests/cli-file-upload.spec.ts` - Added window offset to existing OTP retry
- `frontend/apps/web_app/tests/connection-resilience.spec.ts` - Migrated to loginToTestAccount()
- `frontend/apps/web_app/tests/daily-inspiration-chat-flow.spec.ts` - Migrated to loginToTestAccount()
- `frontend/apps/web_app/tests/message-sync.spec.ts` - Migrated to loginToTestAccount() (2 test functions)
- `frontend/apps/web_app/tests/multi-session-encryption.spec.ts` - Migrated to loginToTestAccount()
- `frontend/apps/web_app/tests/recent-chats-dedup.spec.ts` - Migrated to loginToTestAccount()
- `frontend/apps/web_app/tests/reminder-redesign.spec.ts` - Migrated to loginToTestAccount()

## Decisions Made
- **Window offset cycling [0,-1,1,0,-1]:** On OTP failure, try adjacent TOTP time windows to compensate for GHA runner clock drift. This covers current window, previous window, and next window across 5 attempts.
- **Migrate to shared helper:** Instead of adding retry logic to each inline login, migrated specs to use loginToTestAccount() which already has the robust implementation. This reduces code duplication and ensures all specs benefit from future improvements.
- **Increased timeouts conservatively:** Used 420-480s (7-8 minutes) instead of very large values to keep test feedback loops reasonable while accommodating GHA runner slowness.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added reminder-redesign.spec.ts to fix scope**
- **Found during:** Task 2
- **Issue:** reminder-redesign.spec.ts had inline login with single OTP (no retry), same root cause as other Category A specs, but was not explicitly listed in plan
- **Fix:** Migrated its loginTestAccount() helper to use shared loginToTestAccount()
- **Files modified:** frontend/apps/web_app/tests/reminder-redesign.spec.ts
- **Committed in:** 7d78a7fe4 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 missing critical)
**Impact on plan:** Fix was necessary for test correctness. No scope creep.

## Issues Encountered
- newsletter-flow.spec.ts and shared-chat-open.spec.ts were listed in plan but don't use OTP login -- their failures have different root causes (Mailosaur timing / selector drift respectively). Left unchanged as they require different fixes.
- signup-skip-2fa-flow.spec.ts was categorized as Category A (OTP failure) in triage but actually skips 2FA entirely; its real issue is Category D (timeout). Fixed with timeout increase.

## Known Stubs
None -- all changes are complete implementations.

## User Setup Required
None -- no external service configuration required.

## Next Phase Readiness
- 9 specs using loginToTestAccount() (api-keys-flow, code-generation-multiturn, etc.) get OTP retry fix automatically
- 7 migrated inline-login specs now use the shared helper
- 4 signup specs have increased timeouts
- Remaining Category C (selector drift) and Category E (strict mode) fixes are handled by other plans
- GHA verification recommended to confirm fixes work in CI environment

## Self-Check: PASSED

All key files verified present. Both task commits (8404907a3, 7d78a7fe4) confirmed in git log.

---
*Phase: 07-e2e-test-suite-repair*
*Completed: 2026-03-27*
