---
name: update-prod-server
description: Monitor a production release, verify frontend/backend compatibility, update prod via OpenMates CLI over prod SSH, then verify frontend promotion.
user-invocable: true
argument-hint: "<pr-url-or-number>"
---

# Skill: update-prod-server

## Purpose

Use this when a pull request has been accepted into `main` and production should
be updated from published GHCR images with frontend/backend compatibility checked
before a dependent frontend becomes live.

This skill is intentionally production-scoped. It verifies the release gates
first, opens the prod SSH master only after the user opens the temporary access
window and provides a fresh TOTP, then mutates production only through
`openmates server ...` commands.

## Required Inputs

- PR URL or number, for example `https://github.com/glowingkitty/OpenMates/pull/506`.
- The owner's go-ahead for this production update. The owner merging the PR
  into `main` IS that go-ahead (owner, 23 Nov): after the merge, deploy and
  verify without asking again. Otherwise: typed in this chat, or a
  dev-connector message verified with `python3 scripts/owner_message.py verify
  <receipt>` (VERIFIED for this chat, same text). A verified message is the
  owner's direct approval; never ask for it to be typed again. Messages from
  other agent chats are not approval. The owner merges the PR on GitHub; never
  merge it yourself.
- An open production SSH connection from the dev server (reuse it, see step 4).
  Only when none exists: user confirmation that prod-side temporary SSH access
  is open and a fresh 6-digit TOTP code, supplied immediately before
  `prod-ssh.sh open`.

## Urgent Production Outage

Owner standing rule (2026-11-14): for an urgent production outage (for example
no AI chat replies), apply the necessary hotfix directly on production yourself,
then commit the permanent fix to dev. The owner's go-ahead for the outage
covers the hotfix; it does not cover unrelated changes.

- Diagnose read-only first (Admin Debug API logs, `openmates server status`,
  read-only `docker` inspection); prefer `openmates server restart` before
  patching.
- A hotfix patched into running containers keeps a `.pre-hotfix-<date>` backup,
  is idempotent, and is recorded verbatim in the Task and the dev deploy
  message. It lives only in the container layer: the next recreate or
  `openmates server update` drops it, so the permanent fix must reach `main`
  before the next production update.
- Prove recovery with a real chat that gets an assistant reply (signed out and,
  where an account is available, signed in), not only health checks.
- Example: TASK-832 (2026-11-14), Celery pool children killed by the 4 s
  `worker_proc_alive_timeout`; hotfix raised it in the three worker containers.

## Workflow

### 1. Start Or Reuse A Session

If this is a mutating top-level chat and no session exists, start one:

```bash
python3 scripts/sessions.py start --mode feature --task "update production server from merged PR"
```

Keep the printed session ID for summaries. Do not create a second worktree for
the same Claude conversation.

### 2. Resolve The Production Subject

Use GitHub to identify the merge commit and the image workflow run:

```bash
gh pr view <PR> --repo glowingkitty/OpenMates --json number,state,mergedAt,mergeCommit,headRefOid,baseRefName,title,url
gh run list --repo glowingkitty/OpenMates --branch main --limit 10 --json databaseId,name,status,conclusion,headSha,displayTitle,event,createdAt,updatedAt,url
```

Stop if the PR is not merged into `main` or if no `Publish Self-Host Images` run
exists for the merge commit SHA.

### 3. Check Compatibility And Release Gates

Before merging or promoting a release that adds frontend calls to new API
routes, request/response contracts, or migrated schema, identify the required
capabilities from the reviewed diff. Build the frontend without assigning the
production alias through the configured staged Vercel workflow, then deploy the
backwards-compatible backend and required setup first. Keep the previous
compatible frontend serving until readiness is verified. A Ready deployment,
health endpoint, image tag, or successful build does not prove these dependencies
exist in the running production API.

If this skill starts after merge, inspect the alias immediately. If a dependent
frontend is already live against an incompatible API, report the release as
failed and restore the last compatible frontend through the authorized Vercel
promotion/rollback workflow while preparing the backend update. Do not weaken
authentication checks or silently fall back to older password authentication to
mask a missing endpoint. If staging/alias control is unavailable, block frontend
promotion and resolve release coordination before merging; this skill alone
cannot prevent Vercel's automatic alias assignment.

