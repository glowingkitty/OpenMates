# Tasks: Self-Host Signup Mode

Spec: `docs/specs/self-host-signup-mode/spec.md`
Plan: `docs/specs/self-host-signup-mode/plan.md`

- [ ] T-1: Add explicit self-host signup mode config and first normal invite generation.
  Covers: S-1, S-2, S-3, AC-1, AC-2, AC-3, AC-4
  Areas: `setup.sh`, `backend/core/directus/setup/setup_schemas.py`
  Verify: `bash -n setup.sh`; `python3 -m py_compile backend/core/directus/setup/setup_schemas.py`; CLI unit/helper tests if helpers are extracted
  Independently deployable: yes

- [ ] T-2: Make backend signup requirements use explicit self-host modes.
  Covers: S-1, S-2, S-3, AC-5, AC-6
  Areas: `backend/core/api/app/utils/invite_code.py`, `backend/core/api/app/routes/auth_routes/auth_session.py`, backend unit tests
  Verify: targeted pytest for self-host signup requirement cases
  Independently deployable: yes, after T-1 defaults exist

- [ ] T-3: Remove invite-code admin promotion from account creation.
  Covers: S-4, AC-7, AC-8
  Areas: `backend/core/api/app/routes/auth_routes/auth_password.py`, `backend/core/api/app/routes/auth_routes/auth_passkey.py`, backend tests
  Verify: targeted backend tests for password/passkey account creation admin behavior where feasible
  Independently deployable: yes

- [ ] T-4: Extend self-host smoke for public npm availability and current-branch signup-mode behavior.
  Covers: S-4, S-5, AC-9
  Areas: `.github/workflows/selfhost-smoke.yml`, `frontend/apps/web_app/tests/selfhost-smoke.spec.ts`
  Verify: push-triggered `Self-Hosted: Install Smoke` GitHub Actions workflow
  Independently deployable: yes

- [ ] T-5: Update docs and verify spec.
  Covers: AC-10
  Areas: `docs/self-hosting/setup.md`, `docs/cli/server-management.md`, `docs/specs/self-host-signup-mode/*`
  Verify: `git diff --check`; `verify-spec docs/specs/self-host-signup-mode/spec.md`
  Independently deployable: yes
