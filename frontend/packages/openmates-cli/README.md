# openmates

<img src="https://openmates.org/favicon.png" alt="OpenMates" width="72">

Terminal CLI for OpenMates. Use it to chat from your shell, run app skills,
inspect encrypted account data, export chats, browse docs, and install or manage
self-hosted OpenMates servers.

[OpenMates](https://openmates.org) | [CLI docs](https://openmates.org/docs/user-guide/cli) | [Self-hosting docs](https://openmates.org/docs/self-hosting/setup) | [Source](https://github.com/glowingkitty/OpenMates/tree/dev/frontend/packages/openmates-cli)

## Install

```bash
npm install -g openmates
```

Requires Node.js 20 or newer.

Install the latest dev prerelease:

```bash
npm install -g openmates@alpha
```

Update an existing global install:

```bash
openmates update
openmates update --dry-run
openmates update --version alpha
```

## Quick Start

Run the interactive terminal chat UI:

```bash
openmates
```

In the TUI, use `/help`, `/examples`, `/login`, `/signup`, and `/exit`.
When stdin or stdout is redirected, plain `openmates` prints a script-friendly
quickstart instead of opening the TUI.

Login with pair-auth:

```bash
openmates login
openmates whoami --json
```

The CLI displays a QR code or pair PIN. Approve it in the OpenMates web app.
During login, the CLI never asks for your account password.

Create a new account from the terminal:

```bash
openmates signup
```

Signup collects passwords, 2FA codes, backup codes, and recovery keys through
hidden prompts or owner-only files, not command-line password flags.

## Common Commands

### Chat from the shell

```bash
openmates chats list
openmates chats show last
openmates chats new "Help me plan my day"
openmates chats send --chat <chat-id> "continue"
openmates chats incognito "Answer without saving this chat"
```

Without login, `openmates chats list`, `show`, and `open` display clearly labeled
public example chats from the web app.

### Attach local files and mentions

```bash
openmates chats new "@Sophia review @./src/app.ts"
openmates chats new "@Best summarize @./notes.md"
openmates mentions list
```

The CLI redacts likely secrets before sending file content. Private keys and
high-risk files are blocked by default.

### Export, share, and delete chats

```bash
openmates chats download last --output ~/exports
openmates chats download <chat-id> --zip
openmates chats share last --expires 604800
openmates chats delete <chat-id> --yes
```

Exports include YAML and Markdown. When present, code embeds and video
transcripts are written as separate files.

### Use apps and typed commands

```bash
openmates apps list
openmates apps skill-info web search
openmates tasks create --title "Draft launch checklist"
openmates workflows list
openmates apps code run --language python --code 'print("Hello from CLI")'
```

Typed app commands use your logged-in session by default. For non-interactive scripts,
create an API key in **Settings > Developers > API Keys**, then pass
`--api-key <key>` or set `OPENMATES_API_KEY`.

### Account settings and data

```bash
openmates settings --help
openmates settings account export data --json
openmates settings memories list --json
openmates learning-mode status --json
openmates docs search "API keys"
```

Predefined settings commands are supported. Raw settings path passthrough is not
available. Security-sensitive actions such as passkey management, password
changes, API key creation, device approvals, and card checkout stay in the web
app. The code-level guard is `BLOCKED_SETTINGS_MUTATE_PATHS` in `src/client.ts`.

### Embeds, docs, and benchmarks

```bash
openmates embeds show <embed-id>
openmates embeds share <embed-id> --expires 604800
openmates docs list
openmates docs download cli/server-management
openmates benchmark model google/gemini-3.5-flash --dry-run --json
```

Benchmark commands run real product-path model calls when not in `--dry-run`, so
review the spend confirmation before live runs.

### Local source bridge

```bash
openmates remote-access start --path ./my-repo --source-id repo-1 --local-only
openmates remote-access status --json
openmates remote-access search --source repo-1 "TODO" --limit 20
```

`openmates remote-access` stores source metadata under
`~/.openmates/remote-sources.json`, searches with `rg` inside the approved root,
and does not upload repository files by default.

## Self-Host Server Management

The CLI can install and manage a self-hosted OpenMates server. Server commands do
not require an OpenMates cloud login. They operate on the local Docker Compose
runtime.

### Install a server

```bash
openmates server install
openmates server start
openmates server status
```

The default install path is `~/openmates`. Use `--path <folder>` only when you
want to install somewhere else:

```bash
openmates server install --path /opt/openmates
openmates server start --path /opt/openmates
```

Default installs use prebuilt GHCR images and do not require Git, a source
checkout, or cloud-only deployment flags. The installer writes a runtime
directory, creates `.env`, generates local secrets, saves the self-host API
target in `~/.openmates/server.json`, and prints the first invite code.

After startup, open:

| Service | URL |
| --- | --- |
| Web app | `http://localhost:5173` |
| Backend API | `http://localhost:8000` |

The first invite creates a normal user. Promote your account separately:

```bash
openmates server make-admin your@email.com
```

### Add AI providers or local models

A fresh self-hosted server can start without provider keys, but AI chat and model
processing stay unavailable until at least one real model provider is configured.

Edit `~/openmates/.env` and add a provider key, then restart:

```env
SECRET__OPENAI__API_KEY=sk-...
SECRET__ANTHROPIC__API_KEY=sk-ant-...
SECRET__GOOGLE_AI_STUDIO__API_KEY=...
```

```bash
openmates server restart
```

Or add a local OpenAI-compatible model served by Ollama, LM Studio, or another
runtime:

```bash
openmates server ai models add
openmates server ai models list
openmates server ai models test alibaba/qwen3-8b-local
```

### Operate and update a server

```bash
openmates server logs --tail 200
openmates server logs --container api --follow
openmates server update --dry-run
openmates server update
openmates server backup
openmates server stop
```

Updates pull the matching prebuilt images, restart containers, and wait for
health checks. Before replacing data-bearing services, the CLI creates a
rotating pre-update backup.

Run `openmates server --help` or read the self-hosting docs for advanced server
operations beyond the default install/start/update flow.

## Targets and Environment Variables

The CLI derives the web app URL from the API URL so pair-auth opens the matching
environment.

| Target | Command prefix |
| --- | --- |
| OpenMates cloud | none |
| Dev server | `OPENMATES_API_URL=https://api.dev.openmates.org` |
| Installed self-hosted server | none after `openmates server install` |
| Remote self-hosted server | `OPENMATES_API_URL=https://api.example.com` |

Useful variables:

| Variable | Purpose |
| --- | --- |
| `OPENMATES_API_URL` | Override the API endpoint. |
| `OPENMATES_APP_URL` | Override the derived web app URL for pair-auth. |
| `OPENMATES_API_KEY` | API key for app-skill and SDK calls. |

You can also pass `--api-url <url>`, `--api-key <key>`, and `--json` to most
commands.

## Local Files

The CLI stores local state under `~/.openmates/` with owner-only permissions.

| File | Purpose |
| --- | --- |
| `session.json` | Pair-auth CLI session. |
| `sync_cache.json` | Cached decrypted account data for CLI use. |
| `server.json` | Self-host install path and local API target. |
| `remote-sources.json` | Local source bridge metadata. |

Treat these files like account credentials.

## Node.js SDK

The npm package also exports an API-key SDK for Node.js. Use it when you want a
programmatic client instead of shell commands.

```ts
import { OpenMates } from "openmates";

const om = new OpenMates({ apiKey: process.env.OPENMATES_API_KEY });

const search = await om.apps.web.search({
  requests: [{ query: "OpenMates SDK examples" }],
});

const response = await om.chats.send("Summarize this release note draft.");
```

SDK chats are non-persistent by default. Use `saveToAccount: true` only when you
intentionally want the chat saved to the OpenMates account.

## Versioning

OpenMates shows the short product line, for example `v0.15`, in the web app.
The npm package uses exact artifact versions:

- `0.15.0-alpha.N` is a prerelease from the `dev` branch published under the
  `alpha` npm tag.
- `0.15.0` is a stable release from `main` published under the `latest` npm tag.

Install stable releases with `npm install -g openmates`. Install prereleases with
`npm install -g openmates@alpha`.

## More Documentation

- [CLI guide](https://openmates.org/docs/user-guide/cli)
- [Self-hosting setup](https://openmates.org/docs/self-hosting/setup)
- [SDK guide](https://openmates.org/docs/user-guide/developers/sdk)
- [Source code](https://github.com/glowingkitty/OpenMates/tree/dev/frontend/packages/openmates-cli)
- [Issue tracker](https://github.com/glowingkitty/OpenMates/issues)
