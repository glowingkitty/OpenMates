# Project Research Summary

**Project:** Encryption & Sync Architecture Rebuild
**Domain:** Client-side E2E encrypted chat with cross-device WebSocket sync
**Researched:** 2026-03-26
**Confidence:** HIGH

## Executive Summary

OpenMates already has a cryptographically correct foundation: AES-GCM 256-bit via the Web Crypto API, PBKDF2/HKDF key derivation, AES-KW key wrapping, and IndexedDB persistence for master and chat keys. The encryption primitives do not need to change. The rebuild is an architectural correction: scattered crypto calls throughout the sync handlers bypass the `ChatKeyManager` state machine, race conditions allow multiple code paths to generate duplicate keys for existing chats, and cross-tab coordination is incomplete. These structural gaps — not algorithm weaknesses — are the direct cause of the "content decryption failed" errors reported by users.

The recommended approach is a layered refactor following the existing component dependency graph. Pure stateless crypto functions (`CryptoOperations`, `MessageEncryptor`, `MetadataEncryptor`) form the foundation. Above them, `ChatKeyManager` serves as the single in-memory key authority enforcing the `unloaded → loading → ready → failed` state machine. The sync handlers at the top layer must be rewired to call only `chatKeyManager.withKey()` and the stateless encryptors — never raw `cryptoService.ts` functions. Two browser APIs (`Web Locks` for mutex, `BroadcastChannel` for cross-tab coordination) address the multi-tab key corruption class of bugs. No new npm packages are needed.

The highest-risk phase is the refactor of the sync handler layer: `chatSyncServiceSenders.ts` and the phased sync handlers contain the live bug paths and touch the most code. The rebuild must preserve backward compatibility with all existing ciphertext (documented format: `[IV (12 bytes)][ciphertext][auth tag (16 bytes)]`) because breaking old data is irreversible. The architectural gap around master key transfer to new devices (currently a fresh master key is generated per device, which should break existing wrapped chat keys — but appears to be papered over elsewhere) must be investigated and resolved during the audit phase.

---

## Key Findings

### Recommended Stack

No new libraries are required. The full rebuild runs on browser-native APIs. The only meaningful additions are `Web Locks API` (`navigator.locks`) for mutex control during key generation and `BroadcastChannel API` for cross-tab state propagation — both available since March 2022 and Baseline Widely Available. All crypto stays on `Web Crypto API` (`crypto.subtle`). The existing `tweetnacl@1.0` dependency is retained for the email encryption path only and is explicitly out of scope.

**Core technologies:**
- `Web Crypto API (crypto.subtle)`: AES-GCM encrypt/decrypt, PBKDF2/HKDF derivation, AES-KW wrapping — hardware-accelerated, non-extractable key support, zero bundle cost; already used throughout the codebase
- `IndexedDB`: Master key persistence (as `CryptoKey` object) and per-chat encrypted key cache — structured-clone stores `CryptoKey` natively; already implemented
- `Web Locks API (navigator.locks)`: Mutex for key generation and write operations — prevents the core race condition where two tabs simultaneously generate different keys for the same chat
- `BroadcastChannel API`: Cross-tab key propagation and `clearAll` on logout — modern replacement for the `localStorage storage` event pattern; already partially used
- `Vitest / Playwright`: Unit tests for state machine transitions and E2E multi-tab/multi-device sync scenarios — already in use; expand coverage to lock/broadcast patterns

### Expected Features

All table-stakes features are already architecturally present; the rebuild enforces and hardenes them. The primary work is closing bypass paths, not building new capabilities.

