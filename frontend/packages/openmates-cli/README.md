# openmates

Terminal CLI and Node.js SDK for OpenMates. Use it to pair-login, create or continue encrypted chats, run app skills, manage safe account settings, browse docs, and administer self-hosted installs.

## Install

```bash
npm install -g openmates
openmates chats list
openmates login
```

Without a session, `openmates chats list`, `show`, and `open` display clearly labeled public example chats from the web app. Login uses pair-auth: the CLI shows a QR code or PIN, and you approve it in the web app. To create a new account from the terminal, run `openmates signup`; passwords and recovery secrets are collected through hidden prompts, never command-line flags.

## First Commands

```bash
openmates whoami --json
openmates chats list
openmates chats show example-gigantic-airplanes
openmates chats new "Help me plan my day"
openmates chats send --chat <chat-id> "continue"
openmates apps list
openmates apps ai ask "What is Docker?"
openmates apps code run --language python --code 'print("Hello")'
openmates settings account export data --json
openmates settings memories list --json
openmates docs list
openmates server install
```

Run `openmates --help` or `openmates <command> --help` for the full command surface.

## Environments

The CLI derives the web app URL from the API URL so pair-auth lands on the matching backend.

| Target | Command prefix |
| --- | --- |
| Production | _(none)_ |
| Dev server | `OPENMATES_API_URL=https://api.dev.openmates.org` |
| Self-hosted | `OPENMATES_API_URL=https://api.example.com OPENMATES_APP_URL=https://example.com` |

You can also pass `--api-url <url>` per command. App-skill execution can use your logged-in session, `--api-key <key>`, or `OPENMATES_API_KEY`.

## Safety Limits

Predefined settings commands are supported; raw `settings get/post/patch/delete` passthrough is intentionally unavailable. High-risk or browser-only flows such as passkey management, password changes, API key creation, device approvals, and card checkout stay in the web app. The code-level guard is `BLOCKED_SETTINGS_MUTATE_PATHS` in `src/client.ts`.

## SDK

```ts
import { OpenMatesClient } from "openmates";

const client = OpenMatesClient.load();
const chats = await client.listChats();
```

Source docs: `docs/user-guide/cli/` in the OpenMates repository.
