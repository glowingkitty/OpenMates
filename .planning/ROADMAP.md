# Roadmap: Encryption & Sync Architecture Rebuild

## Overview

This roadmap rebuilds OpenMates' client-side encryption and cross-device sync architecture from the bottom up. The approach is audit-first (understand before changing), layered (pure crypto functions before stateful managers before sync handlers), and regression-safe (test fixtures from Phase 1 validate every subsequent phase). The goal is simple: every encrypted chat decrypts on every device, every time.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Audit & Discovery** - Map every encryption code path, document formats, create regression fixtures, and identify root causes
- [x] **Phase 2: Foundation Layer Extraction** - Extract stateless crypto modules (MessageEncryptor, MetadataEncryptor, CryptoOperations) with clean boundaries
- [x] **Phase 3: Key Management Hardening** - Harden ChatKeyManager with mutex, state machine, and cross-device key delivery guarantees
- [x] **Phase 4: Sync Handler Rewire** - Rewire all sync handlers to route crypto exclusively through ChatKeyManager and encryptor modules
- [x] **Phase 5: Testing & Documentation** - E2E multi-tab/multi-device tests, performance validation, architecture documentation, and file-size monitoring
- [x] **Phase 6: OpenTelemetry Distributed Tracing** - Backend/frontend OTel SDK, privacy filtering, debug.py trace CLI, issue integration
- [x] **Phase 7: E2E Test Suite Repair** - Investigate and fix 46 failing Playwright specs so the daily test suite passes reliably
- [ ] **Phase 8: Sender Barrel Deployment** - Deploy the sender sub-module barrel to replace the monolithic chatSyncServiceSenders.ts (gap closure)
- [ ] **Phase 9: OTel Tracing Fix** - Wire privacy tiers, instrument missing handlers, rework debug.py trace CLI for usable output (gap closure)

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

### Phase 6: OpenTelemetry Distributed Tracing
**Goal**: OpenTelemetry distributed tracing covers backend (auto-instrumented) and frontend (fetch + custom WebSocket spans), with tiered privacy filtering for production and CLI-based trace inspection via debug.py
**Depends on**: Phase 5
**Requirements**: OTEL-01, OTEL-02, OTEL-03, OTEL-04, OTEL-05, OTEL-06, OTEL-07, OTEL-08
**Success Criteria** (what must be TRUE):
  1. Backend OTel SDK auto-instruments FastAPI, httpx, Celery, and Redis -- traces export to OpenObserve via OTLP HTTP
  2. TracePrivacyFilter enforces 3-tier privacy model before spans reach OpenObserve
  3. WebSocket messages carry _traceparent for end-to-end trace propagation (browser to API to Celery to microservices)
  4. Frontend OTel SDK auto-instruments fetch() and injects trace context into WS messages
  5. `debug.py trace` CLI renders indented span timelines from OpenObserve trace data
  6. Issue reports include trace IDs and `debug.py issue --timeline` merges trace spans into log timeline
**Plans:** 5 plans

Plans:
- [x] 06-01-PLAN.md -- Backend OTel SDK setup, auto-instrumentation, TracePrivacyFilter, and unit tests
- [x] 06-02-PLAN.md -- Directus schema field, user opt-in toggle in Settings UI
- [x] 06-03-PLAN.md -- Backend WS custom spans, frontend OTel SDK, OTLP proxy, WS span wrappers
- [x] 06-04-PLAN.md -- debug.py trace CLI subcommand family
- [x] 06-05-PLAN.md -- Issue reporting integration, LoggingMiddleware migration to OTel trace context