For example, a frontend requiring password challenge discovery must pass this
read-only registration check after the backend update and before frontend
promotion. Authentication routes are deliberately excluded from OpenAPI, so
collect a paths-only snapshot through authorized read-only SSH by inspecting
`app.routes` of the installed application in the running API container. Include
hidden routes, path and methods only; do not print configuration or credentials.
Record snapshot time and running image identity alongside the check. This
inspects the installed route table; the live flow check below must still prove
that the serving process and proxy expose it correctly:

Run this read-only Python payload inside the running API container through
`docker exec -i api python -` over the approved SSH connection; save its stdout
privately as `<LIVE_ROUTES_JSON>`. Import output is redirected to stderr to keep
the JSON inventory parseable. Creating the application here inspects installed
route registration without running its lifespan/startup or mutating data:

```python
import contextlib
import json
import sys

with contextlib.redirect_stdout(sys.stderr):
    from backend.core.api.main import create_app
    from fastapi.routing import APIRoute
    app = create_app()

paths = {}
for route in app.routes:
    if isinstance(route, APIRoute):
        methods = paths.setdefault(route.path, {})
        methods.update({method.lower(): {} for method in route.methods})
print(json.dumps({"paths": paths}))
```

```bash
python3 scripts/verify_release_api_routes.py --schema-file <LIVE_ROUTES_JSON> --require POST /v1/auth/password-v2/challenge
```

The snapshot format is `{"paths":{"/v1/auth/password-v2/challenge":{"post":{}}}}`.
For routes included in public OpenAPI, use `--api-url https://api.openmates.org`
instead. Do not expose hidden schemas or substitute a source checkout/candidate
schema for inspection of the installed runtime.

Add `--require METHOD /path` for every new required route. The helper fails
closed on unavailable/invalid OpenAPI or a missing method/path. It proves route
registration only, not database migration success, response semantics, password
sign-in, session authority, or encrypted sync. Verify the affected flow with the
staged frontend against production using an authorized disposable account or
the operator's own confirmation, and require applicable setup/schema evidence
before assigning the alias. If live schema evidence is unavailable, require
equivalent read-only registration evidence; do not waive behavior verification.

Poll the image build with GitHub's built-in watcher:

```bash
gh run watch <RUN_ID> --repo glowingkitty/OpenMates --interval 30 --exit-status
```

For Vercel, avoid running `vercel ls --yes` from a session worktree without
project metadata because it can auto-link/create a throwaway project. Prefer the
known production project name:

```bash
vercel ls open-mates-webapp --meta githubCommitSha=<MERGE_SHA>
vercel inspect <deployment-url>
```

Require all of these before updating the backend:

- `Publish Self-Host Images` for the merge SHA is completed with conclusion `success`.
- The intended frontend deployment for `open-mates-webapp` has `status Ready`, or the release is backend-only. A production alias is not a prerequisite for the backend update.
- The deployment metadata matches the merge SHA when available.
- For new frontend dependencies, the previous compatible frontend remains on `https://app.openmates.org` until the backend/setup and affected flow checks above pass.

Every production web app release, including a frontend-only hotfix, must keep
automatic production domain assignment disabled and use the browser gate in
[production-webapp-gate.md](../../../docs/contributing/guides/production-webapp-gate.md).
Build with production settings and `--skip-domain`. After compatibility checks,
run `python3 scripts/promote_production_webapp.py --deployment <id> --expected-version <version> --out <private-evidence-dir>`.
The helper checks the exact candidate and the live `https://app.openmates.org`
in fresh laptop/phone browsers, requires rendered and interactive login controls,
and fails on console errors or unhandled exceptions. Failed candidate checks
block promotion; failed live checks restore the previous alias. Retain and
review its receipt, screenshots and recordings. Vercel Ready or HTTP 200 alone
cannot complete the release. Repeat the affected flow on the alias as well.
Backend-first compatibility
must include support for the frontend still serving during the update; a
breaking contract needs an explicitly coordinated release plan.

### 4. Reuse An Open Prod SSH Connection, Else Open One After Gates Pass

Owner rule (2026-11-23): always reuse an open production connection first;
ask for a TOTP code only when none exists. The owner often opens the master
from the dev server before a release, so check it before asking anything:

```bash
./scripts/prod-ssh.sh status
./scripts/prod-ssh.sh "id -un"
```

