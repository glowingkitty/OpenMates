---
phase: 5
slug: testing-documentation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-26
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Vitest (unit/perf) + Playwright (E2E) |
| **Config file** | `frontend/packages/ui/vitest.config.ts` / `frontend/apps/web_app/playwright.config.ts` |
| **Quick run command** | `cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/` |
| **Full suite command** | `cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/ && cd ../../apps/web_app && npx playwright test tests/multi-tab-*.spec.ts` |
| **Estimated runtime** | ~30 seconds (unit) + ~120 seconds (E2E) |

---

## Sampling Rate

- **After every task commit:** Run `cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/`
- **After every plan wave:** Run full suite command
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 01 | 1 | TEST-01 | E2E | `npx playwright test tests/multi-tab-same-chat.spec.ts` | ❌ W0 | ⬜ pending |
| 05-01-02 | 01 | 1 | TEST-02 | E2E | `npx playwright test tests/multi-tab-cross-discovery.spec.ts` | ❌ W0 | ⬜ pending |
| 05-02-01 | 02 | 1 | TEST-03 | unit | `npx vitest run src/services/encryption/__tests__/regression-fixtures.test.ts` | ✅ | ⬜ pending |
| 05-02-02 | 02 | 1 | TEST-04 | unit | `npx vitest run src/services/encryption/__tests__/performance.test.ts` | ❌ W0 | ⬜ pending |
| 05-03-01 | 03 | 2 | ARCH-05 | manual | Review `docs/architecture/core/encryption-architecture.md` exists with Mermaid diagrams | ❌ W0 | ⬜ pending |
| 05-03-02 | 03 | 2 | TEST-05 | script | `node scripts/check-file-sizes.js --ci` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `frontend/apps/web_app/tests/multi-tab-same-chat.spec.ts` — E2E stub for TEST-01
- [ ] `frontend/apps/web_app/tests/multi-tab-cross-discovery.spec.ts` — E2E stub for TEST-02
- [ ] `frontend/packages/ui/src/services/encryption/__tests__/performance.test.ts` — Performance benchmark stub for TEST-04

*Existing infrastructure covers TEST-03 (regression-fixtures.test.ts exists).*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Architecture doc completeness | ARCH-05 | Content quality requires human review | Verify Mermaid diagrams render, all modules documented, data flow covers encrypt→sync→decrypt |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
