# OpenMates — CLI + SDK Package

> **Status:** npm MVP implemented (pair-auth + chat/apps/settings/embeds/mentions)
>
> Source: `frontend/packages/openmates-cli/`
> Standards: `docs/claude/cli-standards.md`
> Architecture: `docs/architecture/openmates-cli.md`

---

## Overview

A single npm package (`openmates`) providing both a CLI and a programmatic SDK for interacting with OpenMates from the terminal or Node.js code.

**What it does:**
- Pair-auth login (no password/email — only pair PIN via magic link)
- End-to-end encrypted chat operations (list, search, new, send, share, incognito)
- App skill execution (`openmates apps <app> <skill> "<query>"`)
- Settings read/write, memories CRUD, mentions, embeds, inspirations
- Programmatic SDK: `import { OpenMates } from "openmates"`

**What it does NOT do (by design):**
- Full chat management UI — use the web app for browsing conversation history
- API key creation, password setup, 2FA — blocked in `client.ts` (`BLOCKED_SETTINGS_MUTATE_PATHS`)
- Server management or remote access — see [cli-remote-access.md](./cli-remote-access.md) (planned)

**CLI vs REST API:** The CLI package handles encrypted chat data (zero-knowledge). The REST API (`docs/architecture/rest-api.md`) is for direct skill execution and integrations that don't need chat encryption.

---

## Development — Running from the Git Repo

When developing or testing CLI changes locally, you do **not** need to rebuild after every edit. Use `tsx` to run TypeScript source directly:

```bash
cd frontend/packages/openmates-cli

# Run any CLI command directly from source (no build step needed):
npx tsx src/cli.ts --help
npx tsx src/cli.ts login
npx tsx src/cli.ts chats list
npx tsx src/cli.ts apps --help
```

> **Why not `node --experimental-strip-types`?** The source files use `.js` import extensions (standard ESM convention, e.g. `import { ... } from "./client.js"`). Node's built-in TypeScript stripping cannot resolve `.js` -> `.ts`, but `tsx` handles this automatically.

### Alternative: Watch Mode (auto-rebuild)

If you prefer running from the compiled `dist/` output (e.g. to test the exact build artifact):

```bash
# Terminal 1 — watch mode rebuilds dist/ on every file save:
npm run dev

# Terminal 2 — run from compiled output:
node dist/cli.js --help
```

### Building for Production / Publishing

```bash
npm run build          # tsup -> ESM output in dist/
node dist/cli.js --help  # verify the build works
```

### Linking Globally (optional)

To make the `openmates` command available system-wide during development:

```bash
cd frontend/packages/openmates-cli
npm link

# Now works from anywhere:
openmates --help

# Remove when done:
npm unlink -g openmates
```

### Running Tests

```bash
# Unit tests (no build required):
node --test --experimental-strip-types tests/crypto.test.ts
node --test --experimental-strip-types tests/storage.test.ts

# CLI tests (requires build):
npm run build && node --test tests/cli.test.ts

# Full test suite:
npm test
```

---

## Connecting to the Dev Server

By default the CLI points at production (`https://api.openmates.org`). To use the dev server instead, pass the `--api-url` flag:

```bash
# Any command — just add --api-url:
npx tsx src/cli.ts --api-url https://api.dev.openmates.org login
npx tsx src/cli.ts --api-url https://api.dev.openmates.org chats list
```

Or set the environment variable so you don't have to repeat it:

```bash
export OPENMATES_API_URL=https://api.dev.openmates.org

npx tsx src/cli.ts login    # now hits dev server
npx tsx src/cli.ts chats list
```

The CLI auto-derives the web app URL for pair-auth (`https://app.dev.openmates.org` for dev, `http://localhost:5173` for localhost). Override with `OPENMATES_APP_URL` if needed.

---

## Implemented Commands

All commands support `--json` for machine-readable output, `--api-url <url>` to override the API, and `--help` for contextual help. For full flag details, run `openmates <command> --help`.

### Authentication

| Command | Description |
|---------|-------------|
| `login` | Pair-auth login via magic link + PIN |
| `logout` | Clear session |
| `whoami [--json]` | Show account info |

### Chats

