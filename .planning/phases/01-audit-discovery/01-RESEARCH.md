# Phase 1: Audit & Discovery - Research

**Researched:** 2026-03-26
**Domain:** Client-side encryption code audit, binary format documentation, regression fixture creation
**Confidence:** HIGH

## Summary

Phase 1 is a documentation-and-fixtures-only phase with no code changes. The audit must produce three deliverables: (1) a complete inventory of every encrypt/decrypt/key-gen/key-sync code path across 15 files and 135+ call sites, (2) byte-level documentation of three distinct ciphertext formats (new OM-header messages, legacy messages, and master-key-wrapped chat keys), and (3) a regression test suite of 10+ real encrypted fixtures that validates the current decryption code works correctly.

The codebase is well-documented but has critical complexity. `cryptoService.ts` (1928 lines) contains all crypto primitives plus the two ciphertext formats (new with `[0x4F 0x4D][fingerprint 4B][IV 12B][ciphertext]` and legacy `[IV 12B][ciphertext]`). `ChatKeyManager.ts` (1046 lines) is the key state machine. The sync layer spreads across 5+ files with 135 total `encryptWithChatKey`/`decryptWithChatKey` call sites across 15 files. The master key lifecycle is documented in `zero-knowledge-storage.md` but the cross-device transfer mechanism has a known architectural gap that this phase must investigate and explain.

**Primary recommendation:** Structure the audit as three sequential work units: (1) failures-first root cause tracing of the 3 recent bug reports, (2) systematic code path inventory with call-site mapping, (3) format documentation and regression fixture creation.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Failures-first approach -- trace the 3 recent decryption failure bug reports (f305f5cf, a4ca102f, 7d2d2efc) backwards to root causes first, then map the full encryption architecture. This gets to actionable findings faster.
- **D-02:** After root cause identification, systematically map all remaining encrypt/decrypt/key-gen/key-sync code paths across the 57 files that touch encryption.
- **D-03:** All encryption architecture documentation lives in `docs/architecture/` as permanent project docs -- not in `.planning/`. These are long-term reference documents.
- **D-04:** Mermaid diagrams for all visual representations -- encrypt->sync->decrypt flow, key lifecycle, device sync, master key derivation. No annotated code walkthroughs; diagrams are the primary format for understanding.
- **D-05:** Create regression test fixtures from real encrypted data to validate all format generations. Fixture strategy to be determined by researcher.

### Claude's Discretion
- Fixture creation strategy (IndexedDB export vs debug.py vs mocks)
- Exact file organization within `docs/architecture/` for encryption docs
- Level of detail in code path inventory (file:line granularity where useful, higher-level where appropriate)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| AUDT-01 | Complete inventory of every code path that encrypts, decrypts, generates keys, or syncs keys -- with file paths and line numbers | 15 files with 135+ encrypt/decrypt call sites identified; grep patterns for all 4 operation types documented |
| AUDT-02 | Document the exact binary/ciphertext format for every encrypted field (messages, metadata, embeds, titles) | Three distinct formats identified: OM-header chat key format, legacy IV-only format, master-key-wrapped chat key format; byte layouts documented |
| AUDT-03 | Create regression test fixtures from real encrypted data covering all format generations | Vitest infrastructure exists with jsdom; ChatKeyManager tests exist as model; fixture strategy researched |
| AUDT-04 | Document the full master key derivation path (from user credential to PBKDF2 to wrapping key to chat key) | Full derivation chain documented from zero-knowledge-storage.md + cryptoService.ts analysis |
| AUDT-05 | Document the master key distribution mechanism across devices | Architectural gap confirmed: new device generates fresh master key, but wrapped chat keys use old master key; mechanism must be traced |
| AUDT-06 | Identify every sync handler that calls cryptoService.ts directly instead of going through ChatKeyManager | 10 non-ChatKeyManager files import from cryptoService identified; sync handler bypass paths mapped |
</phase_requirements>

## Standard Stack

