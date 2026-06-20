---
status: active
doc_type: reference
audience:
  - end-users
  - technical-users
last_verified: 2026-06-19
claims:
  - id: cli-readme-lists-command-categories
    type: unit
    claim: The CLI overview lists the top-level command categories exposed by CLI help.
    source:
      - frontend/packages/openmates-cli/src/cli.ts
    test:
      file: frontend/packages/openmates-cli/tests/cli.test.ts
      command: cd frontend/packages/openmates-cli && npm run build && npm run test:unit:cli
      assertion: cli-readme-lists-command-categories
    verified: '2026-06-11'
  - id: cli-npm-readme-onboarding-matches-command-surface
    type: unit
    claim: The npm package README gives concise onboarding with current commands and no removed raw settings examples.
    source:
      - frontend/packages/openmates-cli/README.md
      - frontend/packages/openmates-cli/src/cli.ts
    test:
      file: frontend/packages/openmates-cli/tests/cli.test.ts
      command: cd frontend/packages/openmates-cli && npm run build && npm run test:unit:cli
      assertion: cli-npm-readme-onboarding-matches-command-surface
    verified: '2026-06-11'
---

# OpenMates CLI

A terminal interface and Node.js SDK for interacting with OpenMates. Provides pair-auth login, encrypted chat operations, app skill execution, settings management, and self-hosted server administration.

## Installation

```
npm install -g openmates
```

Requires Node.js 20+. Runtime dependencies are minimal: `qrcode-terminal` (pair-auth QR display), `ws` (WebSocket streaming), `@toon-format/toon` (embed encoding), and `ahocorasick` (mention matching).

## Quick Start

```
openmates login
openmates whoami
openmates chats list
openmates chats show example-gigantic-airplanes
openmates chats new "Hello, what can you help me with?"
openmates apps list
```

`openmates chats list`, `show`, and `open` work before login for clearly labeled public example chats. Private encrypted chats, sending messages, settings, and personalized data require login. Login uses pair-auth -- the CLI never asks for your account password during login. A QR code or pair PIN is displayed in your terminal, which you confirm in the web app. New users can run `openmates signup` for guided account creation. See [authentication.md](./authentication.md) for details.

## Commands

| Category | Description | Doc |
|----------|-------------|-----|
| `signup`, `login`, `logout`, `whoami` | Account creation, authentication, and session | [authentication.md](./authentication.md) |
| `chats` | List, search, show, send, share, download, delete, incognito | [chats.md](./chats.md) |
| `apps` | List apps, run skills, view skill info | [apps-and-skills.md](./apps-and-skills.md) |
| `settings`, `learning-mode` | Predefined settings commands, Learning Mode controls, invoices, notifications, mates, newsletter, memories | [settings.md](./settings.md) |
| `benchmark` | Run real product-path model benchmarks, comparisons, and judged case suites | [benchmarks.md](./benchmarks.md) |
| `embeds`, `mentions` | View embeds, create share links, search mentions | [embeds-and-sharing.md](./embeds-and-sharing.md) |
| `inspirations`, `newchatsuggestions` | Daily inspirations and personalized suggestions | [chats.md](./chats.md) |
| `docs` | Browse, search, show, and download documentation | [docs.md](./docs.md) |
| `server` | Install, start, stop, update a self-hosted instance | [server-management.md](./server-management.md) |

## Global Flags

| Flag | Description |
|------|-------------|
| `--json` | Output raw JSON instead of formatted output |
| `--api-url <url>` | Override API base URL (default: `https://api.openmates.org`) |
| `--api-key <key>` | Optional API key override (or set `OPENMATES_API_KEY` env var) |
| `--help` | Show contextual help for any command |

## Configuration

Session data is stored in `~/.openmates/`:

| File | Purpose |
|------|---------|
| `session.json` | Authentication session token |
| `sync_cache.json` | Cached decrypted data for offline access |
| `server.json` | Self-hosted server configuration |

All files are created with strict permissions (`0o600` owner read/write only, directory `0o700`). See [authentication.md](./authentication.md) for security details.

## Key Files

- See [cli.ts](../../../frontend/packages/openmates-cli/src/cli.ts) for the command entry point and argument router
- See [client.ts](../../../frontend/packages/openmates-cli/src/client.ts) for the SDK client and all API operations
- See [server.ts](../../../frontend/packages/openmates-cli/src/server.ts) for server management commands

## Related Docs

- [Authentication](./authentication.md) -- login flow and session security
- [Chat Commands](./chats.md) -- full chat operation reference
- [Apps & Skills](./apps-and-skills.md) -- app listing and skill execution
- [Settings](./settings.md) -- account, billing, notifications, mates, newsletter, and memories management
- [Benchmark Commands](./benchmarks.md) -- model benchmark suites, comparison mode, and judge scoring
- [Embeds & Sharing](./embeds-and-sharing.md) -- embed viewing and share links
- [Docs Commands](./docs.md) -- browsing and downloading documentation from the terminal
- [Server Management](./server-management.md) -- self-hosted server administration
- [CLI Standards](../../contributing/standards/cli.md) -- development standards for CLI contributors
- [CLI Architecture](../../architecture/platforms/cli-package.md) -- architecture decisions
