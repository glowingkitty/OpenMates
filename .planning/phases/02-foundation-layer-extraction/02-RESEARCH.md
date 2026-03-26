# Phase 2: Foundation Layer Extraction - Research

**Researched:** 2026-03-26
**Domain:** TypeScript module extraction / refactoring (stateless crypto modules from monolithic cryptoService.ts)
**Confidence:** HIGH

## Summary

Phase 2 extracts stateless encryption modules (MessageEncryptor, MetadataEncryptor) from the 1928-line `cryptoService.ts` monolith. The extraction is a pure structural refactor with zero behavior changes. The existing 26 regression tests (14 in regression-fixtures.test.ts, 12 in formats.test.ts) serve as the safety net -- they must pass after every extraction step.

The critical finding from this research is that **30+ dynamic imports** of `"./cryptoService"` exist across sync handlers, export services, and debug utilities. These use `await import("./cryptoService")` and destructure specific functions. This means the safest migration strategy is **extract-and-redirect**: move implementation to new modules but keep `cryptoService.ts` as a thin re-export barrel. This avoids touching 30+ dynamic import sites across 10+ files, which would be high-risk with no functional benefit (Phase 4 will rewire callers to import from encryptor modules directly).

**Primary recommendation:** Extract MessageEncryptor.ts and MetadataEncryptor.ts as new files with the actual implementation, then convert the corresponding functions in cryptoService.ts to re-exports. ChatKeyManager.ts is preserved as-is. Each new module stays well under 500 lines.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
No explicit locked decisions -- all extraction decisions are delegated to Claude's discretion.

### Claude's Discretion
All extraction decisions are delegated to Claude -- module boundaries, file organization, migration strategy, and function groupings. Use Phase 1 audit findings and research recommendations as the primary guide. The constraint is: no behavior changes, all 26 regression tests pass, each new module under 500 lines.

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ARCH-01 | Extract `MessageEncryptor` as a stateless module -- takes key + plaintext, returns ciphertext (and reverse) | Function grouping analysis identifies exactly which functions belong: `encryptWithChatKey`, `decryptWithChatKey`, `encryptArrayWithChatKey`, `decryptArrayWithChatKey`, plus the CryptoKey cache and fingerprint infrastructure they depend on |
| ARCH-02 | Extract `MetadataEncryptor` as a stateless module -- handles title, embed metadata, and other non-message encrypted fields | Master-key encrypt/decrypt functions (`encryptWithMasterKey`, `decryptWithMasterKey`, `encryptWithMasterKeyDirect`) plus embed key operations form a coherent group. Metadata fields documented in encryption-formats.md Formats C and D |
| ARCH-04 | Each encryption-related module is under 500 lines with a single clear responsibility | Line count analysis shows MessageEncryptor will be ~180 lines, MetadataEncryptor ~250 lines, remaining cryptoService.ts ~200 lines of re-exports plus ~800 lines of non-extractable functions (master key lifecycle, email, PBKDF2, recovery, passkey PRF) |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **KISS:** Small, focused, well-named functions. No over-engineering.
- **Clean Code:** Remove unused functions, variables, imports, dead code.
- **No Silent Failures:** Never hide errors with fallbacks. All errors must be visible and logged.
- **File headers:** Every new `.py`, `.ts`, `.svelte` file needs a header comment (5-10 lines).
- **DRY:** Search before writing. Shared logic goes to established shared locations.
- **Two-Commit Rule:** When moving functions between modules, ALL call sites must be updated in the same commit.
- **Never run pnpm build** -- it crashes the server.
- **Sessions lifecycle:** Must use `sessions.py start/deploy` for all changes.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| TypeScript | Project version | Type safety for all modules | Already in use, enforces non-null key parameters |
| Vitest | Project version | Unit test runner | Already configured at `frontend/packages/ui/vitest.config.ts` with jsdom environment |
| Web Crypto API | Browser native | AES-GCM encrypt/decrypt | Already used throughout cryptoService.ts, no external crypto libs needed |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `node:crypto` (webcrypto) | Node built-in | Test environment crypto | Already used in test files to restore real Web Crypto in jsdom |

