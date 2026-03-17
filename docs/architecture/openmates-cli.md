# OpenMates npm CLI Architecture

## Purpose

`frontend/packages/openmates-cli` provides a lightweight npm package with both:

- a terminal CLI (`openmates`)
- a Node SDK (`OpenMatesClient`)

The package is intentionally scoped to account/session operations and app execution, not full admin/security management.

## Authentication Model

- Login is pair-auth only.
- The CLI never asks for account email/password.
- Pair flow endpoints:
  - `POST /v1/auth/pair/initiate`
  - `GET /v1/auth/pair/poll/{token}`
  - `POST /v1/auth/pair/complete/{token}`
  - `POST /v1/auth/login`

## Transport Model

- REST is used for auth/session/settings/apps routes.
- WebSocket is used for chat send/sync and memory entry storage routes.

## Security Guardrails

CLI settings writes are restricted in
`frontend/packages/openmates-cli/src/client.ts` via `BLOCKED_SETTINGS_POST_PATHS`.

Blocked operations:

- API key creation routes
- Password setup/update routes
- 2FA setup/provider routes

## Sync Points With Web Settings

When web settings security endpoints change, update both:

- `frontend/packages/openmates-cli/src/client.ts`
- `frontend/packages/ui/src/components/settings/developers/SettingsApiKeys.svelte`
- `frontend/packages/ui/src/components/settings/security/SettingsPassword.svelte`
- `frontend/packages/ui/src/components/settings/security/SettingsTwoFactorAuth.svelte`
