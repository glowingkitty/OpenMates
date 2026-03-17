# openmates

OpenMates npm CLI + SDK (pair-auth login only).

## Install

```bash
npm install -g openmates
```

## Environment

The CLI auto-derives the web app URL from the API URL so the pair token always lands on the right backend.

| Target               | Command prefix                                                                    |
| -------------------- | --------------------------------------------------------------------------------- |
| Production (default) | _(none)_                                                                          |
| Dev server           | `OPENMATES_API_URL=https://api.dev.openmates.org`                                 |
| Self-hosted          | `OPENMATES_API_URL=https://api.example.com OPENMATES_APP_URL=https://example.com` |

## CLI Commands

```bash
openmates login
openmates whoami --json
openmates chats list
openmates chats new "Hello"
openmates chats send --chat <chat-id> "continue"
openmates apps list --api-key <key>
openmates apps ai ask "What is Docker?" --api-key <key>
openmates settings get /v1/settings/export-account-data --json
openmates settings memories list --json
```

## Safety Limits

The CLI intentionally blocks endpoint writes for:

- API key creation
- Password setup/update
- 2FA setup/provider changes

See `src/client.ts` (`BLOCKED_SETTINGS_POST_PATHS`).

## SDK

```ts
import { OpenMatesClient } from "openmates";

const client = OpenMatesClient.load();
```
