# Requirements: Encryption & Sync Architecture Rebuild

**Defined:** 2026-03-26
**Core Value:** Every encrypted chat must decrypt successfully on every device, every time — no exceptions, no race conditions, no key mismatches.

## v1 Requirements

Requirements for the rebuild. Each maps to roadmap phases.

### Audit

- [ ] **AUDT-01**: Complete inventory of every code path that encrypts, decrypts, generates keys, or syncs keys — with file paths and line numbers
- [ ] **AUDT-02**: Document the exact binary/ciphertext format for every encrypted field (messages, metadata, embeds, titles)
- [ ] **AUDT-03**: Create regression test fixtures from real encrypted data covering all format generations
- [ ] **AUDT-04**: Document the full master key derivation path (from user credential → PBKDF2 → wrapping key → chat key)
- [ ] **AUDT-05**: Document the master key distribution mechanism across devices (how a second device gets access to keys created on the first)
- [ ] **AUDT-06**: Identify every sync handler that calls `cryptoService.ts` directly instead of going through `ChatKeyManager`

### Key Management

- [ ] **KEYS-01**: Cross-tab mutex via Web Locks API prevents two tabs from generating different keys for the same chat simultaneously
- [ ] **KEYS-02**: Key generation is blocked when a valid key already exists for a chat — no overwrite, no duplicate
- [ ] **KEYS-03**: All encrypt/decrypt operations receive keys exclusively from `ChatKeyManager.withKey()` — zero bypass paths
- [ ] **KEYS-04**: Atomic key-before-content guarantee: encrypted content is never delivered to a device that doesn't yet have the decryption key
- [ ] **KEYS-05**: `ChatKeyManager` state machine correctly handles all transitions (`unloaded → loading → ready`, `loading → failed`, retry paths)
- [ ] **KEYS-06**: Master key cross-device mechanism is formally designed and implemented — new devices can decrypt all existing chats

### Sync & Cross-Device

- [ ] **SYNC-01**: WebSocket key delivery includes acknowledgment — sender knows the recipient device received the key
- [ ] **SYNC-02**: Cross-tab key propagation via BroadcastChannel — key loaded in one tab is immediately available in all tabs
- [ ] **SYNC-03**: Foreground devices receive streaming AI responses and decrypt them correctly in real-time
- [ ] **SYNC-04**: Background devices receive synced chat updates and decrypt them correctly when brought to foreground
- [ ] **SYNC-05**: Chat sync works correctly when a device comes online after being offline (reconnection scenario)

### Code Architecture

- [ ] **ARCH-01**: Extract `MessageEncryptor` as a stateless module — takes key + plaintext, returns ciphertext (and reverse)
- [ ] **ARCH-02**: Extract `MetadataEncryptor` as a stateless module — handles title, embed metadata, and other non-message encrypted fields
- [ ] **ARCH-03**: All sync handlers (`chatSyncServiceSenders.ts`, `chatSyncServiceReceivers.ts`, related files) route crypto through encryptor modules — no inline encrypt/decrypt
- [ ] **ARCH-04**: Each encryption-related module is under 500 lines with a single clear responsibility
- [ ] **ARCH-05**: Architecture documentation in `docs/architecture/` explains the full encryption flow end-to-end with diagrams

### Observability & Testing

- [x] **TEST-01**: Playwright test: two tabs open the same chat, send messages, both tabs decrypt correctly
- [x] **TEST-02**: Playwright test: create a chat in tab A, open it in tab B — content decrypts correctly
- [x] **TEST-03**: Test fixture validation: all historical encrypted formats decrypt successfully with current code
- [ ] **TEST-04**: Performance test: encryption/decryption of a 100-message chat completes within acceptable bounds (no sync timeout)
- [ ] **TEST-05**: File-size monitoring script that flags files over a configurable line threshold and suggests splits

### OpenTelemetry Distributed Tracing

