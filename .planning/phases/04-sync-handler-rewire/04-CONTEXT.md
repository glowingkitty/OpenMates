# Phase 4: Sync Handler Rewire - Context

**Gathered:** 2026-03-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Rewire all sync handlers to route crypto exclusively through ChatKeyManager and the encryptor modules. Add WebSocket key delivery acknowledgment, ensure all real-world scenarios work (streaming, background sync, reconnection), and split the oversized chatSyncServiceSenders.ts into focused modules. The sync layer must have zero direct crypto calls after this phase.

</domain>

<decisions>
## Implementation Decisions

### WebSocket Key Delivery Acknowledgment
- **D-01:** Full round-trip acknowledgment — recipient sends explicit `key_received` message back through WebSocket after receiving a key. Sender waits for ack before sending encrypted content. This ensures the sender knows with certainty that the recipient device has the key.

### Reconnection Strategy
- **D-02:** Leverage existing phased sync + withKey() buffering from Phase 3. The phased sync already handles reconnection by re-running the initial sync flow. Phase 3's withKey() conversion ensures messages arriving before keys are buffered. No new reconnection protocol needed — verify the existing path works correctly. This gives both reliability and fast loading.

### Sender-Side Crypto
- **D-03:** Route all inline encrypt calls through MessageEncryptor/MetadataEncryptor AND split chatSyncServiceSenders.ts (2100+ lines) into focused modules. Same pattern as Phase 3 did for decrypt paths, plus file decomposition.

### Claude's Discretion
- How to split chatSyncServiceSenders.ts (module boundaries, naming)
- WebSocket ack message format and protocol details
- Which encrypt paths to convert vs which are already clean
- BroadcastChannel completion for SYNC-02 (partially done in Phase 3)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 1 Audit Deliverables
- `docs/architecture/core/encryption-code-inventory.md` — Call site inventory with bypass classification
- `docs/architecture/core/encryption-root-causes.md` — Root cause analysis

### Phase 2 Extraction Results
- `frontend/packages/ui/src/services/encryption/MessageEncryptor.ts` — Stateless chat-key encrypt/decrypt (338 lines)
- `frontend/packages/ui/src/services/encryption/MetadataEncryptor.ts` — Stateless master-key + embed-key ops (473 lines)

### Phase 3 Hardening Results
- `frontend/packages/ui/src/services/encryption/ChatKeyManager.ts` — Hardened with Web Locks, withKey(), BroadcastChannel
- `.planning/phases/03-key-management-hardening/03-03-SUMMARY.md` — Which sync handler paths were already converted

### Sync Handler Source Files (to rewire)
- `frontend/packages/ui/src/services/chatSyncServiceSenders.ts` — 2100+ lines, primary split target
- `frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts` — AI response handlers (partially converted in Phase 3)
- `frontend/packages/ui/src/services/chatSyncServiceHandlersChatUpdates.ts` — Chat update handlers (partially converted in Phase 3)
- `frontend/packages/ui/src/services/chatSyncServiceHandlersCoreSync.ts` — Core sync handlers
- `frontend/packages/ui/src/services/chatSyncServiceHandlersPhasedSync.ts` — Phased sync handlers (partially converted in Phase 3)

### WebSocket Infrastructure
- `frontend/packages/ui/src/services/websocketService.ts` — WebSocket connection management

### Research
- `.planning/research/ARCHITECTURE.md` — Recommended sync handler rewire approach
- `.planning/research/PITFALLS.md` — WebSocket key delivery fragility warnings

### Regression Tests
- `frontend/packages/ui/src/services/encryption/__tests__/` — 90 tests must pass

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- Phase 3's withKey() conversion pattern — proven approach for decrypt paths, apply same to encrypt paths
- MessageEncryptor and MetadataEncryptor — ready to receive all encrypt calls from senders
- ChatKeyManager.withKey() — the exclusive key access API

### Established Patterns
- Phase 3 converted decrypt paths by classifying each call site as "convert" or "acceptable"
- Phase 2 used extract-and-redirect (re-export barrel) — same pattern applies for sender file split

### Integration Points
- chatSyncServiceSenders.ts imports from cryptoService.ts — need to route through encryptor modules
- WebSocket message handlers need new ack message type
- Backend WebSocket handler may need corresponding ack support

</code_context>

<specifics>
## Specific Ideas

- User wants both reliability AND fast loading for reconnection — no extra roundtrips
- User explicitly chose full round-trip ack over simple server flag — reliability over simplicity
- User wants the 2100-line sender file split, not just crypto routing — code quality matters

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 04-sync-handler-rewire*
*Context gathered: 2026-03-26*