No new dependencies are needed for this phase. This is a pure extraction/refactoring of existing code.

## Architecture Patterns

### Recommended Project Structure (After Extraction)

```
frontend/packages/ui/src/services/
  encryption/
    ChatKeyManager.ts          # PRESERVED AS-IS (1046 lines, state machine)
    MessageEncryptor.ts        # NEW: chat-key encrypt/decrypt + CryptoKey cache (~180 lines)
    MetadataEncryptor.ts       # NEW: master-key + embed-key encrypt/decrypt (~250 lines)
    __tests__/
      ChatKeyManager.test.ts   # Existing
      formats.test.ts          # Existing (imports from ../../cryptoService -- keep working via re-exports)
      regression-fixtures.test.ts  # Existing (same)
      deriveEmbedKey.test.ts   # Existing
      shareEncryption.test.ts  # Existing
  cryptoService.ts             # BECOMES re-export barrel + non-extractable functions (~900 lines)
  cryptoKeyStorage.ts          # UNCHANGED (392 lines)
```

### Pattern 1: Extract-and-Redirect (Re-export Barrel)

**What:** Move implementation to new modules. Keep `cryptoService.ts` as a re-export barrel for the extracted functions. Non-extractable functions remain in cryptoService.ts directly.

**When:** Always use this for Phase 2. The 30+ dynamic import sites (`await import("./cryptoService")`) must continue to work without modification.

**Why:** Dynamic imports like `const { encryptWithChatKey } = await import("./cryptoService")` resolve at runtime. Changing the import path would require updating 30+ call sites across 10+ files. The re-export approach preserves all existing import paths while achieving clean module separation internally.

**Example:**
```typescript
// cryptoService.ts (after extraction) -- re-export barrel section
export { encryptWithChatKey, decryptWithChatKey, encryptArrayWithChatKey, decryptArrayWithChatKey } from "./encryption/MessageEncryptor";
export { encryptWithMasterKey, decryptWithMasterKey, encryptWithMasterKeyDirect } from "./encryption/MetadataEncryptor";

// ... remaining non-extractable functions (master key lifecycle, email, PBKDF2, passkey) stay here
```

### Pattern 2: Stateless Pure Functions (Key-as-Parameter)

**What:** Every encrypt/decrypt function receives the key as an explicit parameter. No function looks up keys internally (except master key convenience wrappers that call `getKeyFromStorage()` internally).

**When:** All functions in MessageEncryptor. MetadataEncryptor's `encryptWithMasterKey()` has an internal `getKeyFromStorage()` call -- this is acceptable because it is a convenience wrapper, and the `encryptWithMasterKeyDirect()` variant takes the key as a parameter.

**Example:**
```typescript
// MessageEncryptor.ts -- pure stateless functions
export async function encryptWithChatKey(
  data: string,
  chatKey: Uint8Array,
): Promise<string> { /* ... */ }

export async function decryptWithChatKey(
  encryptedDataWithIV: string,
  chatKey: Uint8Array,
  context?: { chatId?: string; fieldName?: string },
): Promise<string | null> { /* ... */ }
```

### Pattern 3: Shared Infrastructure Stays in Place

**What:** Helper functions used by multiple extractees (`uint8ArrayToBase64`, `base64ToUint8Array`, `generateSalt`, AES constants) remain in `cryptoService.ts` and are imported by the new modules.

**When:** Any function used by both MessageEncryptor AND MetadataEncryptor, or by other non-encryption code paths.

**Why:** Moving shared helpers to a third file adds complexity without value. cryptoService.ts naturally becomes the "crypto primitives + helpers" module.

### Anti-Patterns to Avoid

