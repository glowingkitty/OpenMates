---
phase: 03-key-management-hardening
plan: 01
subsystem: encryption
tags: [web-locks, mutex, state-machine, cross-tab, key-management, vitest]

# Dependency graph
requires:
  - phase: 02-foundation-extraction
    provides: ChatKeyManager.ts stateless extraction, MessageEncryptor.ts/MetadataEncryptor.ts
provides:
  - createAndPersistKeyLocked() method with Web Locks mutex for cross-tab key generation safety
  - Formalized failed->loading->ready|failed state machine retry transition
  - Web Locks mock infrastructure for future encryption tests
  - 10 new tests covering mutex, state machine retry, and deadlock prevention
affects: [03-02, 03-03, 04-sync-handler-rewire]

# Tech tracking
tech-stack:
  added: []  # Web Locks API is browser-native, no new dependencies
  patterns: [Web Locks exclusive lock per chatId, AbortController timeout fallback, deferredClearAll guard inside lock]

key-files:
  created: []
  modified:
    - frontend/packages/ui/src/services/encryption/ChatKeyManager.ts
    - frontend/packages/ui/src/services/encryption/__tests__/ChatKeyManager.test.ts

key-decisions:
  - "Lock naming convention: om-chatkey-{chatId} for exclusive per-chat locks"
  - "10-second timeout with graceful fallback to unlocked path on AbortError"
  - "deferredClearAll check inside lock callback prevents generating keys during logout"

patterns-established:
  - "Web Locks mock pattern: simulates exclusive locking with queue and abort support for vitest/jsdom"
  - "createAndPersistKeyLocked as the safe entry point for key generation (callers updated in Plan 03 and Phase 4)"

requirements-completed: [KEYS-01, KEYS-02, KEYS-05]

# Metrics
duration: 6min
completed: 2026-03-26
---

# Phase 03 Plan 01: Web Locks Mutex and State Machine Retry Summary

**Web Locks mutex on ChatKeyManager key generation with cross-tab exclusion, SSR fallback, timeout handling, and formalized failed->loading retry**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-26T14:49:52Z
- **Completed:** 2026-03-26T14:55:56Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Web Locks mutex prevents two tabs from generating different keys for the same chat (KEYS-01)
- Existing key check inside lock prevents key overwrite (KEYS-02)
- State machine failed->loading retry formalized with JSDoc and re-entrancy documentation (KEYS-05)
- 10 new tests covering concurrent generation, existing key, timeout fallback, SSR guard, scope isolation, retry success/failure, deadlock prevention, and deferredClearAll abort
- Full encryption suite: 75 tests pass, 0 regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Add Web Locks mock and tests for mutex key generation** - `3622fef94` (test)
2. **Task 2: Implement Web Locks mutex and state machine retry** - `46a9a48d8` (feat)

## Files Created/Modified
- `frontend/packages/ui/src/services/encryption/ChatKeyManager.ts` - Added createAndPersistKeyLocked() with Web Locks, formalized reloadKey() JSDoc
- `frontend/packages/ui/src/services/encryption/__tests__/ChatKeyManager.test.ts` - Added Web Locks mock, 10 new tests in 3 describe blocks

## Decisions Made
- Lock name `om-chatkey-{chatId}` for exclusive per-chat locks (matches research recommendation)
- 10-second AbortController timeout with fallback to unlocked createAndPersistKey (immutability guard is the safety net)
- deferredClearAll check inside lock callback prevents generating keys into a cache about to be cleared (Pitfall 5 from research)
- vi.mock for cryptoService added to test file so new tests can control encryptChatKeyWithMasterKey return values

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added vi.mock for cryptoService in test file**
- **Found during:** Task 1 (writing tests)
- **Issue:** New tests call createAndPersistKeyLocked which internally calls encryptChatKeyWithMasterKey. Without mocking, crypto.subtle is empty in jsdom and the call would fail unpredictably.
- **Fix:** Added vi.mock("../../cryptoService") at top of test file with mockResolvedValue for encrypt/decrypt functions
- **Files modified:** ChatKeyManager.test.ts
- **Verification:** All 33 tests pass (27 existing + 6 new failing as expected in RED phase)
- **Committed in:** 3622fef94 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Essential for test correctness. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Known Stubs
None - all functionality is fully wired.

## Next Phase Readiness
- createAndPersistKeyLocked() is ready for callers to adopt (Plan 03 and Phase 4)
- Existing callers of createAndPersistKey() are unchanged (no breaking changes)
- BroadcastChannel keyLoaded handler completion is Plan 02 scope

---
*Phase: 03-key-management-hardening*
*Completed: 2026-03-26*
