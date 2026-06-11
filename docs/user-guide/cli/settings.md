---
status: active
doc_type: reference
audience:
  - end-users
  - technical-users
last_verified: 2026-06-11
claims:
  - id: cli-settings-lists-predefined-commands
    type: unit
    claim: Settings help lists predefined settings commands instead of raw passthrough paths.
    source:
      - frontend/packages/openmates-cli/src/cli.ts
      - frontend/packages/openmates-cli/src/client.ts
    test:
      file: frontend/packages/openmates-cli/tests/cli.test.ts
      command: cd frontend/packages/openmates-cli && npm run build && npm run test:unit:cli
      assertion: cli-settings-lists-predefined-commands
    verified: '2026-06-11'
  - id: cli-settings-rejects-raw-passthrough
    type: unit
    claim: Raw settings passthrough commands are rejected locally before auth or network access.
    source:
      - frontend/packages/openmates-cli/src/cli.ts
      - frontend/packages/openmates-cli/src/client.ts
    test:
      file: frontend/packages/openmates-cli/tests/cli.test.ts
      command: cd frontend/packages/openmates-cli && npm run build && npm run test:unit:cli
      assertion: cli-settings-rejects-raw-passthrough
    verified: '2026-06-11'
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
openmates settings account username set alice_123
openmates settings account profile-picture set ./avatar.jpg
openmates settings account chats stats
openmates settings account delete preview
openmates settings account delete --yes
```

Profile pictures must be JPEG or PNG files no larger than 300 KB. Resize/compress images before upload; the web app still provides the richer crop/preview flow.

Account deletion uses a stricter CLI-only verification flow. It always sends an email verification code and prompts for that code interactively. If 2FA is configured, it also prompts for a current TOTP code. Verification codes cannot be passed as flags.

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
openmates settings billing buy-credits bank-transfer --credits 110000
openmates settings billing bank-transfer status <order-id>
openmates settings billing bank-transfer list
openmates settings billing invoices list
openmates settings billing invoices download <invoice-id> --output ./invoices
openmates settings billing invoices credit-note <invoice-id> --output ./invoices
openmates settings billing invoices refund <invoice-id> --yes
openmates settings billing auto-topup low-balance set --enabled true --amount 1000 --currency eur --email you@example.com
openmates settings billing gift-card redeem <CODE>
openmates settings billing gift-card list
openmates settings billing gift-card buy bank-transfer --credits 21000
openmates settings billing gift-card purchase-status <order-id>
openmates settings billing gift-card purchased
```

Redemption shows the credits added and your updated balance.

Invoice downloads write PDFs to the current directory by default, or to `--output <dir-or-file.pdf>`. Refund requests use the email encryption key stored during CLI login; if you logged in with an older CLI version, run `openmates login` again to refresh local encryption keys.

Bank-transfer credit and gift-card purchases are supported in the CLI. The gift-card code is not available until the transfer is matched. Card checkout, support payments, and recurring payment setup remain web-only because payment checkout must use browser/payment-provider UI.

## Notifications

```
openmates settings notifications status
openmates settings notifications email set --enabled true --email you@example.com --ai-responses true --backup-reminder true
openmates settings notifications backup set --enabled true --interval 30 --email you@example.com
```

Notification writes use the same WebSocket `email_notification_settings` contract as the web app. Enabling email notifications requires an email address so the backend can encrypt it with the user's vault key before storage.

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

## Mates

```
openmates settings mates list
openmates settings mates info software_development
openmates settings mates consent --yes
```

Mate listing and detail output are local metadata helpers. Use the printed `@mate:<id>` mention in chat commands to route messages to a mate.

## Newsletter

```
openmates settings newsletter categories
openmates settings newsletter categories set --updates true --tips true --daily false
openmates settings newsletter subscribe you@example.com --language en
openmates settings newsletter confirm <token>
openmates settings newsletter unsubscribe <token>
```

Category keys map to the web newsletter preferences: updates and announcements, tips and tricks, and daily inspirations.

## Blocked Settings Paths (Security)

The following operations are blocked in the CLI for security reasons and must be performed in the web app:

- Password updates (`/v1/settings/update-password`; `openmates signup` is the guided CLI password setup path)
- Raw two-factor setup paths (`/v1/auth/2fa/setup/*`; guided CLI setup calls these internally for initial/missing setup only)
- API key creation (`/v1/settings/api-keys` POST is blocked; listing and deletion are allowed)
- Raw account deletion finalization (`/v1/settings/delete-account`; guided CLI deletion sends `require_email_verification: true`)
- Raw sensitive action verification endpoints (`/v1/settings/request-action-verification`, `/v1/settings/verify-action-code`)

These paths are enforced by `BLOCKED_SETTINGS_MUTATE_PATHS` in the client. Additionally, passkey management and device session management are exposed only as informational commands that point to the web app. Recovery-key creation is supported during guided signup/setup; regeneration remains web-only.

## Memories

Memories are managed as a sub-command of settings. See [apps-and-skills.md](./apps-and-skills.md) for the full memories reference (`openmates settings memories ...`).

## Key Files

- See [cli.ts](../../../frontend/packages/openmates-cli/src/cli.ts) for `handleSettings()` and predefined settings command handlers
- See [client.ts](../../../frontend/packages/openmates-cli/src/client.ts) for `settingsGet()`, `settingsPost()`, `settingsPatch()`, `settingsDelete()`, and `BLOCKED_SETTINGS_MUTATE_PATHS`
- See [ws.ts](../../../frontend/packages/openmates-cli/src/ws.ts) for notification settings WebSocket transport

## Related Docs

- [README](./README.md) -- CLI overview
- [Authentication](./authentication.md) -- session required for all settings commands
- [Apps & Skills](./apps-and-skills.md) -- memories CRUD reference
- [CLI Standards](../../contributing/standards/cli.md) -- Rule 9 on blocked settings paths as a security boundary
