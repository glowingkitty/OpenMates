---
status: active
last_verified: 2026-06-04
key_files:
  - frontend/packages/openmates-cli/src/cli.ts
  - frontend/packages/openmates-cli/src/client.ts
  - frontend/packages/openmates-cli/src/mentions.ts
  - frontend/packages/openmates-cli/src/fileEmbed.ts
  - frontend/packages/ui/src/components/settings/settingsRoutes.ts
  - backend/core/api/app/routes/settings.py
---

# CLI Feature Parity

The OpenMates CLI should let users do nearly everything from the web app that is safe and useful in a terminal. The CLI is not a second-class API client: it mirrors the browser's zero-knowledge crypto, chat sync, mentions, embeds, memories, and app-skill execution so terminal users can work with the same encrypted account data.

The main exceptions are browser-bound or high-risk account operations: passkeys, password setup or changes, two-factor authentication setup, recovery keys, active session approval/management, payment checkout, and account deletion. Those remain web-app-only because they require stronger human verification, browser platform APIs, or payment-provider UI.

## Parity Levels

| Level | Meaning |
| --- | --- |
| Full | First-class CLI command exists and mirrors the web flow. |
| Partial | CLI can perform part of the workflow, or only via raw `settings get/post/patch/delete`. |
| Missing | Web app supports it, but CLI has no practical path yet. |
| Web-only | Intentionally excluded from CLI for security, browser, or payment reasons. |

## Current Matrix