- **Moving too many functions at once:** Extract MessageEncryptor first, run tests, then extract MetadataEncryptor. Never move both in a single commit.
- **Breaking the lazy import in decryptWithChatKey:** The `decryptWithChatKey` error handler has a lazy `await import("./encryption/ChatKeyManager")` for provenance logging (line 1199). After extraction, this import path must still resolve correctly from the new `encryption/MessageEncryptor.ts` location (it will be `./ChatKeyManager` -- a simpler path).
- **Extracting ChatKeyManager's imports from cryptoService:** ChatKeyManager imports `_generateChatKeyInternal`, `encryptChatKeyWithMasterKey`, `decryptChatKeyWithMasterKey`, `clearCryptoKeyCache`. These must remain importable from the same relative path or be updated in ChatKeyManager if moved.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Module bundling/barrel exports | Custom index.ts aggregator | Direct re-exports in cryptoService.ts | Simpler, no new files, preserves 30+ dynamic import paths |
| Test infrastructure | New test framework | Existing vitest with jsdom + webcrypto polyfill pattern | Tests already work; just need to verify they pass after extraction |
| Function signature changes | "Improved" APIs | Exact same signatures as current code | Zero behavior change is the constraint; signature changes would require updating 135+ call sites |

**Key insight:** This phase is purely mechanical code movement. Every function signature, every error message, every log statement must be identical in the extracted module. The only changes are `import` paths and file locations.

## Common Pitfalls

### Pitfall 1: Dynamic Import Breakage
**What goes wrong:** Changing `cryptoService.ts` exports breaks the 30+ `await import("./cryptoService")` call sites at runtime, causing encryption failures that are only visible when that code path executes (not at build time).
**Why it happens:** Dynamic imports are not checked by TypeScript at compile time. A missing re-export silently becomes `undefined` at runtime.
**How to avoid:** After extraction, verify every function previously exported from cryptoService.ts is still accessible via `import("./cryptoService")`. The regression tests cover the core functions, but also manually verify the re-export list against the original export list.
**Warning signs:** Runtime `TypeError: X is not a function` errors in sync handlers or debug tools.

### Pitfall 2: Circular Dependency Between New Modules
**What goes wrong:** MessageEncryptor imports from MetadataEncryptor or vice versa, creating a circular dependency that causes `undefined` at import time.
**Why it happens:** Both modules need shared helpers (base64, constants). If one imports from the other instead of from the shared source, cycles form.
**How to avoid:** Shared helpers stay in cryptoService.ts. MessageEncryptor and MetadataEncryptor import from `../cryptoService` (up one level) for shared infrastructure. They never import from each other.
**Warning signs:** `ReferenceError: Cannot access 'X' before initialization` at module load time.

### Pitfall 3: CryptoKey Cache Scope Mismatch
**What goes wrong:** The `cryptoKeyCache` (Map of imported CryptoKey objects) is module-scoped. After extraction, if both `cryptoService.ts` and `MessageEncryptor.ts` each have their own cache instance, the same key gets imported twice (wasting memory and bypassing the cache).
**Why it happens:** Moving the cache to MessageEncryptor means `clearCryptoKeyCache()` (exported from cryptoService.ts, used by ChatKeyManager) no longer clears the right cache.
**How to avoid:** Move the cache AND `clearCryptoKeyCache` AND `getOrImportCryptoKey` together into MessageEncryptor. Update cryptoService.ts to re-export `clearCryptoKeyCache`. ChatKeyManager already imports from `../cryptoService` so the re-export path works.
**Warning signs:** `clearCryptoKeyCache()` calls have no effect after key changes.

### Pitfall 4: Lazy ChatKeyManager Import Path Change
**What goes wrong:** `decryptWithChatKey` (lines 1198-1209) has a lazy `await import("./encryption/ChatKeyManager")` for provenance logging. After moving `decryptWithChatKey` into `encryption/MessageEncryptor.ts`, the relative path changes to `./ChatKeyManager`.
**Why it happens:** The function is copied verbatim but the relative path context changes.
**How to avoid:** Update the lazy import path when moving the function. This is a one-line change: `"./encryption/ChatKeyManager"` becomes `"./ChatKeyManager"`.
**Warning signs:** Provenance info missing from decryption error logs (fails silently due to the try/catch around the lazy import).