If `status` reports the master ACTIVE and the test command answers, use that
connection for every later step; do not ask for a TOTP code or for the
prod-side window. If `status` finds no master, also look for another open
connection before asking: a socket in `~/.ssh/prod-ssh-sockets/`, an outgoing
`ssh` process or a tmux session that reaches the prod host. Only when none
exists, send ONE question asking for the code and say why the existing one
could not be used (for example "the morning connection closed at 09:58").

When no connection is open, ask the user to open the prod-side window with
the dev public key from the configured prod SSH key:

```bash
set -euo pipefail; set +u; set -a; source .env; set +a; set -u; key="${PROD_SSH_KEY/#\~/$HOME}"; if [ -f "${key}.pub" ]; then printf '%s\n' "$(<"${key}.pub")"; else ssh-keygen -y -f "$key"; fi
```

Tell the user to run this on prod, replacing `<DEV_PUBKEY>` with the printed key:

```bash
./scripts/temp-ssh-access.sh start "<DEV_PUBKEY>" --minutes 30
```

After the user says SSH is open, ask for the TOTP code. Run the open command
immediately after the code is provided:

```bash
printf '%s\n' '<TOTP>' | ./scripts/prod-ssh.sh open
```

Never store or log the TOTP. Do not retry stale codes.

### 5. Inspect Prod Before Updating

Check the installed production CLI version before every server update. Resolve
the expected stable CLI version from the merged commit's
`shared/config/product_version.json` (`cli.stableBase`) and confirm its `Publish CLI` run
completed successfully. Upgrade the production CLI to that published version
before generating or applying the update plan:

```bash
./scripts/prod-ssh.sh "openmates --version"
./scripts/prod-ssh.sh "sudo -n /usr/bin/openmates upgrade --version <RELEASE_CLI_VERSION> --channel stable"
./scripts/prod-ssh.sh "openmates --version"
```

Run core lifecycle commands as the server installer user that owns the private `.openmates` directory. Use sudo for the system-wide CLI upgrade, not for core start/update; the runtime ownership guard intentionally rejects a different user. Root-run verification must preserve the installer ownership of generated private health state. The upload VM may use root when its installation is root-owned.

Recheck the version after upgrading. Keep the runtime template tied to the
reviewed merge SHA as well: an older CLI can pull new images while silently
writing its older bundled Compose template. Use the supported immutable template
override for both the dry-run and the actual update. Pin the images to the same
merge SHA so a moving channel cannot advance between build verification and
deployment:

Check host-owned notification configuration on each affected VM without printing
credentials or recipients. A Vault-backed API email service and a delivered
Alertmanager Discord alert do not prove the CLI host notifier or upload VM can
send its required completion email. Treat `IMPORTED_TO_VAULT` as a marker, not a
host credential. Brevo access must be authorized for that VM's IPv4 egress
address (the CLI email adapter uses IPv4); do not disable provider IP security.
Repair secret values only with the user's specific authorization through
`openmates server env set`, entering values through its hidden prompt. For a
legacy generic cloud Discord URL, explicitly bind it to the host environment
using `OPENMATES_RUNTIME_HEALTH_LEGACY_DISCORD_ENVIRONMENT`; never infer a
production destination from an unscoped URL.

```bash
./scripts/prod-ssh.sh "env OPENMATES_SELFHOST_COMPOSE_URL=https://raw.githubusercontent.com/glowingkitty/OpenMates/<MERGE_SHA>/frontend/packages/openmates-cli/templates/core/docker-compose.selfhost.yml /usr/bin/openmates server update --path /home/superdev/openmates --exclude webapp --image-tag sha-<MERGE_SHA> --dry-run"
```

Do not treat an image revision or CLI upgrade alone as proof that the effective
runtime configuration matches the release. During verification, inspect only the
two non-secret CMS cache settings and require `CACHE_SKIP_ALLOWED=true` and
`CACHE_AUTO_PURGE=true` in the running container. Missing settings can hide a
new session-security or workflow record behind a cached empty lookup until the
CMS cache expires, even while health endpoints return 200. Apply configuration
through the CLI update/recreate path; a graceful restart does not apply new
container environment values.

Before the first notification-migration rollout, require the released CLI that
implements the core setup gate. An already-running older CLI or admin sidecar
cannot provide the new ordering. Do not bootstrap this release through the old
sidecar's update endpoint.