| Web app capability | CLI status | Notes |
| --- | --- | --- |
| Pair/login session | Full | `openmates login`, `logout`, `whoami`. CLI uses pair auth only and never asks for account credentials. |
| Chat list/search/open | Full | `chats list`, `search`, `open`. |
| New chat and continue chat | Full | `chats new`, `chats send`, streaming via WebSocket. |
| Follow-up suggestions | Full | `chats show` displays stored suggestions; `chats send --followup <n>` reuses them. |
| Incognito chat | Full | `chats incognito`; incognito transcripts are not stored, so history/clear commands only explain that no history exists. |
| Chat deletion | Full | `chats delete` with confirmation and `--yes`. |
| Chat export/download | Full | `chats download`, Markdown/YAML/code/transcript extraction, optional zip. |
| Chat sharing | Full | `chats share` with expiry and optional password. |
| App store browsing | Full for metadata | `apps list`, `apps <app-id>`, `apps skill-info`. Terminal output is metadata-oriented, not a visual store. |
| Skill execution | Full | `apps <app-id> <skill-id> <query>` or `--input '<json>'`. |
| Travel booking link | Full for terminal handoff | `apps travel booking-link --token ...`; browser still completes external booking. |
| Model, mate, skill, focus, memory mentions | Full | `@Best`, `@Sophia`, `@Web-Search`, focus modes, memory categories, and memory entries are resolved in `mentions.ts`. |
| Local file attachment mentions | Full | `@/path/to/file` supports text/code, images, PDFs, S3 upload, and sensitive-file handling. |
| Embed preview/fullscreen | Partial | `embeds show` renders decrypted content in terminal; visual parity is intentionally terminal-native. |
| Embed sharing | Full | `embeds share` with expiry/password. |
| Daily inspirations | Full | `inspirations` supports public and personalized responses. |
| New chat suggestions | Full | `newchatsuggestions`. |
| Memories and app settings entries | Full | `settings memories list/types/create/update/delete`. |
| User language, dark mode, font | Full | `settings interface language/dark-mode/font ...` predefined commands. |
| Username and timezone | Full | `settings account username set ...` and `settings account timezone set ...`. |
| Email change | Missing | Web has a multi-step verification flow. CLI has no safe guided flow. |
| Profile picture | Full | `settings account profile-picture set <jpg|png>` uploads validated JPEG/PNG files up to 300 KB; browser remains better for crop/preview. |
| Account export/import | Partial | CLI can fetch export manifest/data and import individual chat exports; no guided full-account export/import command. |
| Account storage overview | Full | `settings account storage overview/files/delete ...` wraps supported storage endpoints with confirmation for deletion. |
| Account chat stats and bulk deletion | Partial | `settings account chats stats`; old-chat bulk deletion still needs a safe CLI UX. |
| Account deletion preview | Full | `settings account delete preview`; final deletion remains web-only. |
| Account deletion | Web-only | Should be blocked in CLI client even though backend requires auth verification. |
| Passkeys | Web-only | Requires WebAuthn/browser APIs. |
| Password setup/change | Web-only | Blocked by `BLOCKED_SETTINGS_MUTATE_PATHS`. |
| 2FA setup/change | Web-only | Blocked for setup paths; disabling 2FA should also remain browser-only unless a full reauth model is designed. |
| Recovery key | Web-only | High-risk account recovery surface. |
| Active sessions and pair-session approval | Web-only | CLI is itself a paired/restricted session; approval and session controls stay in browser. |
| Billing overview | Full | `settings billing overview`. |
| Usage history/export | Full | `settings billing usage`, `usage summaries`, `usage daily`, and `usage export`. |
| Buy credits/payment checkout | Web-only | Payment-provider checkout must remain browser-bound. |
| Invoices | Full | `settings billing invoices list/download/credit-note/refund`; refund requires explicit `--email-encryption-key`. |
| Auto top-up | Partial | Low-balance command is implemented; monthly auto-topup remains web-only until policy is decided. |
| Gift card redeem/list | Full | `settings gift-card redeem/list`. |
| Gift card buy/manage | Web-only | Payment/purchase flow. |
| Hidden personal data/anonymization | Partial | Memories and raw settings can cover pieces, but no first-class guided CLI flow exists. |
| Auto-delete chats/files | Partial | Chat auto-delete command is implemented; file auto-delete route should be checked before exposing. |
| Share debug logs | Full | `settings privacy debug-logs share` prompts for consent unless `--confirm`/`--yes`. |
| Reminders | Full | `settings reminders list/update/delete`; deletion requires confirmation unless `--yes`. |
| Chat/backup notification preferences | Full | `settings notifications status`, `email set`, and `backup set` use the web app's WebSocket settings contract. |
| API key list/revoke | Full for safe actions | `settings developers api-keys list/revoke`. |
| API key create | Web-only | Secret shown once and developer-device approval should stay browser-first unless a separate secure CLI design is approved. |
| Developer devices | Web-only | Device approvals/revocations are sensitive. |
| Webhooks | Missing | Web route exists; backend/API surface needs audit before CLI exposure. |
| Support issue report | Full | `settings report-issue create/status`. |
| Support payments/tips | Web-only | Payment flow. |
| Newsletter | Full | `settings newsletter categories/set/subscribe/confirm/unsubscribe`. |
| Server admin settings | Web-only | Web server stats/tests/logs are admin-only; CLI has separate self-hosting `server` commands. |
| Self-hosted server management | Full | CLI-only feature: `server install/start/stop/restart/status/logs/update/reset/make-admin/uninstall`. |
| Docs browsing | Full | `docs list/search/get` covers docs access outside the web UI. |

## Required Security Boundary

The CLI no longer exposes raw `settings get/post/patch/delete` passthrough commands. User-facing settings operations must be predefined commands with help text, examples, validation, and an explicit web-only message when the operation is intentionally blocked. The SDK still has generic `settingsGet`, `settingsPost`, `settingsPatch`, and `settingsDelete` methods for internal command handlers, so `BLOCKED_SETTINGS_MUTATE_PATHS` remains a real security boundary.

The blocklist should include every path that must not be reachable through raw CLI settings commands, not only paths that have first-class CLI help text. At minimum, keep or add blocks for:

- API key creation: `/v1/settings/api-keys` for POST.
- Password setup and changes: `/v1/settings/update-password`, `/v1/auth/setup_password`.
- 2FA setup flows: `/v1/auth/2fa/setup/*`.
- Account deletion finalization: `/v1/settings/delete-account`.
- Sensitive action OTP bootstrap/verification when it only exists to authorize a web-only action: `/v1/settings/request-action-verification`, `/v1/settings/verify-action-code`.

