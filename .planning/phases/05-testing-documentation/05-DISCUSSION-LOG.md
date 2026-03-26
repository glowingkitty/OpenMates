# Phase 5: Testing & Documentation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-26
**Phase:** 05-testing-documentation
**Areas discussed:** Multi-tab test strategy, Performance thresholds, Architecture doc scope, File-size monitor design

---

## Multi-tab Test Strategy

### Q1: How should multi-tab tests relate to existing multi-session-encryption.spec.ts?

| Option | Description | Selected |
|--------|-------------|----------|
| New dedicated specs | Create separate tab-specific specs for TEST-01/02. Existing spec tests cross-browser; new specs test same-browser tabs via BrowserContext. | ✓ |
| Extend existing spec | Add tab-based scenarios to multi-session-encryption.spec.ts. Single file covers all encryption E2E scenarios. | |
| Replace existing spec | Replace existing spec with comprehensive suite covering both tabs and separate browsers. | |

**User's choice:** New dedicated specs
**Notes:** None

### Q2: Should multi-tab tests cover additional scenarios beyond TEST-01/02?

| Option | Description | Selected |
|--------|-------------|----------|
| Just the two required | TEST-01 and TEST-02 only. Existing multi-session spec already covers cross-device. | ✓ |
| Add reconnection scenario | Also test tab offline/reconnection mapping to SYNC-05. | |
| Add key conflict scenario | Also test simultaneous chat creation to verify Web Locks mutex. | |

**User's choice:** Just the two required
**Notes:** None

---

## Performance Thresholds

### Q3: Acceptable time bound for encrypting/decrypting 100-message chat?

| Option | Description | Selected |
|--------|-------------|----------|
| Under 2 seconds | Generous for NaCl symmetric crypto, leaves headroom for slower devices. | ✓ |
| Under 500ms | Strict target, less headroom for mobile. | |
| Under 5 seconds | Very generous, only fails if fundamentally broken. | |

**User's choice:** Under 2 seconds
**Notes:** None

### Q4: Where should the performance benchmark run?

| Option | Description | Selected |
|--------|-------------|----------|
| Vitest unit test | In encryption __tests__/. Fast, repeatable, measures pure crypto. | ✓ |
| Playwright E2E test | Real browser context. More realistic but slower and flakier. | |
| Standalone script | Node.js script in scripts/. Independent of test frameworks. | |

**User's choice:** Vitest unit test
**Notes:** None

---

## Architecture Doc Scope

### Q5: What additional documentation does ARCH-05 need beyond Phase 1 docs?

| Option | Description | Selected |
|--------|-------------|----------|
| End-to-end flow doc | One new document: encryption-architecture.md with module boundaries, data flow, Mermaid diagrams. | ✓ |
| Full developer guide | Multiple new docs: overview + onboarding guide + troubleshooting runbook. | |
| Update existing docs only | No new doc, just update the 3 Phase 1 docs. | |

**User's choice:** End-to-end flow doc
**Notes:** None

### Q6: Should existing Phase 1 docs be updated to reflect post-rebuild state?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, update them | Code inventory and root causes reference pre-rebuild paths. Update for accuracy. | ✓ |
| No, leave as-is | Phase 1 docs are historical artifacts. | |
| Archive and replace | Move to archive/, let new doc be single source of truth. | |

**User's choice:** Yes, update them
**Notes:** None

---

## File-Size Monitor Design

### Q7: What line threshold should trigger a warning?

| Option | Description | Selected |
|--------|-------------|----------|
| 500 lines | Matches ARCH-04 constraint. Consistent with project standard. | ✓ |
| 400 lines | Stricter, catches files earlier. | |
| 600 lines | More lenient for test suites and generated code. | |

**User's choice:** 500 lines
**Notes:** None

### Q8: Where should the file-size monitor run and which directories?

| Option | Description | Selected |
|--------|-------------|----------|
| Script + encryption dirs | scripts/ script monitoring encryption and sync handler files. | |
| Script + all frontend services | Monitor all services/ and components/. Broader coverage. | |
| Pre-commit hook + encryption dirs | Git pre-commit hook blocking commits over 500 lines. | |

**User's choice:** Other — Report + soft CI warning
**Notes:** User raised concern that many existing files exceed 500 lines, making a pre-commit hook impractical. Discussed report-only script with grandfathering (baseline tracking). User chose report-only with soft CI warning: script in scripts/ that reports but doesn't block, with CI integration that adds warnings (not failures) for new files crossing the threshold.

---

## Claude's Discretion

- Playwright test file naming and BrowserContext approach for multi-tab testing
- Mermaid diagram style and detail level in architecture doc
- File-size script implementation (baseline format, CI mechanism)
- Which directories to monitor (encryption/sync strictly, rest informatively)

## Deferred Ideas

None — discussion stayed within phase scope.