Use only OpenMates CLI commands for runtime state changes:

```bash
./scripts/prod-ssh.sh "openmates server status --path /home/superdev/openmates --json"
./scripts/prod-ssh.sh "openmates server update --path /home/superdev/openmates --exclude webapp --dry-run"
```

Also read the JSON dry-run. Require `coreSetupGate.required == true`,
`coreSetupGate.setupService == "cms-setup"`,
`coreSetupGate.failurePolicy == "keep-email-consumers-stopped"`, and
`coreSetupGate.stopServices` containing `api`, `task-worker`, and
`task-scheduler`. Missing capability is a pre-update blocker: upgrade the CLI
and repeat the dry-run, without mutating containers through the older updater.

Review the dry-run for:

- Mode is `image` unless the server is intentionally source-mode.
- Target tag/channel is correct, usually `main` for official-cloud prod.
- Services exclude `webapp`, because production web is served by Vercel.
- Backup is planned.
- Env preflight and Vault secret checks are understood.
- Core setup runs automatically after stopping the old API and email consumers;
  setup failure leaves them stopped. No manual notification SQL is required.

If the dry-run reports missing provider secrets that are known non-core optional
provider entries, rerun with `--yes` only after stating why. Do not edit prod
secrets unless the user explicitly asks.

### 6. Update Prod

First tell the AI test users that production is updating, so no production run
starts or overlaps the update (`scripts/ai_test_users_deploy_guard.py`; runs
also wait 45 minutes after the API start):

```bash
python3 scripts/ai_test_users_deploy_guard.py begin --reason "release <PR or MERGE_SHA>"
```

Run the backend-only update:

```bash
./scripts/prod-ssh.sh "env OPENMATES_SELFHOST_COMPOSE_URL=https://raw.githubusercontent.com/glowingkitty/OpenMates/<MERGE_SHA>/frontend/packages/openmates-cli/templates/core/docker-compose.selfhost.yml /usr/bin/openmates server update --path /home/superdev/openmates --exclude webapp --image-tag sha-<MERGE_SHA> --yes"
```

For a scoped core hotfix with unchanged schema/migration code, avoid rerunning setup while replacing the API. First update only `cms-setup` to the exact target SHA through the CLI with the API and email consumers quiesced until setup succeeds, then wait for that container to exit successfully. This stage still creates the normal pre-update backup:

```bash
./scripts/prod-ssh.sh "env OPENMATES_SELFHOST_COMPOSE_URL=https://raw.githubusercontent.com/glowingkitty/OpenMates/<MERGE_SHA>/frontend/packages/openmates-cli/templates/core/docker-compose.selfhost.yml /usr/bin/openmates server update --path /home/superdev/openmates --services cms-setup --image-tag sha-<MERGE_SHA> --yes"
./scripts/prod-ssh.sh "docker wait cms-setup"
```

Require exit code 0, then use the CLI's guarded reuse path with an explicit list of the affected API/worker/Prometheus services. The flag requires a full immutable SHA, checks that setup completed using that exact image, and checks running healthy infrastructure both before changes and immediately before container replacement:

```bash
./scripts/prod-ssh.sh "env OPENMATES_SELFHOST_COMPOSE_URL=https://raw.githubusercontent.com/glowingkitty/OpenMates/<MERGE_SHA>/frontend/packages/openmates-cli/templates/core/docker-compose.selfhost.yml /usr/bin/openmates server update --path /home/superdev/openmates --services <AFFECTED_SERVICES> --image-tag sha-<MERGE_SHA> --reuse-completed-setup --yes"
```

Do not treat a setup-stage CLI health/reporting failure as proof that setup succeeded. Inspect the failed checks and the setup exit status before continuing. Ordinary updates and releases with migration changes keep their normal setup path; do not bypass migration requirements.

If the update fails during setup or health checks:

- Collect `openmates server logs --container <service> --tail 200`.
- Collect `openmates server status --path /home/superdev/openmates`.
- Prefer CLI rollback before raw Docker or Compose:

```bash
./scripts/prod-ssh.sh "openmates server update --path /home/superdev/openmates --exclude webapp --image-tag <LAST_HEALTHY_TAG> --yes"
```

Use raw `docker` only for read-only diagnostics. Do not use raw `docker compose`
for OpenMates runtime mutations unless the CLI lacks an equivalent and the user
approves the fallback.

