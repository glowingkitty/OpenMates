# Milestones

## v1.0 Encryption & Sync Architecture Rebuild (Shipped: 2026-03-27)

**Phases completed:** 9 phases, 29 plans, 55 tasks

**Key accomplishments:**

- Root cause analysis of 3 "content decryption failed" bugs mapped to async timing races on secondary devices, plus complete 135+ call site inventory with ChatKeyManager bypass classification showing 0 violations
- Byte-level ciphertext format documentation for all 4 AES-GCM formats, plus complete master key derivation chain from credential to content encryption with cross-device distribution analysis
- 26 regression and byte-layout tests covering all 4 encryption format generations (OM-header, legacy, wrapped key, master-key) with error detection and edge cases as safety net for Phases 2-4
- Extracted chat-key encrypt/decrypt functions into stateless MessageEncryptor.ts (338 lines) with re-export barrel in cryptoService.ts preserving all 30+ dynamic import sites
- Extracted 14 master-key and embed-key functions into MetadataEncryptor.ts (473 lines) completing Phase 2 encryption module separation with all modules under 500 lines
- Web Locks mutex on ChatKeyManager key generation with cross-tab exclusion, SSR fallback, timeout handling, and formalized failed->loading retry
- BroadcastChannel keyLoaded propagation with pending-ops guard, ChatKeyManager rewrapKey for hidden chat bypass closure, and formal cross-device master key documentation
- withKey() buffering in 10 sync handler decrypt paths with full KEYS-04 classification, async sidebar fallbacks, and 7 new integration tests proving key-before-content guarantee
- Split 2851-line chatSyncServiceSenders.ts into 5 domain-focused sub-modules with barrel re-export, zero breaking changes, all 95 encryption tests passing
- WebSocket key_received/key_delivery_confirmed round-trip protocol with BroadcastChannel cross-tab verification tests (95 encryption tests passing)
- Converted 30+ dynamic cryptoService imports across 8 sync handler files to static MessageEncryptor/MetadataEncryptor imports with 15-test import audit guard (110 total encryption tests passing)
- Playwright E2E spec testing two-tab encryption with single BrowserContext, plus verification of all 69 encryption unit tests passing post-rebuild
- Vitest encryption benchmark (36ms for 200 AES-GCM ops) and bash file-size script with 500-line threshold grandfathering 45 known large files
- End-to-end encryption architecture document with module map, encrypt-sync-decrypt sequence, and key lifecycle Mermaid diagrams; four Phase 1 audit docs updated with post-rebuild resolution status and cross-references
- OTel SDK 1.40.0 with auto-instrumentation for FastAPI/httpx/Celery/Redis and 3-tier TracePrivacyFilter exporting to OpenObserve
- Directus debug_logging_opted_in field with Settings Privacy toggle and 21-locale i18n support for Tier 3 trace consent
- Custom WebSocket span instrumentation with _traceparent propagation and browser OTel SDK exporting through authenticated OTLP proxy
- debug.py trace CLI with 6 subcommands (request/errors/task/session/slow/login) querying OTLP traces from OpenObserve with indented span timeline output
- OTel trace_id replaces UUID request_id for unified log correlation, with trace IDs flowing into issue reports and debug timeline
- Added 300s subprocess timeout to vitest runner to unblock daily cron pipeline that hangs on vitest deadlocks
- Dispatched 6 representative specs to GHA capturing actual Playwright errors, categorized all 46 failures into 5 root-cause groups with fix strategies for Plans 02-04
- TOTP clock-drift compensation via window offset cycling in loginToTestAccount(), plus signup spec timeout increases from 240s to 420-480s for GHA runners
- Fixed selector drift in 404/status specs, applied embed display type fix, migrated a11y login to shared helper -- 5 specs patched, 2 verified correct as-is
- Date-stamped screenshot archiving with 30-day retention and corrected GHA workflow reference in sync script
- Replaced 2856-line chatSyncServiceSenders.ts monolith with 19-line barrel re-export, closing ARCH-03 (9 forbidden cryptoService imports eliminated)
- Reusable ws_span_helper with user attribute injection so TracePrivacyFilter resolves correct tier (not always Tier 1)
- All 37 WebSocket handlers instrumented with OTel spans via ws_span_helper, with 149-test audit suite preventing regression
- Full span tree rendering with Unicode hierarchy for all trace CLI commands, replacing broken first_event-only output

---
