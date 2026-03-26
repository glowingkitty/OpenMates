# Phase 1: Audit & Discovery - Context

**Gathered:** 2026-03-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Map every encryption code path in the codebase, document the exact binary formats, create regression test fixtures from real encrypted data, and identify root causes of the recurring "content decryption failed" errors. This phase produces documentation and test fixtures only — no code changes.

</domain>

<decisions>
## Implementation Decisions

### Audit Approach
- **D-01:** Failures-first approach — trace the 3 recent decryption failure bug reports (f305f5cf, a4ca102f, 7d2d2efc) backwards to root causes first, then map the full encryption architecture. This gets to actionable findings faster.
- **D-02:** After root cause identification, systematically map all remaining encrypt/decrypt/key-gen/key-sync code paths across the 57 files that touch encryption.

### Documentation
- **D-03:** All encryption architecture documentation lives in `docs/architecture/` as permanent project docs — not in `.planning/`. These are long-term reference documents.
- **D-04:** Mermaid diagrams for all visual representations — encrypt→sync→decrypt flow, key lifecycle, device sync, master key derivation. No annotated code walkthroughs; diagrams are the primary format for understanding.

### Fixtures
- **D-05:** Create regression test fixtures from real encrypted data to validate all format generations. Fixture strategy to be determined by researcher (export from IndexedDB, debug.py snapshots, or mock generation — Claude's discretion based on what's most practical).

### Claude's Discretion
- Fixture creation strategy (IndexedDB export vs debug.py vs mocks)
- Exact file organization within `docs/architecture/` for encryption docs
- Level of detail in code path inventory (file:line granularity where useful, higher-level where appropriate)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Encryption Architecture (existing)
- `frontend/packages/ui/src/services/encryption/ChatKeyManager.ts` — Central key management state machine (1046 lines)
- `frontend/packages/ui/src/services/cryptoService.ts` — Core crypto operations (1928 lines)
- `frontend/packages/ui/src/services/cryptoKeyStorage.ts` — IndexedDB key storage (392 lines)
- `frontend/packages/ui/src/services/db/chatKeyManagement.ts` — DB-level key operations (861 lines)

### Sync Architecture (existing)
- `frontend/packages/ui/src/services/chatSyncServiceSenders.ts` — Outbound sync (2100+ lines, historical bug paths)
- `frontend/packages/ui/src/services/chatSyncServiceHandlersPhasedSync.ts` — Phased sync handlers
- `frontend/packages/ui/src/services/chatSyncServiceHandlersCoreSync.ts` — Core sync handlers
- `frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts` — AI response sync handlers
- `frontend/packages/ui/src/services/chatSyncServiceHandlersChatUpdates.ts` — Chat update handlers

### Backend Encryption
- `backend/core/api/app/utils/encryption.py` — Server-side encryption utilities

### Research
- `.planning/research/ARCHITECTURE.md` — Recommended module structure and data flows
- `.planning/research/PITFALLS.md` — 13 domain pitfalls with prevention strategies
- `.planning/research/FEATURES.md` — Table stakes gaps and anti-features
- `.planning/research/STACK.md` — Web Locks API + BroadcastChannel recommendations

### Bug Reports
- Issue f305f5cf — "Content decryption failed" (13h ago at time of research)
- Issue a4ca102f — "Content decryption failed" (14h ago)
- Issue 7d2d2efc — "Content decryption failed" (1d ago)

### Key Fix Commits
- `3d8148bc4` — "permanent encryption key sync architecture"
- `33e87e0be` — "async key lookup in decryptMessageFields"
- `debbf2772` — "prevent cross-device title corruption"
- `e418f49e6` — "CLI decryption after fingerprint format change"

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ChatKeyManager.ts` — State machine with provenance tracking, queue-and-flush, cross-tab coordination. Research says this is the strongest piece and should be preserved.
- `cryptoService.ts` — Core AES-GCM operations via Web Crypto API. Cryptography is correct; architecture around it is not.
- `db/decryptionFailureCache.ts` — Existing decryption failure tracking (useful for audit)

### Established Patterns
- IndexedDB (`idb`) for all local state including encrypted keys
- WebSocket for real-time sync via `websocketService.ts`
- Phased sync (initial_sync_handler) for loading chats on connection

### Integration Points
- 57 files reference encryption/crypto — the audit must map which are direct crypto callers vs. indirect consumers
- Backend `encryption.py` and vault integration need audit for the server-side key interface
- `chatSyncServiceSenders.ts` (2100+ lines) is where research identified race conditions in dual key generation

</code_context>

<specifics>
## Specific Ideas

- User's primary goal is to fully understand the encryption architecture — documentation must be clear enough for the user to explain the flow to someone else
- User has been burned by whack-a-mole fixes — the audit must be thorough enough that the subsequent rebuild doesn't repeat this pattern
- Embed decryption failures (visible in console/logs) should also be investigated alongside message decryption failures

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-audit-discovery*
*Context gathered: 2026-03-26*