### 7. Verify And Close

Run status and verify after update. Give warm-up time if containers are still
starting:

```bash
./scripts/prod-ssh.sh "openmates server status --path /home/superdev/openmates"
./scripts/prod-ssh.sh "openmates server verify --path /home/superdev/openmates --json"
```

Treat container health and `http.role_health` as the primary rollback/update
health signal. `notifications.destination_configured` must pass: without it the
runtime monitor detects outages but cannot alert anyone (it failed from
2026-08-11 to 2026-11-14, so the 2026-11-13 outage paged nobody). Report any remaining verifier failures as configuration or
runtime-contract gaps, not as a successful full verification.

Require `core.cms_cache_consistency` when the installed CLI provides that check;
otherwise inspect the two effective cache flags without printing other container
environment values. Before declaring a production rollout usable, verify a
signed-in first-party session check and WebSocket phased sync as well as guest
chat. Use an authorized disposable account or the operator's own browser
confirmation; never borrow another user's credentials or clear their local keys
or IndexedDB. A guest response and healthy public API do not prove authenticated
session authority or encrypted chat sync works. Preserve and report any prepared
workflow request stranded by a failed final save; configuration repair alone
does not requeue a row still marked `running`.

Include configured satellite services in release verification. In particular,
require `https://upload.openmates.org/health` and the upload preflight with
`Origin: https://openmates.org` to succeed before treating chat recording as
usable. Realtime transcription alone does not prove its recording upload works.
When a release changes the upload runtime, update its separate VM through the
CLI as well, upgrading that VM's CLI first and pinning its image tag and
`frontend/packages/openmates-cli/templates/upload/docker-compose.yml` override
to the same reviewed merge SHA. Include `vault-setup` and `app-uploads` together
when migrating token volumes: setup must populate the scoped periodic token
before the app starts. A failed upload image must be restored through the CLI
to a verified working image while its packaging defect is repaired.

The official upload host has separate production/dev Origin handlers. Select
`--caddy-profile official-upload` explicitly for its first CLI adoption, in both
the dry run and actual update; this is independent of the core-only cloud
Compose mode. Require both trusted Origin preflights and unknown-Origin denial
before accepting Caddy state. Preserve operator routes and credential-selection
headers. For a routing-only repair, keep the current immutable upload image and
select only a service with no upload-app dependencies (such as `admin-sidecar`)
so the healthy recording upload process remains available. A completion-email
failure leaves the update degraded even when routing and service health pass.

Chat recovery and early chat titles: on its first start at protocol epoch 0
the API activates recovery epoch 1 by itself once no legacy turn is running
(`chat_recovery_auto_cutover.py`; sends pause only for the activation itself).
After the signed-in chat check above, verify it with the update start time:

```bash
python3 scripts/verify_prod_early_title.py --since <UPDATE_START_RFC3339>
```

All four checks (`cutover_state`, `cutover_logged`, `recovery_enqueue`,
`early_title`) must pass. A failure means the chat header gets its title only
after post-processing: report it as a release defect; never lower the epoch.

After the server update succeeds, smoke-test the production web app as a guest
in a signed-out browser context with no prior account session. Keep the same
guest identity for all turns so the daily per-identity allowance is exercised:

1. Read `GET /v1/anonymous/free-usage/status` with that guest identity. Record
   `can_send_text`, `reason`, and `daily_remaining_percent` when exposed. Check
   the configured shared daily and per-identity daily caps through the
   authorized read-only admin budget status.
2. Create a new chat asking for doctor appointments. Wait for a completed
   assistant answer, then send a related follow-up in **that same chat** and
   confirm the answer uses the earlier request's context.
3. Create a **separate** new chat asking about upcoming AI events in Berlin.
   Wait for a completed assistant answer and confirm it has a distinct chat ID.
4. Read the guest status again after each turn. Confirm the guest can send while
   allowance remains and that the reported daily percentage does not increase
   within the same UTC day (integer rounding may hide a small charge). If a
   limit is reached, confirm the status and next attempted send are denied with
   the appropriate signup path. Do not consume extra production credits solely
   to force exhaustion; if no limit is reached, check the release's focused
   shared-daily and per-identity budget-enforcement test evidence and report
   that the live cap boundary was not observed.

