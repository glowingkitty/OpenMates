# Requirements: Encryption & Sync Architecture Rebuild

**Defined:** 2026-03-26
**Core Value:** Every encrypted chat must decrypt successfully on every device, every time — no exceptions, no race conditions, no key mismatches.

## v1 Requirements

Requirements for the rebuild. Each maps to roadmap phases.

### Audit

- [x] **AUDT-01**: Complete inventory of every code path that encrypts, decrypts, generates keys, or syncs keys — with file paths and line numbers
- [x] **AUDT-02**: Document the exact binary/ciphertext format for every encrypted field (messages, metadata, embeds, titles)
- [x] **AUDT-03**: Create regression test fixtures from real encrypted data covering all format generations
- [x] **AUDT-04**: Document the full master key derivation path (from user credential → PBKDF2 → wrapping key → chat key)
- [x] **AUDT-05**: Document the master key distribution mechanism across devices (how a second device gets access to keys created on the first)
- [x] **AUDT-06**: Identify every sync handler that calls `cryptoService.ts` directly instead of going through `ChatKeyManager`

### Key Management

- [x] **KEYS-01**: Cross-tab mutex via Web Locks API prevents two tabs from generating different keys for the same chat simultaneously
- [x] **KEYS-02**: Key generation is blocked when a valid key already exists for a chat — no overwrite, no duplicate
- [x] **KEYS-03**: All encrypt/decrypt operations receive keys exclusively from `ChatKeyManager.withKey()` — zero bypass paths
- [x] **KEYS-04**: Atomic key-before-content guarantee: encrypted content is never delivered to a device that doesn't yet have the decryption key
- [x] **KEYS-05**: `ChatKeyManager` state machine correctly handles all transitions (`unloaded → loading → ready`, `loading → failed`, retry paths)
- [x] **KEYS-06**: Master key cross-device mechanism is formally designed and implemented — new devices can decrypt all existing chats

### Sync & Cross-Device

- [x] **SYNC-01**: WebSocket key delivery includes acknowledgment — sender knows the recipient device received the key
- [x] **SYNC-02**: Cross-tab key propagation via BroadcastChannel — key loaded in one tab is immediately available in all tabs
- [ ] **SYNC-03**: Foreground devices receive streaming AI responses and decrypt them correctly in real-time
- [ ] **SYNC-04**: Background devices receive synced chat updates and decrypt them correctly when brought to foreground
- [ ] **SYNC-05**: Chat sync works correctly when a device comes online after being offline (reconnection scenario)

### Code Architecture

- [x] **ARCH-01**: Extract `MessageEncryptor` as a stateless module — takes key + plaintext, returns ciphertext (and reverse)
- [x] **ARCH-02**: Extract `MetadataEncryptor` as a stateless module — handles title, embed metadata, and other non-message encrypted fields
- [ ] **ARCH-03**: All sync handlers (`chatSyncServiceSenders.ts`, `chatSyncServiceReceivers.ts`, related files) route crypto through encryptor modules — no inline encrypt/decrypt
- [x] **ARCH-04**: Each encryption-related module is under 500 lines with a single clear responsibility
- [ ] **ARCH-05**: Architecture documentation in `docs/architecture/` explains the full encryption flow end-to-end with diagrams

### Observability & Testing

- [ ] **TEST-01**: Playwright test: two tabs open the same chat, send messages, both tabs decrypt correctly
- [ ] **TEST-02**: Playwright test: create a chat in tab A, open it in tab B — content decrypts correctly
- [ ] **TEST-03**: Test fixture validation: all historical encrypted formats decrypt successfully with current code
- [ ] **TEST-04**: Performance test: encryption/decryption of a 100-message chat completes within acceptable bounds (no sync timeout)
- [ ] **TEST-05**: File-size monitoring script that flags files over a configurable line threshold and suggests splits

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Enhanced Observability

- **OBSV-01**: Key provenance tracking surfaced in admin debugging UI
- **OBSV-02**: Structured error recovery flow when decryption fails (retry with re-fetched key, fallback display)
- **OBSV-03**: Dashboard showing encryption health metrics (success/failure rates per device)

### Code Quality

- **QUAL-01**: ActiveChat.svelte god-component split into focused sub-components

## Out of Scope

| Feature | Reason |
|---------|--------|
| Key rotation | Anti-feature: adds complexity for self-encrypted data with no security benefit |
| Per-message keys | Anti-feature: one symmetric key per chat is correct for single-user multi-device |
| Custom crypto primitives | Anti-feature: Web Crypto API AES-GCM is the right choice, don't roll your own |
| Shared chat link encryption | Already working correctly — don't touch |
| Authentication system changes | Passkey/login flow is not causing the encryption bugs |
| Backend AI inference pipeline | Only touch vault-encrypted cache interface if needed at the boundary |
| Signal Protocol / libsodium | Wrong threat model — this is user encrypting their own data, not multi-party E2E |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| AUDT-01 | Phase 1 | Complete |
| AUDT-02 | Phase 1 | Complete |
| AUDT-03 | Phase 1 | Complete |
| AUDT-04 | Phase 1 | Complete |
| AUDT-05 | Phase 1 | Complete |
| AUDT-06 | Phase 1 | Complete |
| KEYS-01 | Phase 3 | Complete |
| KEYS-02 | Phase 3 | Complete |
| KEYS-03 | Phase 3 | Complete |
| KEYS-04 | Phase 3 | Complete |
| KEYS-05 | Phase 3 | Complete |
| KEYS-06 | Phase 3 | Complete |
| SYNC-01 | Phase 4 | Complete |
| SYNC-02 | Phase 4 | Complete |
| SYNC-03 | Phase 4 | Pending |
| SYNC-04 | Phase 4 | Pending |
| SYNC-05 | Phase 4 | Pending |
| ARCH-01 | Phase 2 | Complete |
| ARCH-02 | Phase 2 | Complete |
| ARCH-03 | Phase 4 | Pending |
| ARCH-04 | Phase 2 | Complete |
| ARCH-05 | Phase 5 | Pending |
| TEST-01 | Phase 5 | Pending |
| TEST-02 | Phase 5 | Pending |
| TEST-03 | Phase 5 | Pending |
| TEST-04 | Phase 5 | Pending |
| TEST-05 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 27 total
- Mapped to phases: 27
- Unmapped: 0

---
*Requirements defined: 2026-03-26*
*Last updated: 2026-03-26 after roadmap creation*
