---
phase: 04-sync-handler-rewire
plan: 01
subsystem: frontend
tags: [typescript, refactoring, barrel-exports, module-splitting]

# Dependency graph
requires:
  - phase: 02-encryption-foundation
    provides: cryptoService.ts barrel-export pattern (proven in Phase 2)
provides:
  - 5 focused sender sub-modules (sendersChatMessages, sendersChatManagement, sendersDrafts, sendersEmbeds, sendersSync)
  - Barrel re-export file for backwards compatibility
affects: [04-02, 04-03, sync-handler-rewire]

# Tech tracking
tech-stack:
  added: []
  patterns: [barrel re-export for backwards-compatible module decomposition]

key-files:
  created:
    - frontend/packages/ui/src/services/sendersChatMessages.ts
    - frontend/packages/ui/src/services/sendersChatManagement.ts
    - frontend/packages/ui/src/services/sendersDrafts.ts
    - frontend/packages/ui/src/services/sendersEmbeds.ts
    - frontend/packages/ui/src/services/sendersSync.ts
  modified:
    - frontend/packages/ui/src/services/chatSyncServiceSenders.ts

key-decisions:
  - "Pure move refactor with no logic changes -- function signatures, imports, and behavior preserved exactly"
  - "No shared helpers needed between sub-modules -- no sendersTypes.ts or sendersUtils.ts required"

patterns-established:
  - "Domain-based sender module splitting: messages, management, drafts, embeds, sync"

requirements-completed: [ARCH-03]

# Metrics
duration: 9min
completed: 2026-03-26
---

# Phase 04 Plan 01: Sender Module Decomposition Summary

**Split 2851-line chatSyncServiceSenders.ts into 5 domain-focused sub-modules with barrel re-export, zero breaking changes, all 95 encryption tests passing**

## Performance

- **Duration:** 9 min
- **Started:** 2026-03-26T16:00:46Z
- **Completed:** 2026-03-26T16:10:36Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- Decomposed 2851-line monolith into 5 focused modules under domain boundaries
- Preserved critical-op lock (acquireCriticalOp/releaseCriticalOp) in sendersChatMessages.ts
- All 95 encryption tests pass with zero code changes beyond the move
- No circular dependencies between sub-modules

## Task Commits

Each task was committed atomically:

1. **Task 1: Extract sender sub-modules** - `af8a55359` (refactor)
2. **Task 2: Convert to barrel re-export** - `2bcca807b` (refactor)

## Files Created/Modified
- `frontend/packages/ui/src/services/sendersChatMessages.ts` - sendNewMessageImpl, sendCompletedAIResponseImpl, sendEncryptedStoragePackage (1661 lines)
- `frontend/packages/ui/src/services/sendersChatManagement.ts` - sendUpdateTitleImpl, sendDeleteChatImpl, sendDeleteMessageImpl, sendUpdateChatKeyImpl, sendSetActiveChatImpl (343 lines)
- `frontend/packages/ui/src/services/sendersDrafts.ts` - sendUpdateDraftImpl, sendDeleteDraftImpl, sendDeleteDraftEmbedImpl (129 lines)
- `frontend/packages/ui/src/services/sendersEmbeds.ts` - sendStoreEmbedImpl, sendRequestEmbed, sendStoreEmbedKeysImpl (90 lines)
- `frontend/packages/ui/src/services/sendersSync.ts` - queueOfflineChangeImpl, sendOfflineChangesImpl, and 12 misc senders (631 lines)
- `frontend/packages/ui/src/services/chatSyncServiceSenders.ts` - Barrel re-export file (19 lines, down from 2851)

## Decisions Made
- Pure move refactor with no logic changes -- function signatures, imports, and behavior preserved exactly as in original
- No shared helpers needed between sub-modules -- each module is self-contained with its own imports, avoiding the need for sendersTypes.ts or sendersUtils.ts
- sendersChatMessages.ts exceeds 500 lines (1661) but this is acceptable as it is not an encryption module per ARCH-04

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Known Stubs
None - all functions are complete implementations moved verbatim from the original file.

## Next Phase Readiness
- All sender functions are now in focused domain modules, ready for Plan 02 (handler decomposition) and Plan 03 (encrypt path conversion)
- The barrel re-export ensures all existing imports continue working unchanged during the transition

---
*Phase: 04-sync-handler-rewire*
*Completed: 2026-03-26*
