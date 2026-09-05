---
status: active
last_verified: 2026-08-03
key_files:
- frontend/packages/openmates-cli/src/cli.ts
- frontend/packages/openmates-cli/src/client.ts
- frontend/packages/openmates-cli/src/crypto.ts
- frontend/packages/openmates-cli/src/ws.ts
- frontend/packages/openmates-cli/src/projectRequester.ts
- frontend/packages/openmates-cli/src/storage.ts
- frontend/packages/openmates-cli/src/server.ts
- frontend/packages/openmates-cli/src/embedRenderers.ts
- frontend/packages/openmates-cli/src/outputRedactor.ts
- frontend/packages/openmates-cli/package.json
claims:
- id: arch-platforms-cli-package-behavior
  type: unit
  claim: CLI Package is grounded in current source-of-truth files that parse or resolve successfully.
  source:
  - frontend/packages/openmates-cli/src/cli.ts
  - frontend/packages/openmates-cli/src/client.ts
  - frontend/packages/openmates-cli/src/crypto.ts
  - frontend/packages/openmates-cli/src/ws.ts
  - frontend/packages/openmates-cli/src/storage.ts
  test:
    file: scripts/tests/test_architecture_behavioral_claims.py
    command: python3 -m pytest scripts/tests/test_architecture_behavioral_claims.py
    assertion: arch-platforms-cli-package-behavior
  verified: '2026-06-11'
- id: arch-platforms-cli-package-source-1
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-platforms-cli-package-source-1
  anchors:
  - type: file_exists
    path: frontend/packages/openmates-cli/package.json
- id: arch-platforms-cli-package-source-2
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-platforms-cli-package-source-2
  anchors:
  - type: file_exists
    path: frontend/packages/openmates-cli/src/cli.ts
- id: arch-platforms-cli-package-source-3
  type: static
  file: scripts/tests/test_architecture_static_claims.py
  assertion: arch-platforms-cli-package-source-3
  anchors:
  - type: file_exists
    path: frontend/packages/openmates-cli/src/client.ts
---

# CLI Package

> npm package openmates, 0.18.x artifact line for product line v0.18, providing both a CLI and a programmatic SDK for signup, pair-auth login, encrypted chat operations, app skill execution, settings management, model benchmarking, bank-transfer billing, and self-hosted server management.

## Why This Exists

The REST API cannot decrypt/encrypt chats (zero-knowledge architecture). The CLI package handles encrypted chat data client-side using AES-256-GCM + PBKDF2, enabling chat operations, incognito mode, sharing, and cross-device sync from the terminal or Node.js code.

## How It Works

### Authentication

Pair-auth login via magic link + PIN remains the default login path. `openmates signup` can create a password account from the terminal using hidden prompts and the same client-side encrypted signup crypto as the web app. Session data is stored in `~/.openmates` with strict `0o600` permissions.

CLI login derives and stores the email encryption key after pair-auth by decrypting the account email with the master key and applying the same `SHA256(email + user_email_salt)` derivation as the web app. The key uses the same tiered local protection path as the master key and is used for backend flows such as invoice refund requests.

### Implemented Commands

**Auth:** `signup`, `login`, `logout`, `whoami`

**Chats:** `list`, `search`, `open`, `new`, `send`, `show`, `download`, `delete`, `share` (with expiry/password), `incognito`, `incognito-history`, `incognito-clear`

**Apps:** `list`, `info`, `skill-info`, `<app-id> <skill-id> "<query>"` (run skill with text or `--input` JSON), `code run`, and `travel booking-link`

**Settings:** predefined account, profile picture, interface, privacy, billing, invoices, notifications, reminders, mates, newsletter, developer, issue-report, gift-card, and memory commands. Raw settings path passthrough is not exposed.

**Benchmarks:** `benchmark model <provider/model>` runs real product-path model benchmarks with dry-run credit estimates, live spend confirmation, quick/extensive suites, case filtering, comparison mode, judge scoring, JSON output, and optional image fixture override.

**Billing:** SEPA bank-transfer credit purchase, bank-transfer status/list, bank-transfer gift-card purchase/status, gift-card redemption, purchased/redeemed card lists, invoices, and refunds. Card checkout remains browser-only.

**Test provisioning:** `e2e provision-auth-accounts` writes local ignored artifacts for reserved auth E2E accounts and refuses production API URLs.

**Projects:** deterministic Personal/Team list, show/open, create/update,
archive/unarchive/delete, item/source navigation, and CLI-only encrypted remote
file list/search/read. Destructive JSON/non-interactive calls require exact
confirmation: Project deletion carries the exact Project ID and source removal
carries the exact source ID to the server. Live file calls require an explicit
context; generic boolean DELETE confirmation is not supported.