Deletion preview can remain readable because it is informational and helps exports/offboarding, but final deletion must stay web-only unless a new CLI-specific reauthentication design is approved.

## Next Implementation Tasks

### P0: Tighten Web-Only Boundaries

Acceptance criteria:

- `openmates settings post delete-account ...` is blocked locally before any network request.
- Sensitive action verification endpoints used only for account deletion are blocked locally, or path/method-specific blocking prevents using them to complete web-only actions.
- CLI help and `docs/cli/settings.md` list account deletion and recovery/security operations as web-only.
- Unit tests cover the blocklist for POST, PATCH, and DELETE paths.

Primary files:

- `frontend/packages/openmates-cli/src/client.ts`
- `frontend/packages/openmates-cli/src/cli.ts`
- `docs/cli/settings.md`
- `frontend/packages/openmates-cli/tests/cli.test.ts`

### P1: Expand Safe Settings Convenience Commands

Acceptance criteria:

- Expand ergonomic commands for safe settings that are already supported by backend endpoints beyond the initial predefined command set.
- Commands validate inputs locally and print clear terminal output plus `--json`.
- Raw `settings post/patch/delete` remains unavailable in the public CLI.

Suggested command shape:

```bash
openmates settings interface language set en
openmates settings interface dark-mode set on
openmates settings interface font set lexend
openmates settings account timezone set Europe/Berlin
openmates settings privacy auto-delete-chats set 90d
openmates settings billing auto-topup low-balance set --enabled true --amount 1000 --currency eur --email you@example.com
```

Implemented examples include interface preferences, timezone, username, profile picture upload, storage files, reminders, invoices, notification preferences, mates metadata/consent, and newsletter preferences. Keep expanding only through predefined commands; do not reintroduce raw settings passthrough.

### P1: Add Storage File Management

Acceptance criteria:

- `openmates settings storage overview` wraps `GET /v1/settings/storage`.
- `openmates settings storage files [--category images|videos|...] [--json]` wraps `GET /v1/settings/storage/files`.
- `openmates settings storage delete <file-id>` wraps `DELETE /v1/settings/storage/files` with `scope=single` and a confirmation prompt.
- `openmates settings storage delete --category <name>` and `--all` wrap the backend's supported bulk deletion scopes.
- Download/view behavior is either implemented safely or explicitly documented as browser-only if auth-gated file URLs cannot be streamed from Node.

### P2: Add Privacy and Debug-Log Helpers

Acceptance criteria:

- Hidden personal data/anonymization entries are manageable without requiring users to know raw settings paths.
- Debug-log sharing has an explicit consent prompt and prints what will be shared before upload.
- Terminal output redacts known personal data consistently with `OutputRedactor`.

### P2: Improve Account Export/Import UX

Acceptance criteria:

- `openmates account export --output <dir> [--include-usage] [--include-invoices]` wraps manifest/data fetch and writes a structured export folder.
- `openmates account import chat <file>` validates local export format before calling import.
- CLI docs explain the difference between full account export and per-chat `chats download`.

### P2: Developer Webhooks Audit

Acceptance criteria:

- Audit backend support for developer webhooks before adding CLI commands.
- If safe, add `openmates settings developers webhooks list/create/delete/test` with URL validation and confirmation for deletion.
- If not safe yet, document webhooks as web-only until backend support is complete.

### P3: Email Change Design

Acceptance criteria:

- Decide whether email change belongs in CLI at all.
- If email change is allowed, design a CLI reauth/OTP flow that does not ask for primary credentials and does not weaken pair-auth guarantees.

## Related Docs

- [CLI Package](./cli-package.md) -- package architecture and implemented command surface.
- [CLI Remote Access](./cli-remote-access.md) -- planned connected-server features.
- [CLI Settings](../../cli/settings.md) -- user-facing settings command reference.
- [CLI Standards](../../contributing/standards/cli.md) -- implementation rules and security boundaries.
