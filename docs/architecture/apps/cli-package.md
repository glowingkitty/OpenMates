---
status: active
last_verified: 2026-06-10
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

> npm package (`openmates`, v0.11.0-alpha.0) providing both a CLI and a programmatic SDK for signup, pair-auth login, encrypted chat operations, app skill execution, settings management, bank-transfer billing, and self-hosted server management.

## Why This Exists

The REST API cannot decrypt/encrypt chats (zero-knowledge architecture). The CLI package handles encrypted chat data client-side using AES-256-GCM + PBKDF2, enabling chat operations, incognito mode, sharing, and cross-device sync from the terminal or Node.js code.

## How It Works

### Authentication

Pair-auth login via magic link + PIN remains the default login path. `openmates signup` can create a password account from the terminal using hidden prompts and the same client-side encrypted signup crypto as the web app. Session data is stored in `~/.openmates` with strict `0o600` permissions.

CLI login derives and stores the email encryption key after pair-auth by decrypting the account email with the master key and applying the same `SHA256(email + user_email_salt)` derivation as the web app. The key uses the same tiered local protection path as the master key and is used for backend flows such as invoice refund requests.

### Implemented Commands

**Auth:** `signup`, `login`, `logout`, `whoami`

**Chats:** `list`, `search`, `new`, `send`, `show`, `delete`, `share` (with expiry/password), `incognito`, `incognito-history`, `incognito-clear`

**Apps:** `list`, `info`, `skill-info`, `<app-id> <skill-id> "<query>"` (run skill with text or `--input` JSON)

**Settings:** predefined account, profile picture, interface, privacy, billing, invoices, notifications, reminders, mates, newsletter, developer, issue-report, gift-card, and memory commands. Raw settings path passthrough is not exposed.

**Billing:** SEPA bank-transfer credit purchase, bank-transfer status/list, bank-transfer gift-card purchase/status, gift-card redemption, purchased/redeemed card lists, invoices, and refunds. Card checkout remains browser-only.

**Test provisioning:** `e2e provision-auth-accounts` writes local ignored artifacts for reserved auth E2E accounts and refuses production API URLs.

**Other:** `mentions list/search`, `embeds show/share`, `inspirations`, `newchatsuggestions`

**Server management:** `install`, `start`, `stop`, `restart`, `status`, `logs`, `update`, `reset`, `make-admin`, `uninstall` -- manages self-hosted instances via Docker Compose. No login required.

All commands support `--json` for machine-readable output and `--api-url` to override the API endpoint.

### Security Boundaries

Blocked raw operations (defined in `client.ts` as `BLOCKED_SETTINGS_MUTATE_PATHS`): API key creation, password changes, raw 2FA setup/disable paths, raw sensitive action verification, and raw account deletion finalization. Dedicated CLI commands may call a subset internally when they add terminal-specific checks such as hidden prompts, email-code verification, and local session cleanup.

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
- Keep runtime deps focused (actual deps: `@toon-format/toon`, `ahocorasick`, `qrcode-terminal`, `tweetnacl`, `ws`)
- Manual argument parsing (no Commander/yargs)
- Build: `tsup` (ESM + TypeScript declarations)

## Planned Features

- **Remote access** (`openmates remote-access start`) -- planned connected-server workflow, not part of the implemented CLI command set yet.
- **Secret tokenization** -- reversible secret redaction via Aho-Corasick multi-pattern matching
- **Python SDK** -- `pip install openmates` with Click-based CLI
- **Browser setup** -- Docker + Playwright for localhost app testing
- **System monitoring** -- CPU/memory/disk/Docker status in server requests

## Related Docs

- [REST API](./rest-api.md) -- direct skill execution without chat encryption
- [CLI Feature Parity](./cli-feature-parity.md) -- web app versus CLI capability matrix and roadmap
- [CLI Standards](../../contributing/standards/cli.md) -- coding standards, sync rules, crypto constraints