**Must have (table stakes):**
- Single key authority per chat — only the originating device creates the key; all others receive it via `receiveKeyFromServer()`
- Atomic key-before-content guarantee — phased sync must deliver `encrypted_chat_key` before encrypted content in every message type
- Immutable keys — once a chat key is set in `ChatKeyManager`, it cannot be silently replaced; remove all legacy bypass paths
- Backwards compatibility with all existing encrypted data — every code change must pass a "decrypt all existing chats" test fixture
- Key state machine with explicit transitions — all crypto operations routed through `ChatKeyManager`; no direct `cryptoService.ts` calls from sync handlers
- Operation queuing when key unavailable — `withKey()` pattern queues and auto-flushes; never falls through to key generation
- Cross-tab key coordination — `clearAll` on logout propagates via `BroadcastChannel`; `keyLoaded` broadcast warms cache in other tabs (currently lazy-load only)
- Decryption failure visibility — consistent `[Decryption failed]` UI at every decrypt call site; no silent failures

**Should have (differentiators — already implemented, must survive rebuild):**
- Key provenance tracking (`KeySource` enum) — enables forensic debugging of sync failures
- Key fingerprint comparison (FNV-1a hash) — quick cross-device key mismatch detection without exposing key material
- Critical operation lock (`criticalOpCount`) — prevents `clearAll()` from wiping keys mid-encryption
- Phased sync with progressive decryption — metadata first (sidebar), content on demand; reduces perceived load time
- Hidden chat encryption (dual-layer) — plausible deniability via combined secret re-wrapping; do not break
- Decryption failure cache with auto-retry on key change

**Defer (v2+):**
- Encryption health dashboard — admin UI for key sync status across devices; high complexity, low urgency for single-user system
- Per-device key audit log (persisted) — provenance exists in-memory; durable log is nice-to-have after core is stable
- Key rotation for existing chats — explicit anti-feature for current single-user architecture

### Architecture Approach

The target architecture is not a component replacement but a boundary clarification. The same components survive with cleaner separation: `CryptoOperations` (pure stateless functions) at the base, `ChatKeyManager` as the single in-memory key store and state machine, `MessageEncryptor`/`MetadataEncryptor` as thin stateless wrappers (new extractions), and the sync handler layer rewired to use only `chatKeyManager.withKey()` and the encryptors. The sync layer must never call `cryptoService.ts` directly. `WebSocketTransport` stays as a pure transport with no crypto knowledge. Backend changes are minimal — the server already stores encrypted fields as opaque blobs and never sees plaintext chat content.

**Major components:**
1. `ChatKeyManager` (`encryption/ChatKeyManager.ts`) — single source of truth for chat keys in memory; enforces `unloaded/loading/ready/failed` state machine, queue-and-flush, provenance, and critical-op lock
2. `MasterKeyService` (extract from `cryptoKeyStorage.ts` + master key parts of `cryptoService.ts`) — generate, persist, retrieve, and clear the master `CryptoKey`; distinct lifecycle from chat keys
3. `CryptoOperations` (extract pure functions from `cryptoService.ts`) — stateless AES-GCM encrypt/decrypt, base64, key wrap/unwrap; no state, no IDB, no side effects
4. `MessageEncryptor` / `MetadataEncryptor` (new extractions) — stateless encrypt/decrypt of message fields and chat metadata fields; receive key as explicit parameter
5. `SyncEngine` + handlers — orchestrate 3-phase sync, route WebSocket messages; call only `chatKeyManager.withKey()` and encryptors, never raw crypto
6. `WebSocketTransport` — raw connection lifecycle, auth, reconnection, message dispatch; no encryption logic

### Critical Pitfalls

1. **Key generation races (Pitfall 1)** — a `getOrGenerate` fallback on async IDB miss creates a second key (K2) that permanently corrupts messages encrypted with the original (K1). Prevention: never combine get and generate in one function; `createKeyForNewChat()` is the only key generator and must assert the chat has no prior messages.

2. **Backwards compatibility break (Pitfall 5)** — changing ciphertext format, IV derivation, or `encrypted_chat_key` wrapping format silently makes all existing chats unreadable. Prevention: document exact current binary format before any changes; implement format-version sniffing with legacy fallback; run a test fixture of 10+ real encrypted records after every code change.

