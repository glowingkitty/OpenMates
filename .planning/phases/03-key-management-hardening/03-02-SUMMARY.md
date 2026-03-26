---
phase: 03-key-management-hardening
plan: 02
subsystem: encryption
tags: [broadcast-channel, cross-tab, key-propagation, hidden-chat, cross-device, rewrap]

# Dependency graph
requires:
  - phase: 03-key-management-hardening
    provides: ChatKeyManager with Web Locks mutex (Plan 01), BroadcastChannel infrastructure
provides:
  - BroadcastChannel keyLoaded handler with Pitfall 4 prevention (only warms cache for chats with pending ops)
  - broadcastKeyLoaded helper with SSR guard and infinite-loop prevention
  - ChatKeyManager.rewrapKey() method for caller-provided key re-wrapping
  - Documented legitimate crypto bypasses in hiddenChatService (4 locations)
  - Formal cross-device master key documentation (deterministic derivation mechanism)
affects: [03-03, 04-sync-handler-rewire]

# Tech tracking
tech-stack:
  added: []
  patterns: [BroadcastChannel keyLoaded with pending-ops guard, _receivingFromBroadcast loop prevention flag]

key-files:
  created:
    - docs/architecture/core/master-key-cross-device.md
  modified:
    - frontend/packages/ui/src/services/encryption/ChatKeyManager.ts
    - frontend/packages/ui/src/services/encryption/__tests__/ChatKeyManager.test.ts
    - frontend/packages/ui/src/services/hiddenChatService.ts

key-decisions:
  - "keyLoaded handler only warms cache for chats with pending ops (Pitfall 4 prevention -- no unnecessary async work)"
  - "_receivingFromBroadcast flag prevents infinite broadcast loops between tabs"
  - "Hidden chat crypto bypasses documented inline rather than refactored -- combined secret derivation and wrapping-type tests are legitimate direct crypto uses"
  - "Cross-device master key: no transport protocol needed -- deterministic derivation from credentials + server blob is the distribution mechanism"

patterns-established:
  - "BroadcastChannel keyLoaded pattern: check keys.has -> check pendingOps -> only then async decrypt"
  - "Loop prevention via _receivingFromBroadcast flag for cross-tab key propagation"

requirements-completed: [KEYS-06, KEYS-03]

# Metrics
duration: 8min
completed: 2026-03-26
---

# Phase 03 Plan 02: BroadcastChannel Key Propagation, Hidden Chat Bypass Closure, Cross-Device Doc Summary

**BroadcastChannel keyLoaded propagation with pending-ops guard, ChatKeyManager rewrapKey for hidden chat bypass closure, and formal cross-device master key documentation**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-26T14:58:33Z
- **Completed:** 2026-03-26T15:07:14Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- BroadcastChannel keyLoaded handler warms cache only for chats with pending operations (KEYS-06 cross-tab)
- keyLoaded messages for idle chats are ignored, preventing unnecessary async work (Pitfall 4 from research)
- broadcastKeyLoaded fires after createAndPersistKey and receiveKeyFromServer, with SSR guard and loop prevention
- ChatKeyManager.rewrapKey() method enables callers to re-wrap keys without importing crypto primitives directly (KEYS-03)
- 4 legitimate crypto bypasses in hiddenChatService documented with D-01 rationale comments
- Cross-device master key mechanism formally documented: deterministic derivation eliminates need for key transport (KEYS-06)
- Full encryption suite: 83 tests pass, 0 regressions (8 new tests added: 6 BroadcastChannel + 2 rewrapKey)

## Task Commits

Each task was committed atomically:

1. **Task 1: Complete BroadcastChannel keyLoaded handler and broadcast helper** - `2ecac10b6` (feat, TDD)
2. **Task 2: Add rewrapKey, document hidden chat bypasses, formalize cross-device doc** - `a6630db05` (feat)

## Files Created/Modified
- `frontend/packages/ui/src/services/encryption/ChatKeyManager.ts` - Added keyLoaded handler, broadcastKeyLoaded helper, _receivingFromBroadcast flag, rewrapKey method
- `frontend/packages/ui/src/services/encryption/__tests__/ChatKeyManager.test.ts` - 8 new tests (BroadcastChannel keyLoaded + rewrapKey)
- `frontend/packages/ui/src/services/hiddenChatService.ts` - Added 4 "Legitimate bypass" documentation comments per D-01
- `docs/architecture/core/master-key-cross-device.md` - New doc formalizing cross-device master key distribution via deterministic derivation

## Decisions Made
- keyLoaded handler uses pending-ops guard (Pitfall 4): no async decrypt work unless the receiving tab actually has queued operations for that chat
- _receivingFromBroadcast flag prevents infinite broadcast loops: receiveKeyFromServer skips broadcasting when processing a cross-tab keyLoaded message
- Hidden chat crypto bypasses kept as direct imports with documentation rather than routed through ChatKeyManager -- the combined secret derivation and wrapping-type tests are genuinely different operations from chat key management
- Cross-device doc confirms: no key transport protocol needed because PBKDF2(password, server-salt) + AES-GCM-unwrap(server-blob) deterministically produces the same master key on every device

## Deviations from Plan

None -- plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None

## Known Stubs
None -- all functionality is fully wired.

## Next Phase Readiness
- BroadcastChannel cross-tab key propagation is complete for Plan 03 and Phase 4 callers
- rewrapKey is available for future hide/unhide refactoring if deeper integration is desired
- All ChatKeyManager bypasses are documented; remaining work is in Plan 03 (caller migration to createAndPersistKeyLocked)

---
*Phase: 03-key-management-hardening*
*Completed: 2026-03-26*
