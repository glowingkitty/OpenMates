# Phase 2: Foundation Layer Extraction - Context

**Gathered:** 2026-03-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Extract stateless encryption modules (MessageEncryptor, MetadataEncryptor) from the existing `cryptoService.ts` (1928 lines) with clean single-responsibility boundaries. No behavior changes — all existing tests and regression fixtures from Phase 1 must pass after extraction. Each module stays under 500 lines.

</domain>

<decisions>
## Implementation Decisions

### Module Boundaries
- **D-01:** Claude's discretion — use Phase 1 code inventory (`docs/architecture/core/encryption-code-inventory.md`) and format documentation (`docs/architecture/core/encryption-formats.md`) to determine what goes into MessageEncryptor vs MetadataEncryptor vs what stays in cryptoService.ts
- **D-02:** Claude's discretion — determine the exact function groupings based on the 135+ call site analysis

### File Organization
- **D-03:** Claude's discretion — organize extracted modules under the existing `frontend/packages/ui/src/services/encryption/` directory, following established naming conventions from the codebase

### Migration Strategy
- **D-04:** Claude's discretion — choose between extract-and-redirect (keep old API, delegate internally) vs extract-and-replace (update callers) based on risk assessment from Phase 1 findings

### Claude's Discretion
All extraction decisions are delegated to Claude — module boundaries, file organization, migration strategy, and function groupings. Use Phase 1 audit findings and research recommendations as the primary guide. The constraint is: no behavior changes, all 26 regression tests pass, each new module under 500 lines.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 1 Audit Deliverables
- `docs/architecture/core/encryption-code-inventory.md` — 135+ call sites across 22 files, bypass classification, function groupings
- `docs/architecture/core/encryption-formats.md` — Byte-level ciphertext formats for all 4 encrypted field types
- `docs/architecture/core/encryption-root-causes.md` — Root cause analysis showing bugs are in ChatKeyManager/sync, not crypto operations
- `docs/architecture/core/master-key-lifecycle.md` — Master key derivation and cross-device distribution

### Source Files to Extract From
- `frontend/packages/ui/src/services/cryptoService.ts` (1928 lines) — Primary extraction target
- `frontend/packages/ui/src/services/cryptoKeyStorage.ts` (392 lines) — Key storage operations
- `frontend/packages/ui/src/services/encryption/ChatKeyManager.ts` (1046 lines) — State machine (preserve as-is)
- `frontend/packages/ui/src/services/db/chatKeyManagement.ts` (861 lines) — DB-level key operations

### Research Recommendations
- `.planning/research/ARCHITECTURE.md` — Recommended MessageEncryptor and MetadataEncryptor module structure
- `.planning/research/PITFALLS.md` — Backwards compatibility risks during refactoring

### Regression Test Fixtures
- `frontend/packages/ui/src/services/encryption/__tests__/regression-fixtures.test.ts` — 14 tests, MUST pass after extraction
- `frontend/packages/ui/src/services/encryption/__tests__/formats.test.ts` — 12 tests, MUST pass after extraction

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ChatKeyManager.ts` — State machine with provenance tracking. Research says preserve as-is; extraction should not modify it
- Existing test infrastructure (vitest) with 26 passing regression tests as validation gate

### Established Patterns
- TypeScript services in `frontend/packages/ui/src/services/` use camelCase naming
- Encryption-specific modules live under `frontend/packages/ui/src/services/encryption/`
- Test files use `__tests__/` directory pattern with `.test.ts` extension

### Integration Points
- `cryptoService.ts` is imported by 10+ sync handler files — all callers must work after extraction
- `ChatKeyManager.ts` calls into cryptoService — extraction must preserve this interface

</code_context>

<specifics>
## Specific Ideas

No specific user requirements — full Claude discretion on all extraction decisions. The only hard constraints are:
1. No behavior changes
2. All 26 regression tests pass after every extraction step
3. Each new module under 500 lines
4. Clean single-responsibility boundaries

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 02-foundation-layer-extraction*
*Context gathered: 2026-03-26*