### Phase 7: E2E Test Suite Repair
**Goal**: Investigate and fix the 46 failing Playwright specs so the daily test suite passes reliably -- no new tests, only fixing broken ones
**Depends on**: Phase 5
**Requirements**: E2E-01, E2E-02, E2E-03, E2E-04
**Success Criteria** (what must be TRUE):
  1. All 15 skill-* specs pass (shared infrastructure issue resolved)
  2. All 4 signup-* specs pass (auth flow alignment verified)
  3. Daily test suite Playwright pass rate reaches 85+ of 88 specs
  4. No spec relies on hardcoded timeouts or flaky selectors -- all use data-testid or role-based selectors with proper wait conditions
  5. Failures are categorized and documented so regressions can be quickly attributed
**Plans:** 6 plans

Plans:
- [ ] 07-00-PLAN.md -- Fix vitest timeout in run_tests.py so daily cron pipeline completes
- [ ] 07-01-PLAN.md -- Diagnostic triage: run 6 representative specs on GHA, capture errors, categorize all 46 failures by root cause
- [ ] 07-02-PLAN.md -- Fix all 15 skill-* specs (batch fix based on triage root cause)
- [ ] 07-03-PLAN.md -- Fix 4 signup-* specs + ~20 login-dependent other specs
- [ ] 07-04-PLAN.md -- Fix ~7 non-auth specs + full daily validation run (85+/88 target)
- [ ] 07-05-PLAN.md -- Persistent date-stamped screenshot storage + fix sync-test-results.sh workflow name

### Phase 8: Sender Barrel Deployment
**Goal**: Deploy the sender sub-module barrel so chatSyncServiceSenders.ts is a re-export file and import-audit.test.ts passes — closing the ARCH-03 gap
**Depends on**: Phase 4
**Requirements**: ARCH-03
**Gap Closure**: Closes ARCH-03 from v1.0 audit — sender barrel created but never deployed to dev
**Success Criteria** (what must be TRUE):
  1. chatSyncServiceSenders.ts is a barrel re-export file (~30 lines) with no inline crypto imports
  2. All 5 sender sub-modules are imported via the barrel — zero orphaned files
  3. import-audit.test.ts passes with zero ARCH-03 violations
  4. All existing dynamic imports of chatSyncServiceSenders continue to work unchanged
**Plans:** 1 plan

Plans:
- [x] 08-01-PLAN.md -- Atomic barrel swap + full encryption test suite validation

### Phase 9: OTel Tracing Fix
**Goal**: OTel tracing is practically useful — privacy tiers resolve correctly based on user settings, all WS handlers are instrumented, and debug.py trace CLI shows full span trees with meaningful detail
**Depends on**: Phase 6
**Requirements**: OTEL-02, OTEL-05, OTEL-06
**Gap Closure**: Closes OTEL-02, OTEL-05, OTEL-06 from v1.0 audit + user-reported debug.py trace output issues
**Success Criteria** (what must be TRUE):
  1. WebSocket handlers set enduser.debug_opted_in and enduser.is_admin as span attributes from the user record
  2. TracePrivacyFilter correctly resolves Tier 1/2/3 based on actual user settings (not always Tier 1)
  3. key_received_handler.py has OTel spans visible in traces
  4. `debug.py trace recent --last 5m` shows all requests from the last N minutes with full span trees, HTTP paths, durations, and status codes
  5. `debug.py trace errors` shows error detail including HTTP path, status code, and child spans (not just bare root spans)
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8 -> 9

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Audit & Discovery | 3/3 | Done | 2026-03-26 |
| 2. Foundation Layer Extraction | 2/2 | Done | 2026-03-26 |
| 3. Key Management Hardening | 3/3 | Done | 2026-03-26 |
| 4. Sync Handler Rewire | 3/3 | Done | 2026-03-26 |
| 5. Testing & Documentation | 3/3 | Done | 2026-03-26 |
| 6. OpenTelemetry Distributed Tracing | 5/5 | Done | 2026-03-27 |
| 7. E2E Test Suite Repair | 6/6 | Done | 2026-03-27 |
| 8. Sender Barrel Deployment | 0/1 | Not started | - |
| 9. OTel Tracing Fix | 0/? | Not started | - |