| Command | Description |
|---------|-------------|
| `chats list` | List chats with pagination |
| `chats search <query>` | Search chats |
| `chats new <message>` | Start new chat |
| `chats send [--chat <id>] <message>` | Send/continue message |
| `chats show <chat-id>` | Show chat details (decrypted) |
| `chats delete <id> [id2] [...]` | Delete chats |
| `chats share [<chat-id>] [--expires <s>] [--password <pwd>]` | Share chat |
| `chats incognito <message>` | Send incognito message |
| `chats incognito-history` | Show incognito history |
| `chats incognito-clear` | Clear incognito history |

### Apps

| Command | Description |
|---------|-------------|
| `apps list` | List available apps |
| `apps info <app-id>` | Get app info |
| `apps skill-info <app-id> <skill-id>` | Get skill info |
| `apps <app-id> <skill-id> "<query>"` | Run skill with text query |
| `apps <app-id> <skill-id> --input '<json>'` | Run skill with JSON input |

### Settings & Memories

| Command | Description |
|---------|-------------|
| `settings get <path>` | Fetch settings (billing, usage, chats, api-keys) |
| `settings post <path> --data '<json>'` | Update settings |
| `settings patch <path> --data '<json>'` | Patch settings |
| `settings delete <path>` | Delete settings |
| `settings gift-card redeem <CODE>` | Redeem gift card |
| `settings gift-card list` | List redeemed gift cards |
| `settings memories list [--app-id <id>]` | List memories |
| `settings memories types [--app-id <id>]` | Show memory types |
| `settings memories create --app-id <id> --item-type <type> --data '<json>'` | Create memory |
| `settings memories update --id <id> --app-id <id> --item-type <type> --data '<json>'` | Update memory |
| `settings memories delete --id <entry-id>` | Delete memory |

### Other

| Command | Description |
|---------|-------------|
| `mentions list [--type <type>]` | List available @mentions |
| `mentions search <query>` | Search mentions |
| `embeds show <embed-id>` | Display embed content (decrypted) |
| `embeds share <embed-id> [--expires <s>] [--password <pwd>]` | Share embed |
| `inspirations [--lang <code>]` | Daily inspirations |
| `newchatsuggestions [--limit <n>]` | Personalized new chat suggestions |

---

## Planned Features

These are not yet implemented. Design docs with full details:

- ~~**Server management** (`openmates server install/start/stop/logs/update/reset`)~~ — **Implemented.** Also includes `status`, `restart`, `make-admin`, and `uninstall`. See `src/server.ts`.
- **Remote access** (`openmates remote-access start`) — Enable web app to interact with server's filesystem with security modes. See [cli-remote-access.md](./cli-remote-access.md).
- **Secret tokenization** — Reversible secret redaction using Aho-Corasick multi-pattern matching, so the LLM never sees real secret values. See [cli-remote-access.md](./cli-remote-access.md).
- **Python SDK** — `pip install openmates` with Click-based CLI. Same functionality as Node.js package.
- **Browser setup** (`openmates apps web setup_browser`) — Docker + Playwright for testing localhost apps.
- **System monitoring** — CPU/memory/disk/Docker status included in server requests.

---

## Design Principles

- Subcommands for actions, flags for configuration (`openmates <noun> <verb> [--options]`)
- One package handles both CLI and SDK
- Zero runtime dependencies beyond Node.js built-ins where possible
- Progressive disclosure: basic features by default, advanced features opt-in
- Manual argument parsing (no Commander/yargs framework)
- Build tool: `tsup` (ESM output with TypeScript declarations)

---

## Key Files

| File | Purpose |
|------|---------|
| `src/cli.ts` | Entry point — argument router, help text |
| `src/client.ts` | OpenMatesClient — all SDK operations, decryption, memory registry |
| `src/crypto.ts` | AES-256-GCM + PBKDF2 crypto (Node.js webcrypto) |
| `src/ws.ts` | WebSocket client for chat streaming |
| `src/storage.ts` | `~/.openmates` session/cache persistence (strict `0o600` permissions) |
| `src/http.ts` | Thin fetch wrapper |
| `src/embedRenderers.ts` | Terminal rendering for all embed types |
| `src/outputRedactor.ts` | Output redaction for sensitive data |
| `src/index.ts` | SDK entry for programmatic use |
| `package.json` | Package config, bin entry (`dist/cli.js`), build scripts |

For coding standards, sync rules, and crypto constraints, see `docs/claude/cli-standards.md`.