Also dispatch the free-hourly prod smoke (`python3 scripts/prod_smoke_cron.py
free-hourly --force`). Its signed-out web send check
(`prod-smoke-guest-web-send.spec.ts`) opens a fresh browser, requires an
active Send (never a disabled Send or Sign up in its place), sends, and waits
for the reply. A failure there fails the update even when the API guest chat
works: guests on the web cannot chat.

Then send one signed-in chat with a production test account (the
authenticated production smoke when it exists) and wait for its completed
assistant answer. If no test account is available, say so in the summary: the
signed-in path is then unproven.

Treat missing or incomplete guest or signed-in answers, a broken follow-up, an
unexpectedly blocked guest, or inconsistent allowance reporting as failed
post-update verification. A missing reply fails the update: roll back or
hotfix right away (see Urgent Production Outage) instead of reporting success.
Green health checks never replace a real reply: on 2026-11-13 every AI worker
was crash-looping while `/v1/health` stayed green. Record the observed responses and status without guest IDs or
private chat contents in the completion summary.

### Final step: promote the production web app (only when healthy)

Owner decision (2026-11-18): the update flow ends by promoting the web app
itself, run from the dev server; no GitHub workflow, Vercel secret or extra
runner is involved. Run it only when **all** of these passed for this update:
`openmates server verify`, the guest chat checks, the free-hourly smoke and the
signed-in chat. If any failed or was unproven, do NOT promote: report the
previous web app as still live and stop.

1. Find the ready `open-mates-webapp` deployment of the same full merge SHA
   (`vercel ls open-mates-webapp --meta githubCommitSha=<FULL_MERGE_SHA>`); the
   expected version is that **full 40-character merge SHA**: the deployment's
   `_app/version.json` serves the commit SHA, not the `v0.31` product label
   (using the label fails the browser check with "Served version differs"). Skip the step for a backend-only release that
   built no web app deployment, and say so.
2. Run exactly this one command (script unchanged: browser check of the
   candidate, alias assignment, live check, rollback to the previous
   deployment on failure):

   ```bash
   python3 scripts/promote_production_webapp.py --deployment <DEPLOYMENT_HOST> --expected-version <FULL_MERGE_SHA> --out <NEW_EMPTY_PRIVATE_DIR>
   ```
3. If the script raises "Candidate failed its browser check", production was
   not changed: read `<out>/before/receipt.json` (per-view `failure`, `version`,
   `errors`) and the failure screenshots, report the cause and that the previous
   web app is still live, and do not retry with another method.
4. If it raises "Production alias does not identify the reviewed deployment",
   do not re-run blindly: read `<out>/receipt.json` (`deployment_id`,
   `previous_deployment`, `rollback`), query the live alias and
   `https://app.openmates.org/_app/version.json`, and report plainly whether
   production serves the new or the previous web app. The after-promotion live
   check did not run in that case, so run the browser check on the live origin
   before calling the release done.
5. Confirm `https://app.openmates.org` shows the expected version and report
   the receipt path. A rollback or failed check fails the release; never retry
   by assigning the alias another way. Also check whether `openmates-website`
   changed; promote it only through its own configured flow.

Permission: this command is the only one the step runs against Vercel. The
owner must allow it once in the user settings as the Bash rule
`Bash(python3 scripts/promote_production_webapp.py:*)`; the agent never edits
its own permission settings, and if the permission classifier still blocks the
command, stop and hand the exact command to the owner instead of working around
it.

Close the prod master connection when finished, and clear the AI test-user
update marker (also after a failed or rolled-back update):

```bash
./scripts/prod-ssh.sh close
python3 scripts/ai_test_users_deploy_guard.py end
```

## Completion Summary

Report:

- PR number and merge SHA.
- GitHub Actions run ID and conclusion.
- Vercel deployment URL, production alias, and Ready status.
- Required frontend API/schema capabilities, running-backend registration and
  affected-flow evidence, and whether readiness preceded frontend promotion.
- Prod update command and final image tag or rollback tag.
- `openmates server status` result.
- `openmates server verify` result, including any remaining failed check IDs.
- Result of the free-hourly prod smoke, including the signed-out web send check.
- Results of both distinct guest chats, the first chat's follow-up, and the
  daily allowance and limit checks, including any unobserved live cap boundary.
- Result of the signed-in chat, or that it was not run and why.
- Whether the SSH master was closed.