This phase produces documentation and test fixtures only. No new libraries are needed.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Vitest | (existing) | Unit test runner for regression fixtures | Already configured in `frontend/packages/ui/vitest.config.ts` with jsdom |
| Web Crypto API | Browser native | Understanding target -- the API being audited | All encryption uses `crypto.subtle` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `idb` | (existing) | IndexedDB access for fixture extraction | If fixtures are extracted from live IndexedDB |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Real encrypted fixtures | Synthetic test data | Synthetic data misses format edge cases from historical code changes; real data is strongly preferred |
| Vitest for regression tests | Playwright | Vitest is faster for pure crypto unit tests; Playwright is overkill for format validation |

## Architecture Patterns

### Documentation Structure (in `docs/architecture/`)

The existing `docs/architecture/core/` already contains two relevant docs:
- `chat-encryption-implementation.md` -- field-level encryption details (exists, needs expansion)
- `zero-knowledge-storage.md` -- master key lifecycle and key hierarchy (exists, accurate)

**Recommended organization for new audit docs:**

```
docs/architecture/core/
  chat-encryption-implementation.md  # EXISTS -- expand with byte-level format diagrams
  zero-knowledge-storage.md          # EXISTS -- expand with cross-device gap analysis
  encryption-code-inventory.md       # NEW -- complete code path inventory (AUDT-01, AUDT-06)
  encryption-formats.md              # NEW -- byte-level ciphertext format documentation (AUDT-02)
  master-key-lifecycle.md            # NEW -- full derivation + cross-device analysis (AUDT-04, AUDT-05)
```

### Pattern 1: Failures-First Root Cause Tracing (D-01)

**What:** Trace each of the 3 recent bug reports backwards through the code to identify the root cause pattern, then categorize against the 13 known pitfalls from PITFALLS.md.

**When to use:** First task in the phase. Gets to actionable findings fastest.

**Approach:**
1. For each bug report (f305f5cf, a4ca102f, 7d2d2efc), use `debug.py issue <id> --timeline` if Docker is available, or trace through git log and related fix commits
2. Map each failure to the commit that fixed it (see canonical refs: `3d8148bc4`, `33e87e0be`, `debbf2772`, `e418f49e6`)
3. Document the root cause pattern and which pitfall category it belongs to
4. Identify if the fix was complete or if the same race condition can still trigger from a different code path

### Pattern 2: Systematic Code Path Inventory (D-02)

**What:** Map every function in the codebase that directly calls encryption, decryption, key generation, or key sync operations.

**When to use:** After root cause tracing is complete.

**Approach:** Search for these function signatures across the codebase:

| Operation | Functions to grep | Expected locations |
|-----------|-------------------|--------------------|
| Encrypt (chat key) | `encryptWithChatKey`, `encryptArrayWithChatKey` | 15 files, 135+ call sites |
| Decrypt (chat key) | `decryptWithChatKey`, `decryptArrayWithChatKey` | Same 15 files |
| Encrypt (master key) | `encryptWithMasterKey`, `encryptWithMasterKeyDirect` | drafts, search, metadata, suggestions |
| Decrypt (master key) | `decryptWithMasterKey` | drafts, search, metadata, app settings |
| Key generation | `_generateChatKeyInternal`, `generateChatKey`, `createKeyForNewChat` | ChatKeyManager, cryptoService |
| Key wrapping | `encryptChatKeyWithMasterKey`, `decryptChatKeyWithMasterKey` | cryptoService, ChatKeyManager, chatKeyManagement |
| Key sync | `receiveKeyFromServer`, `bulkInject`, `injectKey` | ChatKeyManager callers in sync handlers |
| Embed key | `deriveEmbedKeyFromChatKey` | cryptoService, embed-related services |
| Master key | `generateExtractableMasterKey`, `saveKeyToSession`, `getKeyFromStorage` | cryptoService, cryptoKeyStorage, auth flows |

For each call site: record file path, line number, whether it goes through ChatKeyManager or bypasses it, and what sync/UI context triggers it.

### Pattern 3: Ciphertext Format Documentation (AUDT-02)

**What:** Document the exact byte layout of every encrypted field format with diagrams.

**Three distinct formats exist in the codebase:**

