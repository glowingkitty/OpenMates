---
status: active
last_verified: 2026-03-24
---

# OpenMates CLI

A terminal interface and Node.js SDK for interacting with OpenMates. Provides pair-auth login, end-to-end encrypted chat operations, app skill execution, settings management, and self-hosted server administration.

## Installation

```
npm install -g openmates
```

Requires Node.js 18+. Runtime dependencies are minimal: `qrcode-terminal` (pair-auth QR display), `ws` (WebSocket streaming), `@toon-format/toon` (embed encoding), and `ahocorasick` (mention matching).

## Quick Start

```
openmates login
openmates whoami
openmates chats list
openmates chats new "Hello, what can you help me with?"
openmates apps list
```

Login uses pair-auth only -- the CLI never asks for your email or password. A QR code or pair PIN is displayed in your terminal, which you confirm in the web app. See [authentication.md](./authentication.md) for details.

## Commands

| Category | Description | Doc |
|----------|-------------|-----|
| `login`, `logout`, `whoami` | Authentication and session | [authentication.md](./authentication.md) |
| `chats` | List, search, show, send, share, download, delete, incognito | [chats.md](./chats.md) |
| `apps` | List apps, run skills, view skill info | [apps-and-skills.md](./apps-and-skills.md) |
| `settings` | Read/write settings, memories CRUD, gift cards | [settings.md](./settings.md) |
| `embeds`, `mentions` | View embeds, create share links, search mentions | [embeds-and-sharing.md](./embeds-and-sharing.md) |
| `inspirations`, `newchatsuggestions` | Daily inspirations and personalized suggestions | [chats.md](./chats.md) |
| `docs` | Browse, search, and download documentation | — |
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
| `incognito.json` | Local-only incognito chat history |
| `server.json` | Self-hosted server configuration |

All files are created with strict permissions (`0o600` owner read/write only, directory `0o700`). See [authentication.md](./authentication.md) for security details.

## Key Files

- See [cli.ts](../../frontend/packages/openmates-cli/src/cli.ts) for the command entry point and argument router
- See [client.ts](../../frontend/packages/openmates-cli/src/client.ts) for the SDK client and all API operations
- See [server.ts](../../frontend/packages/openmates-cli/src/server.ts) for server management commands

## Related Docs

- [Authentication](./authentication.md) -- login flow and session security
- [Chat Commands](./chats.md) -- full chat operation reference
- [Apps & Skills](./apps-and-skills.md) -- app listing and skill execution
- [Settings](./settings.md) -- memories management
- [Embeds & Sharing](./embeds-and-sharing.md) -- embed viewing and share links
- [Server Management](./server-management.md) -- self-hosted server administration
- [CLI Standards](../contributing/standards/cli.md) -- development standards for CLI contributors
- [CLI Architecture](../architecture/apps/cli-package.md) -- architecture decisions
