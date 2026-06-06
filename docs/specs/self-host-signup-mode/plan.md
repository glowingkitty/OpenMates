# Plan: Self-Host Signup Mode

Spec: `docs/specs/self-host-signup-mode/spec.md`

## Existing Patterns

- `frontend/packages/openmates-cli/src/server.ts` — server install/start/make-admin command flow and non-login server operations.
- `setup.sh` — creates `.env`, generated secrets, and install-time operator messaging.
- `backend/core/directus/setup/setup_schemas.py` — first-run schema setup and invite-code insertion.
- `backend/core/api/app/utils/invite_code.py` — shared signup requirement and invite validation logic.
- `backend/core/api/app/routes/auth_routes/auth_password.py` — password account creation and invite consumption.
- `backend/core/api/app/routes/auth_routes/auth_passkey.py` — passkey account creation and invite consumption.
- `backend/core/api/app/routes/auth_routes/auth_session.py` — frontend-facing `require_invite_code` state.
- `.github/workflows/selfhost-smoke.yml` and `frontend/apps/web_app/tests/selfhost-smoke.spec.ts` — self-host install/start/browser smoke coverage.

## Architecture

Self-host signup mode is environment-driven and read by the backend. The setup script run by the CLI installer writes the selected mode into `.env`; `cms-setup` creates the first normal invite code when invite mode is enabled; API routes use one shared helper to decide invite/domain requirements.

No new public API route is needed for this slice. Admin promotion remains the existing local CLI command `openmates server make-admin <email>`, which shells into the `api` container and runs `backend/scripts/create_admin.py`.

## Data Flow

1. Operator runs `openmates server install`.
2. `setup.sh`, run by the CLI install command, asks for signup mode when interactive; defaults to `invite_only` in non-interactive/CI.
3. Installer writes `.env` values such as:
   - `SELF_HOST_SIGNUP_MODE=invite_only`
   - `SELF_HOST_SIGNUP_ALLOWED_DOMAINS=`
   - `SELF_HOST_FIRST_INVITE_CODE=1234-5678-9012`
4. First `cms-setup` run creates `invite_codes` and inserts `1234-5678-9012` with `remaining_uses=1` and `is_admin=false`.
5. `/v1/auth/session` tells frontend whether invite code is required based on `SELF_HOST_SIGNUP_MODE`.
6. Signup endpoints validate invite/domain requirements using `get_signup_requirements()`.
7. Account creation ignores invite `is_admin` metadata and creates a normal user.
8. Operator runs `openmates server make-admin <email>` after signup to grant admin privileges.

## Affected Files

- `setup.sh` — prompt for signup mode, ensure `.env` has default self-host signup mode, and print the generated first invite code.
- `backend/core/directus/setup/setup_schemas.py` — insert first normal invite code from env and update log messages.
- `backend/core/api/app/utils/invite_code.py` — implement explicit self-host signup modes.
- `backend/core/api/app/routes/auth_routes/auth_session.py` — use shared signup requirement helper.
- `backend/core/api/app/routes/auth_routes/auth_password.py` — stop granting admin from invite code.
- `backend/core/api/app/routes/auth_routes/auth_passkey.py` — stop granting admin from invite code.
- `frontend/apps/web_app/tests/selfhost-smoke.spec.ts` — extend self-host assertions where feasible.
- `.github/workflows/selfhost-smoke.yml` — install public npm CLI for real-user smoke, then current branch package for unreleased behavior.
- `docs/self-hosting/setup.md`, `docs/cli/server-management.md` — document signup modes and admin promotion.

## Contracts

API:
- `get_signup_requirements()` returns invite/domain requirements for all signup endpoints.
- `/session.require_invite_code` matches `get_signup_requirements()`.

Data:
- New `.env` config is optional with safe defaults:
  - missing mode => `invite_only` for self-host
  - missing domains => no domain restriction
  - missing first invite => `cms-setup` generates a fallback invite

UI:
- Existing signup UI continues to key off `require_invite_code`.
- No new web UI in the first slice.

Security/privacy:
- Self-host public open signup is not introduced.
- Invite codes no longer create admins.
- Admin grants require local server CLI/container access.

## Rollout

Existing installs with old `invite_codes.is_admin=true` records will no longer grant admin during signup once routes are updated. This is safer and matches the target model. No database migration is required for the first slice.

## Verification Strategy

- YAML/env/script checks:
  - `bash -n setup.sh`
  - `python3 -m py_compile backend/core/directus/setup/setup_schemas.py backend/core/api/app/utils/invite_code.py backend/core/api/app/routes/auth_routes/auth_session.py backend/core/api/app/routes/auth_routes/auth_password.py backend/core/api/app/routes/auth_routes/auth_passkey.py`
  - YAML parse for `.github/workflows/selfhost-smoke.yml`
- Backend unit tests for `get_signup_requirements()` self-host modes.
- GitHub Actions self-host smoke workflow for install/start/browser/backend verification.
- Public npm check in workflow: install `openmates` from npm and run `openmates server --help`; then replace with current-branch package for unreleased install behavior.

## Open Questions

- Full browser signup in self-host smoke may need a test email-code shortcut. If the current no-secret self-host stack cannot retrieve a verification code deterministically, the first implementation should verify signup mode/admin behavior through backend/unit and CLI smoke, then add browser signup once test email plumbing is available.