**Format A: New OM-header (chat key encrypted fields)**
```
Base64 decode ->
[0x4F 0x4D] [fingerprint 4B] [IV 12B] [AES-GCM ciphertext + 16B auth tag]
  "OM" magic   FNV-1a hash     random    encrypted data
  (2 bytes)    of chat key     nonce
```
Used for: `encrypted_content`, `encrypted_sender_name`, `encrypted_category`, `encrypted_active_focus_id`, `encrypted_chat_summary`, `encrypted_chat_tags`, `encrypted_follow_up_request_suggestions`

**Format B: Legacy (no header)**
```
Base64 decode ->
[IV 12B] [AES-GCM ciphertext + 16B auth tag]
  random    encrypted data
  nonce
```
Used for: older messages encrypted before the fingerprint header was added. `decryptWithChatKey` handles both formats via magic byte detection.

**Format C: Wrapped chat key (master key encrypted)**
```
Base64 decode ->
[IV 12B] [AES-GCM ciphertext + 16B auth tag]
  random    encrypted 32-byte chat key
  nonce
```
Used for: `encrypted_chat_key` field -- chat keys wrapped with master key. No OM header. Stored server-side in Directus and synced to all devices.

**Format D: Master key encrypted fields**
Same as Format C structure but encrypting arbitrary data (titles, drafts) rather than keys. Uses `encryptWithMasterKey()` / `decryptWithMasterKey()`.

### Anti-Patterns to Avoid

- **Incomplete inventory:** Missing even one bypass path means the rebuild in Phase 2-4 leaves a legacy race condition alive. The audit must be exhaustive.
- **Documenting only happy paths:** Every code path must document what happens on failure (key not found, decryption fails, WebSocket drops).
- **Assuming existing docs are current:** `chat-encryption-implementation.md` was last verified 2026-03-24 but may not reflect the 20+ encryption commits from March 2026. Verify against actual code.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Ciphertext format documentation | Free-form prose descriptions | Byte-level diagrams with offset tables | Ambiguous descriptions lead to wrong implementations in Phase 2 |
| Code path inventory | Manual file reading | Systematic grep + cross-reference | Manual reading misses call sites; grep is exhaustive |
| Regression fixtures | Synthetic test data only | Real encrypted data from the running system | Synthetic data misses format edge cases from historical changes |

## Common Pitfalls

### Pitfall 1: Missing the Master Key Cross-Device Gap
**What goes wrong:** The audit documents the happy path (single device, master key in IndexedDB) but fails to trace what actually happens when a second device logs in. The architectural gap (new device gets fresh master key, but server has chat keys wrapped with old master key) is the single biggest unknown.
**Why it happens:** The code path for new device login spans auth flows, cryptoKeyStorage, and sync handlers -- it crosses module boundaries.
**How to avoid:** Explicitly trace: (1) what happens at `generateExtractableMasterKey()` on new device login, (2) how the wrapped master key is stored/retrieved from the server, (3) what mechanism allows the second device to unwrap `encrypted_chat_key` values created by the first device. The answer may be in the passkey PRF flow or recovery key flow.
**Warning signs:** If the audit concludes "master key is generated per device" without explaining how cross-device chat key unwrapping works, the audit is incomplete.

### Pitfall 2: Conflating Chat Key Fields and Master Key Fields
**What goes wrong:** The inventory lists all encrypted fields but does not distinguish which use chat keys vs. master keys. This matters because master-key-encrypted fields (titles, drafts) have a completely different code path and failure mode than chat-key-encrypted fields (message content).
**Why it happens:** The field names all start with `encrypted_` and use similar AES-GCM under the hood.
**How to avoid:** Explicitly categorize every field. The existing `chat-encryption-implementation.md` already has this table -- verify it is complete and correct against code.

### Pitfall 3: Fixture Data That Only Covers One Format Generation
**What goes wrong:** Regression fixtures are created using the current code, which writes Format A (OM-header). Legacy Format B messages are not represented. The fixtures pass today but do not validate backwards compatibility.
**How to avoid:** Fixtures must include: (1) Format A (new OM-header) messages, (2) Format B (legacy) messages from before the fingerprint header, (3) wrapped chat keys, (4) master-key-encrypted fields. If real legacy data is unavailable, construct Format B fixtures manually (they are just `[IV][ciphertext]` without the 6-byte header).
**Warning signs:** If all fixture ciphertexts start with base64-encoded `0x4F 0x4D`, legacy format coverage is missing.

