---
status: active
last_verified: 2026-03-24
---

# CLI Standards (TypeScript/Node.js)

Standards for modifying CLI code in `frontend/packages/openmates-cli/` — the `openmates` npm package that lets users interact with the API from a terminal.

Architecture context: [CLI Package Architecture](../../architecture/apps/cli-package.md)

---

## Project Layout

```
frontend/packages/openmates-cli/
├── src/
│   ├── cli.ts            # Entry point — argument router (no Commander/yargs)
│   ├── client.ts         # OpenMatesClient — all SDK operations + decryption
│   ├── crypto.ts         # AES-256-GCM + PBKDF2 crypto (Node.js webcrypto)
│   ├── embedRenderers.ts # Terminal rendering for all embed types
│   ├── http.ts           # Thin fetch wrapper
│   ├── storage.ts        # ~/.openmates session/cache persistence
│   └── ws.ts             # WebSocket client for chat streaming
└── tests/
    ├── crypto.test.ts    # Node test runner — roundtrip + format tests
    ├── storage.test.ts   # Node test runner — session/cache persistence
    └── cli.test.ts       # Requires compiled dist — registry + schema tests
```

---

## Rule 1 — Mirror the Web App, Don't Invent Independently (CRITICAL)

Before writing **any** crypto, sync, decryption, embed key resolution, memory CRUD, or WebSocket envelope logic, **first read the web app counterpart** and mirror it exactly in Node.js idioms.

The CLI is a Node.js mirror of the browser's zero-knowledge client. Diverging from the web app's algorithms silently breaks data compatibility.

| If you need to…                    | First read this web app file                                         |
| ---------------------------------- | -------------------------------------------------------------------- |
| Encrypt/decrypt AES-256-GCM        | `frontend/packages/ui/src/services/cryptoService.ts`                 |
| Derive a key with PBKDF2           | `cryptoService.ts` — `derivePairKey()` / `deriveMasterKey()`         |
| Decrypt chat messages              | `chatSyncService.ts` + `chatSyncServiceHandlersPhasedSync.ts`        |
| Resolve an embed's decryption key  | `frontend/packages/ui/src/stores/embedStore.ts` — `getEmbedKey()`    |
| Sync chats/embeds via WebSocket    | `chatSyncServiceHandlersPhasedSync.ts` — Phase 3 sync                |
| Read/write memories over WebSocket | `frontend/packages/ui/src/stores/appSettingsMemoriesStore/` (barrel) |
| Format a WebSocket envelope        | `frontend/packages/ui/src/services/websocketService.ts`              |

**Comment every non-trivial crypto function** with `// Mirrors <WebAppFile>:<functionName>` so the link stays visible during future reviews.

---

## Rule 2 — Crypto Parameters Are Non-Negotiable

The following constants are fixed by the server and must never be changed in the CLI without a matching server-side change. If you are unsure about any value, read `cryptoService.ts` — do NOT guess.

| Parameter         | Value                              | Source of truth    |
| ----------------- | ---------------------------------- | ------------------ |
| AES key length    | 256 bits                           | `cryptoService.ts` |
| AES mode          | GCM                                | `cryptoService.ts` |
| IV length         | 12 bytes                           | `cryptoService.ts` |
| IV wire format    | prepended to ciphertext (combined) | `cryptoService.ts` |
| PBKDF2 hash       | SHA-256                            | `cryptoService.ts` |
| PBKDF2 iterations | 100,000                            | `cryptoService.ts` |

**Never use `window.crypto`** — the CLI runs in Node.js. Use `import { webcrypto } from 'node:crypto'` and cast as needed to keep types compatible with the Web Crypto API spec.

---

## Rule 3 — MEMORY_TYPE_REGISTRY Must Stay in Sync with app.yml

`client.ts` contains a `MEMORY_TYPE_REGISTRY` (~400 lines) that mirrors the memory field schemas defined in each backend `app.yml` file. These are parsed server-side by `backend/shared/python_schemas/app_metadata_schemas.py:AppMemoryFieldDefinition`.

**When any app.yml memory schema changes:**

1. Find the app's `app.yml` in `backend/apps/<app>/config/app.yml` (look for `memories:` key).
2. Update the matching entry in `MEMORY_TYPE_REGISTRY` in `client.ts`.
3. Run `cli.test.ts` to catch structural validation failures: `node --test tests/cli.test.ts`.

If `MEMORY_TYPE_REGISTRY` diverges from `app.yml`, memory creation will fail silently or produce incorrect validation errors for users.

---

## Rule 4 — WebSocket Event Names Are a Contract

The CLI listens for and emits specific WebSocket event `type` strings. These must exactly match the server's event names:

| CLI usage                    | Event type string                    |
| ---------------------------- | ------------------------------------ |
| Streaming chat responses     | `ai_message_update`                  |
| Background response complete | `ai_background_response_completed`   |
| Typing indicator             | `ai_typing_started`                  |
| Create/update memory         | `store_app_settings_memories_entry`  |
| Delete memory                | `delete_app_settings_memories_entry` |

