---
status: active
last_verified: 2026-03-24
key_files:
  - frontend/packages/openmates-cli/src/cli.ts
  - frontend/packages/openmates-cli/src/client.ts
  - frontend/packages/openmates-cli/src/crypto.ts
  - frontend/packages/openmates-cli/src/ws.ts
  - frontend/packages/openmates-cli/src/storage.ts
  - frontend/packages/openmates-cli/src/server.ts
  - frontend/packages/openmates-cli/src/embedRenderers.ts
  - frontend/packages/openmates-cli/src/outputRedactor.ts
  - frontend/packages/openmates-cli/package.json
---

# CLI Package

> npm package (`openmates`, v0.6.0-alpha.1) providing both a CLI and a programmatic SDK for pair-auth login, encrypted chat operations, app skill execution, settings management, and self-hosted server management.

## Why This Exists

The REST API cannot decrypt/encrypt chats (zero-knowledge architecture). The CLI package handles encrypted chat data client-side using AES-256-GCM + PBKDF2, enabling chat operations, incognito mode, sharing, and cross-device sync from the terminal or Node.js code.

## How It Works

### Authentication

Pair-auth login via magic link + PIN (no password/email prompt). Session stored in `~/.openmates` with strict `0o600` permissions.

### Implemented Commands

**Auth:** `login`, `logout`, `whoami`

**Chats:** `list`, `search`, `new`, `send`, `show`, `delete`, `share` (with expiry/password), `incognito`, `incognito-history`, `incognito-clear`

**Apps:** `list`, `info`, `skill-info`, `<app-id> <skill-id> "<query>"` (run skill with text or `--input` JSON)

**Settings & Memories:** `get/post/patch/delete` settings paths, `gift-card redeem/list`, `memories list/types/create/update/delete`

**Other:** `mentions list/search`, `embeds show/share`, `inspirations`, `newchatsuggestions`

**Server management:** `install`, `start`, `stop`, `restart`, `status`, `logs`, `update`, `reset`, `make-admin`, `uninstall` -- manages self-hosted instances via Docker Compose. No login required.

All commands support `--json` for machine-readable output and `--api-url` to override the API endpoint.

### Security Boundaries

Blocked operations (defined in `client.ts` as `BLOCKED_SETTINGS_MUTATE_PATHS`): API key creation, password setup, 2FA configuration. These must be done via the web app.

### Development

```bash
cd frontend/packages/openmates-cli
npx tsx src/cli.ts --help           # Run from source (no build needed)
npm run dev                          # Watch mode with auto-rebuild
npm run build                        # Production build via tsup (ESM)
npm test                             # Full test suite
```

Connect to dev server: `--api-url https://api.dev.openmates.org` or `OPENMATES_API_URL` env var. App URL auto-derived for pair-auth.

### Key Files

| File | Purpose |
|------|---------|
| `cli.ts` | Entry point, argument router, help text |
| `client.ts` | OpenMatesClient SDK, decryption, memory registry |
| `crypto.ts` | AES-256-GCM + PBKDF2 (Node.js webcrypto) |
| `ws.ts` | WebSocket client for chat streaming |
| `storage.ts` | `~/.openmates` session/cache persistence |
| `server.ts` | Server management via git/docker shell-outs |
| `embedRenderers.ts` | Terminal rendering for all embed types |
| `outputRedactor.ts` | Auto-redaction of sensitive data from memories |
| `index.ts` | SDK entry for `import { OpenMates } from "openmates"` |

### Design Principles

- Subcommands for actions, flags for config: `openmates <noun> <verb> [--options]`
- Zero runtime deps beyond Node.js built-ins where possible (actual deps: `@toon-format/toon`, `ahocorasick`, `qrcode-terminal`, `ws`)
- Manual argument parsing (no Commander/yargs)
- Build: `tsup` (ESM + TypeScript declarations)

## Planned Features

- **Remote access** (`openmates remote-access start`) -- web app interaction with server filesystem. See [cli-remote-access.md](./cli-remote-access.md).
- **Secret tokenization** -- reversible secret redaction via Aho-Corasick multi-pattern matching
- **Python SDK** -- `pip install openmates` with Click-based CLI
- **Browser setup** -- Docker + Playwright for localhost app testing
- **System monitoring** -- CPU/memory/disk/Docker status in server requests

## Related Docs

- [REST API](./rest-api.md) -- direct skill execution without chat encryption
- [CLI Standards](../../contributing/standards/cli.md) -- coding standards, sync rules, crypto constraints
