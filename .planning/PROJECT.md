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

- [ ] Audit current encryption/key management code and document exactly how it works today
- [ ] Identify all code paths that encrypt, decrypt, generate keys, or sync keys
- [ ] Identify root cause(s) of recurring "content decryption failed" errors
- [ ] Identify root cause(s) of embed decryption failures visible in console/logs
- [ ] Design a clean encryption architecture with clear module boundaries
- [ ] Refactor encryption code into well-separated, single-responsibility modules
- [ ] Ensure key generation only happens when no valid key exists (never overwrites)
- [ ] Ensure cross-device key sync is atomic and race-condition-free
- [ ] Ensure foreground devices receive streaming responses with correct decryption
- [ ] Ensure background devices receive synced chats with correct decryption
- [ ] All existing encrypted chats remain readable after the rebuild
- [ ] Create architecture documentation (`docs/architecture/`) explaining the encryption flow end-to-end
- [ ] Create a file-size monitoring script that flags oversized files and suggests splits

### Out of Scope

- Shared chat link encryption — already working, don't touch it
- ActiveChat.svelte god-component split — related but separate project
- New encryption algorithms or protocols — keep the same crypto primitives
- Backend AI inference pipeline — only touch the vault-encrypted cache interface if needed
- Authentication system changes — passkey/login flow is not the problem

## Context

- **Recurring failures:** 3+ "content decryption failed" bug reports in the last 2 days alone (issues f305f5cf, a4ca102f, 7d2d2efc), all from the same admin user testing across Mac and iPhone
- **Whack-a-mole pattern:** Multiple fix attempts since March 2026 — each addresses one symptom but the root architecture keeps producing new failures. Key commits: `3d8148bc4` (permanent key sync architecture), `33e87e0be` (async key lookup race), `debbf2772` (cross-device title corruption), `e418f49e6` (CLI decryption after fingerprint format change)
- **Code quality:** Encryption logic is spread across large, poorly-separated files. The codebase grew through vibe coding without maintaining a clear mental model of the architecture
- **Single user so far:** Only admin (f21b15a5) is actively using the system, so the blast radius of changes is limited
- **Encryption lives in frontend:** Primary encryption/decryption code is in `frontend/packages/ui/src/` (services like `chatSyncService`, `websocketService`, `db`, `encryption`)
- **Server role:** Backend receives cleartext during message processing, caches vault-encrypted versions of last 3 active chats for faster AI inference. Backend also has vault key management code
- **Existing codebase map:** `.planning/codebase/` contains 7 documents mapping the full architecture, stack, conventions, and concerns

## Constraints

- **Backwards compatibility**: All existing encrypted chats must remain decryptable after the rebuild
- **Same crypto primitives**: Use the same encryption algorithms currently in use — this is an architecture/code-quality project, not a cryptography upgrade
- **Brownfield**: This is a running production system (dev server) with real data — changes must be incremental and verifiable
- **Frontend-first**: The encryption bugs originate in frontend code; backend changes should be minimal and only where the interface requires it

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Audit-first approach | Can't fix what you don't fully understand — need complete picture before any code changes | — Pending |
| Preserve existing chats | Real chat data exists that must remain accessible | — Pending |
| Focus on encryption/sync only | ActiveChat.svelte split and other code quality issues are separate projects | — Pending |
| File-size monitoring script | Prevent future god-files from accumulating silently | — Pending |

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
*Last updated: 2026-03-26 after initialization*
