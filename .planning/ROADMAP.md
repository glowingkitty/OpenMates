# Roadmap: Encryption & Sync Architecture Rebuild

## Overview

This roadmap rebuilds OpenMates' client-side encryption and cross-device sync architecture from the bottom up. The approach is audit-first (understand before changing), layered (pure crypto functions before stateful managers before sync handlers), and regression-safe (test fixtures from Phase 1 validate every subsequent phase). The goal is simple: every encrypted chat decrypts on every device, every time.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Audit & Discovery** - Map every encryption code path, document formats, create regression fixtures, and identify root causes
- [ ] **Phase 2: Foundation Layer Extraction** - Extract stateless crypto modules (MessageEncryptor, MetadataEncryptor, CryptoOperations) with clean boundaries
- [ ] **Phase 3: Key Management Hardening** - Harden ChatKeyManager with mutex, state machine, and cross-device key delivery guarantees
- [ ] **Phase 4: Sync Handler Rewire** - Rewire all sync handlers to route crypto exclusively through ChatKeyManager and encryptor modules
- [ ] **Phase 5: Testing & Documentation** - E2E multi-tab/multi-device tests, performance validation, architecture documentation, and file-size monitoring

## Phase Details

### Phase 1: Audit & Discovery
**Goal**: The team has a complete, documented understanding of how encryption works today -- every code path, every binary format, every key derivation step -- with regression fixtures that prove existing chats decrypt correctly
**Depends on**: Nothing (first phase)
**Requirements**: AUDT-01, AUDT-02, AUDT-03, AUDT-04, AUDT-05, AUDT-06
**Success Criteria** (what must be TRUE):
  1. A document exists listing every file and function that encrypts, decrypts, generates keys, or syncs keys -- with file paths and line numbers
  2. The exact binary/ciphertext format for every encrypted field type (messages, metadata, embeds, titles) is documented with byte-level diagrams
  3. A regression test suite of 10+ real encrypted message fixtures passes, covering all known format generations
  4. The full master key derivation path (credential to PBKDF2 to wrapping key to chat key) and cross-device distribution mechanism are documented and the architectural gap is explained
  5. Every sync handler that bypasses ChatKeyManager by calling cryptoService.ts directly is identified and listed
**Plans:** 3 plans

Plans:
- [ ] 01-01-PLAN.md -- Root cause tracing of 3 bug reports + complete code path inventory with bypass classification
- [ ] 01-02-PLAN.md -- Byte-level ciphertext format documentation + master key lifecycle and cross-device gap analysis
- [ ] 01-03-PLAN.md -- Regression test fixtures covering all format generations with 17+ test cases

### Phase 2: Foundation Layer Extraction
**Goal**: Stateless encryption modules exist with clean single-responsibility boundaries, and all existing chats still decrypt correctly after extraction
**Depends on**: Phase 1
**Requirements**: ARCH-01, ARCH-02, ARCH-04
**Success Criteria** (what must be TRUE):
  1. A `MessageEncryptor` module exists that takes a key + plaintext and returns ciphertext (and reverse) with no state, no side effects, no IDB access
  2. A `MetadataEncryptor` module exists that handles title, embed metadata, and other non-message encrypted fields as a stateless operation
  3. Every encryption-related module is under 500 lines with a single clear responsibility
  4. All Phase 1 regression test fixtures pass after every extraction step
**Plans**: TBD

### Phase 3: Key Management Hardening
**Goal**: ChatKeyManager is the single, race-condition-free authority for all key operations -- no duplicate keys can be generated, no content arrives without its key, and keys propagate correctly across tabs and devices
**Depends on**: Phase 2
**Requirements**: KEYS-01, KEYS-02, KEYS-03, KEYS-04, KEYS-05, KEYS-06
**Success Criteria** (what must be TRUE):
  1. Two tabs opening the same new chat simultaneously produce exactly one key (Web Locks mutex prevents duplicate generation)
  2. All encrypt/decrypt operations in the codebase obtain keys exclusively from ChatKeyManager.withKey() -- zero bypass paths remain
  3. Encrypted content is never delivered to a device that does not yet have the corresponding decryption key (atomic key-before-content guarantee)
  4. ChatKeyManager correctly handles all state transitions (unloaded to loading to ready, loading to failed, retry) without deadlocks or lost keys
  5. A new device can decrypt all existing chats via the formally designed and implemented master key cross-device mechanism
**Plans**: TBD

### Phase 4: Sync Handler Rewire
**Goal**: All sync handlers route crypto operations exclusively through ChatKeyManager and the encryptor modules -- the sync layer has zero direct crypto calls and handles all real-world scenarios (streaming, background sync, reconnection)
**Depends on**: Phase 3
**Requirements**: SYNC-01, SYNC-02, SYNC-03, SYNC-04, SYNC-05, ARCH-03
**Success Criteria** (what must be TRUE):
  1. WebSocket key delivery includes acknowledgment so the sender knows the recipient device received the key
  2. A key loaded in one tab is immediately available in all other tabs of the same browser via BroadcastChannel
  3. A foreground device receiving a streaming AI response decrypts each chunk correctly in real-time without errors
  4. A background device brought to the foreground correctly decrypts all chat updates that arrived while it was inactive
  5. A device that reconnects after being offline successfully syncs and decrypts all missed chat updates
**Plans**: TBD

### Phase 5: Testing & Documentation
**Goal**: The rebuild is validated by automated multi-tab and multi-device tests, performance is confirmed acceptable, the architecture is documented end-to-end, and a file-size monitoring script prevents future god-files
**Depends on**: Phase 4
**Requirements**: TEST-01, TEST-02, TEST-03, TEST-04, TEST-05, ARCH-05
**Success Criteria** (what must be TRUE):
  1. A Playwright test opens two tabs with the same chat, sends messages in both, and verifies both tabs decrypt correctly
  2. A Playwright test creates a chat in tab A, opens it in tab B, and verifies content decrypts correctly
  3. All historical encrypted format test fixtures decrypt successfully with the final rebuilt code
  4. Encryption/decryption of a 100-message chat completes within acceptable performance bounds (no sync timeout)
  5. Architecture documentation in docs/architecture/ explains the full encryption flow end-to-end with module boundaries and data flow diagrams

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Audit & Discovery | 0/3 | Planning complete | - |
| 2. Foundation Layer Extraction | 0/? | Not started | - |
| 3. Key Management Hardening | 0/? | Not started | - |
| 4. Sync Handler Rewire | 0/? | Not started | - |
| 5. Testing & Documentation | 0/? | Not started | - |
