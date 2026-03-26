---
phase: 3
slug: key-management-hardening
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-26
---

# Phase 3 — Validation Strategy

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
| TBD | TBD | TBD | KEYS-01 | unit | `npx vitest run src/services/encryption/__tests__/ChatKeyManager.test.ts` | ✅ | ⬜ pending |
| TBD | TBD | TBD | KEYS-02 | unit | `npx vitest run src/services/encryption/__tests__/` | ✅ | ⬜ pending |
| TBD | TBD | TBD | KEYS-03 | grep | `grep -rn 'getKeySync\|cryptoService.*encrypt\|cryptoService.*decrypt' --include='*.ts' frontend/packages/ui/src/services/chat*` | N/A | ⬜ pending |
| TBD | TBD | TBD | KEYS-04 | unit | `npx vitest run src/services/encryption/__tests__/` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | KEYS-05 | unit | `npx vitest run src/services/encryption/__tests__/ChatKeyManager.test.ts` | ✅ | ⬜ pending |
| TBD | TBD | TBD | KEYS-06 | manual | doc verification | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- navigator.locks mock needed for vitest/jsdom (jsdom doesn't implement Web Locks API)
- Existing ChatKeyManager.test.ts needs extension for new mutex/buffering behavior

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Cross-device key sync | KEYS-06 | Requires two physical devices | Open chat on Mac, verify same chat opens on iPhone |
| Message buffering UX | KEYS-04 | Visual timing verification | Open chat on secondary device, verify messages appear after key sync |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
