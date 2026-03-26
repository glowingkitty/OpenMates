# Phase 3: Key Management Hardening - Context

**Gathered:** 2026-03-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Harden ChatKeyManager as the single, race-condition-free authority for all chat key operations. Add Web Locks mutex for cross-tab coordination, eliminate bypass paths that cause decryption failures, implement atomic key-before-content guarantees, and formalize the cross-device master key mechanism. This phase fixes the actual bugs — the recurring "content decryption failed" errors.

</domain>

<decisions>
## Implementation Decisions

### Bypass Handling
- **D-01:** Fix the 3 needs-investigation bypass items and route all chat-key operations exclusively through ChatKeyManager. Leave the 14 legitimate bypasses alone (master key ops, share encryption, email crypto) — they operate on different key types and don't belong in ChatKeyManager.
- **D-02:** Clean architectural boundary: ChatKeyManager owns chat keys exclusively. Other key types (master key, share key, email key) use their own dedicated paths. This is the most reliable solution that doesn't break existing chats.

### Failure Behavior
- **D-03:** The primary goal is **prevention, not error handling**. The architecture must make decryption failures structurally impossible by guaranteeing keys are always available before content arrives.
- **D-04:** As a safety net for edge cases: show a visible error in the chat UI + log to debug.py. Never fail silently. But the error path should be rare-to-never if the architecture is correct.

### Key Delivery Order
- **D-05:** Buffer encrypted messages until the decryption key is confirmed available. Messages may appear slightly delayed but will never fail to decrypt. This is the "hold messages" approach — the most reliable guarantee against the key-before-content race condition that caused the majority of bug reports.

### Claude's Discretion
- Web Locks API integration details (lock naming, timeout, fallback for browsers without support)
- ChatKeyManager state machine extension details
- BroadcastChannel implementation for cross-tab key propagation
- Specific code changes to implement the message buffering guarantee

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 1 Audit Deliverables (root causes and inventory)
- `docs/architecture/core/encryption-root-causes.md` — Root cause analysis of 3 bug reports, fix commit mapping
- `docs/architecture/core/encryption-code-inventory.md` — 135+ call sites, bypass classification (14 legitimate, 3 needs-investigation)
- `docs/architecture/core/master-key-lifecycle.md` — Master key derivation confirmed sound, cross-device mechanism documented

### Phase 2 Extraction Results
- `frontend/packages/ui/src/services/encryption/MessageEncryptor.ts` — Stateless chat-key encrypt/decrypt (338 lines)
- `frontend/packages/ui/src/services/encryption/MetadataEncryptor.ts` — Stateless master-key + embed-key operations (473 lines)
- `frontend/packages/ui/src/services/cryptoService.ts` — Re-export barrel (1147 lines)

### Key Management Source Files
- `frontend/packages/ui/src/services/encryption/ChatKeyManager.ts` — State machine to harden (1046 lines)
- `frontend/packages/ui/src/services/cryptoKeyStorage.ts` — IndexedDB key storage (392 lines)
- `frontend/packages/ui/src/services/db/chatKeyManagement.ts` — DB-level key operations (861 lines)

### Sync Files (affected by key-before-content guarantee)
- `frontend/packages/ui/src/services/chatSyncServiceSenders.ts` — 2100+ lines, historical bug paths
- `frontend/packages/ui/src/services/chatSyncServiceHandlersPhasedSync.ts` — Phased sync handlers
- `frontend/packages/ui/src/services/chatSyncServiceHandlersCoreSync.ts` — Core sync handlers

### Research
- `.planning/research/STACK.md` — Web Locks API + BroadcastChannel recommendations
- `.planning/research/ARCHITECTURE.md` — Recommended ChatKeyManager.withKey() pattern
- `.planning/research/PITFALLS.md` — Key management race prevention strategies

### Regression Tests
- `frontend/packages/ui/src/services/encryption/__tests__/regression-fixtures.test.ts` — 14 tests
- `frontend/packages/ui/src/services/encryption/__tests__/formats.test.ts` — 12 tests

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ChatKeyManager.ts` — Already has state machine (unloaded|loading|ready|failed), provenance tracking, queue-and-flush, and BroadcastChannel cross-tab coordination. Needs hardening, not rewrite.
- MessageEncryptor and MetadataEncryptor from Phase 2 — stateless modules ready to be the exclusive crypto interface
- Existing 65 test suite as regression gate

### Established Patterns
- ChatKeyManager already uses a state machine pattern — extend it, don't replace it
- BroadcastChannel already partially implemented — needs completion
- Web Locks API is browser-native (Baseline since March 2022), no polyfill needed

### Integration Points
- ChatKeyManager.withKey() is the target API — all encrypt/decrypt must flow through it
- Sync handlers need to buffer messages when key is not yet ready (key-before-content)
- 3 needs-investigation bypass items need reclassification and routing

</code_context>

<specifics>
## Specific Ideas

- User emphasized: "the main goal must be to prevent errors in the first place" — architecture must make failures structurally impossible, not just handle them better
- "Hold messages" approach chosen for key-before-content guarantee — slight delay is acceptable, decryption failure is not
- "Most reliable clean solution that doesn't break existing chats" — conservative approach on bypass handling

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 03-key-management-hardening*
*Context gathered: 2026-03-26*
