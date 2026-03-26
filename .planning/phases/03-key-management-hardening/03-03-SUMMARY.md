---
phase: 03-key-management-hardening
plan: 03
subsystem: encryption
tags: [withKey, key-before-content, buffering, state-machine, getKeySync, vitest]

# Dependency graph
requires:
  - phase: 03-key-management-hardening
    provides: ChatKeyManager with withKey() method (Plan 01), BroadcastChannel keyLoaded handler (Plan 02)
provides:
  - All sync handler decrypt paths use withKey() buffering instead of racy getKeySync()
  - Every getKeySync() call site classified with KEYS-04 comments
  - 7 new integration tests for key-before-content guarantee and state machine lifecycle
  - Async getKey() fallback added to chatMetadataCache sidebar render paths
affects: [04-sync-handler-rewire]

# Tech tracking
tech-stack:
  added: []
  patterns: [withKey buffering for decrypt paths, KEYS-04 classification comments on all getKeySync sites]

key-files:
  created: []
  modified:
    - frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts
    - frontend/packages/ui/src/services/chatSyncServiceHandlersChatUpdates.ts
    - frontend/packages/ui/src/services/chatSyncServiceHandlersPhasedSync.ts
    - frontend/packages/ui/src/services/chatMetadataCache.ts
    - frontend/packages/ui/src/services/encryption/__tests__/ChatKeyManager.test.ts

key-decisions:
  - "Classified 10+ getKeySync sites as (a) convert or (b) acceptable with inline KEYS-04 comments documenting rationale"
  - "chatMetadataCache sidebar render paths kept as getKeySync (b) with async getKey() fallback -- sidebar should not block on queue"
  - "Pending message queue pattern in ChatUpdates kept alongside withKey conversion -- both patterns coexist for different use cases"

patterns-established:
  - "KEYS-04 classification comment pattern: every getKeySync call site documented with conversion rationale"
  - "withKey callback pattern for decrypt paths: move all key-dependent code inside the callback"

requirements-completed: [KEYS-04, KEYS-05]

# Metrics
duration: 9min
completed: 2026-03-26
---

# Phase 03 Plan 03: Sync Handler withKey Conversion and Key-Before-Content Guarantee Summary

**withKey() buffering in 10 sync handler decrypt paths with full KEYS-04 classification, async sidebar fallbacks, and 7 new integration tests proving key-before-content guarantee**

## Performance

- **Duration:** 9 min
- **Started:** 2026-03-26T15:11:05Z
- **Completed:** 2026-03-26T15:20:00Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Converted 6 decrypt/encrypt paths in AI handlers from getKeySync to withKey buffering (KEYS-04)
- Converted 3 decrypt/encrypt paths in ChatUpdates handlers to withKey (KEYS-04)
- Converted PhasedSync validateAndHealEncryptedMetadata to withKey (KEYS-04)
- Added async getKey() fallback to chatMetadataCache sidebar render paths
- Classified all 20+ getKeySync calls across 5 files with KEYS-04 comments
- Added 7 new integration tests: 5 for key-before-content guarantee, 2 for state machine lifecycle
- Full encryption suite: 90 tests pass (was 83, +7 new), 0 regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Convert getKeySync decrypt paths to withKey in AI, ChatUpdates, PhasedSync, MetadataCache** - `3bb551994` (feat)
2. **Task 2: Add withKey buffering integration test and state machine lifecycle tests** - `7aa9cb8f1` (test)

## Files Created/Modified
- `frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts` - 6 decrypt paths converted to withKey, 4 classified as (b) acceptable
- `frontend/packages/ui/src/services/chatSyncServiceHandlersChatUpdates.ts` - 3 paths converted to withKey, 4 classified as (b) acceptable
- `frontend/packages/ui/src/services/chatSyncServiceHandlersPhasedSync.ts` - validateAndHealEncryptedMetadata converted to withKey
- `frontend/packages/ui/src/services/chatMetadataCache.ts` - Added async getKey() fallback for sidebar render, 3 KEYS-04 comments
- `frontend/packages/ui/src/services/encryption/__tests__/ChatKeyManager.test.ts` - 7 new tests in 2 describe blocks

## Decisions Made
- Classified each getKeySync site as (a) must convert or (b) acceptable-as-is based on whether the null path leads to error/data loss vs graceful handling
- chatMetadataCache sidebar render paths kept as getKeySync with getKey() fallback -- sidebar should show placeholder immediately, not block on withKey queue
- Existing _pendingMessages manual buffer in ChatUpdates kept alongside new withKey usage -- each pattern serves a different purpose (message buffering vs operation buffering)
- Post-processing encrypt path uses withKey to extract key then proceeds with encryption -- avoids nesting all encryption logic inside callback

## Deviations from Plan

None -- plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Known Stubs
None -- all functionality is fully wired.

## Next Phase Readiness
- All sync handler decrypt paths now use withKey buffering or are documented as acceptable
- chatSyncServiceSenders.ts and db/chatKeyManagement.ts remain Phase 4 scope (per research Open Question 2)
- Phase 03 key management hardening is complete: Web Locks mutex, BroadcastChannel propagation, and withKey caller migration all done

## Self-Check: PASSED

- FOUND: .planning/phases/03-key-management-hardening/03-03-SUMMARY.md
- FOUND: all 5 modified source files
- FOUND: commit 3bb551994 (Task 1)
- FOUND: commit 7aa9cb8f1 (Task 2)
- All 90 encryption tests pass (0 failures)

---
*Phase: 03-key-management-hardening*
*Completed: 2026-03-26*
