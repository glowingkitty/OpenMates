---
phase: 4
slug: sync-handler-rewire
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-26
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | vitest 3.2+ (frontend), pytest (backend) |
| **Config file** | `frontend/packages/ui/vitest.config.ts` |
| **Quick run command** | `cd frontend/packages/ui && npx vitest run src/services/encryption/` |
| **Full suite command** | `cd frontend/packages/ui && npx vitest run` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run encryption test suite
- **After every plan wave:** Run full frontend test suite
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Wave 0 Requirements

- Existing 90 test suite covers regression validation
- New WebSocket ack tests needed (backend pytest)

*Existing infrastructure covers most phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Streaming decryption | SYNC-03 | Requires live AI response | Send message, verify streaming works |
| Background sync | SYNC-04 | Requires multi-device | Open chat on second device in background |
| Reconnection | SYNC-05 | Requires network interruption | Disconnect/reconnect, verify sync |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
