# Phase 5: Testing & Documentation - Context

**Gathered:** 2026-03-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Validate the rebuilt encryption architecture with automated Playwright multi-tab tests, confirm performance with benchmarks, document the architecture end-to-end, update Phase 1 docs to reflect the post-rebuild state, and add a file-size monitoring script with CI integration. This phase produces tests, documentation, and tooling — no encryption/sync code changes.

</domain>

<decisions>
## Implementation Decisions

### Multi-Tab Test Strategy
- **D-01:** Create new dedicated Playwright specs for TEST-01 and TEST-02, separate from the existing `multi-session-encryption.spec.ts`. The existing spec tests cross-browser (simulating cross-device via two browser instances); the new specs test same-browser tabs via BrowserContext. Keeps concerns separate.
- **D-02:** Scope limited to the two required scenarios only: TEST-01 (two tabs, same chat, both decrypt) and TEST-02 (create in tab A, open in tab B, content decrypts). No additional reconnection or key conflict scenarios — the existing multi-session spec and unit tests cover those.

### Performance Testing
- **D-03:** Performance threshold is **under 2 seconds** for encrypting/decrypting a 100-message chat. 2s is generous for NaCl symmetric crypto and leaves headroom for slower devices.
- **D-04:** Performance benchmark runs as a **Vitest unit test** in the encryption `__tests__/` directory. Fast, repeatable, no browser overhead. Measures pure crypto performance.

### Architecture Documentation
- **D-05:** Create one new document: `docs/architecture/core/encryption-architecture.md` — the end-to-end architecture overview. Module boundaries, data flow (encrypt→sync→decrypt), Mermaid diagrams, and how the pieces fit together. References the existing Phase 1 docs for details.
- **D-06:** Update the existing Phase 1 docs (`encryption-code-inventory.md`, `encryption-root-causes.md`, `encryption-formats.md`, `master-key-lifecycle.md`) to reflect the post-rebuild state: new module names from Phase 2, removed bypass paths from Phase 3-4, updated file paths.

### File-Size Monitoring
- **D-07:** 500-line threshold, consistent with ARCH-04 constraint used throughout the rebuild.
- **D-08:** Report-only script in `scripts/` with **grandfathering** — tracks a baseline of existing large files so they're listed but not flagged as regressions. New files crossing the threshold are highlighted.
- **D-09:** Soft CI warning integration — the script also runs in CI and adds a warning (not a blocker) when new files exceed the threshold. No pre-commit hook — avoids blocking legitimate work on existing large files.

### Claude's Discretion
- Playwright test file naming and organization within `tests/`
- BrowserContext vs separate pages approach for multi-tab testing
- Mermaid diagram style and level of detail in architecture doc
- File-size script implementation details (baseline storage format, CI integration mechanism)
- Which directories the file-size script monitors (encryption/sync strictly, rest informatively)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 1 Audit Docs (to be updated)
- `docs/architecture/core/encryption-code-inventory.md` — Call site inventory, bypass classification (needs post-rebuild update)
- `docs/architecture/core/encryption-root-causes.md` — Root cause analysis of 3 bug reports (needs post-rebuild update)
- `docs/architecture/core/encryption-formats.md` — Byte-level ciphertext formats for all encrypted field types
- `docs/architecture/core/master-key-lifecycle.md` — Master key derivation and cross-device distribution

### Existing Test Infrastructure
- `frontend/apps/web_app/tests/multi-session-encryption.spec.ts` — Existing cross-browser encryption E2E test (reference for patterns, not to extend)
- `frontend/packages/ui/src/services/encryption/__tests__/regression-fixtures.test.ts` — 14 regression test fixtures
- `frontend/packages/ui/src/services/encryption/__tests__/formats.test.ts` — 12 format validation tests
- `frontend/packages/ui/src/services/encryption/__tests__/ChatKeyManager.test.ts` — ChatKeyManager unit tests
- `frontend/packages/ui/src/services/encryption/__tests__/import-audit.test.ts` — Import audit test for ARCH-03

### Encryption Modules (post-rebuild)
- `frontend/packages/ui/src/services/encryption/MessageEncryptor.ts` — Stateless chat-key encrypt/decrypt
- `frontend/packages/ui/src/services/encryption/MetadataEncryptor.ts` — Stateless master-key + embed-key operations
- `frontend/packages/ui/src/services/encryption/ChatKeyManager.ts` — Hardened key management with Web Locks, withKey(), BroadcastChannel

### Sync Modules (post-rebuild)
- `frontend/packages/ui/src/services/chatSyncService/senders/` — Decomposed sender modules (from Phase 4 split)
- `frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts` — AI response sync handlers
- `frontend/packages/ui/src/services/chatSyncServiceHandlersCoreSync.ts` — Core sync handlers
- `frontend/packages/ui/src/services/chatSyncServiceHandlersPhasedSync.ts` — Phased sync handlers

### Test Infrastructure References
- `frontend/apps/web_app/playwright.config.ts` — Playwright configuration
- `frontend/packages/ui/vitest.config.ts` — Vitest configuration for UI package
- `.planning/codebase/TESTING.md` — Full testing patterns documentation

### Research
- `.planning/research/ARCHITECTURE.md` — Recommended module structure and data flows
- `.planning/research/PITFALLS.md` — 13 domain pitfalls with prevention strategies

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `multi-session-encryption.spec.ts` — Patterns for dual-login, chat creation, message verification, sidebar discovery. Reuse helper functions for the new tab specs.
- `signup-flow-helpers.js` — TOTP generation, screenshot helpers, test account management — shared across E2E specs.
- `tests/helpers/env-guard.js` — Environment variable guard for skipping tests without credentials.
- 6 existing encryption unit tests in `__tests__/` — established Vitest patterns for crypto testing.

### Established Patterns
- E2E specs use CommonJS `require()` (Playwright Docker runtime convention)
- E2E specs follow naming: `<feature>-flow.spec.ts` or `<feature>.spec.ts`
- Unit tests follow naming: `<module>.test.ts` in `__tests__/` subdirectory
- Test account credentials via env vars (`OPENMATES_TEST_ACCOUNT_*`)

### Integration Points
- New Playwright specs go in `frontend/apps/web_app/tests/`
- New Vitest tests go in `frontend/packages/ui/src/services/encryption/__tests__/`
- Architecture docs go in `docs/architecture/core/`
- Scripts go in `scripts/`

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 05-testing-documentation*
*Context gathered: 2026-03-26*