### Pitfall 5: Test Import Paths
**What goes wrong:** Existing tests import from `../../cryptoService`. After extraction, the functions still exist at that path (via re-exports), but if the re-export is somehow wrong, tests fail.
**Why it happens:** Tests destructure specific named exports. If the re-export uses `export { X }` but the test expects `export function X`, TypeScript is fine but some bundler edge cases may differ.
**How to avoid:** Use `export { X } from "./encryption/MessageEncryptor"` syntax (named re-exports). Run the full test suite after every extraction step.
**Warning signs:** Test compilation errors or `undefined` function values in test files.

## Function Groupings (Extraction Plan)

### MessageEncryptor.ts (ARCH-01)

Functions to extract from cryptoService.ts:

| Function | Lines | Why MessageEncryptor |
|----------|-------|---------------------|
| `getOrImportCryptoKey` (private) | 971-989 | Internal dependency of encrypt/decrypt |
| `chatKeyFingerprint` (private) | 959-966 | Internal dependency of CryptoKey cache |
| `cryptoKeyCache` (module-level) | 953-956 | Module-scoped cache for imported CryptoKeys |
| `clearCryptoKeyCache` | 995-1003 | Public API for cache invalidation |
| `_generateChatKeyInternal` | 1015-1017 | Key generation (called only by ChatKeyManager) |
| `generateChatKey` (deprecated) | 1024-1030 | Deprecated wrapper, keep for backwards compat |
| `CIPHERTEXT_MAGIC`, `FINGERPRINT_LENGTH`, `CIPHERTEXT_HEADER_LENGTH` | 1041-1044 | Constants for OM-header format |
| `computeKeyFingerprint4Bytes` | 1053-1065 | FNV-1a fingerprint used in Format A |
| `encryptWithChatKey` | 1076-1104 | Core: chat-key encryption (Format A) |
| `decryptWithChatKey` | 1122-1220 | Core: chat-key decryption (Format A + B fallback) |
| `encryptArrayWithChatKey` | 1300-1306 | Convenience wrapper for JSON arrays |
| `decryptArrayWithChatKey` | 1314-1327 | Convenience wrapper for JSON arrays |

**Estimated size:** ~180 lines of implementation + ~30 lines header/imports = ~210 lines total.

**Dependencies:** Imports `uint8ArrayToBase64`, `base64ToUint8Array`, `AES_IV_LENGTH`, `AES_KEY_LENGTH` from `../cryptoService`.

### MetadataEncryptor.ts (ARCH-02)

Functions to extract from cryptoService.ts:

| Function | Lines | Why MetadataEncryptor |
|----------|-------|----------------------|
| `encryptWithMasterKey` | 513-523 | Master-key encryption (Format D) |
| `encryptWithMasterKeyDirect` | 531-556 | Master-key encryption with explicit key param |
| `decryptWithMasterKey` | 563-595 | Master-key decryption (Format D) |
| `encryptChatKeyWithMasterKey` | 1227-1255 | Key wrapping (Format C) |
| `decryptChatKeyWithMasterKey` | 1262-1292 | Key unwrapping (Format C) |
| `generateEmbedKey` | 1338-1340 | Embed key generation |
| `deriveEmbedKeyFromChatKey` | 1356-1382 | HKDF embed key derivation |
| `wrapEmbedKeyWithMasterKey` | 1389-1416 | Embed key wrapping (master key) |
| `unwrapEmbedKeyWithMasterKey` | 1424-1459 | Embed key unwrapping (master key) |
| `wrapEmbedKeyWithChatKey` | 1467-1494 | Embed key wrapping (chat key) |
| `unwrapEmbedKeyWithChatKey` | 1503-1542 | Embed key unwrapping (chat key) |
| `encryptWithEmbedKey` | 1550-1579 | Embed data encryption |
| `decryptWithEmbedKey` | 1588-1625 | Embed data decryption |
| `unwrapEmbedKeyWithEmbedKey` | 1892-1928 | Child embed key unwrapping |

**Estimated size:** ~280 lines of implementation + ~30 lines header/imports = ~310 lines total.

**Dependencies:** Imports `uint8ArrayToBase64`, `base64ToUint8Array`, `AES_IV_LENGTH`, `getKeyFromStorage` from `../cryptoService`.

### What Stays in cryptoService.ts