### Pitfall 4: Overlooking the 10 Non-ChatKeyManager Crypto Importers
**What goes wrong:** AUDT-06 asks for sync handlers that bypass ChatKeyManager. But 10 files import directly from `cryptoService.ts` for operations that may not need ChatKeyManager (e.g., master key encryption for drafts/search). The audit must distinguish legitimate direct imports from bypass paths.
**Files importing from cryptoService.ts (not via ChatKeyManager):**
1. `chatMetadataCache.ts` -- `decryptWithMasterKey` (legitimate: master key operation)
2. `hiddenChatService.ts` -- `getKeyFromStorage`, `getEmailSalt` (needs investigation)
3. `mentionedSettingsMemoriesCleartext.ts` -- `decryptWithMasterKey` (legitimate)
4. `chatSyncServiceHandlersAppSettings.ts` -- `decryptWithMasterKey` (legitimate, but also has 6 ChatKeyManager calls)
5. `drafts/draftWebsocket.ts` -- `decryptWithMasterKey` (legitimate)
6. `searchService.ts` -- `decryptWithMasterKey` (legitimate)
7. `accountExportService.ts` -- `decryptWithMasterKey` (legitimate)
8. `drafts/draftSave.ts` -- `encryptWithMasterKey` (legitimate)
9. `db/newChatSuggestions.ts` -- `encryptWithMasterKey`, `decryptWithMasterKey` (legitimate)
10. `onboardingChatService.ts` -- has 9 `encryptWithChatKey`/`decryptWithChatKey` calls (BYPASS - needs investigation)

**How to avoid:** For each import, determine if it is a chat-key operation (should go through ChatKeyManager) or a master-key operation (legitimately direct). Only chat-key bypasses are AUDT-06 violations.

## Code Examples

### Ciphertext Format Detection (from cryptoService.ts lines 1133-1178)
```typescript
// Source: frontend/packages/ui/src/services/cryptoService.ts:1133-1178
// This is the format detection logic that regression fixtures must validate

const combined = base64ToUint8Array(encryptedDataWithIV);

// Check for new format: magic bytes "OM" (0x4F, 0x4D)
if (
  combined.length > CIPHERTEXT_HEADER_LENGTH + AES_IV_LENGTH &&
  combined[0] === 0x4f &&
  combined[1] === 0x4d
) {
  // New format: [OM magic 2B][fingerprint 4B][IV 12B][ciphertext]
  const storedFp = combined.slice(CIPHERTEXT_MAGIC.length, CIPHERTEXT_HEADER_LENGTH);
  const actualFp = computeKeyFingerprint4Bytes(chatKey);
  // ... fingerprint validation, then extract IV and ciphertext
  iv = combined.slice(CIPHERTEXT_HEADER_LENGTH, CIPHERTEXT_HEADER_LENGTH + AES_IV_LENGTH);
  ciphertext = combined.slice(CIPHERTEXT_HEADER_LENGTH + AES_IV_LENGTH);
} else {
  // Legacy format: [IV 12B][ciphertext]
  iv = combined.slice(0, AES_IV_LENGTH);
  ciphertext = combined.slice(AES_IV_LENGTH);
}
```

### Key Fingerprint Computation (FNV-1a, from cryptoService.ts lines 1053-1065)
```typescript
// Source: frontend/packages/ui/src/services/cryptoService.ts:1053-1065
export function computeKeyFingerprint4Bytes(key: Uint8Array): Uint8Array {
  let h = 0x811c9dc5; // FNV-1a offset basis
  for (let i = 0; i < key.length; i++) {
    h ^= key[i];
    h = Math.imul(h, 0x01000193);
  }
  const fp = new Uint8Array(4);
  fp[0] = (h >>> 24) & 0xff;
  fp[1] = (h >>> 16) & 0xff;
  fp[2] = (h >>> 8) & 0xff;
  fp[3] = h & 0xff;
  return fp;
}
```