3. **Cross-device key delivery failure (Pitfall 2)** — WebSocket drops between initial sync and first content message mean Device B never receives the chat key; all subsequent messages are undecryptable. Prevention: every encrypted payload must include `encrypted_chat_key` as a self-contained bootstrap; on reconnect, client re-requests keys for any chats still in `loading`/`failed` state.

4. **Multi-tab key invalidation during auth events (Pitfall 3)** — `BroadcastChannel` `clearAll` from Tab A can wipe Tab B's in-memory keys mid-encryption, triggering the key generation race. Prevention: `clearAll` must check `criticalOpCount` cross-tab (deferred-clear logic already exists in `handleCrossTabMessage`); verify all encrypt-then-send paths acquire the critical-op lock.

5. **Master key architectural gap** — a new device login generates a fresh master key, but server-stored `encrypted_chat_key` values were wrapped with the old master key, which should cause cross-device decryption failures. The current system apparently compensates elsewhere; this root cause must be fully understood and resolved. Prevention: clarify master key transfer/sharing mechanism during the audit phase; the healthy architecture requires either a single shared master key (transferred via QR/backup) or per-device key wrapping with N wrapped copies on the server.

---

## Implications for Roadmap

Based on research, the build-order dependency graph from ARCHITECTURE.md directly maps to phase structure. Do not skip steps — lower layers must be solid before the sync layer is rewired, or debugging becomes exponentially harder.

### Phase 1: Audit and Fixture Creation
**Rationale:** Every subsequent phase is only safe if you know exactly what exists. The rebuild has destroyed data before (Pitfall 5); auditing first prevents that from happening again. This is the ARCHITECTURE.md "audit first" principle.
**Delivers:** Complete inventory of all encrypt/decrypt code paths; exact binary format documentation for every encrypted field; 10+ real encrypted message test fixtures for regression testing; identification of all legacy bypass paths around `ChatKeyManager`; resolution of the master key architectural gap.
**Addresses:** Backwards compatibility (table stakes), master key lifecycle (Pitfall 9), encrypted fields registry (Pitfall 13)
**Avoids:** Pitfall 5 (backwards compatibility break), Pitfall 1 (key generation races introduced by incomplete audit)

### Phase 2: Architecture Design and Protocol Specification
**Rationale:** Before touching production code, the key delivery guarantees and cross-tab coordination protocol must be explicitly designed. PITFALLS.md shows that every major bug class (5 of 8) was a key management race — the design must address these before implementation.
**Delivers:** Formal state machine diagram for `ChatKeyManager`; key delivery guarantee protocol (every payload includes `encrypted_chat_key`); cross-tab coordination design using `Web Locks` + `BroadcastChannel`; master key transfer/sharing mechanism; WebSocket version handshake protocol (Pitfall 8); per-chat field encryption registry.
**Uses:** Web Locks API, BroadcastChannel API (from STACK.md)
**Implements:** ChatKeyManager, MasterKeyService, SyncEngine boundary definitions (from ARCHITECTURE.md)
**Avoids:** Pitfall 2 (key delivery), Pitfall 3 (multi-tab invalidation), Pitfall 6 (message ordering), Pitfall 8 (stale service worker)

### Phase 3: Foundation Layer Extraction (Layer 0-1)
**Rationale:** Low-risk refactoring with no behavior changes. Extracting pure functions first de-risks the sync handler rewire in Phase 4. This is the ARCHITECTURE.md Layer 0 build-order requirement.
**Delivers:** `CryptoOperations.ts` (pure functions extracted from `cryptoService.ts`); `MessageEncryptor.ts` and `MetadataEncryptor.ts` (stateless wrappers); `MasterKeyService.ts` (extracted from `cryptoKeyStorage.ts` + `cryptoService.ts`). All test fixtures from Phase 1 must pass after each extraction.
**Uses:** Web Crypto API — no new dependencies
**Implements:** Layer 0 and Layer 1 from ARCHITECTURE.md build order
**Avoids:** Pitfall 5 (backwards compat — test fixtures run after every extraction)

