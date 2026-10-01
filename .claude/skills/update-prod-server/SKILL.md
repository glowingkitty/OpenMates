---
name: update-prod-server
description: Monitor a merged production PR, wait for GitHub image builds and Vercel production deploy, then update the prod server via OpenMates CLI over prod SSH.
user-invocable: true
argument-hint: "<pr-url-or-number>"
---

# Skill: update-prod-server

## Purpose

Use this when a pull request has been accepted into `main` and production should
be updated from published GHCR images after Vercel production is live.

This skill is intentionally production-scoped. It verifies the release gates
first, opens the prod SSH master only after the user opens the temporary access
window and provides a fresh TOTP, then mutates production only through
`openmates server ...` commands.

## Required Inputs

- PR URL or number, for example `https://github.com/glowingkitty/OpenMates/pull/506`.
- User confirmation that prod-side temporary SSH access is open.
- A fresh 6-digit TOTP code, supplied immediately before `prod-ssh.sh open`.

## Workflow

### 1. Start Or Reuse A Session

If this is a mutating top-level chat and no session exists, start one:

```bash
python3 scripts/sessions.py start --mode feature --task "update production server from merged PR"
```

Keep the printed session ID for summaries. Do not create a second worktree for
the same Codex chat.

### 2. Resolve The Production Subject

Use GitHub to identify the merge commit and the image workflow run:

```bash
gh pr view <PR> --repo glowingkitty/OpenMates --json number,state,mergedAt,mergeCommit,headRefOid,baseRefName,title,url
gh run list --repo glowingkitty/OpenMates --branch main --limit 10 --json databaseId,name,status,conclusion,headSha,displayTitle,event,createdAt,updatedAt,url
```

Stop if the PR is not merged into `main` or if no `Publish Self-Host Images` run
exists for the merge commit SHA.

### 3. Poll Release Gates Every 30 Seconds

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

Require all of these before touching prod:

- `Publish Self-Host Images` for the merge SHA is completed with conclusion `success`.
- The Vercel deployment for `open-mates-webapp` has `target production`, `status Ready`, and alias `https://openmates.org`.
- The deployment metadata matches the merge SHA when available.

### 4. Open Prod SSH Only After Gates Pass

Check whether a master connection already exists:

```bash
./scripts/prod-ssh.sh status
```

If no master is active, ask the user to open the prod-side window with the dev
public key from the configured prod SSH key:

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

Use only OpenMates CLI commands for runtime state changes:

```bash
./scripts/prod-ssh.sh "openmates server status --path /home/superdev/openmates --json"
./scripts/prod-ssh.sh "openmates server update --path /home/superdev/openmates --exclude webapp --dry-run"
```

Review the dry-run for:

- Mode is `image` unless the server is intentionally source-mode.
- Target tag/channel is correct, usually `main` for official-cloud prod.
- Services exclude `webapp`, because production web is served by Vercel.
- Backup is planned.
- Env preflight and Vault secret checks are understood.

If the dry-run reports missing provider secrets that are known non-core optional
provider entries, rerun with `--yes` only after stating why. Do not edit prod
secrets unless the user explicitly asks.

### 6. Update Prod

Run the backend-only update:

```bash
./scripts/prod-ssh.sh "env OPENMATES_SELFHOST_COMPOSE_URL=https://raw.githubusercontent.com/glowingkitty/OpenMates/<MERGE_SHA>/frontend/packages/openmates-cli/templates/core/docker-compose.selfhost.yml /usr/bin/openmates server update --path /home/superdev/openmates --exclude webapp --image-tag sha-<MERGE_SHA> --yes"
```

For a scoped core hotfix with unchanged schema/migration code, avoid rerunning setup while replacing the API. First update only `cms-setup` to the exact target SHA through the CLI while the existing API serves traffic, then wait for that container to exit successfully. This stage still creates the normal pre-update backup:

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
health signal. Report any remaining verifier failures as configuration or
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

Treat missing or incomplete guest answers, a broken follow-up, an unexpectedly
blocked guest, or inconsistent allowance reporting as failed post-update
verification. Record the observed responses and status without guest IDs or
private chat contents in the completion summary.

Close the prod master connection when finished:

```bash
./scripts/prod-ssh.sh close
```

## Completion Summary

Report:

- PR number and merge SHA.
- GitHub Actions run ID and conclusion.
- Vercel deployment URL, production alias, and Ready status.
- Prod update command and final image tag or rollback tag.
- `openmates server status` result.
- `openmates server verify` result, including any remaining failed check IDs.
- Results of both distinct guest chats, the first chat's follow-up, and the
  daily allowance and limit checks, including any unobserved live cap boundary.
- Whether the SSH master was closed.
