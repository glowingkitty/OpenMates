---
status: active
last_verified: 2026-03-24
---

# Settings Commands

Manage account settings with predefined, validated commands. The CLI no longer exposes raw settings `get`, `post`, `patch`, or `delete` passthrough commands; every supported settings operation has an explicit command, help text, examples, and local validation.

## Help

```
openmates settings --help
openmates settings account --help
openmates settings billing --help
openmates settings privacy --help
```

## Account

```
openmates settings account info
openmates settings account timezone set Europe/Berlin
openmates settings account export manifest
openmates settings account export data
openmates settings account import-chat ./chat.yml
openmates settings account chats stats
openmates settings account delete preview
```

Account deletion itself is web-only:

```
openmates settings account delete
```

## Storage

```
openmates settings account storage overview
openmates settings account storage files --category images
openmates settings account storage delete <file-id> --yes
openmates settings account storage delete --category images --yes
openmates settings account storage delete --all --yes
```

## Interface

```
openmates settings interface language set en
openmates settings interface dark-mode set on
openmates settings interface font set lexend
```

## AI

```
openmates settings ai models set-defaults --simple gpt-5.4 --complex claude-opus-4-7
```

## Privacy

```
openmates settings privacy auto-delete chats set 90d
openmates settings privacy debug-logs share --duration 1h --confirm
```

## Billing

```
openmates settings billing overview
openmates settings billing usage
openmates settings billing usage summaries
openmates settings billing usage daily
openmates settings billing usage export --json
openmates settings billing auto-topup low-balance set --enabled true --amount 1000 --currency eur --email you@example.com
openmates settings billing gift-card redeem <CODE>
openmates settings billing gift-card list
```

Redemption shows the credits added and your updated balance.

Buy credits, gift card purchases, support payments, and recurring payment setup remain web-only because payment checkout must use browser/payment-provider UI.

## Reminders

```
openmates settings reminders list
openmates settings reminders update <id> --enabled false
openmates settings reminders delete <id> --yes
```

## Developers

```
openmates settings developers api-keys list
openmates settings developers api-keys revoke <key-id> --yes
```

API key creation, developer devices, and webhooks are web-only or deferred until their security model is audited.

## Report Issue

```
openmates settings report-issue create --title "Bug" --body "What happened"
openmates settings report-issue status <issue-id>
```

## Blocked Settings Paths (Security)

The following operations are blocked in the CLI for security reasons and must be performed in the web app:

- Password setup and updates (`/v1/settings/update-password`, `/v1/auth/setup_password`)
- Two-factor authentication setup (`/v1/auth/2fa/setup/*`)
- API key creation (`/v1/settings/api-keys` POST is blocked; listing and deletion are allowed)
- Account deletion finalization (`/v1/settings/delete-account`)
- Sensitive action verification endpoints used for web-only actions (`/v1/settings/request-action-verification`, `/v1/settings/verify-action-code`)

These paths are enforced by `BLOCKED_SETTINGS_MUTATE_PATHS` in the client. Additionally, passkey management, recovery keys, and device session management are exposed only as informational commands that point to the web app.

## Memories

Memories are managed as a sub-command of settings. See [apps-and-skills.md](./apps-and-skills.md) for the full memories reference (`openmates settings memories ...`).

## Key Files

- See [cli.ts](../../frontend/packages/openmates-cli/src/cli.ts) for `handleSettings()` and predefined settings command handlers
- See [client.ts](../../frontend/packages/openmates-cli/src/client.ts) for `settingsGet()`, `settingsPost()`, `settingsPatch()`, `settingsDelete()`, and `BLOCKED_SETTINGS_MUTATE_PATHS`

## Related Docs

- [README](./README.md) -- CLI overview
- [Authentication](./authentication.md) -- session required for all settings commands
- [Apps & Skills](./apps-and-skills.md) -- memories CRUD reference
- [CLI Standards](../contributing/standards/cli.md) -- Rule 9 on blocked settings paths as a security boundary