Before adding a new WebSocket event handler, **search `websocketService.ts` and the backend** for the canonical event name. Never invent a new event type without a matching server-side emission.

---

## Rule 5 — Embed Key Resolution Has 3 Strategies (Don't Simplify)

`client.ts:resolveEmbedKey()` implements the same 3-strategy key resolution as `embedStore.ts:getEmbedKey()` in the web app:

1. **Master key type** — if the embed's `key_type` is `master`, decrypt the embed's `encrypted_key` with the user's master key.
2. **Chat key type** — if `key_type` is `chat`, decrypt the embed's `encrypted_key` with the parent chat's AES key.
3. **Parent embed fallback** — if the embed has a `parent_embed_id`, recursively resolve the parent embed's key.

**Never collapse these into fewer strategies.** Older embeds use different key types; removing any strategy silently breaks decryption of historical data.

---

## Rule 6 — New Commands Must Add Help Text

Every new command and subcommand added to `cli.ts` must:

1. Be listed in the `--help` / `help` output block.
2. Include a short one-line description.
3. Follow the existing pattern: `openmates <noun> <verb> [options]` (e.g., `openmates chats show <id>`).

Do not add positional-argument parsing without also documenting it in the help text.

---

## Rule 7 — Terminal Output Is User-Facing: Keep It Readable

The CLI outputs to a terminal. Follow these conventions:

- **Errors:** Print to `stderr` (`console.error`). Include enough context that the user can act without debugging.
- **Structured data:** Use `JSON.stringify(..., null, 2)` for `--json` output mode; human-readable plain text otherwise.
- **Decryption failures:** Never silently swallow decrypt errors. Print `[encrypted — cannot decrypt]` or similar so users know data exists but could not be read.
- **Progress/status:** Use `process.stderr.write(...)` for spinner-like output that won't pollute JSON output piped to another program.
- **No raw stack traces** in normal operation — catch errors at the command handler level and print a clean message.

---

## Rule 8 — Storage Files Use Strict Permissions

`storage.ts` writes `~/.openmates/session.json` and `~/.openmates/sync_cache.json`. These files contain session tokens and cached decrypted data.

- Directory permissions: `0o700` (owner only)
- File permissions: `0o600` (owner read/write only)
- **Never relax these permissions.** Do not change them to `0o644` or `0o755` even "for debugging".
- Incognito history (`incognito.json`) must also be `0o600`.

---

## Rule 9 — BLOCKED_SETTINGS_MUTATE_PATHS Is a Security Boundary

`client.ts` maintains a `BLOCKED_SETTINGS_MUTATE_PATHS` list of settings paths that must never be writable through the CLI (e.g., passkeys, billing, device sessions). Before adding new `settings post/patch/delete` functionality, check this list. If a path must be blocked for security, add it there **and** document why with an inline comment.

---

## Rule 10 — TypeScript Types, Not `any`

- Do not use `any` for decryption outputs. Use specific interfaces (`ChatMessage`, `EmbedData`, etc.) or `unknown` with a type guard.
- Memory field values are `unknown` until validated against `MEMORY_TYPE_REGISTRY` — keep the validation step before casting.
- Props from the API that may be `null` or `undefined` should use optional chaining (`?.`) rather than non-null assertions (`!`).

---

## Testing

### Unit tests (no build required for crypto/storage)

```bash
# crypto roundtrip + format tests
node --test --experimental-strip-types frontend/packages/openmates-cli/tests/crypto.test.ts

# session/cache persistence tests
node --test --experimental-strip-types frontend/packages/openmates-cli/tests/storage.test.ts
```

### Unit tests (requires compiled dist)

```bash
cd frontend/packages/openmates-cli && npm run build && node --test tests/cli.test.ts
```

### E2E tests (Playwright — requires running dev server + CLI binary)

```bash
# Full pair-login flow
npx playwright test frontend/apps/web_app/tests/cli-pair-login.spec.ts

# Memory lifecycle (zero-knowledge roundtrip)
npx playwright test frontend/apps/web_app/tests/cli-memories.spec.ts
```

**Run crypto and storage unit tests after any change to `crypto.ts` or `storage.ts`.**
**Run E2E tests after any change to `cli.ts` or `client.ts`.**

---

## Dependency Management

Same rule as frontend-standards: **never add a package with a version from memory.** Before adding any npm dependency:

```bash
pnpm info <package-name> version
```

The CLI has zero runtime dependencies beyond Node.js built-ins (intentional). Before adding any external library, consider whether the functionality can be implemented with `node:crypto`, `node:fs`, or `node:http` built-ins. An external dependency increases install size for users who run the CLI globally.

---

## Build

```bash
cd frontend/packages/openmates-cli
npm run build   # tsup → ESM in dist/
```

The compiled output goes to `dist/cli.js` (bin entry). Do not commit `dist/` — it is gitignored and rebuilt on publish.
