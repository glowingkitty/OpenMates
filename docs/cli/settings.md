---
status: active
last_verified: 2026-03-24
---

# Settings Commands

Read and write account settings via REST. The CLI supports `get`, `post`, `patch`, and `delete` operations on settings paths, plus gift card management and memories CRUD.

## Reading Settings

```
openmates settings get billing
openmates settings get storage
openmates settings get usage
openmates settings get usage/summaries
openmates settings get usage/daily-overview
openmates settings get usage/export
openmates settings get reminders
openmates settings get chats
openmates settings get api-keys
openmates settings get export-account-manifest
openmates settings get export-account-data
openmates settings get delete-account-preview
openmates settings get billing --json
```

## Writing Settings

```
openmates settings post user/username --data '{"encrypted_username":"..."}'
openmates settings post user/timezone --data '{"timezone":"Europe/Berlin"}'
openmates settings post user/language --data '{"language":"en"}'
openmates settings post user/darkmode --data '{"dark_mode":true}'
openmates settings post auto-delete-chats --data '{"period":"90d"}'
openmates settings post auto-delete-usage --data '{"period":"1y"}'
openmates settings post auto-topup/low-balance --data '{"enabled":true,"amount":1000,"currency":"eur"}'
openmates settings post ai-model-defaults --data '{"simple":"...","complex":"..."}'
openmates settings post import-chat --data '<json>'
openmates settings post issues --data '<json>'
```

## Patching Settings

```
openmates settings patch <path> --data '<json>'
```

Sends a PATCH request to update specific fields without replacing the entire resource.

## Deleting Settings

```
openmates settings delete api-keys/<key-id>
```

## Gift Cards

```
openmates settings gift-card redeem <CODE>
openmates settings gift-card list
openmates settings gift-card list --json
```

Redemption shows the credits added and your updated balance.

## Blocked Settings Paths (Security)

The following operations are blocked in the CLI for security reasons and must be performed in the web app:

- Password setup and updates (`/v1/settings/update-password`, `/v1/auth/setup_password`)
- Two-factor authentication setup (`/v1/auth/2fa/setup/*`)
- API key creation (`/v1/settings/api-keys` POST is blocked; listing and deletion are allowed)

These paths are enforced by `BLOCKED_SETTINGS_MUTATE_PATHS` in the client. Additionally, passkey management and device session management are not exposed as CLI-accessible settings paths at all -- the `--help` output shows web app URLs for these operations.

## Memories

Memories are managed as a sub-command of settings. See [apps-and-skills.md](./apps-and-skills.md) for the full memories reference (`openmates settings memories ...`).

## Key Files

- See [cli.ts](../../frontend/packages/openmates-cli/src/cli.ts) for `handleSettings()` and gift card handlers
- See [client.ts](../../frontend/packages/openmates-cli/src/client.ts) for `settingsGet()`, `settingsPost()`, `settingsPatch()`, `settingsDelete()`, and `BLOCKED_SETTINGS_MUTATE_PATHS`

## Related Docs

- [README](./README.md) -- CLI overview
- [Authentication](./authentication.md) -- session required for all settings commands
- [Apps & Skills](./apps-and-skills.md) -- memories CRUD reference
- [CLI Standards](../contributing/standards/cli.md) -- Rule 9 on blocked settings paths as a security boundary
