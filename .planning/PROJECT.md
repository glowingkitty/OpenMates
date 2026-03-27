# Encryption & Sync Architecture Rebuild

## What This Is

A comprehensive audit and rebuild of OpenMates' client-side encryption, key management, and real-time chat sync architecture. The current system suffers from recurring "content decryption failed" errors caused by inconsistent key management, race conditions in cross-device sync, and a codebase that grew through incremental patches without a coherent design. This project replaces the messy, fragile encryption/sync code with a clean, well-structured, fully documented architecture — while preserving backwards compatibility with all existing encrypted chats.

## Core Value

Every encrypted chat must decrypt successfully on every device, every time — no exceptions, no race conditions, no key mismatches.

## Requirements

### Validated

- ✓ Client-side encryption of chat messages before server sync — existing
- ✓ Real-time WebSocket sync of chats across devices — existing
- ✓ Server-side vault-encrypted cache of last 3 active chats for AI inference — existing
- ✓ Shared chat links with URL-fragment key embedding — existing (working fine)
- ✓ Device fingerprinting and key association — existing
- ✓ Passkey authentication flow — existing

### Active

(None — all v1.0 requirements shipped. See next milestone for new work.)

### Validated in v1.0

- ✓ Audit current encryption/key management code — Phase 1 (135+ call sites, 22 files, 3 bug root causes)
- ✓ Identify all encryption code paths — Phase 1 (encryption-code-inventory.md)
- ✓ Identify root causes of "content decryption failed" — Phase 1 (async timing races on secondary devices)
- ✓ Design clean encryption architecture — Phase 2+4 (MessageEncryptor, MetadataEncryptor, ChatKeyManager)
- ✓ Refactor into single-responsibility modules — Phase 2 (338 + 473 lines, under 500 each)
- ✓ Key generation only when no valid key exists — Phase 3 (Web Locks mutex)
- ✓ Cross-device key sync atomic and race-free — Phase 3 (withKey() buffering)
- ✓ Foreground streaming decryption — Phase 4 (encryptor module routing)
- ✓ Background device sync decryption — Phase 4 (phased sync + withKey)
- ✓ All existing chats readable after rebuild — Phase 5 (111 tests, all passing)
- ✓ Architecture documentation — Phase 5 (encryption-architecture.md with Mermaid diagrams)
- ✓ File-size monitoring script — Phase 5 (500-line threshold, 45 grandfathered)
- ✓ OpenTelemetry distributed tracing — Phase 6+9 (backend + frontend SDK, privacy tiers, debug.py trace CLI)
- ✓ E2E test suite repair — Phase 7 (46 failing specs fixed, 85+/88 target)
- ✓ Sender barrel deployment — Phase 8 (ARCH-03 gap closed)
- ✓ OTel tracing fix — Phase 9 (privacy tiers wired, all WS handlers instrumented, trace CLI reworked)

### Out of Scope

- Shared chat link encryption — already working, don't touch it
- ActiveChat.svelte god-component split — related but separate project
- New encryption algorithms or protocols — keep the same crypto primitives
- Backend AI inference pipeline — only touch the vault-encrypted cache interface if needed
- Authentication system changes — passkey/login flow is not the problem

## Context

**v1.0 shipped 2026-03-27.** The encryption architecture rebuild is complete.

- **Current state:** Encryption code is cleanly separated into MessageEncryptor (338 lines), MetadataEncryptor (473 lines), and ChatKeyManager (1046 lines) with zero god-files. All sync handlers route crypto through encryptor modules (ARCH-03 enforced by 15-test import audit).
- **Key management:** Web Locks mutex prevents duplicate key generation across tabs. withKey() buffering guarantees key-before-content in all decrypt paths. BroadcastChannel propagates keys across tabs.
- **Observability:** OpenTelemetry traces all 37 WebSocket handlers with privacy-tier-aware span attributes. debug.py trace CLI shows full span trees with Unicode hierarchy.
- **Test coverage:** 111 encryption unit tests, multi-tab E2E Playwright spec, file-size monitor, 149-test WS handler instrumentation audit.
- **Known gap:** Embed decryption failures (console/logs) not yet investigated — deferred from v1.0 scope.
- **174 files changed, 17K insertions, 9K deletions across 9 phases and 29 plans.**

## Constraints

- **Backwards compatibility**: All existing encrypted chats must remain decryptable after the rebuild
- **Same crypto primitives**: Use the same encryption algorithms currently in use — this is an architecture/code-quality project, not a cryptography upgrade
- **Brownfield**: This is a running production system (dev server) with real data — changes must be incremental and verifiable
- **Frontend-first**: The encryption bugs originate in frontend code; backend changes should be minimal and only where the interface requires it

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Audit-first approach | Can't fix what you don't fully understand — need complete picture before any code changes | ✓ Good — Phase 1 audit revealed 3 root causes and 135+ call sites |
| Preserve existing chats | Real chat data exists that must remain accessible | ✓ Good — 111 tests confirm all formats decrypt correctly |
| Focus on encryption/sync only | ActiveChat.svelte split and other code quality issues are separate projects | ✓ Good — clean scope, no creep |
| File-size monitoring script | Prevent future god-files from accumulating silently | ✓ Good — 500-line threshold with grandfathering |
| Extract-and-redirect barrel pattern | Preserve 105 dynamic import sites while extracting modules | ✓ Good — zero consumer changes needed |
| Web Locks for cross-tab mutex | Prevent duplicate key generation across browser tabs | ✓ Good — proven in tests, SSR fallback included |
| withKey() buffering over getKeySync | Atomic key-before-content guarantee | ✓ Good — eliminated race conditions in 10 decrypt paths |
| Full round-trip key delivery ack | Sender knows recipient received the key | ✓ Good — key_received/key_delivery_confirmed protocol |
| OTel over Sentry | Single observability stack, CLI-first for Claude debugging | ✓ Good — debug.py trace CLI works with full span trees |
| 3-tier privacy model | Balance observability with user privacy | ⚠️ Revisit — tiers now wired but untested in production |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-03-27 after v1.0 milestone completion*