### Phase 4: ChatKeyManager Hardening and Cross-Tab Coordination (Layer 2)
**Rationale:** `ChatKeyManager` is already well-structured; this phase closes the remaining gaps — critical-op lock coverage across all encrypt paths, `keyLoaded` broadcast warming the cache (not just lazy-load), and Web Locks mutex for key generation. This must be complete before the sync handler rewire because the handlers depend on ChatKeyManager's public API.
**Delivers:** Web Locks mutex on `createKeyForNewChat` and all key write operations; `keyLoaded` broadcast warms cache in other tabs immediately; critical-op lock verified across all encrypt-then-send paths; `clearAll` deferred-clear verified cross-tab; `graceful degradation check` for `crypto.subtle` absence at init.
**Uses:** Web Locks API, BroadcastChannel API (from STACK.md)
**Implements:** Layer 2 (ChatKeyManager) from ARCHITECTURE.md
**Avoids:** Pitfall 1 (key generation races), Pitfall 3 (multi-tab invalidation), Pitfall 4 (IDB transaction timing)

### Phase 5: Sync Handler Rewire (Layer 3)
**Rationale:** This is the highest-risk phase — it touches the live bug paths in `chatSyncServiceSenders.ts` and the phased sync handlers. It must come after Phases 3-4 so the encryptors and a hardened `ChatKeyManager` are in place. Each handler is rewired independently (one file per commit) to minimize rollback scope.
**Delivers:** All sync handlers use `chatKeyManager.withKey()` + `MessageEncryptor`/`MetadataEncryptor`; zero direct `cryptoService.ts` calls from sync layer; every encrypted payload includes `encrypted_chat_key` for key bootstrapping; per-chat IDB write locking (Pitfall 7); reconnect triggers key re-request for `loading`/`failed` chats.
**Implements:** Layer 3 (sync handlers) from ARCHITECTURE.md
**Avoids:** Pitfall 1 (key races), Pitfall 2 (key delivery), Pitfall 6 (message ordering), Pitfall 7 (phased sync race), Pitfall 10 (embed key derivation), Pitfall 11 (console logging)

### Phase 6: Integration Testing and Observability
**Rationale:** E2E tests for multi-tab and multi-device scenarios are the only way to verify the race conditions are actually eliminated. Performance regression testing (Pitfall 12) must run against realistic data volumes.
**Delivers:** Playwright multi-tab tests (open two tabs, trigger auth re-verification in one while the other encrypts); multi-device simulation tests (create chat on Device A, decrypt on Device B); performance test with 100+ chats, 1000+ messages; decryption failure monitoring; `console.debug` audit for plaintext log leakage.
**Uses:** Playwright 1.49, Vitest + `@vitest/coverage-v8` (from STACK.md)
**Avoids:** Pitfall 11 (console logging), Pitfall 12 (performance regression)

### Phase Ordering Rationale

- **Audit before any code changes** is non-negotiable: the rebuild has caused regressions before; auditing first documents the safety constraints.
- **Foundation layer before sync layer** because `MessageEncryptor`/`MetadataEncryptor` must exist before sync handlers are rewired to use them (ARCHITECTURE.md Layer 0 → Layer 3 dependency).
- **ChatKeyManager hardening before sync rewire** because the sync handlers call `chatKeyManager.withKey()` — the ChatKeyManager API must be stable and correct first.
- **One module boundary per commit** during Phase 5 to keep rollback scope small — this is the PITFALLS.md Phase 3 warning about big-bang refactors.
- **Feature flag for new sync paths** during Phase 5/6 deployment so the old paths can be re-enabled without a code deploy if key corruption is detected.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 2 (Architecture Design):** The master key transfer/sharing mechanism is architecturally unresolved. Needs investigation into how the existing system actually works across devices and design of a proper solution (QR-code key transfer vs. per-device key wrapping). This is the single biggest unknown.
- **Phase 5 (Sync Handler Rewire):** `chatSyncServiceSenders.ts` is 2100+ lines and contains the historical bug paths. Deeper file-level analysis during planning will be needed to map every encrypt/decrypt call site before touching it.