**Other:** `mentions list/search`, `embeds show/share`, `inspirations`, `newchatsuggestions`, `docs list/search/show/download`, `update`/`upgrade` for updating the globally installed CLI package

**Release channel:** `openmates upgrade --channel dev` selects the dev branch's npm
`alpha` stream; `--channel stable` (or `main`) selects npm `latest`. The preference
is stored in `~/.openmates/updates.json` across authentication profiles and survives
upgrades. Subsequent `openmates upgrade` and `openmates version` use it. Stable
installations default to stable and prereleases default to dev when no preference
exists. A successful update or up-to-date check saves an explicit channel choice;
`--dry-run` and failed updates never save it. `--version` is a one-time override.
Automatic upgrades do not downgrade; use `--allow-downgrade` explicitly when switching
to an older channel version. npm upgrades preserve the running global installation's
prefix instead of installing into a different default prefix. Registry lookup failures
stop before installation. These commands do not read or modify login credentials.

**Server management:** `install`, `start`, `stop`, `restart`, `status`, `logs`, `update`, `reset`, `make-admin`, `uninstall` -- manages self-hosted instances via Docker Compose. No login required.

All commands support `--json` for machine-readable output and `--api-url` to override the API endpoint. Without an explicit override, API target priority is: `--api-url`, `OPENMATES_API_URL`, saved login session, installed self-host server config, then the OpenMates cloud API.

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

Connect to dev server: `--api-url https://api.dev.openmates.org` or `OPENMATES_API_URL` env var. App URL auto-derived for pair-auth; self-hosted `api.example.com` maps to `app.example.com` unless `OPENMATES_APP_URL` is set.

### Key Files

| File | Purpose |
|------|---------|
| `cli.ts` | Entry point, argument router, help text |
| `client.ts` | OpenMatesClient SDK, decryption, memory registry |
| `crypto.ts` | AES-256-GCM + PBKDF2 (Node.js webcrypto) |
| `ws.ts` | WebSocket client for chat streaming |
| `remoteAccess.ts` | Foreground source discovery, lifecycle, and bounded read-only filesystem operations |
| `remoteAccessCrypto.ts` | Project-authenticated peer handshake and encrypted bridge envelopes |
| `projectRequester.ts` | Bounded encrypted Personal/Team live-file requester and protocol timeout |
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

## Remote Access Architecture

`openmates remote-access [--path <folder>]... [--personal|--team <team>] [--json]` is the canonical
foreground source bridge. Without explicit paths it discovers Git repositories
below the current folder; repeated paths replace that scope. One authenticated
WebSocket supervises independently Project-scoped source bindings, heartbeats,
bounded reconnect, exact-device request delivery, and clean disconnect state.

The backend stores ephemeral owner, Project, source, session, capability, and
request-correlation metadata in Dragonfly. List, search, and selected text-read
payloads use a Project-key-authenticated X25519/HKDF/AES-GCM channel between the
requesting first-party client and CLI, so the backend relays opaque ciphertext
without receiving filesystem plaintext or keys. The CLI applies realpath,
no-follow, Git-ignore, protected-path, binary-content, time, concurrency, item,
line, and byte limits before returning a result.

The requester is `openmates projects files list|search|read`. It resolves and
decrypts the selected Project locally, requires explicit context for
non-interactive/JSON calls, selects one online source without fallback, and
uses a 45-second protocol deadline. Team Project keys are returned only as
Team-key-wrapped ciphertext; API projections also return role-derived mutation
permissions. Team routing discovery exchanges only Project-encrypted data and
opaque scoped identities. Requester plaintext is rendered only as the explicit
command result and is never logged or persisted by the relay.

Stored Project CRUD will later have npm and pip parity. Filesystem hosting and
live file requests remain first-party CLI-only and are intentionally absent from
developer SDK facades.

The current bridge is intentionally read-only and foreground-only. Daemon or OS
service hosting, filesystem mutation, shell execution, package installation,
and BYOC model workers are separate future designs and are not implied by source
registration.

## Planned Features

- **Secret tokenization** -- reversible secret redaction via Aho-Corasick multi-pattern matching
- **Python SDK** -- `pip install openmates` with Click-based CLI
- **Browser setup** -- Docker + Playwright for localhost app testing
- **System monitoring** -- CPU/memory/disk/Docker status in server requests

## Related Docs

- [REST API](../apps/rest-api.md) -- direct skill execution without chat encryption
- [CLI Feature Parity](./cli-feature-parity.md) -- web app versus CLI capability matrix and roadmap
- [CLI Standards](../../contributing/standards/cli.md) -- coding standards, sync rules, crypto constraints