- [ ] **OTEL-01**: Backend OTel SDK initializes with auto-instrumentation for FastAPI, httpx, Celery, and Redis — traces export to OpenObserve via OTLP HTTP
- [ ] **OTEL-02**: TracePrivacyFilter enforces 3-tier privacy model — Tier 1 (structural, pseudonymized), Tier 2 (diagnostic, auto-escalated on errors), Tier 3 (full, admin + opted-in only)
- [ ] **OTEL-03**: Backend WebSocket handlers extract `_traceparent` from message payloads and create parent spans for downstream operations
- [ ] **OTEL-04**: Frontend OTel SDK auto-instruments fetch() calls and injects `_traceparent` into all outgoing WebSocket messages
- [ ] **OTEL-05**: OTLP proxy endpoint (`/v1/telemetry/traces`) forwards frontend traces to OpenObserve with authentication
- [ ] **OTEL-06**: User opt-in mechanism: `debug_logging_opted_in` boolean on Directus users collection, Settings UI toggle with disclosure text
- [x] **OTEL-07**: `debug.py trace` CLI subcommand family queries OpenObserve for trace data and renders indented span timelines
- [ ] **OTEL-08**: Issue reports include trace IDs, `debug.py issue --timeline` merges OTel trace spans into log timeline, LoggingMiddleware uses OTel trace_id

### E2E Test Suite Repair

- [ ] **E2E-01**: All 15 skill-* Playwright specs pass — shared infrastructure issue (auth, mocking, or env config) identified and resolved
- [ ] **E2E-02**: All 4 signup-* Playwright specs pass — auth flow alignment verified after encryption rebuild
- [ ] **E2E-03**: Remaining ~27 individually failing specs triaged by root cause category and fixed (stale selectors, timing, env, feature drift)
- [ ] **E2E-04**: Daily test suite Playwright pass rate reaches 85+ of 88 specs with no flaky failures on retry

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
| AUDT-01 | Phase 1 | Pending |
| AUDT-02 | Phase 1 | Pending |
| AUDT-03 | Phase 1 | Pending |
| AUDT-04 | Phase 1 | Pending |
| AUDT-05 | Phase 1 | Pending |
| AUDT-06 | Phase 1 | Pending |
| KEYS-01 | Phase 3 | Pending |
| KEYS-02 | Phase 3 | Pending |
| KEYS-03 | Phase 3 | Pending |
| KEYS-04 | Phase 3 | Pending |
| KEYS-05 | Phase 3 | Pending |
| KEYS-06 | Phase 3 | Pending |
| SYNC-01 | Phase 4 | Pending |
| SYNC-02 | Phase 4 | Pending |
| SYNC-03 | Phase 4 | Pending |
| SYNC-04 | Phase 4 | Pending |
| SYNC-05 | Phase 4 | Pending |
| ARCH-01 | Phase 2 | Pending |
| ARCH-02 | Phase 2 | Pending |
| ARCH-03 | Phase 4 | Pending |
| ARCH-04 | Phase 2 | Pending |
| ARCH-05 | Phase 5 | Pending |
| TEST-01 | Phase 5 | Complete |
| TEST-02 | Phase 5 | Complete |
| TEST-03 | Phase 5 | Complete |
| TEST-04 | Phase 5 | Pending |
| TEST-05 | Phase 5 | Pending |
| OTEL-01 | Phase 6 | Pending |
| OTEL-02 | Phase 6 | Pending |
| OTEL-03 | Phase 6 | Pending |
| OTEL-04 | Phase 6 | Pending |
| OTEL-05 | Phase 6 | Pending |
| OTEL-06 | Phase 6 | Pending |
| OTEL-07 | Phase 6 | Complete |
| OTEL-08 | Phase 6 | Pending |

| E2E-01 | Phase 7 | Pending |
| E2E-02 | Phase 7 | Pending |
| E2E-03 | Phase 7 | Pending |
| E2E-04 | Phase 7 | Pending |

**Coverage:**
- v1 requirements: 39 total
- Mapped to phases: 39
- Unmapped: 0

---
*Requirements defined: 2026-03-26*
*Last updated: 2026-03-27 after Phase 7 addition*