| Section | Lines | Why It Stays |
|---------|-------|-------------|
| Helper functions (base64, generateSalt) | 55-110 | Shared infrastructure used by all modules |
| Master key lifecycle (generate, save, get, clear, validate) | 134-365 | State management (IDB, session), not pure crypto |
| PBKDF2 key derivation | 368-500 | Authentication concern, not chat encryption |
| Email encryption key management | 605-940 | Separate domain (server communication) |
| Recovery key generation | 1636-1682 | Separate domain (account recovery) |
| hashKey / HKDF / passkey PRF functions | 1692-1884 | Separate domain (authentication/passkey) |
| Re-exports of extracted functions | ~30 lines | Barrel exports preserving dynamic import paths |

**Estimated remaining size:** ~800 lines of own code + ~30 lines of re-exports = ~830 lines total. This is still over 500 lines, but cryptoService.ts covers 5+ separate domains (master key lifecycle, email encryption, PBKDF2, recovery keys, passkey PRF). Further splitting is deferred to future phases since ARCH-04 targets "each encryption-related module" -- the non-encryption functions (email, PBKDF2, passkey) are not encryption modules per se.

## Code Examples

### Re-export Pattern (cryptoService.ts after extraction)

```typescript
// ============================================================================
// RE-EXPORTS: Message encryption (implementation in encryption/MessageEncryptor.ts)
// These re-exports preserve the 30+ dynamic import("./cryptoService") call sites
// across sync handlers, export services, and debug utilities.
// ============================================================================
export {
  encryptWithChatKey,
  decryptWithChatKey,
  encryptArrayWithChatKey,
  decryptArrayWithChatKey,
  computeKeyFingerprint4Bytes,
  clearCryptoKeyCache,
  _generateChatKeyInternal,
  generateChatKey,
} from "./encryption/MessageEncryptor";

// ============================================================================
// RE-EXPORTS: Metadata encryption (implementation in encryption/MetadataEncryptor.ts)
// ============================================================================
export {
  encryptWithMasterKey,
  decryptWithMasterKey,
  encryptWithMasterKeyDirect,
  encryptChatKeyWithMasterKey,
  decryptChatKeyWithMasterKey,
  generateEmbedKey,
  deriveEmbedKeyFromChatKey,
  wrapEmbedKeyWithMasterKey,
  unwrapEmbedKeyWithMasterKey,
  wrapEmbedKeyWithChatKey,
  unwrapEmbedKeyWithChatKey,
  encryptWithEmbedKey,
  decryptWithEmbedKey,
  unwrapEmbedKeyWithEmbedKey,
} from "./encryption/MetadataEncryptor";
```

### MessageEncryptor.ts Header

```typescript
/**
 * MessageEncryptor - Stateless chat-key encryption/decryption
 *
 * Pure functions for encrypting and decrypting chat message content using
 * per-chat AES-256-GCM keys. No state, no side effects, no IDB access.
 * Key is always received as an explicit parameter (key-as-parameter pattern).
 *
 * Handles both Format A (OM-header with fingerprint) and Format B (legacy).
 * See docs/architecture/core/encryption-formats.md for byte-level details.
 *
 * Extracted from cryptoService.ts as part of ARCH-01.
 */

import {
  uint8ArrayToBase64,
  base64ToUint8Array,
} from "../cryptoService";

// AES-GCM constants
const AES_KEY_LENGTH = 256;
const AES_IV_LENGTH = 12;
```

### MetadataEncryptor.ts Header

