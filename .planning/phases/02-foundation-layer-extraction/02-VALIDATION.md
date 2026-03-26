---
phase: 2
slug: foundation-layer-extraction
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-26
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | vitest 3.2+ |
| **Config file** | `frontend/packages/ui/vitest.config.ts` |
| **Quick run command** | `cd frontend/packages/ui && npx vitest run src/services/encryption/` |
| **Full suite command** | `cd frontend/packages/ui && npx vitest run` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd frontend/packages/ui && npx vitest run src/services/encryption/`
- **After every plan wave:** Run `cd frontend/packages/ui && npx vitest run`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | ARCH-01 | unit | `npx vitest run src/services/encryption/__tests__/regression-fixtures.test.ts` | ✅ | ⬜ pending |
| TBD | TBD | TBD | ARCH-02 | unit | `npx vitest run src/services/encryption/__tests__/formats.test.ts` | ✅ | ⬜ pending |
| TBD | TBD | TBD | ARCH-04 | grep | `wc -l src/services/encryption/MessageEncryptor.ts src/services/encryption/MetadataEncryptor.ts` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- Existing 26 regression tests from Phase 1 cover all validation needs
- No new test infrastructure required

*Existing infrastructure covers all phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Import paths still work | ARCH-01/02 | Dynamic imports need runtime check | Verify app loads without import errors in dev mode |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