### Wrapped Chat Key Format (from cryptoService.ts lines 1227-1254)
```typescript
// Source: frontend/packages/ui/src/services/cryptoService.ts:1227-1254
// encrypted_chat_key format: Base64([IV 12B][AES-GCM(chatKey 32B)])
// No OM header -- this is AES-GCM encryption of the raw 32-byte chat key
// using the user's master CryptoKey

const iv = crypto.getRandomValues(new Uint8Array(AES_IV_LENGTH)); // 12 bytes
const encrypted = await crypto.subtle.encrypt(
  { name: "AES-GCM", iv },
  masterKey,        // CryptoKey from IndexedDB or memory
  chatKeyBuffer,    // 32-byte raw chat key
);
// Combined: [IV 12B][ciphertext (32B + 16B auth tag = 48B)] = 60 bytes total
const combined = new Uint8Array(iv.length + encrypted.byteLength);
combined.set(iv);
combined.set(new Uint8Array(encrypted), iv.length);
return uint8ArrayToBase64(combined); // ~80 chars base64
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `getOrGenerateChatKey()` anti-pattern | `ChatKeyManager.createKeyForNewChat()` as sole generator | Commit `3d8148bc4` (March 2026) | Eliminated implicit key generation races |
| No ciphertext fingerprint | OM-header with FNV-1a 4-byte fingerprint | Recent (March 2026) | Fast wrong-key detection without AES-GCM attempt |
| `generateChatKey()` direct call | Deprecated with console.warn, delegates to internal | March 2026 | Deprecation wrapper still exists at line 1024 |
| Legacy `[IV][ciphertext]` format | New `[OM][fingerprint][IV][ciphertext]` format | March 2026 | Both formats must be supported forever |

**Deprecated/outdated:**
- `generateChatKey()` export is deprecated but still exists (line 1024) -- audit should confirm no callers remain
- `getOrGenerateChatKey` pattern was removed but may exist in older code paths

## Open Questions

1. **Master key cross-device mechanism**
   - What we know: `zero-knowledge-storage.md` documents that the wrapped master key is stored on the server. Login methods (password, passkey PRF, recovery key) derive a wrapping key. The master key is wrapped with this wrapping key before upload.
   - What's unclear: When a second device logs in with the same password/passkey, does it derive the same wrapping key and download+unwrap the same master key? Or does it generate a fresh master key? The code says `generateExtractableMasterKey()` at signup, but what about subsequent logins?
   - Recommendation: Trace the login flow (not signup) to determine if `getKeyFromStorage()` attempts to download and unwrap the server-stored wrapped master key before falling back to generation. This is AUDT-05's core question.

2. **`onboardingChatService.ts` bypass pattern**
   - What we know: This file has 9 `encryptWithChatKey`/`decryptWithChatKey` calls but also 2 `chatKeyManager` calls. It appears to mix direct crypto calls with ChatKeyManager calls.
   - What's unclear: Whether the direct calls are legitimate (e.g., for a special onboarding flow) or bugs.
   - Recommendation: Include in AUDT-06 inventory with explicit determination.

3. **Bug report availability**
   - What we know: Three bug reports (f305f5cf, a4ca102f, 7d2d2efc) are referenced. Docker may or may not be running for `debug.py` access.
   - What's unclear: Whether these issues still exist in the debug system or have been auto-deleted after fixes.
   - Recommendation: Attempt `debug.py issue <id> --timeline` first. If unavailable, trace via git log and the known fix commits instead.

4. **Fixture data source**
   - What we know: Real encrypted data exists in the running app's IndexedDB and on the server.
   - What's unclear: Whether data can be extracted safely without the running Docker stack.
   - Recommendation (Claude's discretion): Use a hybrid approach -- create synthetic fixtures with known keys for format validation (covers both Format A and Format B), and attempt to capture real fixtures from IndexedDB if the dev environment is available. Synthetic fixtures are more reproducible and can explicitly test both format generations.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Vitest (existing in `frontend/packages/ui/vitest.config.ts`) |
| Config file | `frontend/packages/ui/vitest.config.ts` |
| Quick run command | `cd frontend/packages/ui && npx vitest run src/services/encryption` |
| Full suite command | `cd frontend/packages/ui && npx vitest run` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| AUDT-01 | Code path inventory is complete | manual | N/A (documentation deliverable) | N/A |
| AUDT-02 | Format documentation matches actual ciphertext | unit | `cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/formats.test.ts -x` | Wave 0 |
| AUDT-03 | Regression fixtures decrypt successfully | unit | `cd frontend/packages/ui && npx vitest run src/services/encryption/__tests__/regression-fixtures.test.ts -x` | Wave 0 |
| AUDT-04 | Master key derivation documented | manual | N/A (documentation deliverable) | N/A |
| AUDT-05 | Cross-device mechanism documented | manual | N/A (documentation deliverable) | N/A |
| AUDT-06 | Bypass paths identified | manual | N/A (documentation deliverable) | N/A |

### Sampling Rate
- **Per task commit:** `cd frontend/packages/ui && npx vitest run src/services/encryption -x`
- **Per wave merge:** `cd frontend/packages/ui && npx vitest run`
- **Phase gate:** All regression fixtures pass; documentation review complete

### Wave 0 Gaps
- [ ] `src/services/encryption/__tests__/regression-fixtures.test.ts` -- covers AUDT-03 (format A, B, C fixtures)
- [ ] `src/services/encryption/__tests__/formats.test.ts` -- covers AUDT-02 (byte layout validation)
- [ ] Fixture data files (JSON with known keys + ciphertexts for both format generations)

## Project Constraints (from CLAUDE.md)

- **Documentation location:** `docs/architecture/` for permanent project docs (aligns with D-03)
- **Mermaid diagrams:** Required for visual representations (aligns with D-04)
- **File headers:** Every new `.py`, `.ts`, `.svelte` file needs a 5-10 line header comment
- **No silent failures:** All errors must be visible and logged
- **Comments:** Explain business logic and architecture decisions, link to `docs/architecture/`
- **KISS:** Small, focused, well-named functions
- **Never run pnpm build** -- it crashes the server
- **sessions.py lifecycle:** Must use `sessions.py start` / `sessions.py deploy` for all work
- **Research before new integrations:** Check existing docs first (relevant for audit -- leverage existing `chat-encryption-implementation.md` and `zero-knowledge-storage.md`)

## Sources

### Primary (HIGH confidence)
- `frontend/packages/ui/src/services/cryptoService.ts` -- All ciphertext format constants, encrypt/decrypt functions, key wrapping (lines 1015-1280)
- `frontend/packages/ui/src/services/encryption/ChatKeyManager.ts` -- Key state machine, provenance types, queue-and-flush (lines 1-80)
- `frontend/packages/ui/src/services/cryptoKeyStorage.ts` -- Master key IndexedDB storage, memory/IDB hybrid strategy
- `docs/architecture/core/chat-encryption-implementation.md` -- Existing field-level encryption documentation
- `docs/architecture/core/zero-knowledge-storage.md` -- Master key lifecycle, key hierarchy diagram, derivation methods
- `.planning/research/ARCHITECTURE.md` -- Target architecture, data flows, component boundaries
- `.planning/research/PITFALLS.md` -- 13 domain pitfalls with commit-history evidence

### Secondary (HIGH confidence -- commit history)
- Git commit history: 20 encryption-related commits from March 2026 mapped to pitfall categories
- Bug reports: f305f5cf, a4ca102f, 7d2d2efc (referenced in CONTEXT.md canonical refs)
- Existing tests: `ChatKeyManager.test.ts`, `deriveEmbedKey.test.ts`, `shareEncryption.test.ts`

### Tertiary (MEDIUM confidence)
- Grep analysis of 135+ encrypt/decrypt call sites across 15 files (automated, verified count)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- No new libraries needed; Vitest already configured and working
- Architecture: HIGH -- Three ciphertext formats identified and verified in source code; existing docs provide solid foundation
- Pitfalls: HIGH -- All pitfalls grounded in actual code analysis and commit history; master key gap is the main unknown

**Research date:** 2026-03-26
**Valid until:** 2026-04-26 (stable -- this is an audit of existing code, not a fast-moving ecosystem)
