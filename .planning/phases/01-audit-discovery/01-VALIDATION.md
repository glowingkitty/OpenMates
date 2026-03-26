---
phase: 1
slug: audit-discovery
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-26
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | vitest 3.2+ (frontend) / pytest (backend) |
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
| TBD | TBD | TBD | AUDT-01 | manual | grep-based inventory verification | N/A | ⬜ pending |
| TBD | TBD | TBD | AUDT-02 | manual | doc format verification | N/A | ⬜ pending |
| TBD | TBD | TBD | AUDT-03 | unit | `npx vitest run src/services/encryption/__tests__/` | ✅ | ⬜ pending |
| TBD | TBD | TBD | AUDT-04 | manual | doc completeness check | N/A | ⬜ pending |
| TBD | TBD | TBD | AUDT-05 | manual | doc completeness check | N/A | ⬜ pending |
| TBD | TBD | TBD | AUDT-06 | grep | `grep -rn 'cryptoService' --include='*.ts' | grep -v ChatKeyManager` | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- Existing infrastructure covers AUDT-03 (regression test fixtures via vitest)
- AUDT-01, AUDT-02, AUDT-04, AUDT-05 produce documentation — verified by content checks
- AUDT-06 verified by grep commands

*Existing infrastructure covers all phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Code path inventory completeness | AUDT-01 | Requires human review of grep results against codebase | Verify every encrypt/decrypt function in inventory exists in code |
| Binary format accuracy | AUDT-02 | Byte-level diagrams need human verification | Compare diagram against actual ciphertext hex dump |
| Master key documentation | AUDT-04, AUDT-05 | Architecture understanding requires human validation | Read docs, verify they match actual code behavior |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
