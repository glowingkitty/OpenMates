# Self-Host Signup Mode

## Goal
Make self-host signup safe and easy for individuals and teams. During install,
the operator chooses whether signups use invite codes, an email-domain
allowlist, or both. Self-host setup creates the first normal invite code when
the selected mode requires invites, and admin access is granted only with
`openmates server make-admin <email>` after signup.

## Scope

In:
- Add self-host signup mode configuration during `openmates server install`.
- Support `invite_only`, `domain_allowlist`, and `invite_and_domain` modes.
- Generate and show one first signup invite code when the selected mode includes invites.
- Ensure first signup invite codes do not grant admin privileges.
- Keep `openmates server make-admin <email>` as the admin promotion flow.
- Update backend signup requirement logic and frontend-facing session state.
- Extend self-host smoke coverage for public npm install and self-host signup behavior.

Out:
- Public open signup for self-hosted instances.
- User-count caps for self-hosted instances.
- New web admin invite-management UI.
- Publishing the next npm package version.

## Scenarios

### S-1: Individual installs with invite codes only
Given a person runs `openmates server install`
When they accept the default signup mode
Then the install config is `invite_only`
And one normal first signup invite code is generated
And the CLI output shows the invite code and the `make-admin` next step
And signup requires the invite code.

### S-2: Team installs with email-domain allowlist
Given an operator runs `openmates server install`
When they choose email-domain allowlist and enter `example.org`
Then the install config is `domain_allowlist`
And signup requires an email address from `example.org`
And signup does not require an invite code.

### S-3: Team installs with invite plus domain restriction
Given an operator runs `openmates server install`
When they choose invite code plus email-domain allowlist and enter `example.org`
Then signup requires both a valid invite code and an email address from `example.org`.

### S-4: First signup does not become admin automatically
Given a self-host instance has a first signup invite code
When a user signs up with that invite code
Then the user is created as a normal non-admin user
And the invite code is consumed according to its remaining uses
And running `openmates server make-admin <email>` grants admin privileges.

### S-5: Real-user CLI install path is checked
Given a clean GitHub Actions runner
When the self-host smoke workflow installs `openmates` from public npm
Then the published CLI command is available and can print help
And the workflow still tests the current branch CLI for new install behavior until the package is published.

## Acceptance Criteria

- [ ] AC-1: Non-interactive `openmates server install` defaults to `invite_only`.
- [ ] AC-2: Interactive install uses individual/team wording only.
- [ ] AC-3: Modes that include invites generate and persist one first signup invite code.
- [ ] AC-4: The first signup invite code is stored with `is_admin=false`.
- [ ] AC-5: Self-host signup requirement logic uses explicit signup mode, not implicit domain-restriction bypasses.
- [ ] AC-6: `/v1/auth/session` returns `require_invite_code` consistent with the selected self-host mode.
- [ ] AC-7: Password and passkey signup do not grant admin from invite-code metadata.
- [ ] AC-8: `openmates server make-admin <email>` remains the only admin-promotion path in this slice.
- [ ] AC-9: Self-host smoke verifies public npm CLI availability and current-branch self-host install/start/signup behavior.
- [ ] AC-10: Docs explain invite-code/domain signup modes and the post-signup `make-admin` step.

## Contracts

API:
- `/v1/auth/session` includes `require_invite_code` based on `SELF_HOST_SIGNUP_MODE` for self-hosted instances.
- Signup endpoints reject missing invite codes when mode is `invite_only` or `invite_and_domain`.
- Signup endpoints reject disallowed email domains when mode is `domain_allowlist` or `invite_and_domain`.

Data:
- Add env-driven config:
  - `SELF_HOST_SIGNUP_MODE=invite_only|domain_allowlist|invite_and_domain`
  - `SELF_HOST_SIGNUP_ALLOWED_DOMAINS=<comma-separated domains>`
  - `SELF_HOST_FIRST_INVITE_CODE=<generated code>` when invite mode is enabled
- Existing `invite_codes.is_admin` remains in schema for compatibility but is ignored for new user admin grants.

UI states:
- Signup should show invite-code entry when `/session` reports `require_invite_code=true`.
- Domain allowlist errors continue to surface through existing signup error handling.

Privacy/security:
- No public open signup is introduced for self-hosted instances.
- Admin promotion requires local CLI/server access and a signed-up email address.
- Invite codes remain one-use by default.

## Test Matrix

| Scenario | Test Type | File | Status |
| --- | --- | --- | --- |
| S-1 | CLI unit | `frontend/packages/openmates-cli/tests/server.test.ts` | planned |
| S-2 | Backend unit | `backend/tests/test_self_host_signup_requirements.py` | planned |
| S-3 | Backend unit | `backend/tests/test_self_host_signup_requirements.py` | planned |
| S-4 | GitHub Actions Playwright smoke | `frontend/apps/web_app/tests/selfhost-smoke.spec.ts` | planned |
| S-5 | GitHub Actions workflow | `.github/workflows/selfhost-smoke.yml` | planned |

## Implementation Notes

Existing patterns to reuse:
- `frontend/packages/openmates-cli/src/server.ts` for install/start output and `make-admin`.
- `setup.sh` for generated `.env` defaults.
- `backend/core/directus/setup/setup_schemas.py` for first invite creation.
- `backend/core/api/app/utils/invite_code.py` for shared signup requirements.
- `backend/core/api/app/routes/auth_routes/auth_password.py` and `auth_passkey.py` for account creation.
- `frontend/apps/web_app/tests/selfhost-smoke.spec.ts` for self-host browser verification.

Likely files touched:
- `frontend/packages/openmates-cli/src/server.ts` — interactive install mode prompt and output.
- `setup.sh` — write default non-interactive signup mode and first invite env.
- `backend/core/directus/setup/setup_schemas.py` — first normal invite code creation.
- `backend/core/api/app/utils/invite_code.py` — explicit self-host mode logic.
- `backend/core/api/app/routes/auth_routes/auth_session.py` — shared `require_invite_code` result.
- `backend/core/api/app/routes/auth_routes/auth_password.py` — remove invite-admin promotion.
- `backend/core/api/app/routes/auth_routes/auth_passkey.py` — remove invite-admin promotion.
- `.github/workflows/selfhost-smoke.yml` — public npm install check and current-branch install test.
- `frontend/apps/web_app/tests/selfhost-smoke.spec.ts` — signup/admin assertions if feasible without paid provider keys.
- `docs/self-hosting/setup.md`, `docs/cli/server-management.md` — operator docs.

Risks:
- Public npm cannot test unreleased CLI changes; workflow must separate published CLI availability from current-branch behavior.
- Full signup E2E may require email-code access in the self-host stack; if not available, add a backend/API-level smoke assertion for invite/admin behavior first.
- Existing invite codes with `is_admin=true` may remain in old installs; new account creation should ignore this flag to prevent admin grants.

## Open Questions

- None for the first implementation slice.