Phases with standard patterns (research-phase not needed):
- **Phase 3 (Foundation Extraction):** Pure function extraction is a well-established refactoring pattern with no architectural uncertainty.
- **Phase 4 (ChatKeyManager Hardening):** Web Locks and BroadcastChannel are well-documented browser APIs; the patterns are established and the existing `ChatKeyManager` structure is already correct.
- **Phase 6 (Testing):** Playwright multi-tab testing via `browser.newContext()` is documented; Vitest coverage is already configured.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All recommendations are browser built-in APIs at Baseline Widely Available status; no new npm dependencies; verified against MDN 2026-03-26 |
| Features | HIGH | Based on direct codebase analysis of working and broken code paths; feature categorization grounded in the actual bug reports, not theoretical; WebSearch unavailable but not needed for this domain |
| Architecture | HIGH | Based on 1047-line `ChatKeyManager.ts` and full sync handler analysis; component boundaries and data flows verified against actual file structure; one gap identified (master key cross-device) |
| Pitfalls | HIGH | Every pitfall is grounded in an actual commit history regression — 8 specific commits mapped to pitfall categories; no theoretical risks, all observed failures |

**Overall confidence:** HIGH

### Gaps to Address

- **Master key cross-device mechanism:** The current system appears to work despite generating a fresh master key on new devices, which should break `encrypted_chat_key` unwrapping. The compensating mechanism is not fully understood. This must be traced and documented in Phase 1 before any code changes. Architecture.md flags this explicitly as "likely root cause of cross-device decryption failures."
- **`chatSyncServiceSenders.ts` full call-site map:** This file contains the primary key generation race (lines 1935–2107 per FEATURES.md). A complete map of all crypto call sites needs to be built during Phase 1/2 planning before Phase 5 implementation.
- **Encrypted fields completeness:** `chatCrudOperations.ts` lines 182 and 271 are documented in CONCERNS.md as fields not yet encrypted. The Phase 1 audit must produce a definitive list of intentionally encrypted vs. intentionally unencrypted fields so future fields cannot be silently omitted.
- **Service worker cache invalidation (Pitfall 8):** Commit `1df0863d0` added `SKIP_WAITING` but this has not been verified as still working. Must be confirmed before deploying Phase 5 encryption format changes.

---

## Sources

### Primary (HIGH confidence)
- MDN Web Crypto API — https://developer.mozilla.org/en-US/docs/Web/API/Web_Crypto_API (verified 2026-03-26)
- MDN Web Locks API — https://developer.mozilla.org/en-US/docs/Web/API/Web_Locks_API (verified 2026-03-26, Baseline March 2022)
- MDN BroadcastChannel API — https://developer.mozilla.org/en-US/docs/Web/API/Broadcast_Channel_API (verified 2026-03-26, Baseline March 2022)
- Codebase analysis: `ChatKeyManager.ts` (1047 lines), `cryptoService.ts`, `cryptoKeyStorage.ts`, `chatSyncService*.ts`, `connection_manager.py`, `encrypted_chat_metadata_handler.py`
- `.planning/PROJECT.md`, `.planning/codebase/ARCHITECTURE.md`, `.planning/codebase/CONCERNS.md`

### Secondary (HIGH confidence — commit history)
- Git commit history (15+ encryption-related commits from March 2026): `3d8148bc4`, `33e87e0be`, `debbf2772`, `e418f49e6`, `38e64d359`, `45252837b`, `87c1757f3`, `718450001`
- Bug reports referenced in `.planning/PROJECT.md`: issues `f305f5cf`, `a4ca102f`, `7d2d2efc`

### Tertiary (domain reference)
- Signal Protocol (double ratchet design) — consulted to confirm per-chat symmetric key is correct for single-user scenario; ratcheting is not applicable here
- OWASP PBKDF2 iteration recommendations — confirmed 100k iterations is acceptable for wrapping an already-random key (not a weak password)

---

*Research completed: 2026-03-26*
*Ready for roadmap: yes*