```typescript
/**
 * MetadataEncryptor - Stateless master-key and embed-key encryption
 *
 * Handles encryption of non-message fields: chat titles, drafts, embed data,
 * chat key wrapping/unwrapping, and embed key management. Uses master CryptoKey
 * from IndexedDB for Format C (wrapped chat keys) and Format D (arbitrary data).
 *
 * Embed key operations (derive, wrap, unwrap, encrypt, decrypt) are included
 * because they form a coherent group with master-key operations -- both deal
 * with non-message encryption using keys other than per-chat keys.
 *
 * Extracted from cryptoService.ts as part of ARCH-02.
 */

import {
  uint8ArrayToBase64,
  base64ToUint8Array,
  getKeyFromStorage,
} from "../cryptoService";

const AES_IV_LENGTH = 12;
```

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | vitest (project version, jsdom environment) |
| Config file | `frontend/packages/ui/vitest.config.ts` |
| Quick run command | `cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/` |
| Full suite command | `cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ARCH-01 | MessageEncryptor encrypt/decrypt roundtrip, Format A + B compat | unit | `cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/regression-fixtures.test.ts -x` | Yes |
| ARCH-01 | Byte layout matches documented format | unit | `cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/formats.test.ts -x` | Yes |
| ARCH-02 | Master-key encrypt/decrypt, key wrapping, embed operations | unit | `cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/regression-fixtures.test.ts -x` | Yes (covers master key wrapping) |
| ARCH-02 | Embed key derivation determinism | unit | `cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/deriveEmbedKey.test.ts -x` | Yes |
| ARCH-04 | Module line counts under 500 | manual | `wc -l frontend/packages/ui/src/services/encryption/MessageEncryptor.ts frontend/packages/ui/src/services/encryption/MetadataEncryptor.ts` | N/A |

### Sampling Rate
- **Per task commit:** `cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/`
- **Per wave merge:** Same (all 26 tests in the encryption test directory)
- **Phase gate:** Full suite green before verification

### Wave 0 Gaps
None -- existing test infrastructure covers all phase requirements. The 26 existing tests (14 regression + 12 format) validate that extracted code produces identical results. No new test files needed for Phase 2 (Phase 5 will add integration tests).

## Open Questions

1. **cryptoService.ts remaining size (830 lines)**
   - What we know: After extraction, cryptoService.ts retains ~800 lines of non-encryption code (master key lifecycle, email, PBKDF2, recovery, passkey PRF) plus ~30 lines of re-exports
   - What's unclear: Whether ARCH-04 ("each encryption-related module under 500 lines") applies to the remaining cryptoService.ts, which is primarily non-encryption utility code
   - Recommendation: Accept 830 lines for now. The remaining code covers 5 unrelated domains. Further splitting would be a separate phase. The encryption-specific modules (MessageEncryptor, MetadataEncryptor, ChatKeyManager) will all be under 500 lines.

2. **ChatKeyManager imports after extraction**
   - What we know: ChatKeyManager imports `_generateChatKeyInternal`, `encryptChatKeyWithMasterKey`, `decryptChatKeyWithMasterKey`, `clearCryptoKeyCache` from `../cryptoService`
   - What's unclear: Whether ChatKeyManager should be updated to import directly from the new modules or continue using the re-export barrel
   - Recommendation: Keep ChatKeyManager importing from `../cryptoService` (via re-exports). This preserves ChatKeyManager as-is per the phase constraint. Phase 3 or 4 can update ChatKeyManager's imports to point directly to the new modules.

## Sources

### Primary (HIGH confidence)
- Codebase analysis: `cryptoService.ts` (1928 lines, all 56 exported functions cataloged)
- Codebase analysis: `encryption-code-inventory.md` (135+ call sites, 22 files)
- Codebase analysis: `encryption-formats.md` (4 ciphertext formats documented)
- Codebase analysis: 30+ dynamic import sites via `await import("./cryptoService")`
- Codebase analysis: `ChatKeyManager.ts` (1046 lines, import dependencies verified)
- Codebase analysis: `ARCHITECTURE.md` research doc (module boundary recommendations)
- Codebase analysis: `PITFALLS.md` research doc (backwards compatibility risks)

### Secondary (MEDIUM confidence)
- Line count estimates for new modules (based on function extraction, verified against source)

### Tertiary (LOW confidence)
- None -- this phase is entirely codebase-internal, no external research needed

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - no new libraries, pure extraction
- Architecture: HIGH - function groupings derived from 135+ call site inventory and format documentation
- Pitfalls: HIGH - dynamic import discovery (30+ sites) is the key risk, verified by grep

**Research date:** 2026-03-26
**Valid until:** No expiry -- this is codebase-specific structural analysis, not library version research
